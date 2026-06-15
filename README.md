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

## Run with Docker (no build)

Run the whole stack with prebuilt images — no clone, no build:

```bash
curl -fsSL https://raw.githubusercontent.com/treeleaves30760/Ariadne/main/compose.yaml -o compose.yaml
docker compose up -d
docker compose exec backend codex login --device-auth   # one-time, your ChatGPT account
# open http://localhost:8080
```

Needs Docker (Compose v2.23+). The only required step is the one-time `codex login` — each
user signs in with their own ChatGPT subscription. Optional: put `PC_OPENALEX_EMAIL=...` in a
`.env` beside `compose.yaml` (OpenAlex polite pool); change the port with
`PUBLIC_PORT=9000 docker compose up -d`. To build from source instead:
`git clone … && cd Ariadne && docker compose up -d --build`.

## Quick start (from source)

```bash
# Backend (default port 8008; use --port if 8008 is taken)
cd backend
cp .env.example .env        # set PC_OPENALEX_EMAIL; PC_SEMANTIC_SCHOLAR_API_KEY optional
uv sync
uv run uvicorn app.main:app --reload --port 8008

# Frontend
cd web
cp .env.example .env        # already points at http://127.0.0.1:8008; edit if backend uses another port
npm install
npm run dev                 # open http://localhost:3000
```

**Prerequisites:** Python 3.12+ with [uv](https://docs.astral.sh/uv/), Node 20+ / npm, and
the **Codex CLI** logged in (`codex login`). No OpenAI key is stored by the app.

Full install / run / feature walkthrough: **[Documentation](https://treeleaves30760.github.io/Ariadne/)**
(or browse the source in [`docs/`](docs/)).

## Tests

```bash
cd backend && uv run pytest        # 142 tests, 100% coverage (enforced)
cd web && npm run build            # frontend production build
```

## Status

Working end-to-end (verified against live Semantic Scholar / OpenAlex / Codex).
