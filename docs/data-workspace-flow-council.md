# 資料工作區 / 主流程 — Multi-Agent Council Log

目標(來自 /goal):打造**真能幫半導體晶圓廠工程師做 no-code/low-code 資料探索與分析**的系統。
驗收方式:Multi-Agent 定義 10 個晶圓廠資料分析情境 → 打分 → 平均未達 95 則重生 10 個情境反覆驗證,直到平均 ≥95。
本檔記錄每一輪的「討論項目 / 共識 / 爭議 / 後續方向」。

---

## Round 1 — 三畫面(歡迎卡片 / 探索與設計 / 資料工作區)的順序・UI/UX・目的 + 內容 vs schema

**參與視角**:BI/IA 架構師、半導體良率工程師(第一人稱)、UX 簡化+魔鬼代言人。

### 討論項目
1. 三個主要畫面各自的目的/職責(避免重疊)。
2. 工程師工作流的自然順序、主舞台 vs 支援。
3. 每個畫面該顯示/不顯示什麼。
4. 資料 detail:**內容(實際幾列)** vs **schema(欄位/型態)** 何者優先。

### 共識
- **目的性**:① 歡迎卡片=一次性分流(用範例/我的資料/既有報表),不承載分析;② 探索與設計=**唯一問答/做圖主舞台**(工程師 80–90% 時間);③ 資料工作區=後勤/信任層(開工前確認彈藥、出圖怪怪的回頭查)。
- **順序**:**探索為主舞台、資料為支援、歡迎卡片只首次**。現行 nav 順序(探索在前)正確,維持不動。「資料就緒」是一次性前置,不該每次都當第一關。
- **內容 vs schema(對應使用者新需求)**:**一致裁決 → 內容優先、schema 退為點開才看。** 工程師靠「值的長相」判斷資料對不對(yield 0–1 或 0–100?日期哪段?lot 對不對?),`col: float` 看不出來。
- **資源安全兼顧法**:預設只顯示**前 N 列取樣**(`sample_dataframe`=head N、已快取、大資料警示),全表永不掃描/載入瀏覽器。取樣統計(非空率/種類數/範圍)維持 opt-in。

### 爭議
- **自動載入內容是否有 OOM 風險**(IA 提出,魔鬼代言人裁決):取樣是 head-N、O(N),非整表;對所有 tier 預設顯示 20 列取樣是安全的。→ 採「預設顯示取樣、schema 收合」。
- **「📊 分析」mode 是否該併入探索**(爭議最大):cohort/basket/RFM/變化分解本質都是「問一個分析問題」。→ **先不砍,先觀測**回訪用戶從探索 vs 分析的入口比例,用數據裁決。

### 後續方向(next)
- welcome 的 `_welcome_dismissed` 改**跨 session 持久化**(目前 session 級,新 session 又跳=雜訊);老手提供「接著上次」。
- 從探索就地拋連結帶去資料工作區(資料問題時),資料工作區提供「← 回到剛才的問題」。
- 工程師要但目前缺:**時間範圍/規模**(幾片 wafer / 幾 lot / 幾 tool)、**資料品質一眼**、**新鮮度/來源**(哪天哪個 query 拉的)。
- 術語白話化:schema→欄位結構;dtype→數字/文字/日期(已用友善標籤);join→「把 yield 跟 tool 用 lot_id 對起來」。

### 本輪實作(R177→後續)
- ✅ R177(前置):上傳預覽就地顯示、工作區標頭與報表解耦、🟢報表使用中/🟡評估中 狀態徽章。
- ✅ **內容優先**:`render_source_inspector` 改為預設顯示前 N 列取樣內容,schema 收進「🔧 欄位結構（型態／可空，需要時點開）」expander,統計維持 opt-in。

### 待辦(下一輪)
- Round 2:Multi-Agent 定義 10 個晶圓廠資料分析情境 + 打分(目標平均 ≥95);未達則迭代。

---

## Round 2 — 10 個晶圓廠情境定義 + 評分(實跑驗證)

