"""
LLMクライアント抽象化レイヤー

OpenAI API / Gemini API / Anthropic API の3プロバイダーに対応する統一インターフェースを提供。

Migration: Gemini → Anthropic (2026-04-20) → OpenAI (2026-04-25)
  - AnthropicClient クラスを追加
  - generate_with_tools() を追加（ReAct Agent 用）
  - create_llm_client() に "anthropic" プロバイダーを追加
  - LLM_MODELS / LLM_PRICING / LLM_LIMITS に Claude モデルを追加
"""

from abc import ABC, abstractmethod
# [FIX] TypeVar を追加: generate_structured() の戻り型を具体的な Pydantic クラスに推論させる
from typing import Any, Optional, Type, List, Dict, Tuple, TypeVar
import os
import logging

from pydantic import BaseModel
from dotenv import load_dotenv

# ================================================================
# SDK imports
# ================================================================

# OpenAI
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

# Gemini (既存。gemini_grace_agent との並行運用のため維持)
try:
    from google import genai
    from google.genai import types as genai_types
except ImportError:
    genai = None
    genai_types = None

# Anthropic (後方互換のため維持)
try:
    import anthropic as anthropic_sdk
except ImportError:
    anthropic_sdk = None

import tiktoken

load_dotenv()

logger = logging.getLogger(__name__)

# ================================================================
# [FIX] TypeVar 定義
# generate_structured() の response_schema 引数に渡した Pydantic クラスを
# そのまま戻り型として推論させるためのジェネリック型変数。
#
# 変更前: generate_structured(...) -> BaseModel
#   → 呼び出し側で result: EvaluationResult = llm.generate_structured(...)
#     と書くと「Expected EvaluationResult, got BaseModel」警告が出る。
#
# 変更後: generate_structured(..., response_schema: Type[T]) -> T
#   → response_schema=EvaluationResult を渡せば戻り型が EvaluationResult に確定し警告なし。
# ================================================================
T = TypeVar("T", bound=BaseModel)


# ================================================================
# LLM モデル設定
# ================================================================

# --- Gemini モデル (既存) ---
LLM_MODELS_GEMINI = [
    "gemini-2.5-flash",
    "gemini-3-pro-preview",
    "gemini-2.5-flash-preview",
    "gemini-2.0-flash",
    "gemini-1.5-pro",
    "gemini-1.5-flash",
]

# --- Anthropic モデル ---
LLM_MODELS_ANTHROPIC = [
    "claude-opus-4-7",            # 最新 Opus (2026-04)
    "claude-opus-4-6",            # Opus 前世代
    "claude-sonnet-4-6",          # 最新 Sonnet → デフォルト推奨
    "claude-sonnet-4-5",          # Sonnet 前世代（後方互換）
    "claude-haiku-4-5-20251001",  # Haiku（高速・低コスト）
]

# --- OpenAI モデル ---
LLM_MODELS_OPENAI = [
    "gpt-4o",
    "gpt-4o-mini",
]

# 全モデル一覧（後方互換性のため維持）
LLM_MODELS = LLM_MODELS_ANTHROPIC + LLM_MODELS_GEMINI + LLM_MODELS_OPENAI

# ----------------------------------------------------------------
# 料金設定（USD / 1K tokens）
# ----------------------------------------------------------------
LLM_PRICING = {
    # Anthropic Claude 4.x
    "claude-opus-4-7"         : {"input": 0.005,   "output": 0.025  },
    "claude-opus-4-6"         : {"input": 0.015,   "output": 0.075  },
    "claude-sonnet-4-6"       : {"input": 0.003,   "output": 0.015  },
    "claude-sonnet-4-5"       : {"input": 0.003,   "output": 0.015  },
    "claude-haiku-4-5-20251001": {"input": 0.0008,  "output": 0.004  },

    # Gemini (既存)
    "gemini-2.5-flash"        : {"input": 0.0001,  "output": 0.0004 },
    "gemini-3-pro-preview"    : {"input": 0.00125, "output": 0.010  },
    "gemini-2.5-flash-preview": {"input": 0.00015, "output": 0.0035 },
    "gemini-2.0-flash"        : {"input": 0.0001,  "output": 0.0004 },
    "gemini-1.5-pro"          : {"input": 0.00125, "output": 0.005  },
    "gemini-1.5-flash"        : {"input": 0.000075,"output": 0.0003 },
}

