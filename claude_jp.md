# CLAUDE.md（日本語版）

このファイルは、リポジトリ内のコードを操作する際に Claude Code（claude.ai/code）が従うべき指針を提供します。

---

## ⚠️ ファイル書き込みポリシー

**ユーザーのファイルシステムへの書き込みは基本禁止。**

- `Filesystem:write_file` / `Filesystem:edit_file` によるユーザー側ファイルへの書き込みは、ユーザーの明示的な許可がある場合のみ実行すること。
- 読み取り（`read_text_file`、`read_file`、`list_directory` 等）は許可。
- 新規ファイル作成・既存ファイル編集が必要な場合は、まずユーザーに確認を取ること。

---

## プロジェクト概要

本プロジェクトは日本語RAG（Retrieval-Augmented Generation）Q&Aシステムです。セマンティックチャンキング・Q&A自動生成・Qdrantベクトルデータベースへの登録・Agent検索を一気通貫で管理します。

**技術スタック:**

| 役割 | プロバイダー | モデル |
|---|---|---|
| LLM（チャンク分割・Q&A生成・Agent応答） | **Anthropic** | `claude-sonnet-4-6` |
| Embedding（Qdrant登録・検索） | **Gemini（Google）** | `gemini-embedding-001`（3072次元） |
| ベクトルDB | Qdrant | localhost:6333 |
| タスクキュー | Celery + Redis | localhost:6379 |
| UI | Streamlit | localhost:8501 |

---

## 開発コマンド

### 環境セットアップ

```bash
# 初期セットアップ（パッケージインストールと環境設定）
python setup.py

# 依存パッケージのインストール
pip install -r requirements.txt

# Qdrantベクトルデータベースの起動
docker-compose -f docker-compose/docker-compose.yml up -d

# Qdrantへのデータ登録
python a30_qdrant_registration.py --recreate --limit 100
```

### アプリケーション起動

```bash
# Qdrantサーバー管理スクリプトの起動
python server.py

# Streamlit検索UIの起動
streamlit run a50_rag_search_local_qdrant.py

# セマンティックカバレッジ分析の実行例
python example.py
```

### コード品質チェック

```bash
# ruffリンター実行（設定ファイルは未作成）
ruff check .

# ruffによるコード整形
ruff format .
```

---

## アーキテクチャ

### 主要コンポーネント

1. **SemanticCoverage**（`rag_qa.py`）: ドキュメントのチャンク分割とセマンティックカバレッジ計算を実装するメインクラス
   - ドキュメントからセマンティックチャンクを生成
   - ドキュメントとQ&Aペアの埋め込みベクトルを生成
   - コサイン類似度によるカバレッジメトリクスを計算
   - 文境界検出による日本語テキスト処理に対応

2. **ヘルパーモジュール:**
   - `helper_api.py`: Anthropic API連携・モデル設定・コスト追跡
   - `helper_rag.py`: RAGデータ前処理・設定管理（AppConfigクラス）
   - `helper_st.py`: カスタマーサポートFAQ処理用Streamlitユーティリティ

3. **データ管理スクリプト**（aプレフィックスファイル）:
   - `a01_load_set_rag_data.py`: RAGデータの読み込みと設定
   - `a02_set_vector_store_vsid.py`: ベクトルストアIDの設定
   - `a03_rag_search_cloud_vs.py`: クラウドベクトルストアの検索
   - `a30_qdrant_registration.py`: Qdrantへのデータ登録
   - `a35_qdrant_truncate.py`: Qdrantコレクションのデータ削除
   - `a40_show_qdrant_data.py`: Qdrantデータの表示
   - `a50_rag_search_local_qdrant.py`: ローカルQdrant検索のStreamlit UI

4. **インフラ:**
   - `server.py`: Qdrantサーバーのヘルスチェックと起動管理
   - `docker-compose/docker-compose.yml`: Qdrantのコンテナデプロイ

### データフロー

1. ドキュメントを文境界を保持しながらセマンティックチャンクに分割
2. チャンクとQ&AペアのEmbeddingベクトルを生成（Gemini Embedding API）
3. EmbeddingベクトルをQdrantベクトルデータベースに格納
4. Q&AのEmbeddingとドキュメントチャンクを比較してカバレッジを分析
5. Streamlit UIまたはAPIエンドポイントで結果を提示

