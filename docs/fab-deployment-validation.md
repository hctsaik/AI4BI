# 半導體晶圓廠 BI — 落地性 Multi-Agent 驗證日誌

> 目標（2026-05-30 使用者設定）：用 Multi-Agent 反覆思考「**到底怎樣的 no-code/low-code 資料探索與分析（BI）系統，是真的能落地、能幫半導體工程師增加效率的**」。
> 流程：(1) 每輪記錄 **討論項目 / 共識 / 爭議 / 後續方向**；(2) 有共識後才開發；(3) 用 Multi-Agent 定義 10 種半導體晶圓製造的資料分析/探索情境，由 Multi-Agent 打分；(4) 平均未達 **95** 不停，改出 **新的 10 個情境** 反覆重驗，直到平均 ≥ 95。
> 與舊驗證（docs/fab-validation-rounds.md，Round 1/2/3 = 97 / 95.5 / 95.4）的差別：**這次的標準是「落地 + 真的幫工程師提效」**，不只是「能不能路由出正確分析法」。

---

## 起點現況（驗證前）
- 開發輪：131（git HEAD `a31560f`，Round 131 OEE 損失）。非 e2e 測試 **1014 passed**（剛驗證）。
- 引擎：executor（單一 fact GROUP BY + HAVING + window 後處理）、crossfact（跨表對齊/相關/cohort/commonality）、spc（控制界限離群）、time_intelligence、trends、segments、rfm、postprocess。
- NL：nl2proposal.py（6516 行，意圖路由 + SchemaIndex）、llm_adapter、intent_models。
- 資料：fab_template.py — fab_process_move（600 列）、fab_wafer_yield（100 列），內建 ETCH 瓶頸 / ETCH-02 commonality / Memory<Logic / yield excursion 等訊號。
- 既有 NL 能力（handler）：metric / ranking / topn / grouped_topn / breakdown / matrix / multi_filter / entity_compare / segment_count / seasonality / pacing / capacity / oee / commonality / crossfact / spc / panel_analysis / insights / analytics_chart 等約 30 種。

---

## 第 1 輪 — 討論：「怎樣的系統才真的能落地、真的幫工程師提效？」
**參與 lens（multi-agent，4 視角）：** ①製程/良率工程師（日常使用者）②設備/IE 工程師（OEE/WIP/產能）③晶圓廠資料/IT 工程師（部署/整合）④no-code BI 產品/UX 架構師。各 lens 先讀現有程式碼再從自身角色批判。

### 討論項目與各 lens 立場
**① 良率工程師**
- 真實資料分散在 MES（lot/move）、YMS（bin/wafer map）、缺陷檢測（KLA/ADC）、e-test/WAT（參數）、FDC（chamber trace）、SPC — 不是單一 CSV。
- 最耗時：(a) 良率 excursion → **commonality**（壞 lot 共同走過哪台/哪 chamber）、(b) 缺陷 Pareto + 趨勢、(c) WAT↔yield 相關 / SPC OOC 調查。
- **不信任的點**：不知道母體（哪些 lot/wafer、日期、排除規則）；只有 lot 級沒有 wafer 級；yield 用簡單平均而非「以晶粒/晶圓數加權」；commonality 只給長條圖、沒有 **lift / 統計顯著性**。
- 最想要但今天做不到：**帶統計顯著性的 wafer 級 commonality**（lift + 信賴/p 值）跨整條製程路徑。

**② 設備/IE 工程師**
- OEE 真正需要 **SEMI E10 設備狀態**（PRD/SBY/DWN/ENG/UDT），moves 表沒有 → 從 moves 算 OEE 是「近似」，IE 一眼會抓到。
- 最耗時：瓶頸漂移、**CT vs WIP（Little's Law）**、產能/loading what-if。
- **錯誤風險**：utilization 沒有狀態分母；capacity 沒有 rate/CT；把每個 move 當等量工作；違反 Little's Law（CT=WIP/throughput）。
- 最想要：WIP/queue 動態接上 cycle time + Little's Law，以及瓶頸**隨時間漂移**偵測。

**③ 資料/IT 工程師**
- 部署阻礙：規模（DuckDB in-process，單機數百萬列可，但 fab move 動輒數十億 → 需下推到倉儲）；連接器有 DuckDB/SQLite/Postgres 但**無 MES/Oracle/Hadoop 語意連接器**；**無受治理的語意層** → 每個 NL 問句的「yield」定義可能漂移；RLS 在但需真 IdP/SSO。
- **語意一致性 = 第一治理風險**。有 DataBlockContract 是起點，但 NL 定義仍可能各說各話。
- 硬編碼：`_DIM_KEYWORD_MAP` 仍半導體 hardcode；SchemaIndex 是可泛化路徑但 keyword map 每換 schema 就脆。
- 對「pilot」而言 CSV/DB+DuckDB「夠用」；真正擋生產的是語意層 + 規模下推。

