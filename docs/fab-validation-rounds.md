# 半導體晶圓廠情境驗證（Multi-Agent，每輪 10 情境，平均 >95 才通過）

資料集：`ai4bi/report/fab_template.py`（process_move_fact 600 列、wafer_yield_fact 100 列，
內建瓶頸 ETCH、yield-commonality ETCH-02、Memory<Logic、rework/hold）。

## Round 1 — PASS（平均 97）
基礎情境：整體良率、瓶頸站(等待最長)、ETCH 機台 yield commonality、最差產品、重工率、
缺陷 Pareto、各站移動數、良率預測、機台良率連續下滑(無→誠實回報)、不重複晶圓數。
修了 R113（半導體詞彙）、R114（duration 非日期欄、跨表去正規化維度、最長 trigger、breakdown intent、
panel 數值欄）、R115（rate 消歧、prompt-aware panel、empty→誠實訊息）。

## Round 2 — 初評 ≈26（需開發）
進階情境（multi-agent 生成）。實測路由結果：

| # | 情境 | 預期 | 初評結果 | 缺口 |
|---|---|---|---|---|
| 1 | ETCH 區 Hot vs Normal queue 差 | 兩值比較+area filter | 回整體 queue | entity-compare 未帶條件/未觸發 |
| 2 | queue 超出全廠 μ+3σ 的機台 | SPC 統計門檻清單 | 回整體 queue | 無統計門檻 |
| 3 | 各 etch 機台 × product 良率 | 2 維 matrix | 只回 product 1 維 | 無 2 維 matrix 答案 |
| 4 | ETCH queue 最長批 vs 最後良率 關聯 | 跨表 lot 級相關 | 只回 queue by lot | **跨表** |
| 5 | cycle time 前 20% 批 良率掉多少 | 分位 cohort + 跨表 | 只回 queue by lot | **跨表 + 分位 cohort** |
| 6 | 夜班 Hot LAM rework 的 move 數 | 4 條件 AND filter | fell through | 多條件 filter |
| 7 | 這週 rework rate 比上週高，哪個 area | ratio 變化分解 | 回整體 rework_rate=0 | ratio 分解 |
| 8 | 各 defect type 占比 | Pareto/share | share 圖 proposal ✓ | 大致可 |
| 9 | 各 product 每次 rework 換多少良率（比值）| 跨表 ratio by group | 只回 rework by product | **跨表 ratio** |
| 10 | 良率<80% 的 lot 有無共同機台 | commonality | 回整體良率 | **commonality（跨表集合）** |

最大缺口群：**跨表分析**（#4,5,9,10）— executor 單一 fact 限制。其次：多條件 filter(#6)、
SPC σ(#2)、2 維 matrix(#3)、ratio 分解(#7)、entity-compare 帶條件(#1)。

開發佇列：R116 跨表分析引擎（correlation / ratio-by-group / cohort）· R117 commonality ·
R118 多條件 filter · R119 SPC σ · R120 matrix 答案 + entity-compare filter + ratio 分解。