# ----------------------------------------------------------------
# コンテキスト上限設定（tokens）
# ----------------------------------------------------------------
LLM_LIMITS = {
    # Anthropic Claude 4.x
    "claude-opus-4-7"         : {"max_tokens": 200000,  "max_output": 32000},
    "claude-opus-4-6"         : {"max_tokens": 1000000, "max_output": 32000},
    "claude-sonnet-4-6"       : {"max_tokens": 1000000, "max_output": 64000},
    "claude-sonnet-4-5"       : {"max_tokens": 200000,  "max_output": 64000},
    "claude-haiku-4-5-20251001": {"max_tokens": 200000,  "max_output": 8192 },

    # Gemini (既存)
    "gemini-2.5-flash"        : {"max_tokens": 1000000, "max_output": 8192 },
    "gemini-3-pro-preview"    : {"max_tokens": 1000000, "max_output": 64000},
    "gemini-2.5-flash-preview": {"max_tokens": 1000000, "max_output": 64000},
    "gemini-2.0-flash"        : {"max_tokens": 1000000, "max_output": 8192 },
    "gemini-1.5-pro"          : {"max_tokens": 1000000, "max_output": 8192 },
    "gemini-1.5-flash"        : {"max_tokens": 1000000, "max_output": 8192 },
}

# ================================================================
# Embedding モデル設定（既存のまま維持）
# ================================================================

EMBEDDING_MODELS = [
    "gemini-embedding-001",
    "text-embedding-3-small",
    "text-embedding-3-large",
]

EMBEDDING_PRICING = {
    "gemini-embedding-001"  : 0.0001,
    "text-embedding-3-small": 0.00002,
    "text-embedding-3-large": 0.00013,
}

EMBEDDING_DIMS = {
    "gemini-embedding-001"  : 3072,
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
}

# ================================================================
# デフォルトプロバイダー
# 環境変数 LLM_PROVIDER で切り替え可能
#   export LLM_PROVIDER=anthropic  # anthropic_grace_agent
#   export LLM_PROVIDER=gemini     # gemini_grace_agent (既存)
# ================================================================
DEFAULT_LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")


# ================================================================
# 抽象基底クラス
# ================================================================

class LLMClient(ABC):
    """LLM クライアント統一インターフェース"""

    @abstractmethod
    def generate_content(self, prompt: str, model: Optional[str] = None, **kwargs) -> str:
        """テキスト生成"""
        pass

    @abstractmethod
    def generate_structured(
        self,
        prompt: str,
        response_schema: Type[T],   # [FIX] Type[BaseModel] → Type[T]
        model: Optional[str] = None,
        **kwargs,
    ) -> T:                         # [FIX] BaseModel → T
        """構造化出力（Pydantic モデル）を生成"""
        pass

    @abstractmethod
    def count_tokens(self, text: str, model: Optional[str] = None) -> int:
        """トークン数をカウント"""
        pass


# ================================================================
# OpenAI クライアント
# ================================================================

