# Ariadne

**AI-built citation maps so you never miss a key paper.**

English | [繁體中文](README.zh-TW.md) · 📖 [Documentation](https://treeleaves30760.github.io/Ariadne/)

Ariadne builds a **bidirectional citation graph** from a seed paper or benchmark, lets the
**OpenAI Codex CLI** filter each level for relevance and write short explanations, and lets
you explore the result as an interactive graph with **progressive reports** — so a PhD
student reading papers, scouting research directions, or writing related work never misses a
key paper.

- **Input** a paper title / DOI / arXiv id / benchmark name → pick from candidates.
- **Expand** references (backward) and citations (forward) to depth 3–5.
- **Filter** each level with Codex (loose by default), keeping the most relevant papers.
- **Report** progressively: a report at depth 3, again at 4 and 5, a final synthesis, plus a
  **web-context report** (DuckDuckGo) that surfaces surveys / recent work beyond the graph.
- **Ask the literature** — a tool-augmented chatbot: multi-turn Q&A grounded in the corpus
  (clickable citations), optionally verified with web search and by reading open-access PDFs.
- **Rank** papers by an **importance score** (relevance × citations × top-venue) in a
  sortable papers table.
- **Explore** a readable Cytoscape graph (rings-by-depth or force layout, responsive zoom,
  hover titles, neighbour highlight) with per-paper AI summaries, a live activity feed, and
  open-access PDF links; export BibTeX / Markdown.
- **Manage** saved maps — rename, label, or delete them.
- **Configure** the model (gpt-5.5 / gpt-5.4 × low→xhigh reasoning) and your own
  OpenAI-compatible endpoint / API key on the Settings page.

## Layout

```
backend/   FastAPI service (uv, Python 3.13) — sources, graph, ai, jobs, storage, api
web/       Nuxt frontend (Vue 3, TypeScript) — input, graph, reports
docs/      Docusaurus site (English + 繁體中文)
```

## Quick start

```bash
# Backend (use --port 8008 if 8000 is taken)
cd backend
cp .env.example .env        # set PC_OPENALEX_EMAIL; PC_SEMANTIC_SCHOLAR_API_KEY optional
uv sync
uv run uvicorn app.main:app --reload --port 8008

# Frontend
cd web
cp .env.example .env        # set NUXT_PUBLIC_API_BASE=http://127.0.0.1:8008
npm install
npm run dev                 # open http://localhost:3000
```

**Prerequisites:** Python 3.12+ with [uv](https://docs.astral.sh/uv/), Node 20+ / npm, and
the **Codex CLI** logged in (`codex login`). No OpenAI key is stored by the app.

Full install / run / feature walkthrough: **[Documentation](https://treeleaves30760.github.io/Ariadne/)**
(or browse the source in [`docs/`](docs/)).

## Tests

```bash
cd backend && uv run pytest        # 52 tests
cd web && npm run build            # frontend production build
```

## Status

Working end-to-end (verified against live Semantic Scholar / OpenAlex / Codex).
