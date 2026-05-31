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