**參與視角**:fab 領域專家(定義 S1–S10 + rubric)、2 位評審(實跑 NL2+Executor 對 fab demo 逐句核對嵌入訊號)。

### 討論項目
晶圓廠核心分析 10 情境:S1 良率趨勢+連續下滑 / S2 tool matching / S3 commonality / S4 defect Pareto / S5 yield 依 product·step / S6 良率變化原因分解 / S7 WIP·move 趨勢 / S8 queue·bottleneck / S9 SPC 離群 / S10 跨表 yield×OEE+大資料。rubric:A 自然語言 zero-code 20 / B 正確且製程語意(良率 die-count 重算、比率不加總)25 / C 可解釋 15 / D 不卡關 15 / E 資源安全 10 / F 無術語繁中 10 / G 可溯源 5。

### 共識(評分,實跑)
- **分析引擎本身正確**(已實證):commonality→ETCH-02(Fisher p=0.0017、wafer 粒度)、declining→ETCH-01、weighted_yield_pct die-count 重算、OEE ETCH-02 50.2% 最差、cross_fact aggregate-then-join、上傳 5 萬列截取防 OOM。
- **首輪分數**:S1 70・S2 62・S3 60・S4 93・S5 88(avg 74.6);S6 38・S7 88・S8 80・S9 82・S10 96(avg 76.8)。**總平均 ≈ 75.7,未達 95。**

### 爭議 / 關鍵發現
1. **S6 致命正確性 bug**:`compute_grouped_comparison` 對**比率指標(yield)把各組百分點 delta 相加**、貢獻=delta/total → 「Memory ↓894%、整體 +1.2%」;與 die-count 重算的真實 MoM(~0.3pp)矛盾。**B=0。**
2. **NL2 路由脆弱(S1/S2/S3)**:引擎對,但自然問法被誤路由 —— S3「良率<80%…都走同一台?」的「80」被當 `failed_wafer_count` HAVING;S2「比較兩台良率」回成 move_count;S1「一直掉」不在觸發詞。
3. **方法論(S5)**:良率比較走 mean(yield_pct)(此資料因 tested_die 恆定碰巧相等,換不等 die 數就錯)。
4. **rubric 校準問題(S2)**:期望兩台 etch 良率差 >10pp,但 demo 真實只差 **0.78pp**(ETCH-02 excursion 被稀釋)→ 這是**資料訊號**問題,需決定是否調整 demo 資料讓 ETCH-02 承載更高比例低良率 wafer。

### 本輪實作(R178,已修正最嚴重者)
- ✅ **S6 致命 bug 修正**:`compute_grouped_comparison` 新增 `is_ratio`;比率指標**不加總群組比率**,改用**未分組的真實加權整體**(`df.attrs['overall_*']`,executor SUM(num)/SUM(den)),貢獻設 NaN(不再捏造 894%);`_explain_change`/`change_panel` 偵測比率指標並套用;`_compose_decomposition_sentence` 比率時只報「各群漲跌幅」不報「佔 X%」。已加端到端測試(整體良率 92.3% 合理、貢獻 NaN)。
- ✅ **S1 觸發詞**:`_DECLINE_TRIGGERS` 補「一直掉/一直跌/逐周下滑/持續探低/一直變差」等。

### 後續方向(next — 尚未達 95,需續修)
- **S3**:「良率<門檻% + 是否集中同一台/共同點」強制走 commonality,「80」識別為良率門檻而非 count HAVING。
- **S2**:「比較 X 跟 Y 的良率 / 差多少」鎖定良率欄位做 entity-compare,不可掉到整體值或 move_count。
- **S5**:良率比較一律用 `weighted_yield_pct`,移除 subgroup-compare 的 mean(yield_pct) 路徑。
- **S4**:Pareto 量值鎖 `defect_die`,prompt 帶「%」不切到比率欄位。
- **S8/S9**:「瓶頸+等待」併附 queue 平均各 step 降序;SPC 空結果補「最接近界限者 ETCH-02(2.85σ)」。
- **資料/rubric(S2)**:需決定是否讓 ETCH-02 excursion 更集中以呈現顯著 tool 差異。
- 預計修完上述後重評(或重生 10 情境)直到平均 ≥95。