### モデル設定

```
LLM（テキスト生成）: Anthropic Claude
  - claude-sonnet-4-6（デフォルト）
  - claude-opus-4-6
  - claude-haiku-4-5-20251001

Embedding: Gemini（Google）
  - gemini-embedding-001（3072次元）
```

---

## 環境変数

`.env` ファイルに以下を設定すること:

```bash
# LLM用（必須）
ANTHROPIC_API_KEY=your_anthropic_api_key

# Gemini Embedding用（必須）
GOOGLE_API_KEY=your_gemini_api_key
GEMINI_API_KEY=your_gemini_api_key

# Rerank用（オプション）
COHERE_API_KEY=your_cohere_api_key

# インフラ
QDRANT_HOST=localhost
QDRANT_PORT=6333
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
```

---

## 実装上の重要事項

- **日本語テキスト処理**: 日本語文分割に正規表現パターンを使用
- **チャンキング戦略**: チャンクあたり200トークン上限のセマンティックチャンキング
- **Embeddingモデル**: デフォルトは `gemini-embedding-001`（3072次元）
- **カバレッジ閾値**: Q&AとチャンクのマッチングにコサイN類似度0.8を使用
- **トークンカウント**: `cl100k_base` エンコーディングのtiktokenを使用

---

## 依存パッケージ

主要パッケージ:

- `anthropic>=0.40.0`: LLM（Q&A生成・Agent応答）用APIクライアント
- `google-generativeai>=0.8.0`: Gemini Embedding用APIクライアント
- `qdrant-client>=1.15.1`: ベクトルデータベースクライアント
- `streamlit>=1.48.1`: Web UIフレームワーク
- `fastapi>=0.115.6`: APIサーバーフレームワーク
- `tiktoken`: チャンクサイズ管理用トークンカウント
- `scikit-learn`: コサイン類似度計算
- `celery>=5.4.0`: 非同期タスクキュー
- `redis>=5.0.0`: Celeryブローカー
- `pydantic>=2.0.0`: データモデル検証

---

## 注意事項

- 正式なテストスイートは存在しない。新機能実装時にpytestの追加を検討すること。
- コードベースの一部に日本語の変数名・コメントが含まれている。
- 古い実装は `old_code/` ディレクトリにアーカイブされている。
- データ登録・検索機能を使用する前に必ずQdrantが起動していること。

---

# プロジェクト固有規約

## 7. Mermaidダイアグラム スタイル規約

### 7.1 構文バージョン

**PyCharm Pro v9 互換構文**を使用する。

- ノードラベルにバッククォートや markdown文字列（`` `text` ``）を使用しない
- 特殊文字を含むノードラベルは必ずダブルクォート（`"..."` ）で囲む

### 7.2 カラーテーマ（黒背景・白文字）— **必須**

すべてのMermaidダイアグラムに以下のスタイルを適用すること。

| 要素 | 設定値 |
|---|---|
| ノード背景色 | `fill:#000` |
| ノードテキスト色 | `color:#fff` |
| ノード枠線色 | `stroke:#fff` |
| サブグラフ背景色 | `fill:#1a1a1a` |
| サブグラフテキスト色 | `color:#fff` |
| サブグラフ枠線色 | `stroke:#fff` |

### 7.3 flowchart / graph 図の実装パターン

```
flowchart TB
    subgraph Layer["レイヤー名"]
        NodeA["ノードA"]
        NodeB["ノードB"]
    end
    NodeA --> NodeB
classDef default fill:#000,stroke:#fff,color:#fff
classDef subgraphStyle fill:#1a1a1a,stroke:#fff,color:#fff
class NodeA,NodeB default
style Layer fill:#1a1a1a,stroke:#fff,color:#fff
```

**必須ルール:**

1. `classDef default fill:#000,stroke:#fff,color:#fff` を必ずブロック末尾に追加する
2. `classDef subgraphStyle fill:#1a1a1a,stroke:#fff,color:#fff` を追加する
3. 全ノードに `class <ノードID列> default` を付与する
4. 全サブグラフに `style <サブグラフ名> fill:#1a1a1a,stroke:#fff,color:#fff` を付与する
5. 既存の `style`/`classDef`/`class` 行は重複しないよう整理する

