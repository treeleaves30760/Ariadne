# Paper Connector

Build a **bidirectional citation graph** from a seed paper or benchmark, let the
**OpenAI Codex CLI** filter each level for relevance and write short explanations,
and explore the result as an interactive graph with **progressive reports** — so a
PhD student reading papers, scouting research directions, or writing related work
never misses a key paper.

- **Input** a paper title / DOI / arXiv id / benchmark name → pick from candidates.
- **Expand** references (backward) and citations (forward) to depth 3–5.
- **Filter** each level with Codex (loose by default), keeping the most relevant papers.
- **Report** progressively: a report at depth 3, again at 4 and 5, a final synthesis,
  plus a **web-context report** (DuckDuckGo) that surfaces surveys / recent work
  beyond the citation graph.
- **Ask the literature** — a tool-augmented chatbot: multi-turn Q&A grounded in the
  corpus (clickable citations), optionally verified with web search and by reading
  open-access PDFs.
- **Rank** papers by an **importance score** (relevance × citations × top-venue) in a
  sortable papers table.
- **Explore** a readable Cytoscape graph (rings-by-depth or force layout, responsive
  zoom, hover titles, neighbour highlight) with per-paper AI summaries, live activity
  feed, open-access PDF links; export BibTeX / Markdown.
- **Configure** the model (gpt-5.5 / gpt-5.4 × low→xhigh reasoning) and your own
  OpenAI-compatible endpoint / API key on the Settings page.

## Layout

```
backend/   FastAPI service (uv, Python 3.13) — sources, graph, ai, jobs, storage, api
web/       Nuxt frontend (Vue 3, TypeScript) — input, graph, reports
docs/      Design spec
```

## Prerequisites

- Python 3.12+ with [uv](https://docs.astral.sh/uv/), Node 20+ / npm
- **Codex CLI** installed and logged in (`codex login`) — used for relevance
  filtering, summaries, and reports. No OpenAI key is stored by the app.

## Quick start

```bash
# Backend (default port 8000)
cd backend
cp .env.example .env        # set PC_OPENALEX_EMAIL; PC_SEMANTIC_SCHOLAR_API_KEY optional
uv sync
uv run uvicorn app.main:app --reload

# Frontend (default port 3000)
cd web
npm install
npm run dev                 # open http://localhost:3000
```

The frontend calls the backend at `http://127.0.0.1:8000` by default. To point it
elsewhere, set `NUXT_PUBLIC_API_BASE` (see `web/.env.example`), e.g. if port 8000
is taken: run the backend with `--port 8008` and set
`NUXT_PUBLIC_API_BASE=http://127.0.0.1:8008`.

## How it works

1. **Resolve** — search Semantic Scholar + OpenAlex, pick the seed from candidates.
2. **Expand** — bidirectional BFS over references (backward) and citations (forward).
3. **Filter** — each level is cheaply prefiltered, then scored by Codex; the most
   relevant papers (loose threshold + top-K) are kept and summarized.
4. **Report** — a progressive report at depth 3, again at 4 and 5, plus a final synthesis.
5. **Enrich** — a DuckDuckGo web search adds an external-context report (surveys,
   recent / follow-up work) that may not appear in the citations.
6. **Explore & ask** — interactive graph + AI summaries, and a grounded Q&A tab to
   interrogate the corpus; export BibTeX / Markdown.

## Tuning cost & breadth

The defaults are **loose** (broad, slower) per design. Each Codex call costs time
and tokens, and depth-3–5 bidirectional expansion can be large, so two guardrails
bound every job (reported, never silent, when hit):

- `PC_MAX_NODES` (default 600) — global cap on graph size
- `PC_MAX_CODEX_CALLS` (default 200) — global cap on Codex calls per job

Make runs cheaper/faster by lowering `PC_PER_LEVEL_K`, `PC_MAX_CANDIDATES_PER_LEVEL`,
and `PC_MAX_CODEX_CALLS`. See `backend/.env.example` for all knobs.

## Model & provider settings

The **Settings** page (or `PUT /settings`) configures, for all Codex calls:

- **Model** — `gpt-5.5` or `gpt-5.4`
- **Reasoning effort** — `low` / `medium` / `high` / `xhigh`
- **OpenAI endpoint + API key** (optional) — to use your own key / a compatible
  endpoint instead of the local `codex login`. The key is stored locally and only
  returned masked; it is sent only to your configured endpoint.

## Tests

```bash
cd backend && uv run pytest        # 46 tests
```

## Status

Working end-to-end (verified against live Semantic Scholar / OpenAlex / Codex).
See `docs/superpowers/specs/` for the design.