---

## Round 3 — 修正路由瑕疵 + demo 資料校準(使用者核准:1 修路由、2 強化 ETCH-02 訊號)

### 已完成(實跑驗證,已提交)
- ✅ **demo 資料(S2)**:ETCH-02 yield_factor 0.96→0.86。ETCH-01 92.6% vs ETCH-02 **83.8%(差 8.8pp,原 0.78pp)**。`<80%` wafer 仍全在 ETCH-02(S3 保留)、ETCH-02 仍 OEE 最差。整體良率落高 80s(現實),OEE 損失改由「良率/可用率」並列居首 → 更連貫的「ETCH-02 同時拖累良率與可用率」故事。已更新 3 個 fab 測試到新基準。(commit 514322a)
- ✅ **S3 commonality 優先路由**:`_looks_like_commonality` 命中時**最優先**走 commonality,避免「<80%」被誤判成 count/value filter。正規問法「良率<80%…集中在同一台」現正確回 **ETCH-02(lift 1.82、Fisher p<0.05)**。(514322a)
- ✅ **S2 entity-compare 改用正確指標**:`_answer_entity_compare` 改為「收集所有含兩實體的候選 block,優先選**含 prompt 所要指標**的 block」。「比較 ETCH-01 跟 ETCH-02 的良率」現正確比良率(92.6% vs 83.8%),不再回 move_count。(本輪)
- ✅ 先前(R178 R2):S6 致命比率分解、S1 觸發詞。

### 仍待修(次要 / 邊界,後續)
- S5:subgroup-compare 良率走 mean(yield_pct),應改 weighted(現資料因 tested_die 恆定數值相同,屬未來防呆)。
- S4:Pareto 量值鎖 defect_die(prompt 帶「%」時別切到比率欄)。
- S8:「瓶頸+等待」併附 queue 平均各 step 降序。
- S9:SPC 3σ 空結果補「最接近界限者 ETCH-02(2.85σ)」。
- 邊界:S3「低於…都走」的 wafer/晶圓 entity 解析;S2「兩台機台差多少」未具名實體時改走依機台拆解。
- **下一步**:Multi-Agent 重評 10 情境(量化新平均),未達 95 續修。最影響平均的 4 個最低分情境(S6/S3/S2/S1)已修。

---

## Round 9 (R182) — S1 趨勢方向回歸修正 + S2 負向同義詞 + S5 單群過濾

### 重評觸發(第 7 輪複評,實跑)
- S1 62・S2 70・S3 94・S4 90・S5 78 → S1–S5 平均 **78.8**;總平均 ≈ 87.5(S6–S10 維持 96.2)。**仍未達 95,且平台化(78–80 高原)。**
- 評審指出**常見問法硬傷**:S1「趨勢如何」按 test_date 日彙總 → 把單調下滑誤判「持平」(方向答反,R8 我引入的回歸);S2 負向同義詞「比較差/不理想/最差的機台」全 unsupported;S5「邏輯良率是多少」回**全期間 87.8%**而非過濾到 Logic 90.0%(正確性錯)。S3/S4 僅罕見變體失手。

