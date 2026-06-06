---
sidebar_position: 1
sidebar_label: Overview
slug: /
---

# Ariadne

**AI-built citation maps so you never miss a key paper.**

Ariadne starts from one paper or benchmark, expands its citation graph in **both
directions** (references and citations), uses the **OpenAI Codex CLI** to filter each
level for relevance and write short explanations, and lets you explore the result as an
interactive graph with **progressive reports** — so a PhD student reading papers,
scouting research directions, or writing related work never misses a key paper.

## What it does

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
  zoom, hover titles, neighbour highlight) with per-paper AI summaries, a live activity
  feed, and open-access PDF links; export BibTeX / Markdown.
- **Manage** saved maps: rename them, give them custom labels, or delete them.
- **Configure** the model (gpt-5.5 / gpt-5.4 × low→xhigh reasoning) and your own
  OpenAI-compatible endpoint / API key on the Settings page.

## Next

- [Usage guide →](./usage.md) — install, run, and a feature-by-feature walkthrough.
- Source: [github.com/treeleaves30760/Ariadne](https://github.com/treeleaves30760/Ariadne)