class OpenAIClient(LLMClient):
    def __init__(self, api_key: Optional[str] = None, default_model: str = "gpt-4o-mini"):
        if not OpenAI:
            raise ImportError("openai package is not installed.")
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is not set")
        self.client = OpenAI(api_key=self.api_key)
        self.default_model = default_model

    def generate_content(self, prompt: str, model: Optional[str] = None, **kwargs) -> str:
        model = model or self.default_model
        system = kwargs.pop("system", None)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        # max_tokens → max_completion_tokens 変換（gpt-4o 系列の仕様）
        if "max_tokens" in kwargs and "max_completion_tokens" not in kwargs:
            kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
        response = self.client.chat.completions.create(model=model, messages=messages, **kwargs)
        return response.choices[0].message.content

    def generate_structured(
        self,
        prompt: str,
        response_schema: Type[T],   # [FIX] Type[BaseModel] → Type[T]
        model: Optional[str] = None,
        **kwargs,
    ) -> T:                         # [FIX] BaseModel → T
        """
        構造化出力（Pydantic モデル）を生成

        OpenAI beta.chat.completions.parse を使用。
        response_schema に渡した Pydantic クラスのインスタンスを返す。

        Args:
            prompt: ユーザープロンプト
            response_schema: 出力形式を定義する Pydantic モデルクラス
            model: 使用モデル
            system: システムプロンプト（kwargs 経由）
            max_tokens: 最大出力トークン数（内部で max_completion_tokens に変換）

        Returns:
            response_schema のインスタンス（型チェッカーが具体的な型として認識）
        """
        model = model or self.default_model
        system = kwargs.pop("system", None)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        # max_tokens → max_completion_tokens 変換
        if "max_tokens" in kwargs and "max_completion_tokens" not in kwargs:
            kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
        response = self.client.beta.chat.completions.parse(
            model=model,
            messages=messages,
            response_format=response_schema,
            **kwargs,
        )
        return response.choices[0].message.parsed  # type: ignore[return-value]

    def count_tokens(self, text: str, model: Optional[str] = None) -> int:
        model = model or self.default_model
        try:
            encoding = tiktoken.encoding_for_model(model)
        except KeyError:
            encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))

    def generate_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        system: str = "",
        model: Optional[str] = None,
        max_tokens: int = 4096,
        **kwargs,
    ) -> tuple:
        """
        Tool Use を含む ReAct ループの 1 ステップを実行する。

        Anthropic との差異:
          - ツール定義: "input_schema" → "parameters"
          - ツール検出: stop_reason=="tool_use" → finish_reason=="tool_calls"
          - ツール引数: b.input(dict) → json.loads(tc.function.arguments)
          - system: system= パラメータ → messages 先頭に {"role":"system"} として挿入

        Returns:
            (text, tool_calls, finish_reason) のタプル
            - text:          LLM のテキスト応答
            - tool_calls:    [{"name":..., "input":..., "id":...}, ...]
            - finish_reason: "tool_calls" | "stop" | "length"
        """
        import json as _json

        model_name = model or self.default_model

        full_messages: List[Dict[str, Any]] = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)

        create_kwargs: Dict[str, Any] = {
            "model"   : model_name,
            "messages": full_messages,
        }

        if tools:
            openai_tools = [
                {
                    "type"    : "function",
                    "function": {
                        "name"       : t["name"],
                        "description": t.get("description", ""),
                        "parameters" : t.get("input_schema", t.get("parameters", {})),
                    }
                }
                for t in tools
            ]
            create_kwargs["tools"] = openai_tools

        if "temperature" in kwargs:
            create_kwargs["temperature"] = kwargs["temperature"]

        response = self.client.chat.completions.create(**create_kwargs)
        msg = response.choices[0].message

        tool_calls_result = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    args = _json.loads(tc.function.arguments)
                except Exception:
                    args = {}
                tool_calls_result.append({
                    "name" : tc.function.name,
                    "input": args,
                    "id"   : tc.id,
                })

        text = msg.content or ""
        finish_reason = response.choices[0].finish_reason or "stop"

        return text, tool_calls_result, finish_reason

    def build_tool_result_message(
        self,
        tool_calls: List[Dict[str, Any]],
        results: List[str],
    ) -> List[Dict[str, Any]]:
        """
        ツール結果メッセージを構築する（OpenAI 形式）。

        OpenAI: [{"role":"tool","tool_call_id":id,"content":...}, ...]
                → messages に複数追記（ツール1件ごとに1メッセージ）
        """
        return [
            {
                "role"        : "tool",
                "tool_call_id": tc["id"],
                "content"     : result,
            }
            for tc, result in zip(tool_calls, results)
        ]


# ================================================================
# Gemini クライアント（既存のまま維持 / gemini_grace_agent との並行運用用）
# ================================================================