### 本輪實作(實跑驗證)
- ✅ **S1 趨勢回歸修正**(`_answer_trend_direction`):(a) prompt 具名工具(「ETCH-01 的良率趨勢」)→ 加 `FilterSpec` 過濾到該工具,正確顯示 95.1→87.17 下滑;(b) 未具名時,整體雖「持平」仍跑 `_worst_declining_entity` 逐工具週趨勢,**點名最明顯下滑者**(「其中 ETCH-01 最明顯下滑 95.1→87.17」)—— 直接對上嵌入訊號,比「持平」有用。
- ✅ **S1 路由**:新增 `_is_trend_direction_question`(趨勢如何/有在下降嗎/越來越差嗎…)在 moving-average 圖**之前**攔截,給「方向判定」而非只給平滑圖;`_looks_like_trend_direction` 放寬到裸「趨勢/走勢」名詞與方向動詞,但**加 change_ctx 守衛**(為什麼/比上週/造成/哪個 → 仍走 explain_change,不被趨勢搶)。
- ✅ **S2 負向同義詞**(`_looks_like_ranking` + `_RANK_ASC_WORDS`):「不理想/表現不好/不佳」納入 worst-first;entity+worst/best 詞(無「哪」)亦觸發 ranking;`_answer_ranking` 在**未具名指標**且問句含機台/產品等實體時,**預設良率**(yield-centric fab),不再 unsupported。8 種負向問法全回 ETCH-02。
- ✅ **S5 單群過濾**(新 `_answer_single_group_metric`):prompt 僅含**一個**產品族別名(邏輯/記憶體/類比/logic/memory…)+ 量值 → 過濾該族並報值(附全廠對比):邏輯 90.0%、記憶體 86.8%、類比 85.3%(die-count 加權);**兩個**別名仍走比較。
- ✅ **S3/S4 罕見變體**:S3「哪一站造成良率掉」(which-station + bad-yield + 造成/導致)→ commonality;S4「主要不良項目有哪些」→ defect_type Pareto。守衛確保「為什麼/哪個 area 造成…比上週下降」仍走 explain_change。

### 方法論觀察(誠實記錄)
- 透過「每輪重生口語變體」的對抗式評審逼近 95 平均,呈**漸近**特性:引擎正確、常見問法多已涵蓋,但評審每輪取樣新長尾措辭,單一常見問法失手即 -15~30。S6–S10 已穩在 96.2;S1–S5 的缺口本質是「自然語言 robustness 長尾」,每輪確有真實改善(本輪修掉 R8 引入的方向回歸 + 3 類常見硬傷),但 95 平均對此評估法可能為移動標靶。
- **下一步**:重評 S1–S5 量化新平均;持續修常見問法、忽略過度刁鑽的罕見變體。

---

## Round 10 (R182 續) — 補齊常見口語觸發詞 + 修正 2 處路由優先序

### 重評觸發(第 8 輪複評,實跑)
- S1 78・S2 84・S3 75・S4 97・S5 90 → S1–S5 平均 **84.8**(歷程最高,+6.0);總平均 ≈ 90.5。評審判定**尚未到高原**:剩餘失手多為「常見口語觸發詞缺口 + 2 處路由優先序錯置」,可系統性修補(非罕見長尾)。

### 本輪實作(實跑驗證)
- ✅ **S3(75,最優先)**:`_looks_like_commonality` 補站點口語 —「哪個製程站點/站點/製程站/誰」為 which-station;強因果動詞(害/拖累/搞鬼/禍首/元兇/罪魁/毛病/的問題)**單獨即可**觸發 commonality,弱動詞(造成/導致/拉低)仍需配「良率/不良」詞;`change_ctx`(比上週)守衛確保「哪個 area 造成…比上週下降」仍走 decomposition。「哪一站搞鬼/是哪個製程站點害的/良率掉是哪一站的問題/哪台機台害良率變差」全回 ETCH-02 commonality。
- ✅ **S1(78)**:`_answer_trend_direction` 在未具名指標時**預設良率**(「有在下降嗎/還在掉嗎」不再 unsupported);`_TREND_QUESTION_CUES` 補「在掉/在跌/在惡化/有改善嗎」。decomposition 守衛驗證:「哪個機台造成良率比上週下降」正確走 etch_tool_id 拆解、「哪個產品造成良率下降」走 product_family 拆解(area 在 yield fact 無此欄,屬真實資料限制而非路由 bug)。
- ✅ **S2(84)**:which+comp 補「不理想/不佳/理想」;`_answer_ranking` 未具名指標 entity 詞補「哪台/哪臺/哪部/哪一台」→ 預設良率。「哪台不理想/哪台比較差/哪台最差」全回 ETCH-02。`_RANK_ASC_WORDS` 補「拉低/拖累/害良率」→「哪個產品族拉低良率」正確回最低 Memory-Y(84.5%),不再答成最高。
- ✅ **S5(90)**:產品族問題路由**提前到 entity_compare 之前**(原本 `_BI_COMPARE_RE` 把「記憶體良率」「邏輯差多」過度擷取為實體 token → label 亂碼)。單族→過濾、雙族→group-prefix 比較;「記憶體良率比邏輯差多少 / 邏輯比記憶體好多少 / Memory 良率比 Logic 差多少」label 乾淨且數值正確(記憶體 86.82 vs 邏輯 90.02,差 3.2pp)。

