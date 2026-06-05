# Paper Connector — 引用圖譜建構與 AI 輔助閱讀系統

## Context

博士生在閱讀論文、找研究方向、撰寫論文時,需要不漏掉任何關鍵論文。現有工具(Connected Papers、Semantic Scholar)只給引用圖,不會幫你判斷「哪些跟我的題目真正相關」也不會寫說明。

本系統:輸入一篇論文或 benchmark 名稱 → 自動往前(references)與往後(citations)雙向展開引用圖 → 用 **OpenAI Codex CLI** 對每一層候選論文做相關性篩選、為相關論文撰寫簡短說明 → 透過網頁顯示互動引用圖、論文說明、依「解法/主題」分群的報告。深度 3–5 可調,採**漸進模式**:完成第 3 層出一份報告,第 4、5 層各再出一份,最後出一份完整綜合報告。

目標目錄 `D:\Github\paper-connector` 目前為空,全新專案。

### 已確認的決策(來自 brainstorming)
- **資料來源**:Semantic Scholar Graph API + OpenAlex 結合(S2 為主、OpenAlex 補齊缺漏)
- **AI 介面**:OpenAI Codex CLI(`codex exec`,已安裝 v0.136.0)
- **技術棧**:後端 Python FastAPI(uv 管理,Python 3.13)+ 前端 Nuxt(Nuxt 4 / Vue 3 / TypeScript,Node v24)
- **深度**:3–5 可調,漸進報告(L3 / L4 / L5 / 最終)
- **報告/說明語言**:可切換,**預設英文**
- **輸入歧義**:搜尋後**列候選讓使用者選**
- **篩選取向**:**寬鬆**(低門檻、大 K、廣覆蓋、較慢),但保留可設定的硬性安全上限避免失控

### 環境(已驗證)
- codex-cli 0.136.0(`codex exec` 支援 `--output-schema`、`-o/--output-last-message`、`-s read-only`、`--skip-git-repo-check`、`-m`)
- node v24.14.1 / npm 11.11.0 / python 3.13.12(指令為 `python`)/ uv 0.11.1 / git 2.53

---

## 架構總覽

```
┌─────────────────────────────── Nuxt 前端 ───────────────────────────────┐
│  輸入頁 → 候選選擇 → Job 進度(SSE) → 引用圖(Cytoscape) → 報告 / 匯出  │
└───────────────────────────────────┬──────────────────────────────────────┘
                                     │ REST + SSE
┌────────────────────────────── FastAPI 後端 ──────────────────────────────┐
│ api/        路由層 (resolve, jobs, graph, reports, papers, SSE events)     │
│ jobs/       背景任務編排 (asyncio + SQLite 狀態機, 漸進報告)               │
│ graph/      BFS 雙向展開引擎 (預篩 → Codex 相關性篩選 → 預算/去重)         │
│ ai/         Codex 包裝 (relevance / summarize / report, 結構化輸出)        │
│ sources/    資料來源 (semantic_scholar, openalex, merge 正規化去重)        │
│ storage/    SQLite (papers, edges, jobs, level_snapshots, reports, cache)  │
└───────────────────────────────────────────────────────────────────────────┘
        │ HTTP                          │ subprocess
   Semantic Scholar / OpenAlex      codex exec (read-only sandbox)
```

### 核心資料流
1. 使用者輸入 paper/benchmark 名稱或 ID → `POST /resolve` 經 S2/OpenAlex 搜尋回候選清單。
2. 使用者選定種子論文 + 參數(深度、語言、K、門檻)→ `POST /jobs` 建立背景任務。
3. 背景任務逐層 BFS:
   - 取目前 frontier 每篇的 references + citations 當候選。
   - **便宜預篩**(年份、引用數、領域、關鍵字/標題重疊、abstract 啟發式)縮小候選。
   - **Codex 批次相關性評分**(`--output-schema` 回 `[{paperId, relevance, reason}]`),低門檻保留(寬鬆)。
   - 套用 per-level top-K 預算 + 全域硬上限,寫入 nodes/edges,通過者進入下一層 frontier。
4. 完成第 N 層(N≥3)後產生該層報告;達設定最大深度後產生最終綜合報告。
5. 前端透過 SSE 即時顯示進度,完成後可瀏覽互動圖 + 各層報告。

---

## 後端模組設計 (FastAPI, package `app/`)

### `app/models.py` — 領域模型 (Pydantic / SQLModel)
- `Paper`: `id`(canonical, 優先 DOI 否則 `s2:`/`oa:` 前綴)、`title`、`abstract`、`tldr`、`year`、`authors`、`venue`、`citationCount`、`fieldsOfStudy`、`externalIds`(DOI/arXiv/S2/OpenAlex)、`url`。
- `Edge`: `src`、`dst`、`direction`(`reference`|`citation`)、`level`。
- `Job`: `id`、`status`、`params`、`progress`、`createdAt`、`error`。
- `RelevanceResult`、`Summary`、`Report` 等。

