# AI4BI GUI — UI/UX 改善 Multi-Agent 驗證日誌

> 目標（2026-05-31 使用者設定）：用 Multi-Agent + 10 情境法檢視 GUI 的 UI/UX 手順是否方便。
> 具體痛點：(1) 左側 AI4BI toolbar 階層感不好；(2) Data source 管理不清；(3) 想要 Data source join 功能；(4) 整體更像 Power BI（使用者認為 Power BI 設計很好）。

## 起點現況
左側 sidebar 是 **~25 個面板平鋪一列**（只有 `---` 分隔、無分組標題），絕大多數是預設收合的 expander。**join builder（資料關聯設定）與資料模型檢視其實早已存在**（Round 037/038），但埋在第 13/14 位 → 使用者找不到（正好印證階層問題）。Data source 有兩個入口（上傳、DB 連接器）寫到同一個 user_blocks，但沒有統一的「資料來源管理」。

## 第 1 輪 — Multi-Agent UX 評估（3 lens × 10 情境）
3 個 persona agent：①Power BI 分析師 ②非技術 SMB 老闆（目標用戶）③IA/互動設計師。10 情境＝首次開啟、上傳看圖、上傳第二份並 join、管理資料來源、改圖維度/指標、自然語言問答、新增計算指標、整份篩選、分享發布、找 join 功能。

| Lens | 現況分數 | 最差情境 |
|---|---|---|
| Power BI 分析師 | **47** | 找 join 15、資料來源管理 20、onboarding 25 |
| SMB 老闆 | **33** | join 15、計算指標 20、找 join 20 |
| IA 設計師 | **34/100** | 平鋪 25 項、資料生命週期散落、揭露文法不一致 |

**一致結論**：用 **Power BI 式 view-mode** 取代平鋪列；把 join 升為一級入口；做統一資料來源管理。

## 開發（每輪 test+commit+push，非 e2e 1044 passed）
**Round 147**：sidebar 改為 **view-mode 選擇器**「🔍探索 / 🗂️資料 / 🔗模型 / 📊分析 / 📤分享」，每個 mode 只顯示相關面板（~4-6 項 vs 25）。新增 `render_data_source_manager`（統一列出所有來源＋來源徽章/列數/移除）。join builder 升為 🔗模型 mode 第 1 個面板。持久保留：title、demo 切換、復原/重做/快取 ribbon、篩選 pane、identity（View-as）。**全部既有功能，純重排**。
**Round 148**：把自然語言 ask box 從 sidebar 收合 expander **移到主畫布頂端**（Power BI Copilot 位置，常駐）；join builder 在 🔗模型 mode 預設展開、標籤改白話「把兩份資料用共同欄位連結」。
**Round 148b**：每張圖表下方新增 **per-visual field-well「✏️ 編輯這張圖」**——圖表類型 + 分組（group by）下拉，直接改圖不需打字（走治理 builder）。
**Round 149**：field-well 對「選取中」的視覺**預設展開**（Power BI 行為）。

## 第 2 輪 — Multi-Agent 重新打分
| Lens | 起點 | R147 | R148+b |
|---|---|---|---|
| Power BI 分析師 | 47 | 74.6 | **81.3** |
| SMB 老闆 | 33 | 69.5 | **80.4** |
| IA 設計師 | 34 | 79（預測82） | — |

關鍵情境：找 join 15→**85-90**、資料來源管理 20→**84-90**、onboarding 25→**82-88**、改圖 45→**72-76**、問答 → **85**。

**兩位 agent 最終 VERDICT**：手順已「genuinely convenient and Power-BI-like」「genuinely usable… a clear jump」。使用者四項痛點全部解決：階層感（view-modes）、資料來源管理（統一 manager）、join（升為一級＋預設展開＋AI 偵測 key）、Power BI 感（ribbon／view-modes／Copilot ask box／field-well／filters pane）。

剩餘 ~19 分屬**深度而非導航**：field-well 尚不能換 measure、無 drag-drop fields pane、圖表類型 4 種、計算指標非 DAX 公式列、篩選單層。皆為後續增量。