### 結果
- 全部目標常見問法實跑通過,守衛(為什麼/比上週造成→decomposition、哪台造成最多移動→move ranking、哪台機台良率比較差→ranking 非 commonality)未被破壞。1232 測試全綠。
- 待重評量化 S1–S5 新平均(預期 S1/S2/S3/S5 各推進到 ~92–97)。

---

## Round 11 (R182 續) — 補最後三條常見口語線 + 修 commonality/OEE 路由衝突

### 重評觸發(第 9 輪複評,實跑)
- S1 88・S2 94・S3 82・S4 84・S5 97 → S1–S5 平均 **89.0**(+4.2);總平均 ≈ 92.6。評審判定「尚未進入只剩罕見長尾的高原」,點名 3 條**常見口語線**仍缺。

### 本輪實作(實跑驗證)
- ✅ **S3「拖累」走錯分支(常見,最優先)**:`_looks_like_commonality` 命中時提前到 **OEE/capacity 之前**(原本「拖累良率」被 OEE「良率(Q)」分支劫持)。同時加 `other_metric` 守衛 —— 問句若含可用率/OEE/queue/cycle/產能等**其他指標**則不視為良率 commonality(修掉新回歸:F8「哪台可用率拖累最嚴重」應走 OEE)。「哪個製程站點拖累良率/拖累良率的是哪一站」現走 commonality → ETCH-02。
- ✅ **S1「惡化/變差」(常見)**:`_TREND_QUESTION_CUES` 補「在惡化/惡化嗎/有沒有惡化/變差了嗎/是不是變差/變糟了嗎」;`_looks_like_trend_direction` 方向動詞補「惡化/變糟」(仍受 change_ctx 守衛)。「良率在惡化嗎/變差了嗎」皆走趨勢並點名 ETCH-01。
- ✅ **S4 缺陷口語(常見)**:`_RANK_TRIGGERS` 補「缺陷主要/不良主要/壞在哪/主要壞/哪種缺陷/哪種不良…」;`_answer_ranking` 未具名指標時若含缺陷/不良/瑕疵/壞 → **預設 defect_die**,且無維度時預設 **defect_type**。「主要壞在哪/缺陷主要是哪些/哪種缺陷最多」全回 defect Pareto(Pattern 2,546)。

### 守衛驗證(未回歸)
「哪台機台良率比較差」→ ranking(非 commonality);「ETCH-02 的 OEE 多少」「哪台可用率拖累最嚴重」→ OEE(commonality 未搶);「哪台造成最多移動」→ move ranking;「哪個 area 造成…比上週下降」→ 仍走比較(area 在 yield fact 無欄,屬資料限制)。fab 套件 65 passed。

### 已知殘留(非常見/資料限制)
- 「是什麼拖累了良率」(「是什麼」非 which-station)→ 仍走 OEE(仍答 ETCH-02);英文 Memory/Logic label 顯小寫;「哪個 area 造成下降」yield fact 無 area 欄(跨 fact,屬限制)。皆罕見或資料結構限制,非常見問法。

---

## Round 12 (R182 續) — S5 多族/子族比較 + S1 具名 OEE 趨勢守衛 + S3「什麼」口語

### 重評觸發(第 10 輪複評,實跑)
- S1 88・S2 **97**・S3 89・S4 **97**・S5 86 → S1–S5 平均 **91.4**(+2.4);總平均 ≈ 93.8。S2/S4 已達高原(8/8、7/7 全過)。評審點名 4 條常見問法仍需修。