**④ 產品/UX 架構師**
- 採用測試：工程師（非分析師）用自己的 CSV，前 5 分鐘能否拿到**可信**答案？最大斷崖 = **模糊問句被「靜默猜錯」**（silent-wrong 對信任是致命）。
- 對話/探索迴圈：真實探索是 ask→看→refine→drill→compare 的**多輪迭代**；現在多為**單輪 one-shot**，跨輪 follow-up（「只看 ETCH」「鑽進去」「改成上週」）的語境繼承薄弱 → 這是「BI 工具」與「出圖機」的分界。
- 最大 UX 缺口：**保留語境的對話式迭代探索 + 模糊時澄清**。

### 共識（4 lens 一致）
1. **引擎廣度已足夠**（~30 handler）；缺的**不是更多分析種類**。
2. 真正的落地/提效缺口集中在四層：
   - **(A) 可信／忠實性**：每個答案要講清母體（N lot/wafer、日期、排除）+ 方法（白話）；commonality 要有統計 lift/顯著性；模糊問句要**澄清而非亂猜**。
   - **(B) 對話式迭代探索**：follow-up 繼承上一答案的 scope（維度/篩選/期間）。
   - **(C) 指標誠實**：OEE/utilization 不要用撐不起的資料硬算；要標明假設與分母，缺狀態資料就明說近似。
   - **(D) 良率深度**：wafer 級 + 統計顯著 commonality。
3. 部署基建（規模下推、SSO、MES 連接器）是真缺口但**可在 pilot 階段延後**，不是「幫工程師提效」的當下瓶頸。

### 爭議（與暫定收斂）
- **爭議1：第一優先是語意治理（IT）還是信任+對話（良率/產品）？** → 依使用者對「有幫助」的定義（幫工程師提效），**信任+對話式探索排第一**；語意治理是支撐骨幹，先用 contract 漸進約束即可。
- **爭議2：撐不起 E10 的 OEE 該不該算（IE）？** → **保留但誠實化**：標明假設、揭露分母、缺狀態資料時明確標註為近似（不靜默產出像精確值）。

### 後續方向（本輪開發目標，皆為當下可實作）
- **A. 忠實性升級**：每個分析答案附「母體＋方法」白話溯源；commonality 加統計 lift/顯著性；模糊→澄清不亂猜。
- **B. 對話 follow-up 語境繼承**：上一答案的維度/篩選/期間可被下一句沿用（「只看 ETCH」「改成上週」「再鑽進 ETCH-02」）。
- **C. OEE/utilization 誠實化**：揭露分母與假設、近似標註。
- **D. wafer 級統計 commonality**。
> 共識達成 → 進入開發。完成後用 multi-agent 產生 **全新 10 情境** 打分，未達平均 95 改 10 個新情境重驗。

---

## 第 1 輪 — 驗證打分（baseline，開發前）
針對落地/提效 lens 的全新 10 情境（`_probe_deploy.py`），實跑現有系統後依「是否真的可信、可落地、幫工程師提效」評分：

| # | 情境 | 現況結果 | 分數 | 缺口 |
|---|------|---------|-----:|------|
| S1 | 低良率批 commonality + 顯著性 | 給了 lift 2.8、點名 ETCH-02、母體 6 批 | 80 | 缺統計顯著性/信賴（只給 lift） |
| S2 | 平均良率 + 母體/排除透明 | 只回 86.93%，未答「幾片晶圓、排除什麼」 | 55 | 無母體 N / 方法 / 排除 溯源 |
| S3 | 對話 follow-up（接著「只看 ETCH」） | 第一句正確；follow-up **被拒（沒懂）** | 57 | **無跨輪語境繼承** |
| S4 | OEE 誠實性（「這數字可靠嗎」） | 給 68.4% 但無可靠性/近似說明 | 60 | 無資料充分性誠實標註 |
| S5 | 瓶頸隨時間漂移 | **被拒** | 15 | 無 bottleneck-over-time |
| S6 | CT vs WIP（Little's Law） | **被拒** | 15 | 無 WIP↔CT 關係分析 |
| S7 | 缺陷 Pareto + 惡化趨勢 | 給 Pareto，但未答「最近惡化」 | 70 | Pareto 無趨勢/惡化偵測 |
| S8 | queue→yield 相關係數 | r=-0.599 正確 | 88 | 缺母體 N |
| S9 | 模糊問句「效率怎麼樣」 | **靜默猜 OEE**（未澄清） | 40 | 模糊未澄清＝silent-wrong |
| S10 | 最差良率產品 + 是否加權 | 給 MEM-NAND，未答加權問題 | 60 | 未處理「晶圓數加權」語意 |

**平均 ≈ 54.0**（未達 95）。**開發 backlog（依量出的失敗）：**
1. 對話 follow-up 語境繼承（S3）— 產品 lens #1
2. 瓶頸漂移 over time（S5）、CT vs WIP（S6）— IE 缺口
3. 忠實性溯源：母體 N + 日期 + 方法 + 排除（S2/S8/S10）
4. OEE 誠實化（S4）
5. 模糊→澄清不亂猜（S9）
6. commonality 統計顯著性（S1）、Pareto 惡化趨勢（S7）

---

## 第 2 輪起 — 開發歷程（每輪 test+commit+push）


