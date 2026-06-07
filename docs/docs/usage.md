---
sidebar_position: 2
---

# Usage guide

How to install, run, and use every feature of Ariadne.

---

## 1. Requirements

| Tool | Version | Used for |
|------|---------|----------|
| Python | 3.12+ | Backend (managed with [uv](https://docs.astral.sh/uv/)) |
| Node | 20+ (24 recommended) + npm | Nuxt frontend |
| Codex CLI | logged in (`codex login`) | Relevance filtering, summaries, reports, Ask |

> By default Ariadne uses your local `codex login` (ChatGPT account). The app stores **no**
> OpenAI key unless you enter one on the Settings page (see §6).

---

## 2. Install & run

### With Docker (no build)

Run everything with prebuilt images — no clone, no build:

```bash
curl -fsSL https://raw.githubusercontent.com/treeleaves30760/Ariadne/main/compose.yaml -o compose.yaml
docker compose up -d
docker compose exec backend codex login --device-auth   # one-time, your ChatGPT account
# open http://localhost:8080
```

Needs Docker (Compose v2.23+). A Caddy reverse proxy serves the UI and the API on **one
origin** (`http://localhost:8080`), so there is nothing else to configure — the only required
step is the one-time `codex login` (each user signs in with their own ChatGPT subscription).
Optional: set `PC_OPENALEX_EMAIL` in a `.env` next to `compose.yaml` (OpenAlex polite pool),
and change the port with `PUBLIC_PORT`. Developers building from source:
`git clone … && cd Ariadne && docker compose up -d --build`.

### Backend (from source)

```bash
cd backend
cp .env.example .env          # set PC_OPENALEX_EMAIL; PC_SEMANTIC_SCHOLAR_API_KEY optional
uv sync
uv run uvicorn app.main:app --reload --port 8008
```

Health check: `curl http://127.0.0.1:8008/health` → `{"status":"ok"}`

### Frontend

```bash
cd web
cp .env.example .env          # set NUXT_PUBLIC_API_BASE=http://127.0.0.1:8008
npm install
npm run dev                   # open http://localhost:3000
```

> The frontend calls `http://127.0.0.1:8000` by default. If the backend runs on another
> port (e.g. 8000 is taken so you used 8008), set `NUXT_PUBLIC_API_BASE` in `web/.env`.

---

## 3. The basic flow (input → report)

1. **Enter a seed** — paper title / DOI / arXiv id / benchmark name on the home page.
2. **Pick a candidate** — Ariadne searches Semantic Scholar + OpenAlex and lists matches
   (title, authors, year, citation count, source). Choose the right one.
3. **Set parameters**:
   - **Depth (3–5)** — how many levels to expand bidirectionally. Deeper = broader, slower,
     more Codex calls.
   - **Language** — report and summary language (default English).
4. **Create the job** — you land on the map page with live progress.

### Progress & progressive reports

- The top of the page shows **live progress** (current level, papers collected, Codex
  calls) and an **activity feed**, updated in real time over SSE.
- Reports are **progressive**: one at depth 3, again at 4 and 5, a **final synthesis** when
  everything finishes, plus a **web-context report** (DuckDuckGo) that adds surveys /
  recent work beyond the citations.

### Cost guardrails

Defaults are "loose" (broad, slow). Two hard caps bound every job; when hit, the job
converges early and logs it (never silent):

- `PC_MAX_NODES` (default 600) — global cap on graph size
- `PC_MAX_CODEX_CALLS` (default 200) — global cap on Codex calls per job

To go faster / cheaper, lower `PC_PER_LEVEL_K`, `PC_MAX_CANDIDATES_PER_LEVEL`, and
`PC_MAX_CODEX_CALLS`. All knobs are in `backend/.env.example`.

---

## 4. Exploring results (tabs on the map page)

### Graph
- Interactive Cytoscape graph; rings-by-depth or force layout.
- **Responsive zoom**: mouse wheel / `＋` `－` buttons; **Fit** for overview, **Focus** to
  zoom into a selected node's neighbourhood, **Re-layout**, toggle labels.
- Node size by importance, colour by level; hover shows the title, clicking highlights
  neighbours.
- Click a node → side panel with details, AI summary, relevance, importance, top-venue ★,
  PDF / DOI links.

### Papers
- Sortable table: year, citation count, relevance, importance, level.
- **Importance score** = `0.45 × relevance + 0.40 × log(citations) + 0.15 × top-venue bonus`,
  shown as a bar; papers from top venues (NeurIPS / ICML / ICLR / CVPR / ACL / Nature …)
  are marked ★.
- Clicking a row jumps to that node on the graph; PDF / DOI open directly.

### Reports
- L3 / L4 / L5 / final / web tabs, rendered as Markdown.
- Topic clusters, must-read lists, research gaps / directions; clicking a paper chip jumps
  to the graph.

### Ask the literature
- Multi-turn chatbot whose answers are **grounded in the corpus**, with clickable citations.
- With **tools** enabled, the assistant can also: search DuckDuckGo and download + read
  open-access PDF full text to strengthen accuracy. Each answer shows the tools used
  (🌐 web / 📄 pdf), its sources, and a confidence value.

### Export
- One-click export of the reading list as **BibTeX** or **Markdown**.

---

## 5. Managing saved maps

The **Recent** section on the home page lists every map you've built:

- **Label** — defaults to the seed paper's title; you can **rename** it to a custom label
  (clear it to revert to the seed title).
- **Delete** — permanently removes the map and all its data (papers, edges, reports,
  summaries, Q&A). This cannot be undone.

API: `PATCH /jobs/{id}` (rename), `DELETE /jobs/{id}` (delete).

---

## 6. Model & provider settings

Open **Settings** (top-right). These apply to all Codex calls (filtering, summaries,
reports, Ask):

- **Model** — `gpt-5.5` or `gpt-5.4`.
- **Reasoning effort** — `low` / `medium` / `high` / `xhigh`.
- **OpenAI endpoint + API key** (optional) — to use your own key or a compatible endpoint
  instead of the local `codex login`.

> **Security**: the key is stored only in local SQLite, returned masked (`…1234`) on read,
> sent only to your configured endpoint; leave it blank to keep the existing key. Enter the
> key **yourself** — by design no one should fill in credentials on your behalf. Without a
> key, Codex uses your local `codex login`.

---

## 7. How it works

1. **Resolve** — search S2 + OpenAlex, pick the seed.
2. **Expand** — bidirectional BFS over references (backward) and citations (forward).
3. **Filter** — each level is cheaply prefiltered, then scored by Codex; the most relevant
   papers (loose threshold + top-K) are kept and summarised.
4. **Report** — progressive L3 / L4 / L5 reports + a final synthesis.
5. **Enrich** — a DuckDuckGo web search adds an external-context report.
6. **Explore & ask** — interactive graph + AI summaries + grounded Q&A; export the list.

Sources are merged and de-duplicated across S2 and OpenAlex on DOI / normalised title; all
external responses are cached in `api_cache` to avoid re-fetching.

---

## 8. Tests

```bash
cd backend && uv run pytest      # 142 tests, 100% coverage
cd web && npm run build          # frontend production build
```

---

## 9. Troubleshooting

| Symptom | Fix |
|---------|-----|
| Frontend can't reach backend | Make sure `NUXT_PUBLIC_API_BASE` in `web/.env` matches the backend's actual port |
| Port 8000 already in use | Run the backend with `--port 8008` and set `NUXT_PUBLIC_API_BASE` to match |
| Codex hangs | Ensure you've run `codex login`; the prompt is passed via stdin (built in) so it never waits on stdin |
| Job converges early | Usually `PC_MAX_NODES` / `PC_MAX_CODEX_CALLS` was hit — raise or lower to trade off cost |
| Missing abstracts / PDFs | The source itself lacks them; S2 and OpenAlex backfill each other but gaps can remain |
