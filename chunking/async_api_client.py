# async_api_client.py
"""
非同期APIクライアント（Anthropic版）

- asyncio.to_thread() で同期APIをラップ
- Semaphore で並列数制御
- リトライロジック（3回、指数バックオフ）
- Tool Use 強制による Structured Output（response_schema 対応）

[Migration] google-genai → anthropic
  - genai.Client()                          → anthropic.Anthropic()
  - GenerateContentConfig(response_schema)  → Tool Use 強制（model_json_schema()）
  - response.text (JSON文字列)              → block.input を json.dumps()
  - finish_reason (int/Enum)               → stop_reason (str: "end_turn"/"max_tokens")
  - レート制限キーワード                     → "rate_limit" / "overloaded" を追加
"""

import asyncio
import json
import logging
from typing import Type, Optional

from pydantic import BaseModel
import anthropic

logger = logging.getLogger(__name__)

# Structured Output 用ツール名（固定）
_TOOL_NAME = "structured_output"


class AsyncAPIClient:
    """
    非同期APIクライアント（Anthropic版）

    Structured Output は Tool Use 強制で実現する:
      1. Pydantic モデルを model_json_schema() で JSON Schema に変換
      2. tool_choice={"type":"tool","name":"structured_output"} で強制呼び出し
      3. response.content の tool_use ブロックから block.input を取得
      4. json.dumps() で JSON 文字列化して返却（呼び出し側の互換性を維持）

    戻り値 Optional[str] は以前の Gemini 版と同じ JSON 文字列形式。
    呼び出し側での StructuralResult.model_validate_json() はそのまま動作する。
    """

    def __init__(
        self,
        api_key: str,
        max_workers: int = 8,
        max_retries: int = 3,
        max_output_tokens: int = 8192
    ):
        """
        Args:
            api_key: Anthropic API Key
            max_workers: 並列数（デフォルト: 8）
            max_retries: リトライ回数（デフォルト: 3）
            max_output_tokens: 出力トークン制限（デフォルト: 8192）
        """
        self.client = anthropic.Anthropic(api_key=api_key)
        self.max_workers = max_workers
        self.semaphore = asyncio.Semaphore(max_workers)
        self.max_retries = max_retries
        self.max_output_tokens = max_output_tokens
        self._total_requests = 0
        self._failed_requests = 0
        self._truncated_responses = 0

    def _is_truncated_response(self, response) -> bool:
        """
        レスポンスが切断されたかチェック。

        Anthropic の stop_reason:
          "end_turn"      → 正常終了
          "max_tokens"    → トークン上限で切断（要リトライ）
          "tool_use"      → Tool Use 強制時の正常停止（こちらが期待値）
          "stop_sequence" → 正常終了
        """
        stop_reason = getattr(response, 'stop_reason', None)
        return stop_reason == "max_tokens"

    def _extract_tool_result(self, response) -> Optional[str]:
        """
        Tool Use ブロックから結果を抽出し、JSON 文字列として返す。

        Tool Use 強制時、response.content には必ず tool_use ブロックが含まれる。
        block.input は dict 形式なので json.dumps() で JSON 文字列に変換する。
        """
        for block in response.content:
            if block.type == "tool_use":
                return json.dumps(block.input, ensure_ascii=False)
        return None

    def _build_tool(self, response_schema: Type[BaseModel]) -> dict:
        """
        Pydantic モデルから Anthropic Tool Use 定義を構築する。

        model_json_schema() は $defs / $ref を含む JSON Schema を生成する。
        Anthropic の input_schema は $defs / $ref をサポートしているため
        ネストしたモデル（SentenceUnit → ParagraphUnit → StructuralResult）も正常に動作する。
        """
        return {
            "name"        : _TOOL_NAME,
            "description" : f"Return the structured result as {response_schema.__name__}",
            "input_schema": response_schema.model_json_schema(),
        }

    async def generate_content(
        self,
        model: str,
        contents: str,
        response_schema: Type[BaseModel],
        task_id: Optional[str] = None
    ) -> Optional[str]:
        """
        セマフォで並列数を制御しながら API 呼び出し。
        失敗時は指数バックオフでリトライ。

        Args:
            model: Anthropic モデル名（例: "claude-sonnet-4-6"）
            contents: 入力テキスト（プロンプト）
            response_schema: レスポンスの Pydantic スキーマ
            task_id: タスク識別子（ログ用）

        Returns:
            JSON 文字列（response_schema に準拠）、または失敗時は None
        """
        async with self.semaphore:
            return await self._execute_with_retry(
                model, contents, response_schema, task_id
            )

    async def _execute_with_retry(
        self,
        model: str,
        contents: str,
        response_schema: Type[BaseModel],
        task_id: Optional[str]
    ) -> Optional[str]:
        """リトライロジック（Tool Use Structured Output 対応版）"""

        # Tool 定義はリトライ間で共有（毎回再構築しない）
        tool = self._build_tool(response_schema)

        for attempt in range(self.max_retries):
            try:
                self._total_requests += 1

                # asyncio.to_thread で同期 API を非同期実行
                response = await asyncio.to_thread(
                    self.client.messages.create,
                    model=model,
                    max_tokens=self.max_output_tokens,
                    tools=[tool],
                    tool_choice={"type": "tool", "name": _TOOL_NAME},
                    messages=[{"role": "user", "content": contents}],
                )

                # レスポンス切断チェック（max_tokens での途中終了）
                if self._is_truncated_response(response):
                    self._truncated_responses += 1
                    raise ValueError(
                        f"Response truncated (stop_reason: {response.stop_reason}). "
                        f"max_output_tokens={self.max_output_tokens} を増やすか "
                        f"block_size を小さくしてください。"
                    )

                # Tool Use ブロックから JSON 文字列を抽出
                result_json = self._extract_tool_result(response)
                if result_json is None:
                    raise ValueError(
                        f"tool_use ブロックが見つかりません "
                        f"(stop_reason: {response.stop_reason})"
                    )

                return result_json

            except ValueError as e:
                # 切断・Tool Use なし → リトライ
                wait_time = 2 ** attempt
                logger.warning(
                    f"[{task_id}] {e}. "
                    f"Retrying in {wait_time}s (attempt {attempt + 1}/{self.max_retries})"
                )
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(wait_time)

            except Exception as e:
                error_str = str(e).lower()

                # レート制限・過負荷エラーの判定
                # Anthropic: 429 / "rate_limit" / "overloaded"
                is_rate_limit = any(
                    kw in error_str
                    for kw in ["429", "rate_limit", "rate limit", "quota", "overloaded"]
                )

                if is_rate_limit:
                    wait_time = 30 * (attempt + 1)
                    logger.warning(
                        f"[{task_id}] Rate limit / overloaded. "
                        f"Waiting {wait_time}s (attempt {attempt + 1}/{self.max_retries})"
                    )
                else:
                    wait_time = 2 ** attempt
                    logger.warning(
                        f"[{task_id}] Error: {e}. "
                        f"Retrying in {wait_time}s (attempt {attempt + 1}/{self.max_retries})"
                    )

                if attempt < self.max_retries - 1:
                    await asyncio.sleep(wait_time)

        # 全リトライ失敗
        self._failed_requests += 1
        logger.error(f"[{task_id}] Failed after {self.max_retries} retries. Using fallback.")
        return None

    def get_stats(self) -> dict:
        """統計情報を取得"""
        return {
            "total_requests"     : self._total_requests,
            "failed_requests"    : self._failed_requests,
            "truncated_responses": self._truncated_responses,
            "success_rate"       : (
                (self._total_requests - self._failed_requests) / self._total_requests * 100
                if self._total_requests > 0 else 0
            ),
            "concurrency"        : self.max_workers,
        }

    def reset_stats(self):
        """統計情報をリセット"""
        self._total_requests = 0
        self._failed_requests = 0
        self._truncated_responses = 0