### `app/sources/` — 資料來源 adapters
- `semantic_scholar.py`:`get_paper`、`get_references`、`get_citations`、`search`、`batch`(`/graph/v1/paper/batch`)。支援 DOI / `arXiv:` / S2 id。帶 optional API key,1 req/s 節流 + 重試(429 backoff)。fields 取 `title,abstract,tldr,year,authors,venue,citationCount,fieldsOfStudy,externalIds,references,citations`。
- `openalex.py`:`get_work`、`get_referenced`(`referenced_works`)、`get_cited_by`(`filter=cites:<id>`)、`search`。polite pool 帶 email(env)。`abstract_inverted_index` → 還原 abstract。
- `merge.py`:以 DOI / 正規化標題為鍵合併兩來源成 canonical `Paper`,去重、補齊欄位(abstract/tldr 優先 S2,缺則 OpenAlex)。
- 重點:**沿用** S2 batch 端點批次抓取以降低請求數;所有原始回應寫入 `storage` 的 `api_cache` 表(以 url 為鍵)避免重抓。

### `app/ai/codex_client.py` — Codex CLI 包裝(核心可重用元件)
- `run_structured(prompt, schema_dict, model=None) -> dict`:
  - 寫 schema 到暫存檔,執行
    `codex exec --skip-git-repo-check -s read-only --output-schema <schema> -o <out> [--ephemeral] [-m <model>] "<prompt>"`(prompt 過長改由 stdin 傳入)。
  - 讀 `<out>` 解析最終訊息為 JSON;失敗則重試 / 降級。
  - `asyncio.Semaphore` 控制併發(預設 3–4),逾時保護,結構化錯誤。
- 全域守門:每個 job 的 Codex 呼叫次數上限(config),逼近上限時提前收斂並記錄(不靜默截斷,寫進 job log)。

### `app/ai/relevance.py` — 相關性篩選
- 輸入:種子主題畫像(title + abstract + Codex 抽出的 research problem/keywords)+ 一批候選(title+abstract+tldr)。
- 輸出 schema:`{"results":[{"paperId":str,"relevance":0..1,"reason":str}]}`。
- 一次批次評多篇(預設 ~20/批),寬鬆門檻(預設 relevance ≥ 0.25,可調)。

### `app/ai/summarize.py` — 論文簡短說明
- 對保留下來的論文,Codex 寫 2–3 句:這篇在解什麼問題、用什麼方法、與種子題目的關聯。語言依 job 參數(預設英文)。批次處理。

### `app/ai/report.py` — 漸進報告 + 最終報告
- 層級報告(L3/L4/L5):依「解法/主題」對該層(累積)論文分群、列出 must-read、各群摘要、與種子題目的關聯、研究空白/可能方向。
- 最終報告:跨全圖綜合 + 建議閱讀順序 + BibTeX 區塊。
- 用 `--output-schema` 產生結構化報告(sections/clusters/mustReads/gaps),前端再渲染為 Markdown。

### `app/graph/expander.py` — BFS 雙向展開引擎
- `expand(seed, params, emit) -> graph`:逐層處理,呼叫 sources 抓候選 → `prefilter` → `relevance` → top-K 預算 + 去重 + cycle 防護 → 寫 DB → `emit` 進度事件。
- `prefilter.py`:便宜啟發式(年份範圍、最低引用數、領域過濾、標題/關鍵字重疊)先砍量再送 Codex。
- 寬鬆預設:per-level K 大(如 80)、relevance 門檻低;但設全域硬上限(如 max_nodes 600、max_codex_calls 200,皆可調),保護成本與時間。

### `app/jobs/runner.py` — 背景任務編排
- in-process `asyncio` 任務 + SQLite 持久化 job/進度/報告(不引入 Celery,降複雜度;Windows 友善)。
- 狀態機:`queued → resolving → expanding(L1..Lmax) → reporting(Ln) → ... → completed | failed`。
- 每層完成觸發報告生成;進度事件推到 in-memory pub/sub 供 SSE。
- 服務重啟可從 SQLite 恢復 job 結果(進行中任務標記 interrupted)。

### `app/storage/db.py` — SQLite (SQLModel/SQLAlchemy)
- 表:`papers`、`edges`、`jobs`、`level_snapshots`(每層快照供漸進報告)、`reports`、`summaries`、`api_cache`。

### `app/api/routes.py` — FastAPI 路由
- `POST /resolve` → 候選清單(標題/作者/年份/來源/citationCount)。
- `POST /jobs` → 建立任務(seed id + depth + language + K + thresholds)。
- `GET /jobs/{id}` → 狀態 + 進度。
- `GET /jobs/{id}/events` → **SSE** 即時進度。
- `GET /jobs/{id}/graph` → nodes + edges(供 Cytoscape)。
- `GET /jobs/{id}/reports` / `GET /jobs/{id}/reports/{level}` → 報告(含 final)。
- `GET /papers/{id}` → 論文詳情 + summary。
- `GET /jobs/{id}/export?format=bibtex|markdown` → 匯出閱讀清單。
- CORS 允許 Nuxt dev server。