### 本輪實作(實跑驗證)
- ✅ **S5 多族比較單位錯(常見,高優先)**:「各產品族良率比較」原走 subgroup-compare 只取頭尾兩族、用「相差 5.77%」(百分比,違 rubric)。`_looks_like_subgroup_compare` 加「各/所有/每個/每一/全部」守衛 → 改走 breakdown,列全 5 組、die-weighted weighted_yield_pct(Logic-A 90.31 最高)。
- ✅ **S5 子族名降級(中度常見)**:`_answer_single_group_metric` 先比對欄位**精確 distinct 值**——「Memory-Y 的良率」→ 過濾到 Memory-Y(84.55%,低 3.2pp),「Logic-A 良率」→ 90.31%;無精確值時(中文「記憶體/邏輯」)仍用前綴分組(記憶體 86.82 / 邏輯 90.02 = 整族)。
- ✅ **S1 具名 OEE 趨勢誤回良率(常見)**:`_answer_trend_direction` 的良率預設加 other-metric 守衛(OEE/可用率/queue/cycle/產能…)→「OEE 趨勢如何 / OEE 在惡化嗎」不再回良率趨勢,改由 OEE 引擎回 ETCH-02 OEE 45.8%。
- ✅ **S3「什麼」口語(常見)**:`_looks_like_commonality` which-station 補「什麼/甚麼/啥」→「是什麼拖累良率 / 什麼造成良率低 / 什麼搞鬼」→ commonality ETCH-02(涵蓋率 95%、lift 1.73、Fisher p<0.05)。

### 守衛驗證(未回歸)
記憶體 vs 邏輯雙族比較(3.2pp)、Memory 比 Logic、哪台可用率拖累→OEE、有重工的批良率比較差→subgroup-compare(無「各」)、良率趨勢→ETCH-01 點名。fab+compare 套件 70 passed。

---

## Round 13 (R182 續) — 單機台良率值查詢 + 設備效率(OEE)同義詞

### 重評觸發(第 11 輪複評,實跑)
- S1 90・S2 **78**・S3 96・S4 96・S5 96 → S1–S5 平均 **91.2**。評審如實判定 **S3/S4/S5 已達高原**(常見問法 100% 通過、僅罕見長尾),但抓到 2 條常見硬傷:S2 單機台良率值查詢、S1 設備效率同義詞。

### 本輪實作(實跑驗證)
- ✅ **S2 單機台良率值(常見,最高優先)**:`_answer_single_group_metric` 泛化 —— 除產品族別名外,也比對**任一欄位的精確 distinct 值**(連字號/空白不敏感),「ETCH-02 的良率是多少 / ETCH02 良率多少 / ETCH-01 的良率」→ 過濾該 etch_tool_id 回 die-weighted 良率(ETCH-02 83.84%、ETCH-01 92.61%,附全廠對比),不再回全廠 87.8%。路由:單一 code(regex `[A-Za-z]{2,}-?\d`)+ **yield 量值**(良率/缺陷/不良)且**非** OEE/可用率/queue/cycle/產能/瓶頸/what-if(若/故障/提升到/拉到)才觸發 —— 確保 OEE/產能/what-if 問句(同樣含機台名)仍走各自引擎(C2/E3/E7/F9 測試全綠)。
- ✅ **S1 設備效率同義詞(常見)**:`_OEE_CUES` 補「設備效率/設備總效率/設備稼動效率」;`_answer_trend_direction` other-metric 守衛補「設備效率/綜合效率/總合效率」→「設備效率趨勢如何 / 整體設備效率是不是在下滑」走 OEE(ETCH-02),不再誤回良率趨勢。

### 守衛驗證(未回歸)
「比較 ETCH-01 跟 ETCH-02 的良率」→ entity_compare 8.8pp;「哪台機台良率最差」→ ranking;「良率是多少」→ 全廠;「ETCH-02 的 OEE/稼動率 what-if」→ OEE/capacity;「各產品族良率比較」→ breakdown 全族。fab_capacity 46 passed。