class GeminiClient(LLMClient):
    def __init__(self, api_key: Optional[str] = None, default_model: str = "gemini-2.0-flash"):
        if genai is None:
            raise ImportError(
                "google-genai package is not installed. "
                "Install with: pip install google-genai"
            )
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError("GOOGLE_API_KEY is not set")
        self.client = genai.Client(api_key=self.api_key)
        self.default_model = default_model

    def generate_content(self, prompt: str, model: Optional[str] = None, **kwargs) -> str:
        model_name = model or self.default_model
        config = {}
        if "temperature" in kwargs:
            config["temperature"] = kwargs.pop("temperature")
        if "max_output_tokens" in kwargs:
            config["max_output_tokens"] = kwargs.pop("max_output_tokens")
        response = self.client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=genai_types.GenerateContentConfig(**config) if config else None,
        )
        return response.text

    def generate_structured(
        self,
        prompt: str,
        response_schema: Type[T],   # [FIX] Type[BaseModel] → Type[T]
        model: Optional[str] = None,
        **kwargs,
    ) -> T:                         # [FIX] BaseModel → T
        model_name = model or self.default_model
        config: Dict[str, Any] = {
            "response_mime_type": "application/json",
            "response_schema"   : response_schema.model_json_schema(),
        }
        if "temperature" in kwargs:
            config["temperature"] = kwargs.pop("temperature")
        if "max_output_tokens" in kwargs:
            config["max_output_tokens"] = kwargs.pop("max_output_tokens")
        schema_prompt = (
            f"{prompt}\n\nOutput in JSON format following this schema: "
            f"{response_schema.model_json_schema()}"
        )
        response = self.client.models.generate_content(
            model=model_name,
            contents=schema_prompt,
            config=genai_types.GenerateContentConfig(**config),
        )
        try:
            return response_schema.model_validate_json(response.text)
        except Exception as e:
            logger.error(f"JSON parse error: {e}")
            logger.error(f"Raw response text from Gemini:\n{response.text}")
            raise

    def count_tokens(self, text: str, model: Optional[str] = None) -> int:
        model_name = model or self.default_model
        response = self.client.models.count_tokens(model=model_name, contents=text)
        return response.total_tokens


# ================================================================
# Anthropic クライアント（後方互換のため維持）
# ================================================================