---

## 前端設計 (Nuxt 4, `web/`)

- **輸入頁** (`pages/index.vue`):輸入 paper/benchmark/DOI/arXiv;進階:深度(3–5)、語言(預設 English)、篩選取向(寬鬆預設)。
- **候選選擇** (`pages/resolve.vue` 或 modal):列 `POST /resolve` 結果,點選確認 → 建 job。
- **任務/圖譜頁** (`pages/jobs/[id].vue`):
  - 上方:SSE 即時進度條(目前層、已收論文數、Codex 呼叫數)。
  - 主區:**Cytoscape.js** 互動引用圖(往前/往後不同色、依群著色、依相關性調大小);點節點 → 側欄顯示論文詳情 + AI 說明 + 相關性 + 外部連結。
  - 分頁:**報告**(L3/L4/L5/最終,Markdown 渲染,含分群、must-read、研究空白)。
  - **匯出**:BibTeX / Markdown 閱讀清單。
- API 層 `composables/useApi.ts` 封裝 REST + SSE(`EventSource`)。
- 圖形庫選 Cytoscape.js(成熟、效能佳、適合引用網路);報告 Markdown 用 `markdown-it`。

---

## 設定 / 機密
- 後端 `.env`:`SEMANTIC_SCHOLAR_API_KEY`(選填)、`OPENALEX_EMAIL`(polite pool)、`CODEX_MODEL`(選填)、併發/上限參數。Codex 認證沿用本機 `codex login`(不需在 app 放 OpenAI key)。
- `.env.example` 提供範本;`.gitignore` 排除 `.env`、`*.db`、`node_modules`、`.venv`。

---

## 實作里程碑(每階段皆可獨立驗證)

> 雖然 v1 目標是深度 3–5 + 漸進報告,但分階段建置以確保隨時有可運作切片。

- **M0 鷹架**:`uv init` 後端、`npx nuxi init web` 前端;`app/` 套件骨架、SQLite、設定載入、`/health`。
- **M1 資料來源 + resolve**:S2 + OpenAlex adapters + merge + cache;`POST /resolve`;`GET /papers/{id}`。深度 1 抓 refs/citations(尚無 AI)。
- **M2 Codex 整合**:`codex_client` 結構化輸出 + relevance 批次評分 + summarize。以小樣本驗證結構化 JSON 正常。
- **M3 BFS + 漸進報告 + Jobs**:expander(預篩→Codex→預算)、jobs runner 狀態機、SSE、層級報告 + 最終報告。深度 3–5 端到端跑通。
- **M4 Nuxt 前端**:輸入 → 候選 → job 進度(SSE)→ Cytoscape 圖 → 報告 → 匯出。
- **M5 收尾**:節流/重試/快取強化、成本守門驗證、錯誤處理、README、端到端驗證。

實作將採 TDD(sources adapters、merge、prefilter、codex_client 解析、expander 預算邏輯皆有單元測試;API 用 FastAPI TestClient;Codex 與外部 API 在測試中 mock)。

---

## 驗證方式(端到端)

1. **後端單元/整合測試**:`uv run pytest`(adapters 用錄製/mock 回應;expander 用假資料驗證預算/去重/cycle;codex_client 用假 `codex` 回應驗證解析)。
2. **Codex 連通性**:腳本對 3–5 篇真實論文跑一次 relevance 評分,確認 `--output-schema` 回合法 JSON。
3. **小規模真實跑**:用一篇知名論文(如某 benchmark 論文)深度 3 跑完整流程,檢查:候選解析正確、圖有合理節點/邊、L3 報告產出、SSE 有進度。
4. **前端**:`npm run dev` 起 Nuxt,走完輸入→候選→進度→圖→報告→匯出;用 Claude-in-Chrome MCP 截圖驗證圖與報告渲染。
5. **成本守門**:確認逼近 `max_codex_calls` / `max_nodes` 時提前收斂並在 job log 記錄(非靜默截斷)。

---

## 主要風險與對策
- **深度 3–5 指數爆量** → 便宜預篩 + Codex 批次評分 + per-level top-K + 全域硬上限(寬鬆預設但有天花板)。
- **Codex 速度/成本** → 批次化(一次評多篇)、併發上限、快取相關性/摘要結果、可選較小模型。
- **API 速率限制** → 節流 + 429 backoff + S2 batch 端點 + `api_cache` 去重抓取。
- **論文去重/ID 對齊** → DOI/正規化標題為鍵的 merge 層。
- **Windows 環境** → 避免 Celery/Redis,用 in-process asyncio + SQLite;subprocess 呼叫 codex 用絕對/PATH 解析。

> 核准後:我會將此設計另存為正式 spec(`docs/superpowers/specs/`)並用 writing-plans 產出逐步實作計畫,再進入實作。