### 7.4 sequenceDiagram 図の実装パターン

```
%%{ init: { "theme": "base", "themeVariables": {
  "background": "#000000", "mainBkg": "#000000",
  "textColor": "#ffffff", "lineColor": "#ffffff",
  "actorBkg": "#000000", "actorTextColor": "#ffffff",
  "actorLineColor": "#ffffff", "noteBkg": "#1a1a1a",
  "noteTextColor": "#ffffff" } } }%%
sequenceDiagram
    participant A as "参加者A"
    A->>B: メッセージ
```

**必須ルール:**

- `sequenceDiagram` の前に必ず `%%{ init: ... }%%` ヘッダーを挿入する
- `classDef` / `class` 行は `sequenceDiagram` では使用しない（非対応）

---

## 8. コーディング規約

### 8.1 型ヒント

`Optional[]` の型パラメータには必ず `typing.Callable`（大文字）を使用すること。

```python
# ❌ 誤り: callable（小文字）はOptional[]の型パラメータに使用不可
def func(callback: Optional[callable] = None): ...

# ✅ 正しい
from typing import Optional, Callable
def func(callback: Optional[Callable] = None): ...
```

### 8.2 Streamlit DataFrame の幅指定

```python
# ❌ 誤り: TypeError: 'str' object cannot be interpreted as an integer
st.dataframe(df, width='stretch')

# ✅ 正しい
st.dataframe(df, use_container_width=True)
```

### 8.3 出力ファイル命名（チャンク分割）

後続バッチとの連携のため、出力ファイル名は**固定ファイル名をデフォルト**とする。

```bash
# ✅ デフォルト: 固定ファイル名（後続バッチとの連携のため）
入力: OUTPUT/cc_news_1per.csv
出力: output_chunked/cc_news_1per_chunks.csv

# タイムスタンプが必要な場合は --timestamp オプションで明示指定
python -m chunking.csv_text_to_chunks_text_csv \
  --input-file OUTPUT/cc_news_1per.csv \
  --output output_chunked \
  --timestamp   # ← このオプションがある場合のみ日時サフィックスを付与
```

### 8.4 後続バッチとの連携コマンド例

```bash
# Step 1: チャンク分割（固定ファイル名で出力）
python -m chunking.csv_text_to_chunks_text_csv \
  --input-file OUTPUT/cc_news_1per.csv \
  --output output_chunked \
  --model claude-sonnet-4-6 \
  --workers 8
# → output_chunked/cc_news_1per_chunks.csv が生成される

# Step 2: Q&A生成 + Qdrant登録（Step1の固定ファイル名を入力として使用）
python qa_qdrant/make_qa_register_qdrant.py \
  --input-file output_chunked/cc_news_1per_chunks.csv \
  --collection cc_news_1per \
  --model claude-sonnet-4-6 \
  --concurrency 8 \
  --recreate
```

---

## 9. ドキュメント規約

### 9.1 技術スタック表記の統一

コードサンプル・説明文・Mermaid図内の表記を以下に統一すること。

| 用途 | ✅ 正しい表記 | ❌ 禁止表記 |
|---|---|---|
| LLM全般 | `Anthropic Claude` / `Claude Sonnet` | `Gemini`, `gemini-3-flash-preview` |
| デフォルトモデル | `claude-sonnet-4-6` | `gemini-3-flash-preview` |
| Embedding | `Gemini Embedding` / `gemini-embedding-001` | `text-embedding-3-small`（LLM用途での混用） |
| LLM設定クラス | `ModelConfig` | `GeminiConfig` |
| LLM用APIキー | `ANTHROPIC_API_KEY` | `GOOGLE_API_KEY`（LLM用途での使用） |

### 9.2 ドキュメント一覧

| ファイル | 内容 |
|---|---|
| `README.md` | プロジェクト全体・GRACE自律エージェント詳細 |
| `readme_make_env.md` | Mac向け環境構築手順 |
| `readme_usage_tools.md` | チャンク作成・Q&A生成・Qdrant登録の操作手順 |
| `readme_rag.md` | RAGパイプライン設計・クラス・関数 IPO詳細 |
| `readme_react_reflection.md` | ReAct+Reflectionエージェントの設計と実装 |
| `readme_autonomous_agent.md` | GRACEアーキテクチャ（Plan+Executor）詳細 |

