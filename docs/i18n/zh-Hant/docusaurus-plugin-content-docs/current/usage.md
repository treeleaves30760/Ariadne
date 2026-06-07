---
sidebar_position: 2
---

# 使用說明

如何安裝、啟動，以及使用 Ariadne 的每一項功能。

---

## 1. 環境需求

| 工具 | 版本 | 用途 |
|------|------|------|
| Python | 3.12+ | 後端（以 [uv](https://docs.astral.sh/uv/) 管理） |
| Node | 20+（建議 24）+ npm | 前端 Nuxt |
| Codex CLI | 已 `codex login` | 相關性篩選、摘要、報告、Ask 問答 |

> 預設使用本機 `codex login`（ChatGPT 帳號）。app **不會**儲存任何 OpenAI key，
> 除非你在設定頁自己填（見 §6）。

---

## 2. 安裝與啟動

### 用 Docker(免 build)

用預建 image 把整套開起來 —— 不必 clone、不必 build:

```bash
curl -fsSL https://raw.githubusercontent.com/treeleaves30760/Ariadne/main/compose.yaml -o compose.yaml
docker compose up -d
docker compose exec backend codex login --device-auth   # 一次性,用你自己的 ChatGPT 帳號
# 開 http://localhost:8080
```

需要 Docker(Compose v2.23+)。Caddy 反向代理把 UI 與 API 收在**同一個來源**
(`http://localhost:8080`),所以沒有別的要設定 —— 唯一必要步驟是一次性的 `codex login`
(每位使用者各自用自己的 ChatGPT 訂閱登入)。選填:在 `compose.yaml` 旁放 `.env` 設
`PC_OPENALEX_EMAIL`(OpenAlex polite pool)、用 `PUBLIC_PORT` 改埠。開發者從原始碼建:
`git clone … && cd Ariadne && docker compose up -d --build`。

### 後端(從原始碼)

```bash
cd backend
cp .env.example .env          # 設定 PC_OPENALEX_EMAIL；PC_SEMANTIC_SCHOLAR_API_KEY 選填
uv sync
uv run uvicorn app.main:app --reload --port 8008
```

健康檢查：`curl http://127.0.0.1:8008/health` → `{"status":"ok"}`

### 前端

```bash
cd web
cp .env.example .env          # 設定 NUXT_PUBLIC_API_BASE=http://127.0.0.1:8008
npm install
npm run dev                   # 開 http://localhost:3000
```

> 前端預設打 `http://127.0.0.1:8000`。若後端用其他埠（例如 8000 已被佔用而改用 8008），
> 務必在 `web/.env` 設 `NUXT_PUBLIC_API_BASE` 指向正確埠。

---

## 3. 基本流程（從輸入到報告）

1. **輸入種子**：在首頁輸入論文標題 / DOI / arXiv id / benchmark 名稱。
2. **選候選**：系統用 Semantic Scholar + OpenAlex 搜尋，列出候選（標題、作者、年份、
   被引用數、來源）。點選正確的那一篇。
3. **設定參數**：
   - **深度（Depth 3–5）**：雙向展開層數。越深越廣、越慢、Codex 呼叫越多。
   - **語言**：報告與說明語言，預設 English。
4. **建立 Job**：送出後進入該 map 的頁面，即時顯示進度。

### 進度與漸進報告

- 頁面上方有 **即時進度**（目前層、已收論文數、Codex 呼叫數）與 **活動串流**
  （activity feed），透過 SSE 即時更新。
- 採**漸進模式**：跑到第 3 層出一份報告，第 4、5 層各再出一份，全部完成後出一份
  **最終綜合報告**，另加一份 **Web 補充報告**（DuckDuckGo，補上引用圖外的綜述 /
  近期工作）。

### 成本守門

預設「寬鬆」（廣、慢）。每個 Job 有兩道硬上限，逼近時會提前收斂並在 log 記錄（不靜默截斷）：

- `PC_MAX_NODES`（預設 600）— 圖總節點上限
- `PC_MAX_CODEX_CALLS`（預設 200）— 每個 Job 的 Codex 呼叫上限

要更快 / 更省：調低 `PC_PER_LEVEL_K`、`PC_MAX_CANDIDATES_PER_LEVEL`、`PC_MAX_CODEX_CALLS`。
所有旋鈕見 `backend/.env.example`。

---

## 4. 瀏覽結果（Job 頁分頁）

### Graph（引用圖）
- Cytoscape 互動圖，可 rings-by-depth 或 force 佈局。
- **靈敏縮放**：滑鼠滾輪 / `＋`、`－` 鈕；**Fit** 全覽、**Focus** 聚焦選取節點鄰域、
  **Re-layout** 重排、可切換標籤。
- 節點大小依重要性、顏色依層級；hover 顯示標題，點節點高亮鄰居。
- 點節點 → 側欄顯示論文詳情、AI 說明、relevance、importance、頂會 ★、PDF / DOI 連結。

### Papers（論文清單）
- 可排序表格：年份、被引用數、relevance、importance、層級。
- **Importance score** = `0.45 × relevance + 0.40 × log(被引用數) + 0.15 × 頂會加成`，
  以長條視覺化；發表於頂會（NeurIPS / ICML / ICLR / CVPR / ACL / Nature …）標 ★。
- 點任一列會跳到圖上對應節點；PDF / DOI 直接開啟。

### Reports（報告）
- L3 / L4 / L5 / 最終 / Web 各分頁，Markdown 渲染。
- 含主題分群、must-read 清單、研究空白 / 方向；可點論文 chip 跳到圖。

### Ask（向語料庫提問）
- 多輪對話式 chatbot，回答**以語料庫為根據**並附可點擊引用。
- 開啟 **工具** 後，AI 可額外：DuckDuckGo 搜尋、下載並閱讀開放取用 PDF 全文，
  以強化答案正確性。每則回答會標示用到的工具（🌐 web / 📄 pdf）與來源清單、信心值。

### 匯出
- 一鍵匯出閱讀清單為 **BibTeX** 或 **Markdown**。

---

## 5. 管理已建立的 Maps

首頁的 **Recent** 區列出所有已建立的 map：

- **標籤**：預設顯示種子論文標題；可 **重新命名**（rename）成自訂名稱，留空則還原為種子標題。
- **刪除**：永久刪除該 map 及其所有資料（論文、邊、報告、摘要、Q&A）。此動作不可復原。

對應 API：`PATCH /jobs/{id}`（改名）、`DELETE /jobs/{id}`（刪除）。

---

## 6. 模型與供應商設定（Settings 頁）

右上角 **Settings**。設定會套用到所有 Codex 呼叫（篩選、摘要、報告、Ask）：

- **Model**：`gpt-5.5` 或 `gpt-5.4`。
- **Reasoning effort**：`low` / `medium` / `high` / `xhigh`。
- **OpenAI endpoint + API key**（選填）：若想用自己的 key 或相容端點而非本機
  `codex login`，在此填入。

> **安全**：key 只存在本機 SQLite，GET 時只回傳遮罩（`…1234`）；留空表示沿用既有 key；
> 僅送往你設定的端點。請**自行**輸入 key —— 系統設計上不會、也不應由他人代填憑證。
> 不填 key 時，Codex 沿用本機 `codex login`。

---

## 7. 運作原理

1. **Resolve** — S2 + OpenAlex 搜尋，選種子。
2. **Expand** — 對 references（往前）與 citations（往後）做雙向 BFS。
3. **Filter** — 每層先做便宜預篩，再用 Codex 批次評分，保留最相關者（寬鬆門檻 + top-K）並寫摘要。
4. **Report** — L3 / L4 / L5 漸進報告 + 最終綜合。
5. **Enrich** — DuckDuckGo 補一份外部脈絡報告。
6. **Explore & Ask** — 互動圖 + AI 說明 + 有根據的問答；匯出清單。

資料來源以 DOI / 正規化標題為鍵在 S2 與 OpenAlex 間 merge 去重；所有外部回應寫入
`api_cache` 避免重抓。

---

## 8. 測試

```bash
cd backend && uv run pytest      # 142 個測試,100% 覆蓋率
cd web && npm run build          # 前端 production build
```

---

## 9. 疑難排解

| 症狀 | 處理 |
|------|------|
| 前端打不到後端 | 確認 `web/.env` 的 `NUXT_PUBLIC_API_BASE` 與後端實際埠一致 |
| 8000 埠被佔用 | 後端改 `--port 8008` 並同步設 `NUXT_PUBLIC_API_BASE` |
| Codex 卡住不回 | 確認已 `codex login`；prompt 經 stdin 傳入（已內建）避免等待 stdin |
| Job 提早收斂 | 多半是觸及 `PC_MAX_NODES` / `PC_MAX_CODEX_CALLS`，調高或調低取捨成本 |
| 抓不到某些 abstract / PDF | 來源本身缺漏；系統會在 S2 與 OpenAlex 間互補，仍可能有缺 |
