---
sidebar_position: 1
sidebar_label: 總覽
slug: /
---

# Ariadne

**AI 自動建構引用圖譜，讓你一篇關鍵論文都不漏。**

Ariadne 從一篇論文或 benchmark 出發，**雙向**展開引用圖（references 與 citations），
用 **OpenAI Codex CLI** 對每一層做相關性篩選並撰寫簡短說明，讓你透過互動圖與
**漸進報告** 探索結果 —— 幫助博士生在閱讀論文、找研究方向、撰寫 related work 時，
不漏掉任何一篇關鍵論文。

## 它能做什麼

- **輸入** 論文標題 / DOI / arXiv id / benchmark 名稱 → 從候選中挑選。
- **展開** references（往前）與 citations（往後），深度 3–5。
- **篩選** 每一層用 Codex（預設寬鬆），保留最相關的論文。
- **報告** 採漸進模式：第 3 層出一份、第 4、5 層各再出一份、最後一份綜合報告，
  另加一份 **Web 補充報告**（DuckDuckGo），補上引用圖外的綜述 / 近期工作。
- **向語料庫提問** —— 帶工具的 chatbot：多輪、以語料庫為根據（可點擊引用），
  並可選擇用網路搜尋與閱讀開放取用 PDF 來驗證。
- **排序** 以 **重要性分數**（relevance × 被引用數 × 頂會）在可排序表格中呈現。
- **探索** 易讀的 Cytoscape 圖（rings-by-depth 或 force 佈局、靈敏縮放、hover 標題、
  鄰居高亮），含每篇 AI 說明、即時活動串流、開放取用 PDF 連結；可匯出 BibTeX / Markdown。
- **管理** 已建立的 maps：重新命名、自訂標籤、或刪除。
- **設定** 模型（gpt-5.5 / gpt-5.4 × low→xhigh 推理強度）與你自己的
  OpenAI 相容端點 / API key（於設定頁）。

## 接著

- [使用說明 →](./usage.md) —— 安裝、啟動，以及逐項功能導覽。
- 原始碼：[github.com/treeleaves30760/Ariadne](https://github.com/treeleaves30760/Ariadne)