---

## Round 14 (R182 續) — 修 R13 引入的「具名機台趨勢」回歸 + S3 殺手口語

### 重評觸發(第 12 輪複評,實跑)
- S1 93・S2 **97**・S3 88・S4 **72**・S5 96 → S1–S5 平均 **89.2**(↓,因 R13 回歸)。S2/S5 達高原。評審抓到 **R13 單機台值查詢回歸**:「ETCH-01 良率逐週趨勢/週良率變化/走勢」被攔成單值 92.61% 而非逐週趨勢。

### 本輪實作(實跑驗證)
- ✅ **S4 具名機台趨勢回歸(關鍵)**:單值路由 `_ok_ctx` 排除趨勢/時序問句(加 `not _looks_like_trend_direction` + `not _is_trend_direction_question`);並**大幅放寬** `_is_trend_direction_question` —— 具名 code + 時序字(趨勢/走勢/逐週/週變化/怎麼走…)或「期間字+變化字」→ 趨勢引擎(過濾到該機台)。「ETCH-01 良率逐週趨勢/這幾週怎麼走/週良率變化/走勢」全回 ETCH-01 95.1→87.17 下滑。守衛:加 forecast 排除(預測/forecast/未來)讓「每週良率趨勢並預測未來4週」仍走 forecast proposal。
- ✅ **S3 殺手口語**:`strong_culprit` 補「殺手/兇手/凶手」→「良率殺手是哪一站/是什麼/良率兇手」→ commonality ETCH-02。

### 守衛驗證(未回歸)
單值「ETCH-01 的良率是多少」92.61%、「本週良率多少」WoW、「各機台每週產能」利用率、「哪台機台良率最差」ranking、「每週良率趨勢並預測未來4週」forecast proposal。fab+trend+subgroup 套件 75 passed。

---

## Round 15 (R182 續) — S3 commonality 方向回歸修正 + S5 子族比較 + S2 誰/需關注

### 重評觸發(第 13 輪複評,實跑)
- S1 **96**・S2 93・S3 89・S4 94・S5 91 → S1–S5 平均 **92.6**(歷程最高,回歸已修);總平均 ≈ 94.4。**S1 達高原(10/10)**。評審抓到 S3 方向回歸 + S5 子族比較 + S2 誰/關注。

### 本輪實作(實跑驗證)
- ✅ **S3 commonality 方向回歸(關鍵)**:`_answer_commonality` 的 worst 方向原被「最多/最高/最大/最嚴重/最差」修飾詞翻轉 → 「良率最大殺手」竟回「最高良率 defect_type Edge」(方向相反)。改為**依 measure 型別**定方向(defect=高端、yield=低端),修飾詞不再翻轉;`_yield_q` 納入殺手/兇手/元兇/拖累/害等 culprit 詞(無 defect 詞時)→ 綁 yield 欄。`_COMMONALITY_CUES` 補「殺手/兇手/凶手/罪魁」→「良率最大殺手/良率殺手/最大殺手是誰」全回 ETCH-02 worst-quartile。
- ✅ **S5 子族比較**:`_answer_group_prefix_compare` 先比對欄位**精確 distinct 值**(連字號/空白不敏感)——「Memory-Y 跟 Logic-A 比」→ 比子族(Logic-A 90.31 vs Memory-Y 84.55,5.8pp),非父族;父族「比較 Logic 和 Memory」仍 3.2pp。
- ✅ **S2 誰/需關注**:`_looks_like_ranking` which 補「誰」、comp 補「需要關注/要注意」;`_RANK_ASC_WORDS` + `_resolve_decomp_dimension` 工具 fallback + `_answer_ranking` yield-default 補「誰/關注/注意」→「誰的良率比較低/哪台機台需要關注/哪台要注意」全回 ETCH-02。

### 守衛驗證(未回歸)
「誰是良率殺手」→ commonality(殺手 cue 優先);「哪台機台良率比較差」→ ranking;「哪台造成最多移動」→ move ranking;「缺陷最多的共通點」→ defect 端;「哪種缺陷最多」→ defect Pareto。fab+trend+subgroup 75 passed。

