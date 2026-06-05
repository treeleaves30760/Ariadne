# Paper Connector — Backend

FastAPI service that builds bidirectional citation graphs (Semantic Scholar + OpenAlex),
filters papers for relevance with the OpenAI Codex CLI, and emits progressive reports.

## Dev

```bash
uv sync
uv run uvicorn app.main:app --reload
uv run pytest
```
