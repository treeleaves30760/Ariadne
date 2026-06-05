# Paper Connector

Build a **bidirectional citation graph** from a seed paper or benchmark, let the
**OpenAI Codex CLI** filter each level for relevance and write short explanations,
and explore the result as an interactive graph with **progressive reports** — so a
PhD student reading papers, scouting research directions, or writing related work
never misses a key paper.

- **Input** a paper title / DOI / arXiv id / benchmark name → pick from candidates.
- **Expand** references (backward) and citations (forward) to depth 3–5.
- **Filter** each level with Codex (loose by default), keeping the most relevant papers.
- **Report** progressively: a report at depth 3, again at 4 and 5, plus a final synthesis.
- **Explore** the graph (Cytoscape) with per-paper AI summaries; export BibTeX / Markdown.

## Layout

```
backend/   FastAPI service (uv, Python 3.13) — sources, graph, ai, jobs, storage, api
web/       Nuxt frontend (Vue 3, TypeScript) — input, graph, reports
docs/      Design spec
```

## Quick start

```bash
# Backend
cd backend
cp .env.example .env        # edit as needed
uv sync
uv run uvicorn app.main:app --reload

# Frontend
cd web
npm install
npm run dev
```

Codex must be installed and logged in (`codex login`).

## Status

Under active development. See `docs/superpowers/specs/` for the design.