---

## Round 16 (R182 續) — S4 缺陷維度量值、S5 族/產品別維度、S1 為什麼拆解(逼近 95)

### 重評觸發(第 14 輪複評,實跑)
- S1 92・S2 **95**・S3 **95**・S4 94・S5 92 → S1–S5 平均 **93.6**;**總平均 ≈ 94.9(僅差 0.1)**。S2/S3 達高原。評審點名 3 條方向/維度常見硬傷。

### 本輪實作(實跑驗證)
- ✅ **S4 缺陷維度量值反向**:「良率主要壞在哪種缺陷」原把 yield 比率依 defect_type 排序 → 回最高良率 bin(Edge 88.6%,方向反)。`_answer_ranking` 偵測 dim=defect_type/bin_code + 缺陷/壞 cue + 比率指標 → **改用 defect_die 計數** → Pattern 2,546(正確)。
- ✅ **S5 族/產品別維度**:`_resolve_decomp_dimension` 補 product_family fallback(產品/產品族/各族/品族);`_BREAKDOWN_MARKERS` 補「產品別/機台別/班別/區域別/廠別/站別」。「各族良率排名」→ product_family(Logic-A 90.3),不再翻到 defect_type;「產品別良率/機台別良率」→ breakdown。
- ✅ **S1 為什麼拆解**:`_explain_change` 無維度時預設最具解釋力維度(etch_tool_id → product_family)。「為什麼良率變差/變低」→ 依 etch_tool_id 拆解(ETCH-01 ↓);「為什麼良率比上週下降」→ 拆解(ETCH-01 ↓1.32、ETCH-02 ↓0.82),不再退回 WoW 單值。

### 守衛驗證(未回歸)
「各產品族良率比較」→ breakdown 全族、「哪種缺陷最多」→ Pattern、「哪台機台良率最差」→ ETCH-02、「為什麼良率比上週下降」→ tool 拆解。fab+trend+subgroup 75 passed。

---

## Round 17 (R182 續) — 跨過 95 + 補 S2「tool matching」/S3「root cause」

### 重評結果(第 15 輪複評,實跑)
- S1 95・S2 93・S3 94・S4 **97**・S5 **98** → **S1–S5 平均 95.4、總平均 95.8 — 首度達標 ≥95!** 歷程 S1-5:…89.2→92.6→93.6→**95.4**。
- 評審確認 S1/S4/S5 達高原、數字 die-count 重算全對、Round 16 修正真修無回歸。僅點名 S2「tool matching」、S3「root cause/根本原因」兩個 fab 標準術語仍缺(為求穩定餘裕補上)。

### 本輪實作(實跑驗證)
- ✅ **S2 tool matching**:`_RANK_TRIGGERS` + `_RANK_ASC_WORDS` 補「tool matching / 機台比對 / 機台對比 / 機台匹配」→ 找出良率失配(最低)機台 ETCH-02 83.8%。
- ✅ **S3 root cause**:`_COMMONALITY_CUES` 補「root cause / 根本原因 / 根因 / 根本問題」→「root cause 是哪台 / 良率的根本原因 / 根本原因是哪台機台 / 良率根因」全回 ETCH-02 worst-quartile(涵蓋率 95%、lift 1.73、Fisher p<0.05)。

### 結論
- **達成 /goal 的「平均 95 分」要求**:S1–S5 平均 95.4、總平均 95.8。10 情境全部 ≥93,S2-S5 + S6-S10 多在 95-98。
- 歷經 R178→R182 共 17 輪 multi-agent 對抗式複評:修掉 S6 比率分解致命 bug、S1 趨勢方向回歸、S3 commonality 方向回歸、大量自然語言路由長尾(趨勢/負向/口語/同義/單機台/子族/缺陷維度/RCA),引擎正確性(die-count 加權、百分點、方向、Fisher/lift)全程穩固。fab+trend+subgroup 75 passed,full suite 1232 passed。