class AnthropicClient(LLMClient):
    """
    Anthropic Claude API クライアント

    Gemini API との主要な差異：
      - 構造化出力: response_schema 直渡し不可 → Tool Use で代替
      - システムプロンプト: config.system_instruction → system= パラメータ
      - レスポンス: response.text → response.content[0].text
      - ツール呼び出し検出: stop_reason == "tool_use" で判定
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        default_model: str = "claude-sonnet-4-6",
    ):
        if anthropic_sdk is None:
            raise ImportError(
                "anthropic package is not installed. "
                "Install with: pip install anthropic"
            )
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY is not set")
        self.client = anthropic_sdk.Anthropic(api_key=self.api_key)
        self.default_model = default_model
        logger.info(f"AnthropicClient initialized: model={default_model}")

    def generate_content(
        self,
        prompt: str,
        model: Optional[str] = None,
        **kwargs,
    ) -> str:
        model_name = model or self.default_model
        system = kwargs.pop("system", "You are a helpful assistant.")
        max_tokens = kwargs.pop("max_tokens", 4096)
        temperature = kwargs.pop("temperature", None)

        create_kwargs: Dict[str, Any] = {
            "model"     : model_name,
            "max_tokens": max_tokens,
            "system"    : system,
            "messages"  : [{"role": "user", "content": prompt}],
        }
        if temperature is not None:
            create_kwargs["temperature"] = temperature

        response = self.client.messages.create(**create_kwargs)
        return response.content[0].text

    def generate_structured(
        self,
        prompt: str,
        response_schema: Type[T],   # [FIX] Type[BaseModel] → Type[T]
        model: Optional[str] = None,
        **kwargs,
    ) -> T:                         # [FIX] BaseModel → T
        """
        構造化出力（Pydantic モデル）を生成

        Anthropic には response_schema 直渡し機能がないため、
        Tool Use（tool_choice: "tool"）で JSON を強制取得し
        Pydantic の model_validate() でパースする。

        Returns:
            response_schema のインスタンス（型チェッカーが具体的な型として認識）
        """
        model_name  = model or self.default_model
        system      = kwargs.pop("system", "You are a helpful assistant. Return structured data as requested.")
        max_tokens  = kwargs.pop("max_tokens", 4096)
        temperature = kwargs.pop("temperature", None)

        tool_def = {
            "name"        : "structured_output",
            "description" : (
                "Return the result as a structured JSON object "
                "matching the given schema exactly."
            ),
            "input_schema": response_schema.model_json_schema(),
        }

        create_kwargs: Dict[str, Any] = {
            "model"      : model_name,
            "max_tokens" : max_tokens,
            "system"     : system,
            "tools"      : [tool_def],
            "tool_choice": {"type": "tool", "name": "structured_output"},
            "messages"   : [{"role": "user", "content": prompt}],
        }
        if temperature is not None:
            create_kwargs["temperature"] = temperature

        response = self.client.messages.create(**create_kwargs)

        if response.stop_reason != "tool_use":
            raise ValueError(
                f"Unexpected stop_reason: {response.stop_reason}. "
                f"Content: {response.content}"
            )

        try:
            tool_block = next(
                b for b in response.content if b.type == "tool_use"
            )
        except StopIteration:
            raise ValueError(
                f"No tool_use block in response. Content: {response.content}"
            )

        try:
            return response_schema.model_validate(tool_block.input)
        except Exception as e:
            logger.error(f"Pydantic validation error: {e}")
            logger.error(f"Raw tool input: {tool_block.input}")
            raise

    def count_tokens(self, text: str, model: Optional[str] = None) -> int:
        model_name = model or self.default_model
        response = self.client.messages.count_tokens(
            model=model_name,
            messages=[{"role": "user", "content": text}],
        )
        return response.input_tokens

    def generate_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        system: str = "",
        model: Optional[str] = None,
        max_tokens: int = 4096,
    ) -> Tuple[str, List[Dict[str, Any]], str]:
        """
        Tool Use を含む ReAct ループの 1 ステップを実行する（Anthropic 形式）。
        """
        model_name = model or self.default_model

        create_kwargs: Dict[str, Any] = {
            "model"     : model_name,
            "max_tokens": max_tokens,
            "tools"     : tools,
            "messages"  : messages,
        }
        if system:
            create_kwargs["system"] = system

        response = self.client.messages.create(**create_kwargs)

        tool_calls = [
            {
                "name" : b.name,
                "input": b.input,
                "id"   : b.id,
            }
            for b in response.content
            if b.type == "tool_use"
        ]

        text = " ".join(
            b.text for b in response.content if b.type == "text"
        )

        return text, tool_calls, response.stop_reason

    def build_tool_result_message(
        self,
        tool_calls: List[Dict[str, Any]],
        results: List[str],
    ) -> Dict[str, Any]:
        """
        ツール実行結果を Anthropic の tool_result メッセージ形式に変換する。
        """
        content = [
            {
                "type"       : "tool_result",
                "tool_use_id": tc["id"],
                "content"    : result,
            }
            for tc, result in zip(tool_calls, results)
        ]
        return {"role": "user", "content": content}


# ================================================================
# ファクトリ関数
# ================================================================

def create_llm_client(provider: str = "openai", **kwargs) -> LLMClient:
    """
    LLM クライアントのファクトリ関数

    Args:
        provider: "openai" | "anthropic" | "gemini"
                  デフォルト: "openai"（openai_grace_agent）
        **kwargs: 各クライアントの __init__ に渡すパラメータ
                  例: default_model="gpt-4o-mini"

    Returns:
        LLMClient インスタンス
    """
    provider = (provider or DEFAULT_LLM_PROVIDER).lower()

    if provider == "anthropic":
        return AnthropicClient(**kwargs)
    elif provider == "openai":
        return OpenAIClient(**kwargs)
    elif provider == "gemini":
        return GeminiClient(**kwargs)
    else:
        raise ValueError(
            f"Unknown provider: '{provider}'. "
            "Choose from 'anthropic', 'openai', 'gemini'."
        )


# ================================================================
# ヘルパー関数
# ================================================================

def get_available_llm_models() -> List[str]:
    """全プロバイダーの利用可能モデル一覧"""
    return LLM_MODELS


def get_available_llm_models_by_provider(provider: str) -> List[str]:
    """プロバイダー別モデル一覧"""
    provider = provider.lower()
    if provider == "anthropic":
        return LLM_MODELS_ANTHROPIC
    elif provider == "openai":
        return LLM_MODELS_OPENAI
    elif provider == "gemini":
        return LLM_MODELS_GEMINI
    return []


def get_llm_model_pricing(model_name: str) -> Dict[str, float]:
    return LLM_PRICING.get(model_name, {"input": 0.0, "output": 0.0})


def get_llm_model_limits(model_name: str) -> Dict[str, int]:
    return LLM_LIMITS.get(model_name, {"max_tokens": 0, "max_output": 0})


def get_available_embedding_models() -> List[str]:
    return EMBEDDING_MODELS


def get_embedding_model_pricing(model_name: str) -> float:
    return EMBEDDING_PRICING.get(model_name, 0.0)


def get_embedding_model_dimensions(model_name: str) -> int:
    return EMBEDDING_DIMS.get(model_name, 0)