---

# ⚠️ 変更前に必ず読むこと：重大規約 ⚠️

## 1. OpenAIモデル名 — モデル名マッピングを絶対に作成しないこと

**以下のモデルはすべて実在する正式なモデルです:**

- `gpt-5-nano`、`gpt-5-mini`、`gpt-5` ← 実在するGPT-5シリーズモデル
- `gpt-4.1`、`gpt-4.1-mini` ← 実在するGPT-4.1モデル
- `o3`、`o3-mini`、`o4`、`o4-mini` ← 実在するOシリーズモデル

**❌ 以下のようなモデル名マッピングを絶対に作成しないこと:**

```python
MODEL_MAPPING = {"gpt-5-nano": "gpt-4o-mini"}  # ← 誤り！絶対にやらないこと
```

**✅ `helper_rag.py` の28〜87行目に定義されているモデル名をそのまま使用すること**

---

## 2. OpenAI APIメソッド — 2種類の正しいAPIが存在する

**両方のAPIが正しく、どちらも実在します:**

### 構造化出力API（Q&A生成に推奨）

```python
response = client.responses.parse(
    input=combined_input,
    model=model,
    text_format=QAPairsResponse,  # 型安全な出力のためのPydanticモデル
    max_output_tokens=1000
)
```

- **用途**: Pydanticモデルによる型安全な出力
- **使用箇所**: `celery_tasks.py:202-207, 429-434`
- **ドキュメント**: `doc/helper_api.md` 14行目

### Responses API（標準テキスト生成）

```python
response = client.responses.create(
    input=input_messages,
    model=model,
    max_output_tokens=1000
)
```

- **用途**: 標準的なテキスト生成
- **使用箇所**: `helper_api.py:743`
- **ドキュメント**: `doc/helper_api.md` 12行目

**⚠️ `.parse()` と `.create()` はどちらも正しい — 用途に応じて使い分けること**

---

## 3. 変更前の必須確認事項

**OpenAI APIコードを変更する前に、以下を必ず実施すること:**

1. ✅ `doc/helper_api.md` を読む（完全なAPIドキュメント）
2. ✅ `helper_api.py` の715〜758行目を読む（実際の実装）
3. ✅ `helper_rag.py` の28〜87行目を読む（モデル一覧）
4. ✅ 自問する：「ドキュメントには何と書いてあるか？」
5. ✅ 不確かな場合 → **まずユーザーに確認すること**

---

## 4. よくある誤り — 絶対に避けること

**❌ 誤り1: モデル名が間違っていると思い込む**

```
誤った考え: "gpt-5-nanoがエラーを返すので、存在しないモデルのはずだ"
真実: gpt-5-nanoは実在するモデル — 実際のエラー原因を調査すること
```

**❌ 誤り2: parse()とcreate()を混同する**

```
誤った考え: "responses.parse()は存在しないので、create()を使うべきだ"
真実: どちらも実在する — parse()は構造化出力用、create()はテキスト生成用
```

**❌ 誤り3: "親切心"からモデル名マッピングを作る**

```
誤った考え: "古いモデル名を新しいものに変換するマッピングを作ろう"
真実: モデル名はすでに正しい — マッピングを作成してはいけない
```

---

## 5. 変更前の緊急チェックリスト

**変更をコミットする前に以下を確認すること:**

- [ ] MODEL_MAPPINGを作成したか？（YESの場合 → 削除すること）
- [ ] `responses.parse()` を `responses.create()` に変更したか？（YESの場合 → 元に戻すこと）
- [ ] `doc/helper_api.md` を読んだか？（NOの場合 → 今すぐ読むこと）
- [ ] これが正しいと確信があるか？（NOの場合 → ユーザーに確認すること）

---

## 6. エラー発生時の対処

**「model not found」や「API error」が表示された場合:**

1. ❌ モデル名が間違っているためではない
2. ❌ APIメソッドが間違っているためではない
3. ✅ 確認すべき項目: APIキー・ネットワーク・Celeryワーカー・Redis接続
4. ✅ 確認すべき項目: 実際のエラーメッセージとスタックトレース
5. ✅ **最初の対応としてモデル名やAPIメソッド名を「修正」しようとしないこと**
