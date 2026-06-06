# Ariadne — Backend

FastAPI service that builds bidirectional citation graphs (Semantic Scholar + OpenAlex),
filters papers for relevance with the OpenAI Codex CLI, and emits progressive reports.

```bash
uv sync
uv run uvicorn app.main:app --reload
uv run pytest
```

---

# Ariadne — 後端(繁體中文)

FastAPI 服務:建立雙向引用圖(Semantic Scholar + OpenAlex),用 OpenAI Codex CLI 篩選論文
相關性,並產生漸進報告。

```bash
uv sync
uv run uvicorn app.main:app --reload
uv run pytest
```
