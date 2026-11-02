# P00 基準驗證

RFM 交付完整性專項 **60 通過，5.53 秒**，驗證完整／空結果、客戶唯一性、計數守恆、日期與分位分數、風險／名稱／設定竄改及金額精度。保存分析批次返回前已檢查，提交收據驗證函式已備妥，但發布／四格式輸出尚未接上，過渡拒絕保留。API 建置 `21c24a83…` 通過、前端產物沿用，證據 `.artifacts/rfm-integrity-evidence/evidence.json`；不以本專項宣稱完整交付或全套回歸通過。

RFM 保存增量來源建置 `6975fcab…` 通過，RFM／報表擴充 **220 項通過，41.10 秒**，驗 CRUD／冪等／歷史、固定快照重播、頁面複製與移除、欄位型別變更及無來源改名／刪除；發布／匯出過渡拒絕在查詢前生效。瀏覽器 **1 案通過，8.6 秒**，保存／整頁重載／套用／重算金額及原分頁／取消流程全部通過。證據 `.artifacts/rfm-saved-evidence/evidence.json`。尚未串接 RFM 完整交付，不以設定保存代表發布、匯出或全產品完成；此輪未重跑全套 API 或更新安裝包。

RFM 面板來源建置 `a6161e90…` 通過，真實瀏覽器 **1 案通過，6.8 秒**：核對五群金額、空範圍、設定改變清除結果、600 位客戶六頁及延遲接受回應的取消競態。CLI exit=0，畫面已檢視，證據 `.artifacts/rfm-ui-evidence/evidence.json` 保存面板／App／樣式／測試副本與建置、瀏覽器日誌雜湊。第一版僅查詢／空結果案例 5.0 秒通過，但 PowerShell 對 stderr 回報退出 1，保留原日誌；擴充案例以明確擷取 CLI 退出碼驗證成功。未修改後端或重建 wheel；完整 API／前端單元／全套瀏覽器未在此輪重跑，保存與發布匯出仍未完成。

RFM API／範圍串接完成來源驗證：RFM、SPC、共同性 **134 項通過，86.26 秒**，包含真實背景工作、冪等重送、原始範例逐客戶金額對照、篩選後大整數精度與既有分析回歸。OpenAPI／TypeScript／Vite 建置通過，build `fa58e19b…`。`.artifacts/rfm-api-evidence/evidence.json` 記錄來源、測試、XML／日誌雜湊；初輪 24 通過／2 預期錯誤的紀錄保留。下段計算層後續已有 HTTP 接入，React 面板、保存／發布／匯出、完整 API／瀏覽器與離線交付仍待驗收。

RFM 計算層新增 **19 項測試通過，0.76 秒**。使用固定 wheel 的實際 compute_rfm，人工核對五客戶排名、不同購買日數、淨額、截止日與 UTC 日界；另驗精確金額、相鄰大整數排名、無效輸入、識別型別、空結果、上限、欄位碰撞及輸入不變。證據 `.artifacts/rfm-boundary-evidence/evidence.json` 含核心及新檔副本／SHA，XML 為 `.artifacts/rfm-boundary-expanded.xml`。這是新增內部計算邊界，尚無 HTTP／React／保存／發布接入；未重跑完整 API 或重建 wheel，完整範圍仍未完成。

變化拆解四格式邊界新增 16 案，專項 **133 通過，36.57 秒**，涵蓋 160 群完整輸出、大整數、精細小數字串及空結果。JSON／CSV 保留原值，Excel 字串欄位保留文字型別，PDF 全部群組及長數字讀回核對；投影測試使用固定查詢結果，不混稱為新增真實 HTTP 驗證。產品與 b0b32e45 manifest 未改，證據 `.artifacts/change-document-boundary-evidence/evidence.json`。同版新版 wheel 與專案外離線安裝／HTTP／重啟發布重播已通過，安裝版瀏覽器驗證中，詳見 app-release.md。

變化拆解 v6 來源交付：建置 `b0b32e45c68bff975b72517b6782ce5686ffd6cfbc0fe4b094b6ff5a7cfe8983` 正式建置通過，完整 API **865 通過，347.05 秒**、前端 **34 通過**，全部 **34 個瀏覽器案例同一輪通過，7.0 分鐘**。新增變化拆解發布流程 12.6 秒；保存與發布設定一致，四格式真實下載成功，刪除草稿後重開固定發布仍可查詢。文件讀回五個群組及設定／資料版本，JSON／CSV 原值一致，Excel 数值逐項核對，PDF 11 頁保留分析身分、全部群組及 v6。發布截圖已檢視，良率差異標百分點，缺期保留「—」。`.artifacts/change-delivery-browser-results/evidence.json` 保存來源、日誌／XML、文件與截圖雜湊；driver／manifest 在瀏覽器整輪期間不變。此次移除過渡交付拒絕，查詢／發布／匯出與唯讀頁均接入保存變化拆解。舊 v5 或更早發布仍可讀，但不能以 v6 執行；新版安裝／NativeApp 與其餘完整產品驗收仍待完成。

交付完整性內部增量：change_analysis.py 的完整結果及發布摘要檢查專項 **115 通過，22.00 秒**（`.artifacts/change-delivery-receipts.xml`），初輪完整結果檢查 **109 通過，21.24 秒**。驗證加總／加權／空結果、大整數差異 1、缺漏／重複群組與分析、數值編碼、差異及百分比一致性、版本／設定／期間／資料版本與提交摘要篡改拒絕。API 來源建置 `ecae76433b6e4846294f35e455f3957c4387d7443727948bc2236c604e56ae86` 核對通過，僅 change_analysis.py 後端雜湊變更、前端產物雜湊與 bb3894d8 相同；證據 `.artifacts/change-delivery-integrity-evidence/evidence.json`。檢查尚未接入公開交付路徑，發布／匯出仍拒絕含保存變化拆解的報表；未重跑完整 API／瀏覽器／安裝／NativeApp，不以內部準備宣稱完整交付已完成。

保存變化拆解範圍新增 9 案（8 個多頁／鑽取／加總或加權組合、1 個真實書籤命令重播），專項 **76 通過，18.74 秒**。每頁的保存條件及所選查詢、目前頁臨時篩選、鑽取作用與跨頁隔離，均對照原始資料獨立計算兩期值；鑽取頁先允許兩產品，再由鑽取縮小。舊書籤與現行篩選分別保留 Logic-A／Logic-B，使用各篩選內錨點；結果不同、資料版本一致且快照未變。初輪 4 個鑽取失敗源於測試快照未附 datasets 契約，補齊真實快照必要內容後通過。證據 `.artifacts/change-saved-scope-evidence/evidence.json` 含來源及日誌雜湊。未修改產品，建置 `bb3894d8…` manifest 核對通過，先前 815 API／34 前端／33 分次瀏覽器證據仍屬前輪；發布與匯出串接未完成。

變化拆解保存來源 `bb3894d8fce4ac2271bf093ac5b814fabbcb10488b3ea2c16cf15e737f5a40ef`：正式建置通過，完整 API **815 通過，334.62 秒**、前端 **34 通過**、變化拆解專項 **67 通過，16.00 秒**。保存／更新／改名／重載／套用／刪除／復原的真實瀏覽器案例通過，畫面已檢視。完整瀏覽器初輪 **29 通過／4 失敗，8.0 分鐘**；四案測試修正後補驗 **4 通過，1.0 分鐘**。日期粒度先等待新工作區查詢、Plotly 切換時等待 trace；圓餅圖／地圖的全期間數值不能與範本預設最近 30 天 KPI 比較，測試先將 KPI 明確設為全期間，再保留鼠標／鍵盤篩選及匯出驗證。產品 manifest 完全一致，另外 29 案程式未變，未放寬 timeout；33 案為分次完成。完整失敗紀錄、trace、來源副本與雜湊見 `.artifacts/change-saved-evidence.json`、`change-saved-full-browser-results/` 及 `change-saved-retry-browser-results/`。保存指標公式／欄位型別身分、固定快照重播、命令歷史、30 組上限及批次先驗證已測；多頁／書籤完整矩陣仍須補齊。保存變化拆解的發布與四格式匯出尚未串接，過渡版本明確拒絕交付；新安裝／NativeApp 與完整產品仍未完成。

精度來源驗證完成：同一 `73581138…` 建置，完整 API 802、前端 34 與正式建置通過；瀏覽器初輪 **14 通過／1 失敗，3.6 分鐘**，失敗為新增 CSV 案例將帶圖示與數量的資料工作區按鈕當作精確文字，尚未進入匯入。第一次補驗完成真實 CSV 匯入，但新增圖表以 getByLabel 精確定位包住 select 的隱含標籤而逾時；改成實際 combobox 名稱後，**CSV 補驗 1 通過，7.3 秒（runner 11.3 秒）**。兩次僅修改該測試定位，保留所有失敗日誌、trace、driver 與 manifest；沒有延長既有 timeout。逐位驗證 HTTP 結果和畫面 previous="9007199254740993"、current="9007199254740994"、delta=1，截圖已檢視。`.artifacts/change-precision-evidence.json` 綁定全部日誌、XML、來源／測試副本、前後數值對照與截圖，並核對補驗前後產品 manifest 相同、其餘 14 案測試文字完全未變；15 個案例分次完成，未宣稱全套 15 案同次全綠。此修正只作用於變化拆解，不能作為全部查詢的大整數精度驗收；設定保存／發布／匯出與新安裝／NativeApp 仍待完成。下段「瀏覽器驗證進行中」為保留的中途狀態，已由本段完成。

變化拆解精度增量：`change-v2`／來源 `7358113870f1e8acac562f2013f03f7455f338553d6ae02a3cd20f070703b405`，專項 **54 通過，7.14 秒**（`.artifacts/change-precision-numeric.xml`），完整 API **802 通過，327.57 秒**（`.artifacts/change-precision-api-regression.xml`，一個既有 OLS 退化矩陣警告），前端 **34 通過**、正式建置通過。未修改固定核心 wheel；SQL 聚合、條件、RLS 與公式仍由核心執行，只在變化拆解的輸出 context 中避免 `.df()` 先將 HUGEINT／DECIMAL 轉成 float。Decimal 差異／百分比與穩定同值排序由版本化 adapter 負責，其他查詢不啟用此模式。成功／失敗皆確認 context 復原。`.artifacts/change-precision-before-after.json` 使用完全相同的受治理資料與 SUM 指標對照：原核心 previous=9007199254740992.0、current=9007199254740994.0、delta=2.0；新版 previous="9007199254740993"、current="9007199254740994"、delta=1。另驗证真實 SQL SUM 超過 int64、負差異、精細 Decimal、缺期群組與三種來源排列的結果順序一致。新版瀏覽器驗證進行中；保存、發布、匯出及安裝／NativeApp 未完成。

變化拆解入口最終來源驗證：`989da9ce010f03e00dc61f65fbc2fe89442ce4fb191428d04f8dd11a2aa2e51e` 的 **13 案瀏覽器重驗全部通過，3.2 分鐘**，完整報表 1.4 分鐘；百分點顯示斷言與加權結果畫面已核對。證據 `.artifacts/change-entry-verified-browser-results/evidence.json` 綁定不變的 driver／manifest、API 與前端測試日誌／XML、變化拆解來源副本及截圖。額外實際 600 群分頁 **1 案通過，6.8 秒（runner 10.8 秒）**：六頁每頁 100 群，逐頁首列及最後一列對照真實 API 全量結果，末頁下一頁停用、上一頁返回 401–500，改回 step_name 後舊結果清除且重跑呈現六群、不保留舊 offset。末頁截圖已檢視，證據 `.artifacts/change-pagination-browser-results/evidence.json` 綁定補驗 driver 與相同產品 manifest。此為 13 案完整流程加 1 案補驗，不宣稱新增一次全套 14 案執行。產品來源未再修改；以下「新版瀏覽器重驗進行中」為中途歷史紀錄，已由本段完成。設定保存、發布／匯出、離線安裝與 NativeApp 新版驗證仍待完成。

變化拆解操作入口：專項 `.artifacts/change-entry-scope.xml` **48 通過，6.89 秒**；完整 API `.artifacts/change-entry-api-regression.xml` **796 通過，331.37 秒**（一個既有 OLS 退化矩陣警告）；前端 34 通過、正式建置通過。涵蓋 UTC timestamp 最後一日／下一日界、原範圍自動錨點、明確截止日、三層日期與類別 AND 條件的 keep／replace、混合 OR 拒絕、選取查詢條件保留且 HAVING 不裁切群體、計算指標、真實 worker 加權數值對照、重送去重、revision／key 衝突及舊執行契約先於來源讀取拒絕。初輪 `.artifacts/change-entry-initial.xml` 35 通過／3 失敗是測試假設修正：good_die 是合法整數分組欄位，範例群組數改以實際原始資料計算，錯誤碼沿用 SNAPSHOT_RUNTIME_INCOMPATIBLE；保留初輪日誌。

第一輪來源建置 `a960c419be37fc51aa424b6d8af52176bcf6bccf0eb0558fd6e9031c676d51a9` 的 **13 個瀏覽器案例通過，3.2 分鐘**，完整報表 1.4 分鐘。新增兩案為 7.6／4.7 秒，使用真實來源、真實任務與延遲真實接受回覆驗證取消，不以假結果代替計算；驗證六類→Etch 一類、改條件清除、五種產品的加權結果與缺期 null。截圖已檢視，發現絕對良率差異仍以 % 標示，已改為「百分點」，本期／前期各附單位；新增畫面斷言後重新建置為 `989da9ce010f03e00dc61f65fbc2fe89442ce4fb191428d04f8dd11a2aa2e51e`，前端 34 再次通過，後端 manifest 的全部檔案雜湊與上述 796 案版本一致。新版瀏覽器重驗進行中。初輪證據 `.artifacts/change-entry-browser-results/evidence.json` 保留原 driver／manifest／截圖，不覆寫為新版；產生證據時修正 PowerShell 日誌 UTF-16 解碼，非產品或瀏覽器失敗。尚未新增設定保存、發布／匯出或新安裝／NativeApp 驗證。

變化拆解計算轉接：`.artifacts/change-adapter-verified.xml` **25 通過，2.33 秒**；測試直接使用固定核心的 grouped comparison，驗證尾隨視窗邊界、加總貢獻率、加權整體值、缺期率值 null、空群組維度、別名碰撞、四個核心查詢位置的失敗傳遞、非有限／未定義／字串數值拒絕、日期下溢、重複群組與上限、運算溢位。兩案另以真正 `report_executor` 與固定 fab 合約執行 `good_die`／`weighted_yield_pct`，跟獨立原始資料聚合比較且確認契約未修改。`.artifacts/change-existing-comparison-regression.xml` **21 通過，4.67 秒**，168 案未選取，並非完整 API 回歸。初輪 18 與第二輪 20 案皆通過，日誌保留。`.artifacts/change-adapter-evidence.json` 綁定產品／測試來源副本與最終兩組 XML／日誌雜湊。尚無 API route、UI、保存／發布／匯出接入，未做新建置、瀏覽器或安裝驗證；下方 `9b5ef223…` 是此前交付版本，不能當作此次新增來源的安裝證據。

跨表範圍補驗：`.artifacts/crossfact-complete-scope-tests.xml` **139 通過，66.69 秒**，包含新增 12 個多頁／條件／鑽取／書籤與多分析原子性案例。8 組矩陣以原始資料獨立篩選及 pandas 聚合，對照各共同鍵的 A、B、比率與 Pearson；同時驗證只有作用頁面收到臨時條件，B 側鑽取不裁切 A 的 600 列來源。書籤條件重播、兩份設定預先驗證與第二次計算失敗的整批拒絕另行核對。初輪 8 失敗為將空 path 的根階層誤判為無 drill context；第二輪 9 通過／2 失敗為測試填入不存在的 LITHO-01，已依實際資料改成 PHOTO-01，保留有效配對大於零的斷言。兩次日誌保留，產品程式未改。`.artifacts/crossfact-scope-evidence.json` 綁定測試副本、XML／日誌與既有 `9b5ef223…` manifest；此為補驗，不另稱完整 API 或新安裝建置。

同一 v5／`9b5ef223…` 的安裝與桌面增量驗證：App wheel **2,081,001 bytes**，`.artifacts/release/offline-crossfact-delivery/evidence.json` complete=true，環境建立／離線安裝／pip check／HTTP probe 均 exit 0（9.41／89.56／1.12／23.83 秒）。probe 加入保存加權跨表、200 列／20 配對、CSV 全列讀回、重啟後刪除草稿再重播固定發布。`.artifacts/installed-crossfact-browser/evidence.json` **11 案通過，3.0 分鐘**，driver 未變、安裝 build 相符；跨表下載四格式一致，PDF 16 頁，畫面已檢視。

NativeApp `.artifacts/nativeapp/package-crossfact-delivery/` 已驗證 195 檔、封裝 SHA-256 `e831dc6ab9282c1cbc12fb31c0cf9fe3d5a41c1c0dc3e939301c51c1c09f9366`。host-crossfact-delivery complete=true，由包內內容建立新環境（98.73 秒），Host launch／stop 1.84／5.20 秒且實際程序退出、埠關閉。electron-crossfact-delivery complete=true／passed=true、**28 steps**、shell_unchanged=true；SPC、共同性、跨表保存／重載、四格式與發布 JSON、關閉取消／確認通過。下載讀回核對三種分析完整表格與固定版本，PDF 29 頁，跨表發布截圖已檢視。完整 receipts、driver 與下載雜湊保留於對應目錄。此為來源殼與指定 CPython 的測試，不代替正式 Runtime／新機、自動 bootstrap、OS 另存對話框或升級回滾；完整目標仍在進行。

v5 來源交付最終驗證（`9b5ef223…`）：完整 API **736 通過，300.23 秒**（crossfact-delivery-verified-api.xml），僅既有退化 OLS 情境的 SingularMatrixWarning；前端 **34 通過**、正式建置及 **11 個瀏覽器案例全部通過，3.0 分鐘**，完整報表 1.4 分鐘。跨表發布案例 13.8 秒，涵蓋加權指標、發布頁 Etch 篩選、四種實際下載、草稿刪除後固定版本重播。JSON／CSV／Excel 完整對齊、相關性、分位資料表與設定、來源數量、篩選及資料版本讀回一致；PDF **16 頁**保留 20 組數值、指標及版本雜湊，核對時排除續列行號、頁首與頁尾，未修改產品文件。完整瀏覽器證據 `.artifacts/crossfact-delivery-browser-results/evidence.json` 保留當時 driver、manifest、測試與下載雜湊。初次長元素截圖遭對話框裁切，改為實際可見摘要與最後一列，發布單例補驗通過（14.8 秒，runner 18.8 秒），截圖已檢視；獨立證據 `.artifacts/crossfact-publication-view-results/evidence.json`。此補驗是同一案例，不計為第 12 個不同案例。新版安裝／NativeApp 尚未驗證，仍不能宣稱全產品完成。

v5 完整回歸初跑保留：`.artifacts/crossfact-delivery-api-regression.xml` 為 **734 通過／2 失敗，302.75 秒**。兩項新加入的發布提交測試誤把內部 `CROSSFACT_DELIVERY_INVALID` 當作任務層公開錯誤；既有 jobs 層統一轉成 `PUBLICATION_INVALID`。修正測試為先直接驗證提交函式拒絕跨表收據，再驗證任務失敗及發布清單維持空白；產品程式未改。兩項 **通過，3.30 秒**（crossfact-commit-correction.xml），完整回歸重跑中。

跨表發布／匯出串接（`9b5ef223…`）：初始跨表與發布專項 **152 通過，83.60 秒**；正式 React／API 建置通過。已新增發布提交遺失／錯誤 receipt 的原子拒絕與舊 v4 快照拒絕測試，完整 API 回歸正在執行。執行契約現為 v5；React 共用結果元件與發布頁查詢已接入。真實瀏覽器案例已加入加權設定發布、發布頁 Etch 篩選、四格式下載、刪除草稿再開啟固定版本，尚待執行結果。下方 guard 描述均為先前版本歷史，不代表目前功能限制。

跨表文件與完整性增量（`1cb9b45a…`）：先前文件專項 **67 通過，32.02 秒**，新增完整性檢查後跨表 **117 通過，35.86 秒**；跨表／共同性／全部匯出／發布共 **292 通過，134.76 秒**。資料表測試實際讀回 CSV ZIP、Excel 與 PDF，核對加權指標設定、全部對齊列、來源版本、空／常數／缺值狀態及 PDF 全部 160 列。完整性測試涵蓋大整數、重複分位邊界、零分母與 36 種錯配／缺漏／非有限值；保存分析返回前已實際啟用完整檢查。API 素材建置與 manifest 校驗通過，前端沿用。證據 `.artifacts/crossfact-document-integrity-evidence.json` 綁定來源、測試 XML／日誌及建置日誌雜湊。此輪未執行完整 API／瀏覽器或安裝／桌面驗證，且正式跨表發布／匯出 guard 尚未移除；不以文件 writer 測試宣稱公開交付完成。

本輪最終驗證（`e0dd342c…`）：跨表、發布與全部匯出專項 **178 通過，86.99 秒**；完整 API **669 通過，274.71 秒**、前端 **34 通過**、正式建置通過，瀏覽器 **10 項全部通過，2.8 分鐘**。完整報表 1.5 分鐘，未放寬 180／45 秒限制。跨表保存案例 6.1 秒，驗證加權指標參數、更新／改名、保存後刷新與重新選回工作區、套用、真實 worker 計算、刪除與 Undo；已檢查保存畫面截圖。`.artifacts/crossfact-saved-browser-results/evidence.json` 綁定來源 manifest、driver、完整 API XML 與截圖雜湊。下方兩輪失敗保留；最終只將跨表交付限制放在 `run_query` 成功後、寫檔前，保留原有版本拒絕責任與無部分交付要求。

跨表保存交付檢查修正續記：第二輪完整回歸 `crossfact-saved-fixed-api-regression.xml` 為 **632 通過／37 失敗，244.03 秒**。失敗均為獨立文件產生測試直接提供已計算結果，新增的重複 runtime 檢查卻要求其提供完整快照。現保留 `run_query` 的原有版本／來源檢查，於查詢成功後、任何匯出檔寫入前才檢查跨表交付限制；發布檢查／提交仍先驗證契約。正在重驗跨表、發布及全部文件產生路徑，未將上述失敗改寫成成功。

跨表保存增量（`964b684e…`）：新增命令 CRUD、30 組上限、名稱／ID 唯一、全部角色型別、頁面引用、複製重映射／移除及離線 metadata 修復；固定快照重播不受後續草稿編輯影響，獨立服務重啟讀回一致。初始跨表專項 58 通過；加入重啟、上限與唯讀後，首輪完整 API 為 **667 通過／2 失敗，272.73 秒**，證據 crossfact-saved-api-regression.xml／log。兩項為空／舊契約快照先觸發 report KeyError，已修正為先驗證執行契約，跨表／發布 **88 項通過，53.83 秒**（crossfact-saved-contract-tests.xml）。完整修正版回歸與瀏覽器驗證進行中。

跨表操作入口（`ff41eca0…`）：完整 API **654 通過，265.29 秒**，前端 **34 通過**、正式建置通過。API 包含真實 worker、20 批／Pearson −0.716、保存與臨時條件交集、接受後修改仍重送原任務、欄位錯誤無部分結果、舊分析／Web 契約在讀來源前拒絕。專項首輪 48 通過／1 失敗為測試誤寫舊契約錯誤碼，已依既有 SNAPSHOT_RUNTIME_INCOMPATIBLE 修正，完整回歸通過。僅既有 OLS 退化案例 warning。

首輪瀏覽器（d52b7bae）8 通過／1 失敗：新增跨表流程 8.9 秒通過；完整報表滑桿拖曳的座標在 focus 捲動前擷取，trace 中滑鼠 y=788.796875 超出 viewport 720，命令數為 0。driver 改為鍵盤操作後 scrollIntoView、重新取座標與 elementFromPoint 命中確認，未放寬時限、未修改滑桿產品程式。原失敗 trace 與 driver 留在 `.artifacts/crossfact-entry-browser-results/`。另以 12 位有效數字整理跨表顯示，title 保留原值；數值計算未變。新版9 個瀏覽器案例重驗全部通過（runner 2.6 分鐘，完整報表 1.4 分鐘），保留原 180／45 秒限制。證據 `.artifacts/crossfact-entry-verified-browser-results/evidence.json` 含來源 manifest、driver 與截圖雜湊；跨表截圖已檢視。

跨事實表計算驗證（`b0b8c3b8…`）：44 項新專項加 SPC／共同性共 **152 項通過，65.15 秒**，`.artifacts/crossfact-analysis-regression.xml`。以可手算的重複共同鍵驗證先聚合再對齊（A=30、B=5、比率=6），加權比率 91/102×100 與平均百分比區分；fab 20 批與固定核心 Pearson 一致。涵蓋 NULL／COUNT／零分母、常數／不足樣本／分位 ties、鍵型別、惡意或衝突欄名、未匹配群體、10,000 群體上限及數值溢位。

首輪 2 失敗／34 通過，原因為固定核心 combine 用 pd.NA 表示零分母，object Series 在 round 時失敗；轉接層轉為 nullable Float64 後 36 項通過，再加入 8 項邊界案例完成上述 152 項回歸。保留 `.artifacts/crossfact-calculation-tests.log` 原失敗；未修改固定核心。build_app.py --skip-web 已更新來源／靜態 manifest，未重跑前端或建立新版安裝包。`.artifacts/crossfact-calculation-evidence.json` 記錄來源與測試雜湊；此步沒有 Web 操作入口或固定發布，不等於完整跨表遷移完成。

共同性安裝交付更新：`43275411…` 已通過專案外離線安裝與重啟重播，安裝版 **8 個瀏覽器案例全通過**（runner 2.8 分鐘、完整報表 1.7 分鐘），driver 未變、安裝來源與 ready build 一致。四份下載已獨立讀回：JSON 31,984 bytes、CSV ZIP 7,633 bytes、Excel 13,704 bytes、PDF 54,689 bytes／12 頁；Etch 範圍的 ETCH-02、100 群體／11 目標、完整設定與資料版本一致，並已檢視發布結果截圖。證據 `.artifacts/installed-commonality-browser/evidence.json` 及其 playwright-results 共同性發布案例內 download-verification.json。

新版 NativeApp 包與從封存檔建立全新環境、Host 啟停已通過；Electron 來源殼 24 項流程與實際四格式及發布 JSON 讀回均通過（SPC 600 列／12 實體、共同性 100 群體／11 目標／11 實體，PDF 18 頁），平台來源未變、程序與埠停止確認。詳細雜湊／環境與限制以 app-release、integrations/nativeapp/README 為準。此更新取代下方同版「安裝／NativeApp 尚未更新」的歷史狀態，未勾選全產品驗收。

Commonality 發布與四格式交付（2026-09-06）：来源建置 `43275411e9f62e979609096ea9880c27955fb0b885c22f8a93b0618f98f6f57d`，Web 契約升為 v4，SPC 仍為 spc-entity-v2，共同性仍為 commonality-v1。完整 API **605 通過，260.93 秒**（既有 OLS 退化資料測試 1 項 warning），前端 **34 通過**、建置通過，**8 個瀏覽器案例全部通過，runner 3.9 分鐘**。完整報表本次 2.8 分鐘，未放寬 180／45 秒限制，也不將其宣稱為完整效能矩陣通過。本輪無測試失敗；發布前／執行前 v3 拒絕、固定發布重播、原草稿設定刪除、結果數量／狀態核對與各格式失敗不產物均通過。新 CommonalityResultView 與探索面板共用唯讀呈現，新增檔案置於既有 components 目錄。

共同性發布案例 15.1 秒；瀏覽器實際下載並另外讀回 JSON 31,983 bytes、CSV ZIP 7,634 bytes、XLSX 13,710 bytes、PDF 54,664 bytes／12 頁。下載套用 Etch 臨時條件，只含 ETCH-02；母體 100、目標 11、對照 89、lift 1.82、p 0.0008。JSON／CSV／Excel 的完整設定、資料版本及實體數值一致，各匯出 job 的 snapshot ID 可不同，CSV manifest 必須對應自身 analysis.json。刪除草稿後重新開啟發布版本時回到原始 11 實體範圍；已檢查結果截圖。證據 `.artifacts/commonality-publication-browser-results/evidence.json` 與案例內 download-verification.json。新版安裝／NativeApp、完整探索矩陣及全產品交付仍未驗收；先前過渡 guard 已移除並改以完整結果驗證保護交付。

Commonality 文件 writer 前置（2026-09-06）：來源 manifest `1baf44041ea938a45da42422dac469dec98a27c486c6476a749d677373e5ed5a`，共同性／SPC／匯出回歸 **185 通過，78.14 秒**。新增文件測試讀回完整 CSV／JSON／Excel／PDF，涵蓋 11 個實體、欄位型別／資料版本、名稱公式防護、工作表避重名、PDF 字面標題、空目標及無對照狀態；既有 SPC 共用 writer 後的匯出仍通過。初次 `commonality-document-tests.xml` 為 182 通過／1 失敗，PDF 測試使用預設 Type 3 字型，讀回得到 glyph 名称；依正式匯出原有 pdf.fonttype=42 對齊測試後，5 個文件專項及完整三模組回歸通過，未放寬內容断言。證據 `.artifacts/commonality-document-evidence.json`。使用 --skip-web 更新 API manifest，前端、完整 API／瀏覽器及安裝版未重驗；公開 commonality 發布／匯出 guard 尚未移除，此輪不宣稱完成交付。

Commonality 固定快照重播前置（2026-09-06）：來源 manifest `0d8cec3ca5b6a162c6b3dd8f7c35ebc07a983b2a09497c2bd7179c48f84ccfb6`；專項 **39 通過，16.78 秒**，包含既有 commonality API／保存測試，以及新增固定快照、跨頁、一份來源契約共用、全部定義先驗證、失敗無部分回傳、重啟後完全相同結果與無效鑽取在來源讀取前拒絕。先前本輪 38 項亦通過，後補保留原有鑽取檢查順序及其測試，未出現測試失敗。`build_app.py --skip-web` 完成，已核對來源與 manifest；前端素材未變、沒有重跑完整 API／瀏覽器或更新安裝包。證據 `.artifacts/commonality-replay-evidence.json`。這是內部重播前置，發布／匯出拒絕尚未解除，不宣稱已完成固定發布交付。

Commonality 保存設定（2026-09-06）：來源建置 `86dcf7a8bfd811d242f965458fe8375b42bd516bfb37832bc507995f62ee5bb5`，完整 API **582 通過，233.32 秒**（既有 OLS 退化資料測試 1 項 warning），前端 **34 通過**、建置與 **7 個來源瀏覽器案例全通過，約 2.3 分鐘**。保存／刷新／套用／重算／刪除復原案例 6.7 秒；服務重啟、來源離線修復、型別不相容、頁面複製與超限、四種命令唯讀拒絕也已驗證。沿用既有目錄；共同性與 SPC 共用頁面分析複製流程。證據 `.artifacts/commonality-saved-browser-results/evidence.json`，已核對 build manifest 與原始檔、保存 driver 並檢查截圖。

本輪保留失敗與修正：`commonality-settings-tests.xml` 為 82 通過／1 失敗，测试誤認保存點會增加 revision，改讀伺服器版本；`commonality-settings-regression.xml` 為 575 通過／3 失敗，包含唯讀 fixture 試圖透過禁止的編輯切成唯讀，以及新交付 guard 在舊契約檢查前讀取不存在的 report。唯讀改由既有測試 fixture 覆蓋全部四命令；guard 不提前讀缺失 report，含設定時亦先核對 execution contract。修正專項 `commonality-settings-fix-tests.xml` **65 通過**，最終完整回歸與瀏覽器皆通過，未放寬原有保護或時間限制。共同性發布／匯出目前以 COMMONALITY_DELIVERY_UNAVAILABLE 拒絕，不省略分析交付；正式整合與安裝／NativeApp 尚待完成，下方 e82／b5 屬歷史來源／交付證據。

Commonality 來源操作入口（2026-09-06）：建置 `e82c98c351e5acdf388f76f6bc5a9d1ff685dd250ef5a2472c1c23a0265bd2ef`，新增 commonality API／worker 與 React 面板；共用探索驗證歸入 `analysis_scope.py`。完整 API **567 通過，226.31 秒**（既有退化 OLS 測試產生 1 項預期 warning），前端 **34 通過**，正式建置通過；6 個來源瀏覽器案例 **全部通過，約 2.1 分鐘**。共同性使用 100 晶圓母體、11 目標／89 對照，ETCH-02 lift=1.82、p=0.0008；畫面已檢查，門檻使用 yield_pct 原始 0–100 單位。證據 `.artifacts/commonality-panel-browser-results/evidence.json` 含測試、建置、driver 與截圖雜湊。

保留初次失敗：`.artifacts/commonality-api-tests.xml` 為 73 通過／1 失敗，測試把 yield_pct 門檻寫成 0.8，依固定資料原始單位修正為 80，未修改核心數值；後續完整回歸通過。`.artifacts/commonality-entry-browser.log` 為 4 通過／2 失敗，新面板誤用 SPC 的 CSS class，既有截圖定位器找到兩個面板。修正新面板使用獨立 class，以 CSS 共用 selector 保留樣式，並使單位說明跨整列；重建後同一組 6 案例全通過，未放寬測試或時間限制。SPC、發布及完整流程繼續使用真實 API。新增 commonality 設定保存、發布／匯出、完整探索矩陣及新版安裝／NativeApp 仍待完成；以下 b5 安裝證據屬前版，不代表本次新功能已交付。

SPC 安裝／NativeApp 交付驗證（2026-09-06，同一 `b5dd13a3…`）：只擴充既有 `scripts/probe_app_wheel.py`、`scripts/validate_nativeapp_desktop.cjs`；產品來源未變，來源 544 API／34 前端／5 瀏覽器證據仍對應本版。wheel 2,060,065 bytes，SHA-256 `f6d9855a0100d460f82efa7057b92d2acd9ecc5cd4a971c1a293cccff56ec5c4`，保存在 `.artifacts/release/spc-delivery-wheels/`。獨立環境 `C:/Users/hctsa/AppData/Local/Temp/ai4bi-release-zm6bojpt` 不讀取兩個舊專案或本 repo 的 API／核心；離線安裝及 pip check、SPC 200 列／4 實體與保存／CSV／發布／服務重啟皆通過。release `.artifacts/release/offline-spc-delivery/evidence.json` complete=true、runner exit 0：create-env 9.50 秒、offline-install 91.16 秒、pip-check 1.14 秒、probe 14.88 秒。75 套件 notice inventory 仍有 ai4bi／streamlit 缺 license text，沒有宣稱完整授權證據。

安裝版 `.artifacts/installed-spc-delivery-browser/` 五項通過，runner 約 2 分鐘，完整報表約 1.4 分鐘；原 180／45 秒限制保留。receipt 綁定 installed origins／build、driver hash、fresh report；complete=true、exit_code=0、drivers_unchanged=true。download-verification.json 讀回發布篩選後 100 列／2 實體；JSON／CSV 除各自接受的 snapshot ID 外一致，Excel 數值與資料版本相同，PDF 12 頁可抽取全部實體及分析 ID。

新發布 Kit 解壓至 `.artifacts/nativeapp/kit-spc-delivery`；87 項，來源 ZIP SHA-256 `6c08dd026190fc45aa6eb93f273376439a6d57bdae33f8ac853b68a07a63a554`，receipt 在 kit-spc-delivery-receipt.json。接入包 `.artifacts/nativeapp/package-spc-delivery/ai4bi-web-0.1.0.napkg.zip` 195 檔、168,486,268 bytes，SHA-256 `2760e91d31ec54ed4eae19048277a800bb1ab39590d2608069eab1cac4d961d1`，validate／pack 皆 passed。`.artifacts/nativeapp/host-spc-delivery/` 由指定相容 CPython、包內 lock／wheels 建立全新環境，create-environment 97.95 秒；complete=true、provisioned_from_archive=true，準備／啟動／build 核對及同一持續 Host API 停止均通過，launcher_exited=true、endpoint_closed=true。

最新 Electron `.artifacts/nativeapp/electron-spc-transport/evidence.json` complete=true、passed=true、20 steps、runner exit 0。真實 iframe 手動配對、五圖、命名 SPC 保存、Host 重載後重開／套用／掃描、工作報表四格式下載、發布重播／JSON 下載、關閉取消／確認及 PID／埠退出均通過；所核對的 5 份殼來源檔前後雜湊相同。維護工具先核對新 workspace／report 的 query 請求，避免重用 Store 時誤操作相同 KPI 的舊工作區。下載事件使用 Electron will-download，測試 setSavePath 指定路徑；save_path_assigned_by_test=true、native_save_dialog_exercised=false。

桌面 download-verification.json 核對 600 列／12 實體：工作 CSV 7,791 bytes、JSON 31,706 bytes、PDF 64,919 bytes／12 頁、Excel 15,646 bytes；發布 JSON 31,706 bytes，read_only=true，設定／實體數值／資料版本與工作報表一致。每檔 SHA-256 及精度界線都在該記錄。SPC 與發布結果截圖保留且已檢視同版畫面。前兩輪 electron-spc-delivery（18 步）與 electron-spc-publication（20 步）亦通過並保留；其 native_save_dialog_automated 舊欄位名稱過廣，已由最後一輪明確欄位取代，實際都未操作原生 Save As 對話框。

所有新包、測試 Store、Kit 解壓、下載及日誌位於排除版本控制的 `.artifacts/`；維護腳本沒有新增責任目錄，外部平台來源未修改。本機公開 Kit＋Electron 來源殼不是正式發布 Electron Runtime、另一台新機或升級／回滾證據。P02／P05／P06 剩餘項目保持待辦。

SPC 發布／匯出（2026-09-06，`b5dd13a32163a64551cca14c259c816a6fd36ba023294eb6c0b1957a1d60daa2`）：`web-query-v3` 接入保存分析的批次執行；一般 query 明確 include_spc 才掃描，發布與匯出強制執行全部定義。每組固定自身頁面／選取圖與欄位契約，共用已核對來源，只對原探索頁套用臨時條件。發布檢查保存 SPC 狀態、實體／母體列數與分析契約；任何分析失敗都拒絕整筆交付。

完整 API `.artifacts/spc-delivery-api.xml`／log **544 passed，219.35 秒，exit 0**；前端 `.artifacts/spc-delivery-web-unit.log` **34 passed**；正式建置 `.artifacts/spc-delivery-build.log` 通過，verify_manifest 核對上述 build。一項既有退化 OLS warning。新增跨頁 100／600 列獨立母體與來源僅讀一次、一般圖表不隱式掃描、四格式實際內容、惡意公式／數學字串名稱、发布後刪除草稿設定仍重播、停止服務後重啟、舊 web-query-v2 接受前與執行前拒絕、分析失敗不產生部分檔案。初輪專項為 6 通過／1 Excel 浮點精確相等失敗，差異為正常 15 位數序列化；修正為逐列識別碼精確核對、數值 rel=1e-14／abs=1e-12 後納入完整通過，JSON／CSV 數值仍精確對照。

`.artifacts/spc-delivery-browser.log` **5 通過，runner 約 2 分鐘，exit 0**：SPC 篩選／取消 8.3 秒、保存重開 5.5 秒、發布／下載 12.2 秒、舊契約呈現 5.4 秒、完整報表約 1.4 分鐘；180 秒流程／45 秒查詢上限未改。發布案例驗證 600→100 列篩選、四格式下載、刪除草稿設定後重新打開原發布仍為 600 列、k=1.5。共用 SpcResultView 的截圖 `.artifacts/spc-publication.png` 已檢視，界限圖／離群表與狀態可見。

實際瀏覽器下載讀回：JSON 31,536 bytes、CSV ZIP 7,562 bytes、Excel 15,372 bytes、PDF 68,315 bytes／12 頁；均對應 100 列、2 實體與不足三組狀態。JSON／CSV 除各自接受任務的 snapshot_id 外完全一致，CSV manifest 與自有 analysis snapshot_id 一致；Excel 兩列實體、數值与資料版本核對；PDF 可抽取分析 ID、實體名稱與 web-query-v3。CSV 格式升為 2，新增 spc_summary／spc_points／spc_outliers 表，Excel 表保留原 analysis ID 註解，PDF 包含界限圖／狀態與完整表。檔案 SHA-256、driver、build、544 API 結果、固定發布設定／檢查、job timings 與資料根記錄在 `.artifacts/spc-delivery-browser-results/evidence.json`，完整 HTML 報告在 spc-delivery-browser-report。任務共 query 成功 80／取消 24、SPC 成功 5／取消 2、assistant 2、export 8、publish 4，沒有 failed job。

檔案結構：共用唯讀結果呈現新增於既有 `apps/web/src/components/SpcResultView.tsx`；其餘沿用既有 API／測試／文件模組，產生物都在忽略的 `.artifacts/`。此段為來源驗證；同版後續 wheel／離線安裝／NativeApp 證據見本文開頭；SPC 完整矩陣與 P05／P06 其餘項目保持待辦。

SPC 設定保存（2026-09-06，`4f59875226804a7e1ca608bb36b95e55eb19f3f574fe01994fa6190e4962bf11`）：新增共用 SpcSettings、SavedSpcAnalysis、四種設定命令及 React 保存／套用入口。伺服器捕捉欄位型別與分析契約，保存／更新驗證頁面、圖表、來源與欄位，改名／刪除可離線修復；頁面副本重映射設定，刪頁移除所屬設定，超限與型別變更拒絕。所有修改沿用報表歷史、冪等、唯讀與保存點。

完整 API `.artifacts/spc-settings-api.xml`／log **532 passed，211.36 秒，exit 0**；一項既有刻意退化 OLS SingularMatrixWarning。涵蓋設定保存／更新、保存點、undo／redo、實際服務停止後重啟及原請求冪等重送、過期版本、metadata 離線修復、已驗證圖表 proof 重用、非法設定、大小寫重名、來源型別漂移與修復、頁面／圖表歸屬、30 組原子性及新增四命令唯讀拒絕。初測的 Store 重啟案例誤在舊服務持鎖時建立第二個 Store，與未預熱 proof 的快取測試各失敗一次；修正測試生命週期／前置條件後納入本輪完整通過，未放寬產品資料鎖與驗證。

前端 `.artifacts/spc-settings-web-unit.log` **34 passed**；`.artifacts/spc-settings-build.log` TypeScript／Vite 通過，verify_manifest 核對上述 build。瀏覽器第一輪 `.artifacts/spc-settings-browser.log` **2 通過／1 失敗**：原 SPC 8.5 秒、完整報表約 1.4 分鐘通過（原 180／45 秒門檻保留），新保存案例在 getByLabel 精確匹配資料來源 select 時逾時；error-context 已顯示正確 combobox。修改新案例為 combobox 角色＋名稱定位，同一產品建置再跑 `.artifacts/spc-settings-save-browser.log` **1 通過，6.1 秒，exit 0**，證明命名保存、更新 k／aggregation、改名、報表保存、重載並核對原 workspace ID、套用選取圖、600 列真實掃描、刪除與復原。只有測試定位改變，不提高時限。

兩輪 results／report 分別保存在 spc-settings-browser-results／report 與 spc-settings-save-browser-results／report；各自 evidence.json 保留建置、532 API 結果、driver hash、受測資料根與 SPC 結果，後輪亦讀回保存定義。首輪 jobs 為 query 成功 73／取消 20、SPC 成功 4／取消 2、assistant 2、export 4、publish 2；後輪 query 3、SPC 1，均無 failed job。`.artifacts/spc-saved-settings.png` 為保存與刪除復原後畫面。新增輸出均在忽略的 `.artifacts/`，維護內容沿用既有模組／測試／文件，無新增責任目錄。本輪未重新封裝、未驗 NativeApp，也未完成 SPC 分析結果的發布／匯出。

35a89577 修正測試工作區就緒條件後的最終結果：`.artifacts/spc-exploration-identity-browser.log` **2 通過**（SPC 8.3 秒、完整流程約 1.5 分鐘、runner 1.7 分鐘、exit 0）。results／report、driver 與 evidence.json 保存於 spc-exploration-identity-results／spc-exploration-identity-report；包含重新驗證的 build、88 項相關 API 結果、driver hash、各 SPC 母體／條件與背景任務狀態。原 180 秒總流程、45 秒查詢及鍵盤選取／Plotly DOM 保留斷言均保留。SPC 案例除 600→100→600 母體及欄位保留外，還將真實接受回應延後，分別由手動取消及改跨圖條件取消，並核對取消請求的確切 SPC job ID，避免誤收一般查詢的取消回應；結果與 worker 未用 fixture 替換。前一輪舊工作區競態失敗保留，以下「重跑進行中」已由此結果完成。

SPC 探索 v2 來源 `35a89577f93e6af4192e2da9e563df00cd4915049673fc08c83a2e514cd031ec`：目前頁面／保存條件、選取圖 query.filters 的核心全域繼承、鑽取與臨時跨圖條件交集已接入。`.artifacts/spc-exploration-complete.xml` 88 項相關測試通過（45.58 秒，另 261 項未選入），涵蓋 SPC、AI、鑽取、書籤；本輪沒有重跑全部 API，不沿用 bd432448 的 504 項宣稱新全回歸。正式建置 1.43 秒通過。首輪 `.artifacts/spc-exploration-final-browser.log` 為 SPC 通過（9.4 秒）／完整流程失敗；SPC 已驗證 600→100→600 列、保留欄位與手動／改跨圖條件取消接受中的任務。完整流程在建立工作區後的鍵盤選取失敗；trace 記錄 focus=18845.735 ms，而建立 POST 開始 18729.247 ms、耗時 182.773 ms，即 focus 比回應完成早約 66 ms。原測試以兩個工作區皆有的 KPI 600 判斷就緒，尚未確認本次工作區。現測試先等建立回應、對話框消失、新 workspace ID 與該 report 的查詢請求，再執行原鍵盤／DOM 保留斷言；產品未變，原時限保留。失敗報告與 driver 保存於 spc-exploration-final-first-results／spc-exploration-final-first-report；修正後整輪驗證進行中。

bd432448 來源瀏覽器最終結果：`.artifacts/source-index-browser.log` **2 通過**（SPC 5.3 秒、完整流程約 1.4 分鐘、runner 1.6 分鐘、exit 0），保留原 180 秒總流程與 45 秒查詢門檻。完整 results／report 與測試來源保存於 source-index-browser-results／source-index-browser-report；evidence.json 記錄重新驗證的 build、504 API 結果、測試來源 hash、資料根與每個成功任務的分段耗時。此結果取代下方「新版瀏覽器尚待跑」狀態；來源索引已通過當前指定回歸，尚未重新封裝或 NativeApp 驗收，也不把兩輪執行時間差全部歸因於產品變更。

bd432448 完整回歸結果：`.artifacts/source-index-api-complete.xml`／`.log` **504 通過（225.80 秒）**，一項既有刻意退化 OLS 警告。前輪 source-index-api.xml 是 492 通過／12 失敗，全部失敗都在同一個恢復成功結果的舊精確斷言，因 coordinator 新增 timings_ms 而不匹配；故障釋放、錯誤碼、取消與後續派發斷言均已通過。測試改為精確檢查 recovered／timings_ms 欄位集合、三個時間欄位及其關係，12 個案例專項通過（5.39 秒），再完整重跑 504 通過；產品在兩輪間未改動。舊失敗證據保留，並非忽略其結果或放寬功能要求。

worker 來源索引（2026-09-06，`bd432448f84fc0b792f129aa2971e4a4184a442e97ab2bee6ac8e1697e01a70f`）：函式 profile `.artifacts/coordinator-million-load.prof`／`.log` 顯示百萬列載入 3.328 秒，其中核心 put_dataframe／hash 2.986 秒；此為獨立 profile，不直接和未 profile 的總流程比較。新增最多 32 筆 byte digest→core key 索引後，`.artifacts/source-index-focused.xml` 14 通過（5.45 秒），包括資料損壞、快取遺失／修改、變更 bytes、容量限制、dtype 碰撞、日期與 decimal 語義。`.artifacts/source-index-benchmark/evidence.json` 兩案各三次、六圖獨立數值對照均通過：十萬列 596.13／228.31／222.74 ms（載入 372.95／42.14／39.39 ms）；百萬列 3,587.26／492.23／513.80 ms（載入 3,338.64／278.62／276.84 ms）。峰值 working set 258.7／887.6 MiB、commit 約 549.0／1,245.7 MiB；均 exit 0。首次差異可能含機器狀態變化，索引收益主要對應同內容後續呼叫；百萬列正式 worker 仍會因記憶體峰值退役，這是 direct backend 同程序基準，不是正式 HTTP 重用或完整效能 gate。完整 API 回歸 504 項通過（225.80 秒，既有退化 OLS 警告一項），新版瀏覽器尚待跑。

前版 b4583637 的發布／匯出追加回歸 `.artifacts/coordinator-latency-publication-tests.xml`：118 通過（88.69 秒）；加上其 worker／接受／SPC 61 項，分別覆蓋協調器分段時間加入後的各種成功結果，不能說成重跑了前版完整 501 項。

協調器分段量測（2026-09-06，`b458363740d5a7fbbd1eb0b25044dbaf1fe98c77012042eb31c1e96a1a7f0659`）：61 項 worker／接受／SPC 回歸通過（38.87 秒），建置 1.37 秒；`.artifacts/coordinator-latency-browser.log` 兩項通過（SPC 5.4 秒、完整流程約 2.4 分鐘、runner 2.5 分鐘、exit 0），原時限不變。完整 results／report、driver 與 evidence.json 保存於 coordinator-latency-browser-results／coordinator-latency-browser-report。99 個任務共 75 個成功、24 個取消，沒有 failed；所有成功種類都有 coordinator 時間，包含兩次發布、四次匯出。最慢接受至收集 5,470.41 ms、排隊 37.69 ms、派送返回至收集 5,422.00 ms。前輪 f583b974 的 9.78 秒 imports 是預熱，其任務實際接受至完成約 3.28 秒；不可把所有 imports 都算成使用者等待。另一筆前輪 19.19 秒任務的 worker 執行僅 5.47 秒，旧資料沒有獨立排隊欄位，無法把其餘時間完全定因。重跑通過保留為目前版本證據，不宣稱歷史逾時已根治。

同版 `.artifacts/coordinator-latency-benchmark/evidence.json`：重用既有 benchmark_queries.py，在 22 欄、600 列種子延展資料執行六圖，逐一對照獨立 pandas 結果。100,000 列三次為 1,124.46／935.78／931.18 ms，峰值 working set 274.3 MiB；1,000,000 列為 6,730.84／7,250.96／7,163.54 ms，峰值 working set 1,182.0 MiB、commit 約 1,579.8 MiB；兩案 exit 0。百萬列載入／轉接為 6,213.65／6,797.56／6,668.95 ms，聚合明顯較小。此工具是直接後端、同程序三次且 OS 快取可用；沒有 HTTP、jobs、冷 OS 或瀏覽器 p95 驗收。正式 worker 的 768 MiB 完成後退役政策保持不變，不能用基準程序三次呼叫聲稱正式 worker 可在百萬列下重用。

SPC 最終來源 `f583b974e107eae0ffaa37d1bfebf5b6b68ec7958dfa267daccd82e633679691`：新增獨立 spc-panel 樣式後 TypeScript／Vite 通過（2.91 秒），修正初版復用 assistant-card 造成完整流程截圖定位不唯一的問題；該失敗保留於 spc-browser-regression-first-results。`.artifacts/spc-panel-browser.log` 為 1 通過／1 失敗（runner 4.2 分鐘）：SPC 19.8 秒通過，另檢查四條 Plotly trace 名稱與實際截圖；完整流程到發布檢視的清除篩選操作才達 180 秒總時限。results／report 與 driver 保存於 spc-panel-browser-results／spc-panel-browser-report，evidence.json 記錄版本與耗時。85 個背景任務沒有 failed；慢查詢 total 16.23 秒，其中 imports 10.44 秒，另一個 imports 9.78 秒。這不是單圖 45 秒失敗，亦不能憑沒有 failed 宣稱完整流程成功。完整 API 501 通過（430.35 秒）屬同一後端的前一前端 build 756afa68；後續只修改 SPC 類別和 CSS。前端 34 項通過（2.67 秒）。本版尚未離線安裝／NativeApp 驗證，效能回歸需接續處理。

SPC 來源 `756afa681b794e5fb05b1fc82b22448c37b185c3d6ccd0b538235f46b5815518`（2026-09-06）：`.artifacts/spc-api-focused.xml` 15 通過（9.87 秒），涵蓋手算 μ／母體 σ、mean／sum、缺值／少組／零變異、非有限值、類別空組、實體上限與真實 worker 快照／篩選／重試。TypeScript／Vite 建置通過（2.92 秒）。`.artifacts/spc-browser-complete.log` 及 `spc-browser-complete-results/` 真實瀏覽器 1 通過（案例 11.2 秒、runner 19.3 秒）：欄位／門檻、界限圖、表格、改聚合後重算及接受回應延遲時取消。取消只延遲真實接受回應，未替換 worker 結果。前兩次測試定位失敗保留於 spc-browser-first-results／spc-browser-role-results；修正 label 與巢狀 details 定位，未改產品或放寬時限。完整 API 回歸 501 項通過（430.35 秒，既有退化 OLS 案例產生一項警告），本版尚未離線安裝／Electron 驗證。

ef4e0b16 交付更新（2026-09-06）：新 wheel／195 檔接入包已核對，專案外離線安裝通過（建環境 19.09 秒、安裝 188.70 秒、pip check 3.05 秒、HTTP probe 28.36 秒）。Host 接用該獨立安裝環境啟停成功，provisioned_from_archive=false。`.artifacts/nativeapp/electron-download-lifecycle/` 真實來源 Electron 殼 passed=true、exit 0，完成配對、五圖查詢、編輯保存／重載重開、四格式下載、關閉取消／確認及實際程序／埠退出。content-validation.json 已核對四檔 hash、保存標題、KPI 600、CSV ZIP CRC、Excel 契約、PDF 五頁；下載／重載修復成立，不能延伸為完整桌面／發布版交付。先前 5 秒停止斷言與工作區 ID 競態皆屬工具問題，修正與各輪失敗證據詳見 NativeApp 接入文件。本段取代下方同版建立 wheel 中等較早狀態。

受認證下載修正（2026-09-06，build ef4e0b1698b4beeb23903d75741e68985539ae0196e49df74307166de8349352）：沿用 lib/api.ts、App、PublicationPanel，新增 tests/web/artifact-download.test.mjs 歸入既有前端測試目錄。前端 34 項通過（746 ms），新增認證 fetch／blob、401 不下載錯誤文件、關閉發布視窗中止的三項測試。TypeScript／Vite 1.41 秒建置通過；完整來源瀏覽器流程 1 通過（2.0 分鐘，runner 2.1 分鐘、exit 0），報告保存於 `.artifacts/authenticated-download-browser/`，原時限未放寬。首次透過根目錄 npm 轉接遺失 grep 參數，沒有找到測試、exit 1；改由維護中的 Playwright CLI 直接執行，未修改案例。wheel 建立中，尚未獨立安裝／Electron 驗收。本輪未改後端，不將前版 486 API 數字說成新跑。

1363c750 安裝桌面證據 `.artifacts/nativeapp/electron-partitioned-product/`：真實來源 Electron 殼與從封存檔建立的安裝環境成功配對、五圖查詢、編輯保存、殼內重載及重新開啟本輪唯一工作區／圖表；cookie 為 HttpOnly、Secure、SameSite=None、partitionKey=file://。後續 Electron will-download 收到 report.xlsx，但 state=interrupted，因此整輪 passed=false／exit 1；關閉取消／確認尚未執行。没有攔截產品回應，這證明重載修復但不代表完整桌面流程成功。

分區 session 修正（2026-09-06）：來源 build `1363c750…`，`.artifacts/partitioned-session-tests.xml` 4 通過（1.55 秒），覆蓋 strict／partitioned HTTP cookie 契約、來源拒絕、CSRF、一次配對、重啟失效與 launcher 選擇。TypeScript／Vite 建置通過（2.04 秒），`.artifacts/partitioned-session-api.xml`／`.log` 完整 API **486 通過（206.86 秒）**，一項刻意退化 OLS 警告，沒有失敗。正在建立 wheel，不能沿用下方 46dffae6 安裝驗收。真實 iframe CDP 已確認 SameSiteStrict 為 cookie 被拒原因；測試攔截回應的分區實驗可重載，但 Excel 下載逾時，整輪失敗，詳見接入文件。

Electron 實測（2026-09-06）：`.artifacts/nativeapp/electron-pairing/` 成功透過真實來源殼內嵌 build 46dffae6 安裝 App，配對與五圖查詢通過。擴充 `.artifacts/nativeapp/electron-report-flow/` 則失敗：編輯／保存兩次 commands HTTP 200 後，殼內重載的 workspaces 請求回傳 401，畫面退回配對頁；截圖已檢視，未執行後續 Excel／UI 關閉案例。不是瀏覽器回歸失敗，也不能把來源殼首次登入成功視為完整 NativeApp 驗收。平台 D27 正式殼已改 Electron，Tauri 選配；工具、限制與前兩次控制端修正見 NativeApp 接入文件。

交付更新（2026-09-06）：46dffae6 的獨立離線驗證已通過，receipt 為 `.artifacts/release/offline-execution-contract/evidence.json`，四個安裝／驗證步驟皆 exit 0，包含查詢、CSV 契約與發布後重啟查詢。安裝版六項瀏覽器案例全部通過（2.2 分鐘），證據 `.artifacts/installed-execution-contract-browser/`，其中完整報表 1.4 分鐘；runner／驗證器 exit 0、fresh_report／drivers_unchanged 皆 true，18 份下載已保存並計算雜湊，未放寬原時限。已檢視本輪 workspace-report.png，三個 KPI 與兩張分組圖正常呈現。新版 195 檔 NativeApp 包已驗證；`.artifacts/nativeapp/host-execution-contract/evidence.json` 的 complete／provisioned_from_archive 皆 true，新環境建立 101.19 秒、launch 2.45 秒、stop 5.22 秒，確認 launcher 退出與埠關閉。完整交付尚未完成；下方本版 wheel 建立中等文字為先前狀態。

## Web 執行契約（2026-09-06，完整回歸中）

完整 API 結果：`.artifacts/execution-contract-api.xml`／`.log` **483 通過，260.25 秒**，僅既有刻意退化 OLS SingularMatrixWarning，沒有失敗。包含新增的 JSON／CSV／Excel／PDF 契約資訊讀回，以及日期快照在來源改變後仍保留原數值。本版 wheel 正在建立；安裝版與完整瀏覽器流程須各自驗證，不沿用前版結果。

build `46dffae6f2b9e5c3cd23de143e84bb4bbaaacf69416e63867f53e9f0b60ea71d` 已加入 `execution_contract=web-query-v2`。新工作接受時納入 snapshot digest；發布 checks 與完成交易再次核對，列表與詳情明示相容性。查詢、AI、匯出及發布均在讀資料前拒絕缺失／不相符的快照契約；已發布工作亦核對資料庫 checks 的核心與 Web 契約。歷史紀錄保留可讀，不回填成新版本，不重建冪等請求。維護來源沿用 publications.py、jobs.py、core.py、exports.py、PublicationPanel 與既有測試，無新增目錄。JSON analysis、CSV manifest／analysis、Excel 來源工作表及 PDF Subject 也記錄契約，格式讀回測試已納入完整回歸。

初輪專項 8 通過／1 fixture 失敗（47.89 秒）：歷史發布 fixture 缺對應 jobs 外鍵，已補齊其歷史工作紀錄，未移除外鍵或修改不可變 trigger。後續發布／任務接受／worker 回歸 73 通過（174.09 秒），證據 `.artifacts/execution-contract-regression.xml`。包含兩種版本變更的真實 worker 查詢／匯出拒絕、接受後變更、列表一致性、10 種缺失／舊／未知／錯型別歷史契約，以及四類草稿工作的讀資料前拒絕。

TypeScript／正式建置通過（Vite 3.79 秒）。瀏覽器 `.artifacts/execution-contract-browser/` 1 通過（13.5 秒，runner 23.3 秒、exit 0），真實發布後注入不相容呈現，確認選單標示、仍可檢視、匯出停用且不送出查詢／匯出；截圖已檢視。API／worker 的實際拒絕由上段真實測試證明，不拿畫面 fixture 取代。完整 API 回歸正於 `.artifacts/execution-contract-api.log`／`.xml` 執行，本版尚未離線封裝。前版 be016e34 的完整瀏覽器成功只屬該版。

## 日期維度分組（2026-09-06，專項通過）

完整流程結果：`.artifacts/date-dimensions-full-browser/` 保存 build be016e34 的本輪報告、結果與 10 份下載雜湊，Playwright 1 通過（測試 2.8 分鐘，runner 3.0 分鐘），外層明確回傳 npm exit 0；原 180 秒總時限與 45 秒查詢斷言均未修改。包含查詢、編輯、復原、保存、發布、唯讀與刷新全流程。這次在清理已知舊測試程序後通過；沒有据此宣稱所有歷史延遲已定因、長期壓測已完成或安裝版通過。發布契約版本缺口已寫入 P04，尚未實作，因此不可交付為完整成品。

build `be016e34199bc07dd8478e987ddefaac0f7deec25ce2a17d63e6e423e3df43f6`。新增 date_dimensions.py 集中粒度白名單、日期型別與 UTC SQL 轉接，沿用 ComparisonExecutor、核心報表驗證與 App 維度編輯器。沒有修改固定核心。日期／naive timestamp 按 UTC 解讀，offset timestamp 先轉 UTC；日／週一為起點的週／曆月季年／星期／小時皆由核心查詢路徑聚合，NULL 保留分組。不可把任意字串插入日期 SQL，非日期欄位明確拒絕。分組點選篩選沿用禁止狀態並提供說明，保存／復原沿用原子命令。

`.artifacts/date-dimensions-regression.xml` 41 通過（11.46 秒），涵蓋新日期分組、期間比較、sparkline；初輪 12 通過的空 pytest match 警告已移除，這轮無警告。`.artifacts/date-dimensions-export.xml` 1 通過（4.08 秒），資料來源更新後，舊快照 Excel 仍保留 2024-02 的 5 與 2024-03 的 7。TypeScript／Vite 正式建置通過（Vite 4.94 秒）。日期粒度瀏覽器案例 1 通過（16.0 秒，runner 27.6 秒），涵蓋月／年切換、復原、保存重載与不產生錯誤日期篩選；截圖 date-dimensions.png 已檢視，三個月 266／301／33 合計 600。PowerShell 對 stderr 訊息的包装回傳 1，Playwright 實際報告 status=passed、failedTests=[]，日誌 `.artifacts/date-dimensions-browser.log` 保留；不把 wrapper exit 1 當作 CLI exit 0。本版完整流程正在 `.artifacts/date-dimensions-full-browser.log` 重驗，尚未離線封裝。

慢查詢單獨重播：`.artifacts/installed-worker-read-lock-browser/slow-query-profile.json`，五圖皆 ready，query_total 919.64 ms、初始 import 2.55 秒，五次 DuckDB connect 累計約 0.30 秒。它不能證明完整流程性能，也不能用單次重播歸因原 5.1 秒執行或 7 秒 worker import。另確認舊 CLI 驗證遺留 7 組程序（14 個 PID），已逐一比對自己的驗證 launch.json 與命令路徑後清理，程序和埠均確認消失，證據 `.artifacts/nativeapp/orphan-cleanup.json`；未刪除資料。清理後重驗可排除這批已知背景程序，但不能預設逾時已修復。

停止驗證更正（2026-09-06）：host-worker-read-lock 的獨立環境建立與 ready build 核對成立，但原工具用不同 CLI 程序呼叫 launch／stop，Kit 的記憶體啟動登錄未共享；stop 回報成功後 PID 10184／35908 與 57441 埠仍存在。已將該 evidence.complete 改為 false，保留 cli-evidence.json 原紀錄及 stop_audit，並核對本輪命令路徑後清理程序與監聽埠。先前相同工具的停止成功紀錄也不足以證明實際退出。須改用同一持續 Host API、檢查真實程序與埠，再重新驗證；不得引用清空 running 清單宣稱停止通過。

## 安裝版 assignment 讀取拒絕（2026-09-06，修正驗證中）

e9fe06de 安裝版四案例已結束：KPI 小圖 26.1 秒、期間比較 18.9 秒、固定目標 18.5 秒通過；完整流程在發布視窗等待版本標題時達 180 秒總時限（workspace.spec.ts:1356），仍未通過。這輪已走過前版讀檔失敗位置，98 個工作為 78 succeeded／20 cancelled、沒有 failed，最慢 query 的 created→updated 為 10.059 秒，不能直接視為純 SQL 耗時。證據 `.artifacts/installed-worker-read-lock-browser/`：job-timings.json、action-timings.json、完整 trace 與 15 份本輪下載。工具確認 fresh_report=true、drivers_unchanged=true，但 runner／最終 exit_code=1；complete=true 僅表示驗證程序已結束。不同 trace 層的操作時間重疊，不能加總推導效能根因；本輪沒有證明完整互動通過或所有歷史失敗皆已修復。

666431ce 安裝版四案例結果：逐日小圖 20.5 秒、期間比較 17.9 秒、固定目標 17.0 秒通過；完整流程在清除探索篩選後等候 KPI 從 100 回到 600 達 45 秒門檻失敗（workspace.spec.ts:966），本次不是 180 秒總時限失敗。證據 `.artifacts/installed-sparkline-browser/` 綁定實際已安裝 core／App 路徑與 release receipt；6 份 PDF／截圖另存 downloads/ 與 downloads.json，避免後續測試覆蓋。

真實工作 `81c175d9f7704dce8ac43de93ed330fe` 於 07:28:32.387–07:28:32.712 UTC 失敗；診斷 assignment-read／PermissionError／errno 13／winerror null，worker.py:260、PID 11168、sequence 3、job_id 尚未讀出。`.artifacts/installed-sparkline-browser/failed-jobs.json` 保存有限診斷。這證明本輪讀檔失敗，不證明先前所有退出或逾時皆為同一根因。

以真實 Windows CreateFileW 禁止讀取，修正前讀取短暫鎖 0.2 秒仍造成退出，其他持續讀鎖與既有刪鎖案例符合預期：`.artifacts/worker-read-lock-before.xml` 為 1 失敗／3 通過（14.00 秒）。現在 read_assignment 只對 Windows PermissionError／errno EACCES 採最多 1 秒、間隔最多 25 ms 的讀取重試；持續拒絕仍退出並保留診斷，不重跑分析或改變工作綁定。已建置為 `e9fe06de4179508631907a9901d1730115c9be647710e0701e1e12d28ce5abec`，證據 `.artifacts/worker-read-lock-build.log`；worker／任務接受回歸 45 通過（59.93 秒），證據 `.artifacts/worker-read-lock-regression.xml`。

666431ce wheel 的離線安裝與 HTTP 基本驗證結果仍有效，但安裝版完整互動未通過；其 195 檔接入包亦尚非最終交付。e9fe06de wheel 已通過 offline-worker-read-lock 的獨立離線安裝、pip check 與 HTTP 查詢／匯出／重啟驗證（receipt complete=true，全部 exit 0）。本版安裝版四項瀏覽器案例正在 `.artifacts/installed-worker-read-lock-browser/` 執行；NativeApp 包尚未更新。

## KPI 逐日趨勢小圖（2026-09-06，專項通過）

聚合粒度邊界增補：`.artifacts/sparkline-grain-boundaries.xml` 2 通過（2.39 秒）。跨日重複值的日去重計數為 2／2，整體主數字為 3；每日 HAVING >10 排除日值 5／7 時，小圖明示無可繪值，原純量查詢仍為 12。測試修改獨立 fixture 契約，沒有改產品來源或固定核心；459 項完整 API 紀錄是增補前一輪，這兩項為額外專項證據。

交付已接續到新 wheel 與 71 套件的完整依賴集合；獨立離線安裝正在 `.artifacts/release/offline-sparkline/` 執行，詳細版本、雜湊與進度由 app-release.md 維護。前一版 052f8f04 的完整瀏覽器 trace 已依各 trace 檔案分別配對 before／after call ID，摘要 `.artifacts/worker-lock-browser/action-timings.json`。其中測試結束後 hook 約 9.30 秒，不能算成使用者查詢延遲，也不能直接加總不同層的重疊 action；根因仍未據此確定。

呈現邊界增補：新增 `tests/web/kpi-sparkline.test.mjs`，在記憶體中編譯正式 TSX 並以 React server renderer 檢查實際 SVG／表格，不另維護一份繪圖實作。4 個新案例涵蓋缺日／空值不連線、單點／常數的有限座標、±1e308 的縮放，以及大整數／高精度字串保留與 HTML 跳脫。前端合計 **31 通過，2028.52 ms**，證據 `.artifacts/sparkline-rendering-validated.log`。首次執行因測試根目錄找不到 apps/web 的 TypeScript 而失敗，改由 apps/web/package.json 解析既有相依套件後通過；沒有新增依賴或修改產品來源。此結果不取代瀏覽器鍵盤／焦點驗收。

建置 `666431ce815259d71664dd4c15c5bf06061a141fb583c16c526b33f76840e5e7`。新增 API `sparkline.py` 負責受治理日序列、React `KpiSparkline.tsx` 負責 SVG 與可讀資料表；均歸既有 API／components 目錄。日期轉接延伸 ComparisonExecutor，設定與原子保存延伸 KpiSettings／App，測試沿用現有 API／匯出／瀏覽器檔案。產物歸排除版本控制的 `.artifacts/`，未新增目錄責任。

沿用 show_sparkline。純量卡可選日期欄位，啟用期間比較時改用同一本期視窗、日期欄位與 keep／replace 策略；主數字不取小圖第一列或加總日值。每日 UTC 聚合透過原 executor 保留權限、作用範圍與篩選，HAVING 按每日粒度判定；序列最新 365 個有結果日期，查詢 366 列判斷截斷，缺日不補零或跨日連線。單點與常數值保留標記；無有限值明示原因，精確字串保留資料表。舊分組卡仍保留原表格，不偷偷清除 query dimensions。

Web 提供 SVG、鍵盤可展開的逐日原值表、截斷及 UTC 說明；show_sparkline 納入查詢指紋，單獨關閉亦重新查詢。PDF 額外產生趨勢頁及版本 footer，Excel 在主數字／期間比較表後附日期與原值、容量說明，JSON／CSV analysis 保留序列 metadata。

`.artifacts/sparkline-governed.xml`：9 通過，5.38 秒，涵蓋 UTC 與 RLS、比較範圍、365 日期上限、非加總 AVG 主數字、無效日期設定，以及 PDF／Excel 原值。初版 Excel 測試誤取版本來源工作表，改以 value 欄定位資料表；AVG fixture 先因未核准覆寫被核心拒絕，明確設定獨立契約的 average 方法後通過。未改核心拒絕規則。正式建置（含 TypeScript）通過，證據 `.artifacts/sparkline-final-build.log`。瀏覽器 `.artifacts/sparkline-browser/` 1 通過（18.0 秒，runner 26.5 秒），涵蓋啟用、資料表、保存重載、PDF 下載與單獨關閉觸發重查。截圖已檢視；下載 PDF 6 頁，第 2 頁為趨勢、每頁 revision，SHA-256 05647bf0b5a8852e36a7f59c81e9a3799fcf22be9af3d029dbd54c4220c76c6d，證據 pdf-check.json。27 項既有前端回歸通過（1137.77 ms），證據 `.artifacts/sparkline-web.log`。完整 API 回歸 459 通過（369.70 秒，一項刻意退化 OLS warning），XML failures／errors／skipped 均為 0（`.artifacts/sparkline-api.xml`／`.log`）；新版離線交付仍待驗證。

## 期間比較保留精確原值（2026-09-06，253 項回歸通過）

來源已建置為 `d633ea9a23b43fde4fee1a893b5b310af8691eae5ac41116ddc01d8cca621cb0`。`compare_query` 原先把純量呈現判定後的值重新組成結果表，使超出 JavaScript 安全範圍的整數與 Decimal 在比较無法呈現時變成 null。新增兩個轉接層案例以已治理查詢結果為輸入，先重現 2 失敗（`.artifacts/comparison-scalar-before.xml`，2.44 秒）；不是宣稱固定核心所有大數計算皆無損。

修正保留原 current_frame，只有 HAVING 等原因確實移除資料列時才補明確空值列；差異計算的有限數字條件不變。報表擴充與匯出回歸 253 通過（137.90 秒，一項刻意退化 OLS warning），包含兩項新增原值保留案例。輸出 `.artifacts/comparison-scalar-regression.xml`／`.log`；建置證據 `.artifacts/comparison-scalar-build.log`。尚未宣告本版瀏覽器或完整 API 通過，448 項完整 API 結果屬下方 052f8f04 版。

前一版完整報表逾時的資料根共有 106 個工作、沒有 failed 狀態，最慢工作是匯出 8.951 秒（created 至 updated，包含排程及協調成本，不是純引擎耗時）。摘要 `.artifacts/worker-lock-browser/job-timings.json`，不含查詢內容或資料值。本次證據指向整體流程超過總時限，尚不能定因為單一 worker 或特定查詢。

最新 worker 建置與回歸證據見本文「Worker 致命錯誤診斷與檔案鎖」；目前來源為 `052f8f04…`。完整 API 回歸 448 通過，539.92 秒；XML 核對 failures／errors／skipped 皆 0，唯一 warning 是刻意退化 OLS 案例。輸出 `.artifacts/worker-lock-api.xml`／`.log`。測後 manifest 已重新驗證一致。同版瀏覽器 KPI 雙案例通過（23.1／26.8 秒），完整報表流程於 workspace.spec.ts:1387 的版本相容提示達 180 秒總時限。證據 `.artifacts/worker-lock-browser/`，合計 2 通過／1 失敗；日誌未見 Worker result rejected 或 Idle worker failed，不將本次逾時歸因於 worker 退出。

## KPI 期間比較（2026-09-06）

來源 build **`bd4feb5511767a9345d36984ee9bbb0788ae77fa2376afed25c3b28a1bcd5b23`**。新增 API `comparison.py`，承接比較設定驗證、固定核心的 SQL 擴充點、期間視窗與篩選策略；一般查詢仍走原 GroupedExecutor，沒有比較 context 時不改 SQL。沿用 report_extensions／core、KpiSettings／VisualChart／types、exports 與既有測試檔。新增檔案歸既有 API 轉接責任，沒有建立另一份核心或規格；建置／pytest／Playwright／重播證據歸排除版控的 .artifacts。

支援固定 7／30／90／365 天對前一視窗，以及日曆月／季／年至今對去年同期間。日曆視窗重用固定核心 `_calendar_window`，不把固定 365 天標成日曆去年同期。錨點取同一接受快照、作用範圍與 RLS 內最新日期，probe 清除 HAVING／sort／limit；兩期各自執行原指標與 HAVING。期間查詢 data_version 包含日期範圍，metadata 加入 UTC 起訖與 anchor 說明。日期與無時區時間按其原值，帶時區時間以 UTC 日期解讀；每次比較查詢明確設定連線 UTC，期間為開始日含／隔日不含。

compare_filter_policy=replace 沿用原版可分離日期條件替換，keep 保留全部條件。取代只處理指定來源／日期欄位的 query filters 與適用的持久條件；純日期群組可移除，AND 可分離，與其他欄位混合的 OR 拒絕並提示修改。其他來源、非日期條件、其他視覺範圍、RLS 不被移除；原報表與來源不變。前期零值只算絕對差異，负前期以絕對值為百分比分母；無日期、缺期或 HAVING 排除時明示原因，不退回全部期間數字。非有限差異不送出 Infinity。

Web 與 PDF 顯示同一組本期／前期起訖、數值差異與原因；Excel 在原指標表後附本期／前期數值、半開區間、百分比與策略，JSON／CSV ZIP analysis 保留完整 kpi.comparison version 1。期間比較目前限單一未分組指標，群組日期分析仍依完整計畫另行接入。

首輪 comparison-focused 為 **1 通過／3 失敗**，失敗是測試呼叫既有 filter_command 的名稱與參數次序錯誤，修正後 comparison-scope **4 通過，3.06 秒**。擴充後 comparison-expanded **14 通過／1 失敗**，抓到空陣列 compare_period 被誤當成關閉；改為只接受 None／空字串關閉，其他非法型別拒絕。comparison-validated **15 通過，9.65 秒**，包含 UTC 午夜／時差與 RLS、keep／replace、混合 OR 拒絕、閏日、零／負／缺期、無日期、非法設定與真實快照及 PDF／Excel。另補 HAVING 每期重算、DST 時差、日曆季／年與發布 worker／JSON 下載案例，已納入最後完整 API 回歸（443 通過），詳見本段末尾。

comparison-build.log 的 TypeScript／Vite 正式建置通過（Vite 4.83 秒）；補上 metadata 說明後 comparison-lineage-build.log 重建 API 與型別，前端未變。既有前端純呈現回歸 **27 通過，1414.55 ms**（comparison-web.log），不把這 27 項冒稱新期間比較 DOM 測試。

首輪 `.artifacts/comparison-browser/` **1 通過／1 失敗**：期間比較 21.6 秒通過，後續固定目標案例遇到 worker exit 1、無 completed marker 與 result.json，等待 45 秒後失敗。失敗查詢 `331a39d3966b4e2c91db41118e7247f3` 在隔離資料副本交給 fresh worker 重播 exit 0，產生正常結果；重播證據 `.artifacts/worker-replays/bcb4d63597054b19be063a108482b522/`。這不等於待命 worker 交接已修復，也不代表根因已定位；原程序 stderr 被丟棄，尚無足夠證據判定具體異常。

相同 build／測試 SHA、全新資料根重跑 `.artifacts/comparison-repeat-browser/` **2 通過，21.4／18.7 秒，runner 47.9 秒**，未調整門檻或重寫失敗断言。期間案例驗證 600→本期 33、前期 77、差異 -44／-57.14%，實際區間 2026-05-01～05-07 對 04-24～04-30；切換日曆月後前期缺資料，仍呈現本期 33 而非全部期間 600；保存重載與 PDF 通過。第二案例回歸固定目標與格式。截圖已檢視，日期／差異／UTC 及策略文字完整可見。

同輪比較 PDF **39,798 bytes、5 頁**，SHA-256 `c07d036413d425d28d9f349a68b21bf8cded48a6227f04de71814ca645064ef7`；固定目標 PDF **34,544 bytes、5 頁**，SHA-256 `9f40bc6290e2ce5a00d63ba164351b52488ae130bb7c832d0a20d41a335d12f3`。兩份皆已讀回核對期間／差異或目標標籤及每頁 revision，verify_manifest 與同輪 build 相符，見 pdf-check.json。

本輪期間比較與固定目標專項通過，但 worker 偶發失敗仍待診斷；未宣稱完整穩定性或 P06。sparkline、其他日期／分析／圖表主題、真正 NativeApp、安全 bootstrap、完整效能／恢復與最新離線交付仍未完成。最近已驗證安裝包仍為 a2341d，來源版不得當成新版已交付。

完整回歸初跑 comparison-api.log 在約 80% 時主動停止，**不是通過結果**，停止紀錄見 comparison-api-stopped.json。新增比較測試直接修改了核心 fab_template._CACHE 中的共用 DataBlockContract，造成其後 KPI、樞紐、日期資料框及其他工作區測試資料被污染；這是本輪新增 fixture 的隔離缺失。已在 comparison_fixture 修改前深複製 contracts，並新增共用範本不變的回歸。發布案例另用了 7 字元冪等鍵，低於既有 8 字元要求，已改為合法鍵；產品驗證規則未放寬。新程序的 comparison-isolated.xml **23 通過，22.22 秒**，涵蓋上述比較、發布、快取隔離及既有 KPI／日期資料框回歸。全套另以新程序與新資料根重跑，comparison-api-isolated.xml／log 最終 **443 通過，663.56 秒**，零失敗／錯誤／跳過。唯一 warning 為既有刻意退化 OLS 測試。來源 manifest 再次核對為 bd4feb55，沒有在全套期間改動產品來源。此耗時不代表效能穩定，前述瀏覽器 worker 偶發退出也沒有因此獲得根因或修復證據。

## KPI 格式、固定目標與狀態（2026-09-06）

來源 build **`f720c5c4d655eb52b81397cf9a45a2f6765d61cf6f04b95aaf506e0d5ff18d8a`**。新增 `services/api/src/ai4bi_web_api/kpi.py` 負責查詢結果的格式與判定，`apps/web/src/components/KpiSettings.tsx` 負責同一原子命令的設定草稿；均使用原有分層目錄。Core、Web 呈現、PDF、型別與測試沿用既有檔案。所有 build／pytest／Playwright／PDF 證據歸既有排除目錄 `.artifacts/`。

小數位可選 0–6，缺省保留 Web 最多兩位、不強制補零；K／M／B 縮寫須明確開啟，單位最多 64 字。沿用原版 `extra.target`／`target_good_if` 與 `rag.target`／`warn`／`good_if`，由未四捨五入的有限原始值判定。注意門檻不能在達標側，非法設定在接受報表前拒絕。前端只顯示伺服器回傳的 `kpi` version 1，不自行重算或改變聚合。分組、多列、多指標、截斷結果保留資料表；PDF 亦補上單列但有分組時使用表格的規則。

進度是目前數值相對固定目標，沒有日期推估。正目標與非負實際值才提供比例；越高越好使用 value/target，越低越好使用 target/value，實際為零且正目標時視為已達標，進度封頂 1。文字另外標示 actual/target 百分比，避免把倒數進度當成實際占比。零／負目標仍判定是否達標，但明示比例不可用；非有限值不判定狀態，溢位比例不送出 Infinity。原始數字在資料／JSON 中保留。

首輪 `.artifacts/kpi-focused.xml` **25 通過，5.38 秒**，包含真實核心查得 600、驗證前拒絕矛盾門檻、兩方向／等值邊界、零／負／非有限值、顯示四捨五入不改判定、縮寫與實際 PDF 內容。該輪 14 項測試警告來自多餘的空字串 match，已移除；另一警告顯示中文字型缺少 ≥，共享標籤改為 >=／<=，避免 PDF 缺字。

TypeScript／OpenAPI 型別生成與正式建置通過（最後 Vite 2.60 秒，`.artifacts/kpi-accessible-build.log`）。既有前端呈現回歸 **27 通過，1229.65 ms**（kpi-web.log），新 KPI DOM 操作由瀏覽器案例驗證，沒有宣稱這 27 項是 KPI 新增測試。

首輪瀏覽器在精確定位方向選單時失敗，保留 `.artifacts/kpi-browser/`。補上兩個 select 的固定 aria-label 後重建，`.artifacts/kpi-target-browser/` **1 通過，19.2 秒，runner 26.8 秒**：600.0 件、800 目標／500 注意門檻／75% 進度、非法 900 注意門檻保持原狀、零目標移除進度條、改越低越好 400 目標／700 注意門檻得到注意及實際占比 150%、保存重載與 PDF。未放寬等待門檻。截圖已檢視，卡片完整呈現數字、文字狀態與進度，沒有只靠顏色傳遞狀態。

PDF **34,397 bytes、5 頁**，SHA-256 `450891c0dbe4bd0951456506cea674dd5177c5dc9eee7ff27d7b6b9f5e5366f0`；600.0 件、注意目標 <= 400.0 件、150.0% 及每頁 revision 已讀回，並以 verify_manifest 核對同輪 build。見該目錄的 pdf-check.json／evidence.json。

最後完整 API 回歸 `.artifacts/kpi-api.xml`／log：**424 通過，335.18 秒**。唯一 warning 為刻意退化 OLS 的既有數值測試，首輪的空 match／字型警告已消除。新增 KPI 判定、真實查詢與 PDF，以及既有報表交易、發布、worker／CLI／備份／匯入／權限等現有 API 測試全部通過。本輪未再跑主要報表長流程，最新同版瀏覽器證據為上述 KPI 專項；309112d1 的完整流程證據保留原版身分。

日期比較／delta／sparkline、完整圖表主題與領域分析、效能／恢復、真正 NativeApp WebView、安全 bootstrap 及新版離線交付仍未完成；已驗證交付包仍是 a2341d。上一版 309112d1 的全流程與完整 API 證據列於下段，版本不得混用。

## 整合回歸（2026-09-06，309112d1）

同版完整 API 回歸 `.artifacts/integrated-api.xml`／log：**399 通過，343.26 秒**。一項 warning 來自刻意退化的 OLS 數值測試。涵蓋 worker 生命週期、Windows 清理、啟動身分、工作區與報表 API；不代表所有計畫功能已實作。

`.artifacts/integrated-report-browser/evidence.json` 記錄 build `309112d19ea047f625f85459c3c631d78b114b1025471708154f9927294f89e7`、獨立資料根與測試 SHA。主要報表 E2E **1 通過，案例 177.307 秒、runner 184.963 秒**，零非預期失敗／flaky／跳過。包含真實查詢、篩選、鑽取、參數、保存重載、匯入、匯出及固定版本發布；LLM 使用 mock，最後相容性與唯讀畫面使用回應 fixture，真實授權拒絕另由 API 測試涵蓋。中文 composition 事件測試不代表 OS IME 驗收。

未放寬 180 秒案例與 45 秒查詢門檻，距案例上限僅約 2.7 秒；不能視為穩定效能或完整 P06。workflow-check.json 保留慢步驟，job-timing-check.json 的 94 個任務中，最慢完成查詢 created→updated 約 8.08 秒；此時間包含排隊與執行，不宣稱根因已定位。HTML 報告與本輪截圖已保存，發布畫面已檢視。NativeApp 真正 WebView、安全 bootstrap、新版離線包與完整功能／效能／恢復仍未完成。

## 平均值與自訂基準線（2026-09-06，專項通過）

前次基準線建置 **`309112d19ea047f625f85459c3c631d78b114b1025471708154f9927294f89e7`**。沿用 chart_format.py 計算及驗證、cartesianFormat.ts／barChart.ts 呈現、App 設定控制與 exports.py 匯出；未新建統計來源或目錄。測試沿用既有 API／web／E2E 目錄，證據歸 .artifacts。

baseline=mean 對第一指標已接受查詢結果的有限數值作算術平均，回傳母體 scope=query_result、有效／排除筆數及固定兩位小數標籤；不是原始事件的加權平均，也不把分組堆疊高度当成重新聚合後的平均。查詢自身的 limit 仍屬查詢母體；超過顯示上限的 truncated 結果不產生冒充完整結果的平均線。無有效值或 fsum 溢位時回傳 unavailable 與原因。custom 接受有限數字，拒絕空值、字串、布林及無限值；非正基準在 log 軸不可呈現，保留原圖與原因。關閉基準線不改變查詢數值。

Web 使用 [Plotly shape 的資料座標](https://plotly.com/javascript/reference/layout/shapes/) 畫參考線，與軸 range 的 log10 表示分開；不新增可點擊的資料系列。直向長條／折線畫水平線，橫向長條畫垂直線。基準文字與平均母體在图卡可讀文字中呈現，PDF 使用同一值及標籤，不另算平均。保存重載沿用既有報表命令與版本契約。

`.artifacts/baseline-regression.xml` **208 項報表／匯出回歸通過，108.75 秒**，一項既有數值奇異測試 warning。新增案例涵蓋有限第一指標平均、排除文字／布林／NULL、截斷母體、空母體、log 非正基準、無效自訂值及直向／橫向實際 PDF 線座標。`.artifacts/baseline-web.log` **27 通過，983.62 ms**，包含兩種方向的 shape 原始座標與 unavailable 不畫線。`.artifacts/baseline-build.log` TypeScript／Vite／API 建置通過（Vite 2.11 秒）。

同版 `.artifacts/baseline-browser/` **1 通過，22.3 秒（runner 30.3 秒）**：move_count 平均 100、自訂 50、切換橫向、log 軸 0 值提示與 shape 移除、恢復 50、保存重載及 PDF 下載。截圖已檢視，垂直基準線與 50.00 標籤可見。下載 PDF **29,920 bytes、5 頁**，SHA-256 `8085e4254988cee443e390b50329810c48d4f2bb46ab022fd88641498b3ee098`；基準 50.00 及每頁 revision 已讀回核對，實際 manifest 與同輪 build 一致，見 pdf-check.json。

這是基準線專項，不表示全部格式／主題、KPI 比較與目標、領域分析、完整 API／工作流程、效能／恢復或真實 NativeApp 已完成。尚未重建含本次來源的 wheel／接入包，最近已驗證交付仍為 a2341d。

## 橫向與分組長條（2026-09-06，專項通過）

前次分組長條建置 **`9b5f46bf01251b00e28e5c1d3b7d6e529fc33862b516ee078947661e672f11f8`**。新增 API bar_chart.py 產生分類索引、系列及原始列綁定，components/barChart.ts 呈現相同投影；PDF 沿用 exports.py，抽出共用座標格式與長條繪製 helper。檔案歸既有 API／components／測試目錄，產物歸排除版控的 .artifacts。

支援 vertical／horizontal、group／stack／overlay。第二維度決定系列、第一指標決定值，其餘指標保留資料表；額外維度加入分類，維持原查詢粒度。單維度仍保留 Web 既有多指標系列，相對原版只用第一指標屬明確擴充。數字 1、字串 1、NULL 具有不同分類／系列身分，圖面以索引定位避免 Plotly 文字類別合併，篩選仍使用原始第一維度值。沒有補零或重新聚合稀疏分類。橫向圖交換分類／數值軸，數值格式、對數界限及標題隨數值軸移動；設定面板明示這項行為。

排列依 [Plotly 長條契約](https://plotly.com/javascript/reference/bar/) 與 [barmode 語意](https://plotly.com/python/reference/layout/)；stack 逐系列累積幾何基底，不將堆疊結果宣稱為新的可加總業務指標。overlay 使用透明度顯示重疊。PDF 使用同一分類與個別值，分組圖後附完整資料表。其他主題／基準線與完整高基數驗收仍待完成。

`.artifacts/bar-group-regression.xml` **201 項報表／匯出回歸通過，109.15 秒**，一項既有數值奇異測試 warning。新增型別分類／稀疏原始值測試與六種方向／排列的實際 PDF 幾何驗證，包含負值、空值、原始額外指標與完整資料頁。前端初驗因 Node 無法解析無副檔名的跨 helper import 失敗（bar-group-web.log）；改明示 .ts 並在既有 noEmit tsconfig 啟用 allowImportingTsExtensions，未另建編譯輸出或測試來源。`.artifacts/bar-group-import-web.log` **26 通過，1062.29 ms**；`.artifacts/bar-group-build.log` TypeScript／Vite／API 建置通過（Vite 2.12 秒）。

同版 `.artifacts/bar-group-browser/` **2 通過（26.5／23.0 秒，runner 57.5 秒）**。分組案例實際新增 product_family 五系列、增加第二指標後仍只顯示第一指標且合計 600、切換橫向、滑鼠點擊使其他 KPI 600→100→600、切換並排／重疊／堆疊、保存重載及 PDF 下載；另一案例回歸軸標題／log 範圍／清除界限／標籤／長條轉折線。測試 SHA、獨立資料根、manifest、報告與截圖保留；截圖已檢視。

下載的分組 PDF **38,956 bytes、8 頁**，SHA-256 `a5e0c5827efe8e666ffd624bc1b0e7653ae47c1dbaaebc2c86ed0d75befc58db`；五個產品系列、move_count、avg_queue_time_hr 完整表與每頁 revision 已讀回。格式 PDF **29,755 bytes、5 頁**，SHA-256 `c81a18cb5e0d542f873b1b9d3ebc65d9ffc728af5b86aca6a83118c241a40bf3`，軸名／100.00 標籤及版本已核對。兩份與實際來源 manifest 一致，見 pdf-check.json。

本次未重建 App wheel／NativeApp 接入包，不代表完整 API、全報表 E2E、領域分析、效能／恢復或 P06 完成。最近已驗證交付仍為 a2341d。

## 直向長條／折線格式與範圍（2026-09-06，專項通過）

前次格式建置 **`9ece5cd7d603461f58db95c76d1bd5bab0daddf24f30c47be9014a47c9a6c295`**。API 新增 chart_format.py 驗證 linear／log、單邊／雙邊有限範圍與圖例位置，產生格式化資料標籤；空值顯示破折號，查詢原始值與篩選契約不變。數值格式支援 Python／D3 共通的有限精度 f／e／g／% 表示（例如 ,.0f、.2f、.1%），未支援格式明確報錯。對數界限必須為正，雙界限須遞增。這不是全部格式或全部 D3 語法完成。

React components/cartesianFormat.ts 負責 Plotly 軸與圖例投影；VisualChart 套用伺服器標籤，App 提供設定與將格式相關欄位納入查詢指紋，exports.py 套用同一範圍、標題及資料標籤。格式範圍改變時更新 uirevision，清除界限恢復自動範圍；一般查詢更新仍保留既有縮放。檔案依既有 API／元件／測試目錄責任新增，沒有引入另一套資料或統計來源。

初版瀏覽器 `.artifacts/cartesian-format-browser/` 發現單邊 log 下限 10 被當成指數 10。依 [Plotly autorange 原始碼](https://github.com/plotly/plotly.js/blob/master/src/plots/cartesian/autorange.js) 的 minallowed／maxallowed 行為修正為 log10，與雙邊 range 同樣轉換一次；[軸參考](https://plotly.com/javascript/reference/layout/yaxis/) 的範圍與圖例設定作為呈現依據。`.artifacts/cartesian-log-browser/` 清除上限案例選到與自動上限相同的 1000，無法辨別兩種狀態；改為固定 10000 後再清除，沒有放寬時限。同輪既有單圖更新／縮放保留案例 **12.3 秒通過**。`.artifacts/cartesian-range-browser/` 隨後格式專項 **24.6 秒通過（runner 32.5 秒）**，但截圖顯示下方圖例太接近軸文字；最終改為 container 底部定位及留白，加入圖例位於橫軸標題下方的幾何斷言。

後端 `.artifacts/cartesian-format.xml` **184 通過／10 失敗，119.68 秒**，10 項皆為新增 fixture 缺核心必需 BlockRef；補齊後 `.artifacts/cartesian-focused.xml` **10 通過、40 deselected，4.82 秒**，覆蓋無效界限／刻度／圖例／格式、空值與百分比、長條和折線實際 PDF 軸及標籤。兩次結果分開保存，不宣稱單次完整回歸全綠。一項既有 warning 來自數值奇異測試。最終 `.artifacts/cartesian-layout-web.log` **24 項通過，905.66 ms**；`.artifacts/cartesian-layout-build.log` TypeScript／Vite／API 建置通過（Vite 2.35 秒）。

最終 `.artifacts/cartesian-layout-browser/` **1 通過，25.2 秒（runner 33.0 秒）**，實際操作軸標題、log 下限 10、上限 10000、清除／重設上限、下方圖例、小數標籤、長條轉折線、保存重載与 PDF 下載。截圖已檢視，圖例位於橫軸標題下方。PDF **29,724 bytes、5 頁**，SHA-256 `ddf46e9b5f927f801ad997b0291e91cb2972b6876ac108535b9bbe61d2251efc`；Process／Moves、100.00、move_count 與每頁 revision 已讀回，manifest 核對同版來源，見 pdf-check.json。

橫向／第二維度分組長條、基準線、其他格式／主題／領域分析、完整工作流程、效能／恢復、真實 NativeApp 與新版離線交付仍未完成。本次未更新 wheel／接入包，a2341d 仍是最近已驗證交付；不勾選 P04 或 P06 整體完成。

## 圓餅／圓環與鑽取 PDF 欄位修正（2026-09-06，專項通過）

前次圓餅建置 **`b26fdbf9c5b45d9be3776c14dd13381b03df0b8d3cad47b9b9a82d72603ac12a`**。新增 API `pie.py` 負責受治理查詢列的比例附加資訊，React `components/pieChart.ts` 負責純呈現與點擊索引解析；設定沿用 App、匯出沿用 exports.py、驗證沿用既有 API／web／E2E 目錄。生成資料、建置及測試證據仍歸排除版控的 `.artifacts/`，不增加第二份功能規格。

第一指標決定切片，其他指標保留完整資料表；多維度使用完整組合標籤，同名文字以列序號消歧義，避免 Plotly 再次合併加總。篩選保留第一維度的原始型別和值。百分比依查詢的有限非負權重計算，隱藏圖例不重新定義母體。負權重、非正總和及截斷结果顯示原因與原始資料；空值／非有限權重明示排除。支援內徑 0–0.9、百分比、數值與五種圖例位置。Web／PDF 共用比例資料；PDF 圖後保留包含額外指標的完整表格。

初版真實點擊回傳的 Plotly `customdata` 是陣列，錯誤送入 SQL 等值篩選；改由單一 `pointNumbers`／`pointNumber` 取得伺服器切片原值，拒絕模糊或越界索引。失敗證據 `.artifacts/pie-browser/` 保留。`.artifacts/pie-filter-browser/` 捕捉新增指標後無指定排序的查詢列重排，測試改按分類比對金額；`.artifacts/pie-row-binding-browser/` 捕捉伺服器確認前的核取方塊立即斷言，改為真實點擊後等待設定及圖面一致，不延長既定限時。

`.artifacts/pie-settings-browser/` 的操作與保存已通過，但 PDF 工作失敗；同一固定快照於 `.artifacts/pie-export-reproduction.log` 重現 `KeyError: 地區`。原因為 PDF 索引保存規格的別名，而鑽取查詢實際回傳 city。exports.py 現在使用查詢結果附帶的有效 query，且不修改保存報表。新增長條／折線鑽取別名、實際 PDF 標籤及保存規格不變的回歸。

驗證：`.artifacts/pie-focused.xml` 11 通過；比例後端的完整報表／匯出回歸 `.artifacts/pie-regression.xml` **182 通過，121.18 秒**，一項既有數值奇異測試的預期 warning。`.artifacts/pie-filter-web.log` **22 通過，669.50 ms**。TypeScript／Vite 完整建置 `.artifacts/pie-filter-build.log` 通過（Vite 2.44 秒）。最後 PDF 欄位修正後 `.artifacts/pie-drill-export.xml` **全部 40 項匯出測試通過，55.21 秒**，並以 `.artifacts/pie-drill-build.log` 重建 API 與 manifest，沿用未改動的前端。

最終 `.artifacts/pie-drill-browser/` **1 通過，34.6 秒（runner 42.1 秒）**，實際零售報表驗第一指標不被新增指標改變、圓餅滑鼠與表格鍵盤篩選、清除恢復、內徑 0／0.6、百分比與數值、圖例隱藏／下方、保存重載及 PDF 下載。截圖已檢視。PDF **96,826 bytes、12 頁**，SHA-256 `aa5f3928f47c7f72eb9b90ca56015bbd2613645504836de3678d038a8ebff928`；第 7 頁為圓環圖，第 8 頁完整分類／營收／order_count 表。720730／1644310／1638520、四個鑽取城市及每頁 revision 已讀回核對，見 `pdf-check.json`；manifest 實際檔案完整性與本輪 build 一致。

這是圓餅及跨圖 PDF 專項，不代表完整 API／全報表流程、高基數、全部格式／分析或 P06 完成。尚未重新生成含本次來源的 App wheel／NativeApp 接入包，最近已驗證交付仍為 a2341d。新 statsmodels 依賴與離線閉包剩餘工作見下段。

## 分組 OLS／LOWESS 趨勢與依賴（2026-09-06，專項通過）

前次趨勢建置 **`46866caef2cbfd59760a0221a18a354f39bd81a740a03332853db3814d09dbec`**，TypeScript／Vite／API manifest 建置通過（`.artifacts/trendline-legend-build.log`）。沿用 scatter.py、scatterChart.ts、VisualChart、App、exports.py，不建立第二份統計模組；伺服器按原始型別群組分別擬合，Web／PDF 使用同一排序曲線。OLS 含截距並回傳斜率、截距與 R²；LOWESS 固定 frac=0.6666666、it=3、delta=0，對齊 [Plotly 趨勢函式](https://github.com/plotly/plotly.py/blob/main/plotly/express/trendline_functions/__init__.py) 及 [statsmodels LOWESS](https://www.statsmodels.org/stable/generated/statsmodels.nonparametric.smoothers_lowess.lowess.html) 參數。

至少兩筆有限座標及兩種 X 才擬合；數值奇異、非有限擬合或結果截斷時保留原點與不可擬合原因，不以截斷樣本冒充完整查詢母體。常數 Y 的未定義 R² 回傳 null，不輸出 NaN／Infinity。趨勢線獨立於資料點篩選，與同組點共用圖例／顏色；PDF 圖後有完整資料表及六欄擬合摘要，避免把係數分頁後失去群組身分。設定經既有命令保存與重載。

`.artifacts/trendline-focused.xml`：12 項初驗通過（27.36 秒），含原版 Plotly 的 OLS／LOWESS 非退化分組曲線逐點對照、已知 y=2x+1、單點／常數 X／截斷拒絕與實際 PDF 曲線。最終統計邏輯的完整 `test_report_extensions.py`＋`test_exports.py` **170 通過，130.25 秒**（`.artifacts/trendline-regression.xml`／`.log`）；一項預期 SingularMatrixWarning 來自刻意建立的數值奇異測試，結果已標不可擬合。最後只修正圖例重複與 PDF 標題，另跑 **8 項散點 PDF 回歸，11.38 秒**（`.artifacts/trendline-legend.xml`）及 **18 項前端測試，710.79 ms**（`.artifacts/trendline-legend-web.log`），全部通過。

同版 `.artifacts/trendline-legend-browser/` **1 通過，33.7 秒**（runner 44.7 秒），驗六組單點提示、增加 tool_id 後六條 OLS 曲線、切換 LOWESS／OLS、係數摘要、保存重載、六項共用圖例及實際 PDF 下載。截圖已檢視。下載 PDF **52,993 bytes**、SHA-256 `99c8e9acab980c32c90f6f013e1cc2fa1542421f701aaecae597d1a2265a41d9`，7 頁，第 6 頁擬合摘要；六群組、OLS 係數及每頁版本標記已讀回核對，見 `pdf-check.json`，同時驗 manifest 一致。`.artifacts/trendline-filter-browser/` 原有散點滑鼠／鍵盤篩選與匯出回歸 **1 通過，25.7 秒**（runner 35.0 秒）。各自保留測試 SHA、資料根與報告。前次圖例未整併的 4ab1a9 建置與 32.2 秒瀏覽器通過亦保留於 `.artifacts/trendline-browser/`，不混為最終 UI 證據。

新增直接依賴 **statsmodels==0.15.0**；本機解析新增 formulaic 1.2.2、patsy 1.0.3、interface-meta 2.0.1、wrapt 2.4.0，沿用既有 NumPy／SciPy／pandas。`.artifacts/trendline-dependencies/` 保存安裝報告、五個 wheel、`wheel-check.json`（逐一比對安裝報告 SHA-256）、八份逐字節告知文件與 `notices.json`。statsmodels CPython 3.11 Windows AMD64 wheel SHA-256 `5e1214312d6362cebe0b5c53b4f478d9072559709000369dfc528211cb993e8a`。已重建 editable 套件中繼資料，Requires-Dist 包含新依賴，pip check 通過；初次未隔離建置缺 bdist_wheel，改用 pyproject 宣告的隔離建置後成功，兩份日誌保留。沒有變更機器基礎 Python 的套件。

這是新依賴的準備與功能證據，並非完整安裝閉包或全新離線環境驗收。最新 wheel／NativeApp 包尚未重建；全部 API／完整報表 E2E、完整圖表格式與分析、效能／恢復、中文字型交付及真正 WebView 驗收仍未完成。

## 散點圖數值座標、分組與 PDF（2026-09-06，專項通過）

前次散點建置 **`2753c36f883055d2b9f209869071012c1acf42c4789051ee59abfd25a7d3aa87`**，型別／Vite／API manifest 完整建置通過（`.artifacts/scatter-build.log`）。舊版 scatter_chart.py 的第一指標為 X、第二指標為 Y；Web 原本以第一維度為 X、各指標各畫一組點，已修正。新 API `scatter.py` 將已接受查詢列轉為 version 1 附加座標，保留 row_index、原始 group 型別、x／y／size 及排除筆數；只有一個指標時 Y 使用原始零起算列序號，排除空值後不重編號。原始查詢列不變，CSV／JSON 保留原始結果。

新 React `components/scatterChart.ts` 僅排列座標，第一維度以顏色及形狀分組，群組數字／文字／空值不合併；tooltip 逸出文字，點擊沿用原始維度值。VisualChart 顯示非有限座標排除筆數，App 增加大小欄位控制及 scatter 查詢指紋，切換類型必須取得正確附加結果。大小欄位非負、有限，零／空值保留最小標記，負值明確拒絕。PDF 直接使用同一座標，圖後附完整資料表；不把分類值誤畫成量測 X 軸。檔案歸既有 API 轉接／前端 components／測試目錄，產物仍放 .artifacts。

前端 **17 通過，3068.83 ms**（`.artifacts/scatter-web.log`），新增兩項涵蓋精確座標、型別分組、符號、大小、原值、HTML 逸出與非法列索引。完整 `test_report_extensions.py`＋`test_exports.py` **165 通過，215.48 秒**（`.artifacts/scatter-regression.xml`／`.log`）：新增一項真實核心六站點合計 600 的座標逐列核對，兩項單／雙指標實際 PDF 及四項非法面積拒絕；既有地圖／直方圖／樞紐及資料／篩選回歸通過。

`.artifacts/scatter-browser/` **1 通過，30.2 秒**（runner 41.9 秒），真實操作驗單指標 Y=0–5、加入第二指標後座標與資料表一致、氣泡大小差異、滑鼠與鍵盤篩選 600→100→600、設定保存重載及 PDF 下載。截圖已檢視，X 為 move_count、Y 為 avg_queue_time_hr，六群組以不同形狀呈現。實際 PDF 39,143 bytes、SHA-256 `16699ad27760ff0cb448cf06cf001dd1140880cb4cea5a42b3c2a69a8acfb931`，6 頁、第 4 頁散點图與兩指標軸、下一頁完整資料表、每頁版本標記已核對；`pdf-check.json` 同時驗證 manifest 與測試 build 一致。測試雜湊、獨立資料根、報告及 PDF 保留於同目錄。

OLS／LOWESS 仍未遷移；帶 trendline 設定的報表在 Web 明示目前尚未計算擬合結果。沒有宣稱全部散點圖格式、高基數效能、全部 API／完整報表 E2E 或完整 P04 已通過。本版未更新離線 wheel／NativeApp 包，真正 WebView、完整分析與效能／恢復等驗收仍待完成。

## 離線地圖 PDF 與換日線（2026-09-06，專項通過）

前次地圖 PDF 建置 **`0946cb9e77782ac7a647b91ff80d0b1740b424021114570cab9d3a19eb54dbea`**。本次只修改 API 匯出與測試，`build_app.py --skip-web` 沿用已驗證 4bfb9394 React 資產，重建 API 型別與 manifest（`.artifacts/geographic-pdf-build.log`）。新增 API `geographic_pdf.py` 負責離線底圖解析及靜態排版；`exports.py` 在地圖頁後附完整原始查詢資料表，不聚合或丟棄未知地點。

同一份 world_50m 資產用於 Web／PDF；解碼差分弧線、反向索引及多環圖形。自動／台灣採 Mercator，世界採 Natural Earth I；跨換日線先展開經度再裁切，極區封閉通過極點。第一指標的絕對值控制面積，負數紅色、空值灰色、零值最小標記。固定台灣範圍為經度 118.5–123、緯度 21.5–26，PDF 不複製瀏覽器暫時縮放。格式依據 [TopoJSON 規格](https://github.com/topojson/topojson-specification#213-arcs)，投影係數核對 [d3-geo Natural Earth I](https://github.com/d3/d3-geo/blob/main/src/projection/naturalEarth1.js)。未增加地圖依賴或外部網路請求。

最終完整 `test_exports.py` **19 通過，80.35 秒**（`.artifacts/geographic-pdf-dateline.xml`／`.log`，basetemp 指標 `.artifacts/geographic-pdf-dateline-root.txt`）。含 7 項新案例：反向弧線／投影、換日線／極區、四種地圖資料與範圍，以及缺底圖拒絕。實際 PDF 保留 100／-25／0／空值與未知地點 888，標記面積及顏色符合契約；CSV、Excel、樞紐／直方圖 PDF 及完整分頁回歸亦通過。

`.artifacts/geographic-pdf-browser/` **1 通過，約 1.7 分鐘**（runner 約 2.0 分鐘）：同時驗既有地圖真正滑鼠／鍵盤篩選、範圍、滾輪、保存重載，以及背景匯出 PDF 下載；前端攔截外部 HTTP(S) 後請求清單為空。實際 PDF 787,408 bytes、SHA-256 `ae8456d2188cf9bc86a022961e1f1f659b4bc2c9fd62443c268ee416b1f651ad`，12 頁，第 6 頁地圖、下一頁四城市完整資料表、每頁版本標記已讀回核對。`pdf-check.json` 同時核對本機 manifest 與測試 build 一致；報告、資料根、測試 SHA 及 PDF 保留於同目錄。

台灣與世界地圖的 PDF 排版來源圖已檢視，PNG 保留於本次 basetemp 的 taiwan／world 案例目錄。中間版本雖 18 項數值與文件測試通過，世界圖仍出現跨換日線橫線，視覺檢查抓到後補上裁切與專項测试再驗。最初 1 失敗／5 通過為反向環線測試起點預期不正確，已修正並保留 `.artifacts/geographic-pdf.log`；不將中間綠燈冒充最終驗收。

本版未跑全部 API／完整報表 E2E，尚未重新打包離線 wheel／NativeApp。完整圖表格式與分析、效能／恢復、中文字型交付與真正 WebView 接入仍未完成。

## 直方圖與精確區間篩選（2026-09-06，專項通過）

前次直方圖建置 **`4bfb9394b0f4666ef45b0709adc1c46ec06bb77933ee71e9d9d176506b822daa`**。TypeScript／Vite／API 型別與 manifest 建置通過（`.artifacts/histogram-layout-build.log`）；瀏覽器後重新核對 API 與靜態檔完整性，證據 `.artifacts/histogram-layout-browser/integrity-check.json`。

API `histogram.py` 在原始受治理查詢之後、呈現列數上限之前分箱，回傳 lower／upper／right_inclusive／count 與完整母體統計。非末箱右界以相鄰浮點數轉為既有 between 閉區間；來源圖不自我篩選，其他圖使用相同伺服器界限。明示排除空值／無限值與 query.limit 的母體限制；非數值及不安全數值拒絕。舊 Plotly 建議箱數改為精確等寬箱數，與舊版逐箱邊界可能不同，實作計畫已記錄。

React 支援建立直方圖、選擇數值欄位、1–200 箱、保存重載、滑鼠及原生選單篩選；長區間文字僅在 hover 呈現。改回長條圖時，指標 alias 避免與原始數值維度同名。CSV／Excel 直接使用完整頻數表，PDF 繪製相同頻數，JSON 保留摘要及界限。新增模組歸既有 API 轉接層，前端／匯出／測試重用原位置，驗證產物歸 `.artifacts/`。

完整 `test_report_extensions.py`＋`test_exports.py` **151 通過，318.32 秒**，見 `.artifacts/histogram-regression.xml`／`.log`。新增 12 項核心與 3 項匯出案例，涵蓋邊界、常數、空值、非法設定、6000 列母體不受 5000 列上限截斷、跨圖精確區間，以及實際 ZIP／Excel／PDF；先前聚焦 15 項通過（44.85 秒）保留於 `.artifacts/histogram-ranges.xml`。

`.artifacts/histogram-layout-browser/` **1 通過，59.8 秒**（runner 約 1.9 分鐘），保留 build manifest、測試雜湊、獨立資料根、報告與截圖。零售 1246 筆由 25 箱改為 10 箱，頻數總和與表格保持 1246；保存重載、新增 20 箱圖、選單與真正滑鼠點第一箱篩選為 758 筆、清除還原、切回長條圖並顯示 revenue_metric 欄位均通過。截圖已檢視，沒有柱內長區間文字擠壓。

保留先前 `.artifacts/histogram-controls-browser/` 的 1 失敗／1 通過：初始查詢超過 45 秒，任務最後於 54.59 秒成功，不能將後續專項通過視為冷啟動效能問題已消失。中間 `.artifacts/histogram-ranges-browser/` 亦有 1 項通過，但尚未包含最後滑鼠與柱內文字檢查。沒有放寬測試時限。

本版尚未跑全部 API／完整報表 E2E，未更新離線 wheel／NativeApp 包。完整圖表格式、分析、效能／恢復、地圖 PDF 與真正 WebView 驗收仍未完成。

## 離線地圖與城市互動（2026-09-06，專項通過）

前次地圖建置 **`e368813183a3debfbe61b80c924877ff3c772e053e12273aa1ea56d9c11bf222`**。完整 TypeScript／Vite／API 型別及 manifest 建置通過（`.artifacts/geographic-zoom-build.log`）。新增 API geo.py 沿用固定核心 resolve_coords；依原始結果 row_index 附座標，不覆寫使用者 `_lat` 等欄位、不合併地名別名、不丟棄未知地點的資料列。React geographicMap.ts 使用同源 Plotly scattergeo，氣泡取第一指標絕對值、負數紅色、空值灰色及零值最小標記，tooltip 逸出文字；控制自動／台灣／世界範圍。VisualChart 共用既有點選事件、資料表鍵盤操作與資源失敗提示，App 查詢指紋納入 map 契約以便切圖重查。

`apps/web/public/maps/` 含未修改的 Plotly.js v4.0.0 world_50m.json、MIT LICENSE.txt 及來源 README。底圖 1,692,310 bytes，SHA-256 `20a160dbd13dd2bfa22f1858c0ae657860ea066d889563c51da383fd9696d759`；來源、建置輸出及 manifest 再次核對一致，見 `.artifacts/geographic-zoom-browser/asset-check.json`。資料來源與授權連結見 [底圖來源](../../apps/web/public/maps/README.md)。此目錄是待維護靜態素材，由 Vite 複製，不是測試產物；其他驗證輸出仍在 .artifacts。

前端 **15 通過，906.4151 ms**（`.artifacts/geographic-unit.log`），含 3 項地圖符號／空值／原值／逸出、範圍投影與錯誤座標／索引測試。核心地名對照 1 項初驗通過，最終完整 `test_report_extensions.py`＋`test_exports.py` **136 通過，85.40 秒**（`.artifacts/geographic-regression.xml`／`.log`）。沒有宣稱全部 API 測試已重跑。

瀏覽器 `.artifacts/geographic-zoom-browser/` **2 通過**：地圖 38.3 秒、既有單圖更新 25.4 秒（runner 約 1.2 分鐘）。零售四城市正確定位，底圖回應 200；路由攔截並記錄任何非本機 HTTP(S) 請求，最後外部請求清單為空。已驗鍵盤城市篩選、真實滑鼠點氣泡、清除後營收還原、世界／台灣設定、滾輪放大、保存重載恢復台灣 scale=45，以及既有局部更新保留其他圖表。截圖已檢視，台灣海岸及四氣泡可見。前次 `.artifacts/geographic-filter-browser/` 的單項 50.2 秒通過亦保留；更早兩次失敗分別是包含 options 的 label 定位，以及零售範例預設鑽取而測試期待篩選。已改用 combobox role 並透過 UI 停用鑽取，沒有改範例或放寬時限。

目前底圖提供離線概略地理背景，沒有街道瓦片；只解析核心既有地名，未知地點明示筆數並保留資料表。地圖 PDF 仍為表格，完整主題／分析／地理匯出與高基數性能尚未驗收；截圖另確認零售 histogram chart_mode 尚未專用呈現而空白，下一階段須補。完整報表 E2E、全部 API、新 wheel／NativeApp 與 P06 驗收仍未完成。

## 樞紐矩陣匯出及完整列分頁（2026-09-06，專項通過）

前次樞紐匯出建置 **`b3879ea1693943545714dac6c2d97120171101ad4190f32834b2f6a18e63f1ad`**。本次只改後端及測試，`build_app.py --skip-web` 沿用前次已驗證 React 資產，重新產生 API 型別與 manifest（`.artifacts/pivot-export-build.log`）；瀏覽器後重新核對 manifest 一致。`pivot.py` 增加矩陣分段產生器，`exports.py` 將同一矩陣供 CSV／XLSX／PDF 使用；每指標獨立、每段四個欄分類，保留完整列標籤、列總計、欄總計與總計。分段不重新計算或跨段相加；軸標籤加型別、欄位置編號避免重名，未回傳與核心空值分開。CSV 保留 typed analysis.json 及分段 manifest；XLSX 總計是數值而非公式，固定表頭／首欄；PDF 每段保持六欄內再分頁。

`.artifacts/pivot-export-regression.xml`／`.log`：**13 通過，36.86 秒**，含完整 `test_exports.py` 9 項，以及 4 項背景匯出、工作／發布 CSV 的快照篩選與唯讀報表回歸。實際產出 ZIP／XLSX／PDF 再讀回驗證：不同筆數總計不被儲存格相加、單軸／多指標、型別區分、空值／缺組合、使用者文字與公式安全、分類完整分段。前次 8 項初驗 15.26 秒保留於 `.artifacts/pivot-export.xml`。

`.artifacts/pivot-export-browser/`：**2 通過**（操作及匯出 29.8 秒、列分頁 26.6 秒，runner 約 1.1 分鐘）。實際瀏覽器下載的 `pivot-browser.xlsx` 已用 openpyxl 讀回，`workbook-check.json` 證明三段包含全部 12 個設備分類、每段六列各總計 100、總計 600、無公式。另一案例逐一走完 600 列的 12 頁，50 列／頁、600 個不重複分類；外部 Etch 篩選縮為 100 列／2 頁並重設第一頁，清除恢復 600／12。建置、測試雜湊、獨立資料根及報告均保留。

沒有建立新正式目錄；新增測試沿用 test_exports.py 與 workspace.spec.ts，驗證產物歸 .artifacts。尚未跑本版全部 API／完整報表 E2E，未封裝新 wheel／NativeApp；樞紐後處理組合、其他圖表與完整分析、效能／恢復及真實 NativeApp 驗收仍未完成。

## 樞紐矩陣與核心總計（2026-09-06，專項通過）

前次矩陣建置 **`42f4bb7669911cd049147ce27483c35acf7d95b12d5295b82f4698ab6d4bca62`**，TypeScript／Vite／API 型別與 manifest 建置通過（`.artifacts/pivot-refresh-build.log`）。核心 5 項通過、6.50 秒（`.artifacts/pivot-grains.xml`）：不等筆數的平均、跨群重疊去重、加權比率、視覺層篩選、一維／二維、query.limit 不影響總計、重發資料後舊快照維持相同數值、各聚合粒度 HAVING 與總計截斷標記。前端 `npm run test:web` 12 項通過、614.6824 ms，含新增 6 項樞紐稀疏矩陣、型別身分、空值／缺值、歧義拒絕與 5000 個列／欄分類；沒有在前端加總。

`.artifacts/pivot-regression-browser/` 保存相符建置、測試雜湊、獨立資料根與截圖：**3 項瀏覽器通過**，樞紐 27.4 秒、小倍數操作 30.3 秒、小倍數分頁 15.6 秒（runner 合計約 1.4 分鐘）。樞紐驗證一維切二維、600 總計、6 列／12 欄分類、欄分頁仍為 600、鍵盤列篩選、滑鼠欄篩選、清除與保存重載。首次 `.artifacts/pivot-matrix-browser/` 失敗發現查詢指紋未包含 pivot 契約，切圖後持續使用沒有總計的原結果；已加入 pivot 布林旗標觸發重查。獨立修復驗證 `.artifacts/pivot-refresh-browser/` 1 項通過、38.4 秒，截圖已檢視。測試選取圖表改用明確編輯按鈕，避免點中原圖資料點觸發意外篩選；沒有放寬時限。

後端在既有 core.run_query 中呼叫新 pivot.py，總計共用已載入來源及 executor。前端新增同目錄 pivotMatrix.ts／PivotTable.tsx，各自負責稀疏索引與可及性矩陣操作；測試沿用既有 tests/web 與 E2E 位置。完整報表擴充回歸 126 項通過、71.91 秒，證據為 `.artifacts/pivot-extensions.xml`／`.log`；建置 manifest 重新核對一致。此範圍為完整 test_report_extensions.py，未宣稱整體 API 全套通過。此階段當時未驗樞紐列分頁與矩陣匯出，已於上節 b3879ea1 補齊；JSON 保留 pivot 契約，後處理组合暫時明確拒絕。完整報表 E2E、地圖及全部分析遷移、效能／恢復、真實 NativeApp 與新交付包仍未驗收。

## 小倍數圖專用呈現（2026-09-06，專項通過）

前次小倍數圖建置為 **`1f1affcf15ddf61693b5932cc46c4e651ce61e6e9c0e6c165f83696da65eec98`**。完整 TypeScript／Vite／API 型別與靜態 manifest 建置通過（`.artifacts/small-multiples-layout-build.log`）；驗證後再次核對 manifest 與來源一致。小倍數圖兩項瀏覽器專項 **2 通過，37.3 秒**（操作 19.2 秒、分頁 10.8 秒），`.artifacts/small-multiples-layout-browser/` 保存相符建置、測試雜湊、獨立資料根、報告與已檢視截圖。尚未更新 wheel／NativeApp 包，P00–P06 整體及完整瀏覽器流程仍未完成。

`apps/web/src/components/smallMultiples.ts` 將核心已聚合列排列成第一維度分面、第二維度趨勢或一維長條，不重新加總；最多兩個維度，重複組合或缺少欄位時明示拒絕。`VisualChart.tsx` 共用原 Plotly 更新／清理，提供每頁最多 12 分面、每列 1–6 面板、獨立或全資料共用 Y 範圍、原始型別的分面選取及完整數據表。`App.tsx` 的建圖與格式控制已接上，第七種圖表不再落入一般折線分支。600 個 move_id 分面實測 50 頁，切換分頁可見 12 個分類；Etch 篩選後 100 分面、9 頁並回到第一頁，清除後恢復 600／50。另一案例核對六個 100、鍵盤及真正滑鼠點擊後 KPI 600→100→600、二維曲線每個點與核心表格一致且合計 600，以及保存回應 200 後重載保留圖種、兩欄、共用刻度及標題／高度設定。

新增 `tests/web/small-multiples.test.mjs` 由現有 Node 24.13 內建 test runner 執行，入口 `npm run test:web`，不另加測試套件。6 項單元測試涵蓋 14 分面的型別身分、空值、原始值不變、跨頁共用刻度、數值排序、歧義／缺欄位／非數值／超量維度拒絕、別名與文字 markup；證據 `.artifacts/small-multiples-unit-confirmed.log`，最終版面來源重驗 6 通過、359.9672 ms，見 `.artifacts/small-multiples-layout-unit.log`。首次型別命令誤用根 node_modules 的路徑，改成實際 workspace 路徑後通過；正式建置亦包含型別檢查。

前次 f67fe642 建置的完整瀏覽器為 **1 通過／2 失敗**（`.artifacts/small-multiples-browser/`）：既有局部更新 20.2 秒通過；新案例因 getByLabel 無法定位含選項文字的選單而失敗，快照確認 combobox 存在；完整報表流程走到當時第 645 行，參數 0.25 更新後等待表格回第一頁時達 180 秒總時限。後續兩次單項失敗分別是受控 checkbox 尚未等到報表保存回應，以及 SVG 路徑上方的 Plotly drag layer 攔截直接點擊；trace 證明共用刻度命令回 200。測試改用角色定位、點擊後等待已接受狀態與真正滑鼠座標，沒有 force click、刪除數值斷言或放寬時限。f67 的兩項專項先以 37.1 秒通過（`.artifacts/small-multiples-render-browser/`）；截圖檢視發現按鈕繼承全域 nav 直列及首排標題裁切，修正 scoped CSS 與頂端邊界後產生目前建置，最新專項再次通過。新增檔案歸屬元件純呈現及前端單元測試，產物全部沿用忽略的 `.artifacts/`。

前次後端 d6ba5d95 的完整 API 回歸 **314 通過／1 失敗，1072.33 秒**（`.artifacts/bookmark-proof-regression.xml`／`.log`）。唯一失敗是取消後立即刪除目錄的斷言：實際 cancelled、空結果、worker exit code 1，清理遇 PermissionError／winerror 32，日誌為 attempt=1、retry=True。修訂測試符合既定每五秒重試、最多三次的協定，立即驗程序退出與名額釋放；新增真實 Windows 目錄 handle 拒絕刪除，釋放後推進 scheduler 時鐘並由 tick 清乾淨，取消終態不變。相關 **4 通過，12.72 秒**（`.artifacts/cancel-cleanup-contract.xml`）。沒有修改產品後端或放寬 import／退出／查詢時限，也沒有宣稱已重跑新定義的全部 316 項。獨立失敗資料根由 `.artifacts/bookmark-proof-regression-root.txt` 保留。

繪圖介面參考 [Plotly 子圖](https://plotly.com/javascript/subplots/) 與 [Y 軸 matches／range](https://plotly.com/javascript/reference/layout/yaxis/)；純 TypeScript 模組的測試載入參考 [Node TypeScript](https://nodejs.org/dist/latest/docs/api/typescript.html)。這些文件支援介面選擇，產品行為仍以上述本機測試及畫面為證據。

## 書籤驗證成功指紋（2026-09-06，驗證中）

`build_app.py --skip-web` 通過，建置 **`d6ba5d95ce98f429c319e1534eb66a0ad73d00aee7843e9986dea60e013f9153`**。瀏覽器 **1 通過／1 失敗**：單圖／全域刷新 47.8 秒通過；完整流程越過前次第 326 行書籤保存，最後在第 483 行參數改為 0.5、等待 KPI 300 時達 180 秒總時限，當時斷言仍讀到 540。`test.trace` 記錄 fill→blur→失敗只有約 1.3 秒，資料庫最後成功的相關任務仍為 discount=0.1、adjusted_moves=540，沒有接受 discount=0.5 的查詢紀錄，不能據此認定公式把 0.5 算成 540，也不能認定整體互動已完成。

`.artifacts/bookmark-proof-browser/` 保存建置 manifest、測試雜湊、獨立資料根、完整報告及 trace；53 個任務為 45 成功（41 query、2 assistant、2 export）、8 取消、0 失敗。`http-timings.json` 中八筆書籤 GET 全為 200，耗時 44.775–1779.48 ms，後三筆為 284.86、310.962、44.775 ms；這只是本輪樣本，不是 p95，也不能將跨輪差異全部歸因於快取。`command-summary.json` 保存安全摘錄的命令類型與延遲，`last-jobs.json`／`parameter-jobs.json` 保存末段任務與數值核對。注意 `1-trace.trace`／network 的記錄在約第 378 行附近已結束，末段參數操作須以 `test.trace`、失敗日誌及資料庫交叉核對，不能用較早截圖判定最後參數畫面。完整 API 回歸 314 通過／1 項取消後清理斷言失敗（1072.33 秒），日誌及 XML 為 `.artifacts/bookmark-proof-regression.log`／`.xml`，獨立 basetemp 指標 `.artifacts/bookmark-proof-regression-root.txt`；失敗詳情及後續驗證見本頁開頭，未宣稱完整綠燈。最新 wheel／NativeApp 包尚未產生。

新增專項 **10 通過、111 未選取，62.60 秒**，證據 `.artifacts/bookmark-proof-focused.xml`／`.log`，獨立資料根記錄於 `.artifacts/bookmark-proof-focused-root.txt`。既有書籤、發布、鑽取與資料驗證的整合回歸 **66 通過、208 未選取，297.55 秒**（`.artifacts/bookmark-proof-integration.xml`／`.log`），XML 核對無失敗、錯誤或跳過。瀏覽器結果見下段；完整 API gate 尚未完成。

書籤解析確實會執行核心查詢，因此不能改成只驗 metadata。來源已讓保存／更新與工作／發布書籤解析共用既有最多 256 筆的成功驗證快取；每次仍讀取並校驗當次快照的完整資料 bytes，欄位簽章、選取圖表、鑽取及持久條件引用仍逐次驗證。指紋包含作用範圍、所有來源版本與契約、已解析的有效報表和探索條件；僅排除不影響已解析條件的書籤清單與間接引用 ID。發布 scope 另含 publication ID，沿用原核心版本及 revision 檢查。未命中時才解析已校驗的同一份 Parquet bytes 並執行真實查詢，失敗不留成功指紋，不快取資料表或查詢結果。worker 不使用此快取。

修改均歸屬既有 `core.py`、`bookmarks.py`、`app.py` 與 `test_report_extensions.py`；測試資料及日誌放於忽略的 `.artifacts/`，每次 basetemp 為新 UUID。本輪來源已建置為 d6ba5d95，下面 e917 是前次建置及瀏覽器證據。專項核對重複 GET／保存／更新不重解析、來源變更的 600→1200、Etch 條件 100、metadata／scope／參數失效，以及損壞來源、過期簽章、刪除圖表與不合法查詢拒絕；結果見本節開頭。

## 閒置計時與 CLI 啟動拒絕修正（2026-09-06，驗證中）

前次來源建置為 **`e917d03dd06b4575cb4927d92d2a910055620b2b4388270b80aa90f7392205a5`**，`build_app.py --skip-web` 通過；沒有重新產生 wheel 或 NativeApp 包。合法 CLI 單獨重跑通過（`.artifacts/lazy-startup-cli.xml`，13.26 秒），保留前一輪逾時，不將重跑視為全套回歸。未插樁的分段探測（`.artifacts/cli-stage-profile.json`）在綁定、建置檢查、API／uvicorn 載入、產生配對碼及 create_app 共 2596.37 ms，pandas 未載入；此探測未啟動服務，不是完整 readiness 時間。

此 build 的瀏覽器回歸 **1 通過／1 失敗**：單圖更新案例 50.4 秒通過，完整流程於 `workspace.spec.ts:326` 儲存「全部製程」書籤時達 180 秒總時限。`.artifacts/lazy-startup-browser/` 保存 build manifest、三份測試來源雜湊、獨立資料根、報告／截圖／trace 及 `job-timings.json`、`http-timings.json`、`action-summary.json`。40 個任務為 35 成功、5 取消、0 失敗；新工作區初始查詢從接受到終態 8653.15 ms，已不再停在先前的初始 KPI 等待。該程序的 23103.72 ms imports 發生在預載階段，之後待命 15811.78 ms 才接受任務，不能把 worker_total 當成 HTTP 查詢延遲。

完整流程仍有累計延遲；trace 中書籤 GET 約 3495.89–3835.96 ms、部分命令 POST 約 2182.64–3070.26 ms。下一步檢查書籤解析與命令是否需要完整解析所有資料，先以相同快照／型別／引用語意驗證再調整。這些都是單次失敗流程的診斷數值，不是 p95 或 P06 效能完成證據。最新來源尚未跑完完整 API 回歸，整體產品及交付維持未完成。

核心介面核對更正：已安裝的 `ai4bi.blocks.datastore` 提供全域 `clear()`，docstring 註記「used by tests」；因此先前「沒有清理介面」的描述不夠準確。已核對 datastore.py 的 SHA-256 為 b15ad0735c8a4a50be5067325f7b93fa6289f8ca61759af8abb4dda13de75d2c，與固定 ai4bi 0.1.0 wheel 相同。它沒有逐項驅逐介面，目前 worker 也沒有使用該全域清理函式。若後續採用，須驗證只在獨占任務完成並釋放引用後執行，且結果／匯出／下一任務不依賴已清除的 handle；本輪未據此更改 8 任務、記憶體或工作區隔離限制。當前效能調查先針對 trace 已指出的書籤與命令載入。

後續專項 `.artifacts/idle-and-preflight-focused.xml` 已結束：**76 通過、3 失敗、90 未選取（752.96 秒）**。新增兩項活動時間案例、三項 CLI 提前拒絕、原來源 bytes 重驗與複製頁面查詢均通過；仍失敗的是雙待命回收案例在成功後沒有 spare、取消案例的初始 worker 載入超過 30 秒，以及合法 CLI 啟動超過 20 秒。CLI 這次失敗在合法啟動，與前次錯誤建置拒絕逾時不同。雙待命案例已增加 teardown 前的程序退出碼、名額、閒置年齡與退避狀態斷言，原因仍待確認。

`.artifacts/app-import-profile.json`／`.log` 記錄一次帶 `-X importtime` 的 API 載入，exit 0、總計 **27.531 秒**；較大的單模組 self time 包含 pandas groupby 2963.56 ms、shared_docs 1441.26 ms、FastAPI OpenAPI models 1084.30 ms、pyarrow.lib 864.70 ms。這是帶量測工具的一次模組載入，不等同未插樁啟動或 p95。來源已讓 API 的分析操作在需要時 import core／pandas，匯入清單不再為了載入 helper 模組而載入解析器；既有純 Python 驗證快取移到 `validation_cache.py`，核心保留相同類別匯出。migration、恢復、鎖定、靜態完整性及 build／instance 檢查保持原契約；首次分析仍有載入成本，不能以較快的 metadata 啟動宣稱端到端效能完成。

新增獨立子程序測試，用 import hook 禁止載入 pandas／core，實際完成 readiness、未配對拒絕、配對、工作區／資料／匯入清單及報表讀取。第一次執行因未建立 basetemp 父目錄，記錄為 1 通過／9 setup errors（`.artifacts/lazy-startup-focused.xml`），不是 9 項產品失敗。補建父目錄並修正 README 命令後，`.artifacts/lazy-startup-confirmed.xml` 記錄 **9 通過／1 失敗（73.07 秒）**；上述獨立啟動、真實頁面複製查詢、完整匯入驗證、快取、雙待命回收與取消均通過，但合法 CLI 的 20 秒啟動仍失敗。失敗服務日誌為空，保存的 manifest 與目前後端檔案逐一雜湊比對一致。獨立資料目錄由 `.artifacts/lazy-startup-confirmed-root.txt` 記錄，原案例可繼續檢查；後續分段量測、CLI 重跑、建置與瀏覽器結果見本節開頭；目前尚未交付。

新增預載備援後的完整 API 回歸已結束：`.artifacts/fresh-spare-regression.xml`／同名 `.log` 記錄 **296 通過、3 失敗（1735.08 秒）**。失敗為同工作區來源 bytes 重驗案例的待命程序身分斷言、CLI 拒絕錯誤建置的 20 秒等待，以及複製頁面查詢的 45 秒等待。手動 fixture 去除背景排程後，第一項仍再次出現，因此不能將原始問題歸因於該 fixture。這次結果未達完整驗收。

接著在既有 worker 生命週期測試新增執行中／剛完成兩種情境，讓活動時間的年齡增加 61 秒，但保留真實子程序與交接標記；`.artifacts/idle-age-before.xml` 記錄修正前 **2 失敗（67.23 秒）**。確認先前從派發開始累計的閒置時鐘會把長任務執行時間計入，回收仍需要的預載備援或剛完成工作的可重用程序。來源已改為 `last_activity`：執行中持續記錄活動，收取終態時重新起算，真正無工作滿 60 秒才回收。任務 120 秒、全域兩程序、8 次重用及 768 MiB 退役門檻不變。這項重現證明計時缺口存在，但尚未以原始失敗當下的活動時間證明兩者必然同因。

CLI 原本先 import 完整 API／pandas 再檢查預期 build。來源已把相同驗證抽到既有 `static_assets.py`，在保留 loopback socket 後、載入分析 runtime 前拒絕無效 instance／build；`create_app` 仍使用相同檢查並再次校驗完整性。新增三種拒絕測試以 import hook 禁止載入 API／pandas／uvicorn，並核對不建立資料根、不輸出配對資訊。worker、CLI、ready 與原失敗案例的專項及後續建置／瀏覽器結果見本節開頭；完整回歸與交付仍待完成。

保存失敗資料時，原共用暫存目錄 `pytest-4310` 已不存在；目前可追溯的是 XML／日誌，未取得該輪資料副本或完成重播。README 的 pytest 命令已改用每次全新的 `.artifacts/test-runs/<UUID>/` 作 basetemp，後續需保留重播資料的驗證也使用獨立目錄，避免共用暫存的清理機制移除證據。不得重用 basetemp 指向已有資料的目錄。

## 同工作區有限 worker 重用（2026-09-06，驗證中）

此階段前版建置為 `981f18ded8cee5760caf2679f02d1833c77579a0e79d9bc1f13b5cf76445bddc`，後續來源修正尚未重建或交付。

由前版 trace 的 worker 模組載入成本出發，沿用 jobs／worker 及 `test_worker_lifetime.py`，沒有修改舊核心或另建程序管理框架。父子雙方綁定工作區；同一程序最多 8 個任務，完成後峰值 working set／commit 達 768 MiB、記憶體資訊未知、錯誤／取消即退役。此門檻不限制單任務峰值。結果檔關閉後才原子送出 job-specific ready，主程序依最新取消狀態決定發布，下一個 assignment 前 worker 不再寫前一任務。全域最多兩程序、一個待命；60 秒閒置與父程序管線退出維持。

最初生命週期 16 項通過（22.94 秒，`.artifacts/reusable-worker-lifetime.xml`）；補上同程序資料版本 600→1200 數值核對、損壞來源拒絕並退役、跨工作區換程序、768 MiB 與資訊未知退役判斷後，生命週期與任務接受共 30 項通過（31.79 秒，`.artifacts/reusable-worker-focused.xml`）。再加入完成標記必須匹配 job ID，以及結果寫好但未發布時取消仍優先的實際程序測試。

初次完整回歸 **295 通過／1 失敗，342.69 秒**（`.artifacts/reusable-worker-regression.xml`）：工作報表 CSV 匯出為 WORKER_FAILED，但保留的 CSV ZIP 與 result.json 完整，後者可通過 `finished_payload(..., 0)`；缺乏當時退出碼，不能確定根因。同一份測試資料重播三次均到達完成標記、沒有 stderr（`.artifacts/reusable-worker-csv-replay/evidence.json`），這只是未重現。隨後補上結果拒絕的退出碼／標記／檔案存在診斷；每次讀取任務資料明確關閉 SQLite 連線；已寫完結果後若記憶體查詢或重用交接 I/O 失敗，正常退出並走單次結果路徑。模擬 ready.tmp 替換失敗、完成標記／取消競態及 CSV 下載共 **5 項通過，99.95 秒**（`.artifacts/reusable-worker-handoff-focused.xml`）。不宣稱此保護已證明修復原始退出原因。

再次完整回歸 **296 通過／1 失敗，1,157.27 秒**（`.artifacts/reusable-worker-regression-confirmed.xml`）：`test_governed_query_in_real_worker` 在 45 秒內未看到任務終態，與前次 CSV 的錯誤不同。其測試資料在 `.artifacts/reusable-worker-query-replay/` 重播完成，程序就緒 11,203 ms、派發後 5,234 ms；五圖全部 ready／未截斷，KPI moves=600。完成任務的 imports 9,343.41 ms、資料載入 3,065.58 ms、query_total 4,955.18 ms。重播通過不取代失敗的整批回歸。`.artifacts/reusable-worker-host-resources.json` 是之後建置期間的單次主機快照（約 3.23 GB 可用實體記憶體），不能用來證明先前逾時原因。

同 build 初次瀏覽器 **2 失敗**，證據 `.artifacts/reusable-worker-browser-failure/`：聚焦案例初始 KPI 等待失敗；Playwright 更換測試 worker 後，第二案例的記憶體 cookie 遺失，API 回傳 SESSION_REQUIRED／PAIRING_REJECTED，屬測試連帶失敗。已新增 `tests/e2e/session.setup.ts`，由總程序做一次實際 UI 配對，用程序環境傳給測試 worker，無 storageState 檔；各新 context 仍以 cookie 連接實際 API。依據 [Playwright global setup](https://playwright.dev/docs/next/test-global-setup-teardown)。這份新檔歸屬既有 E2E 啟動支援，沒有更改產品配對規則。

配對修正後的回歸仍 **2 失敗**（`.artifacts/reusable-worker-session-failure/`）：聚焦案例在初始 KPI 等待失敗；第二案例已能進入分析流程，於 `workspace.spec.ts:424` 達 180 秒總上限，沒有再因配對拒絕立即失敗。另確認初次 trace 的兩個查詢分別屬於舊工作區及本次新建工作區，固定 `.artifacts/e2e-data` 已有 80 個工作區。現已改為每次 run 建立 `.artifacts/e2e-runs/<UUID>/data`，保留舊資料，測試內的保存／reload／發布流程仍使用同一資料根。

隔離後回歸 **1 通過／1 失敗**（`.artifacts/reusable-worker-isolated-browser-failure/`）：聚焦互動案例 38.8 秒通過；完整流程於新工作區初始 KPI（`workspace.spec.ts:117`）達個別 45 秒等待門檻，並非 180 秒總上限。該 run 的資料根是 `.artifacts/e2e-runs/d7c2d51b-f797-467b-8259-889779ac3d6f/data`。事後唯讀檢查 SQLite／staging 顯示最後任務已 succeeded：首次 imports **44,264.63 ms**、execution **3,015.37 ms**、worker_total **47,280.01 ms**；因此這次可定位為切換工作區後冷啟動進入關鍵路徑。前一工作區已在同一 worker 完成序號 1–5，序號 2–5 imports=0；實際明細在 `.artifacts/reusable-worker-isolated-job-summary.json`。不能據此倒推此前兩次 API 失敗的原因。

後續來源已實作未綁定工作區的預载備援：執行中與待命合計仍最多兩個，可同時保留一個已綁定的可重用程序與一個未讀取工作區資料的程序。切換工作區時退役原綁定程序並提升備援；兩個待命程序均受 60 秒閒置回收，備援異常退出另有 5 秒重試退避。備援可能仍在載入，這項設計不保證所有切換都已完成預熱。

`.artifacts/fresh-spare-focused-confirmed.xml` 記錄 **35 通過、0 失敗（183.860 秒）**，涵蓋真正子程序的跨工作區備援身分、同工作區重用、來源 bytes 重新核對、雙待命回收、備援故障退避、取消與交接。先前一次專項有一項待命身分斷言失敗；手動 tick 測試 fixture 現在以 no-op 背景執行緒建立協調器，避免測試自行清除 stop_event 後可能恢復背景排程。這不是對原失敗原因的確證，也沒有改動正式背景迴圈或放寬門檻。完整 API 回歸、建置及瀏覽器重測尚待完成；上述 981f18 為前版建置，新增備援尚未交付。

## 延後解析已校驗來源（2026-09-06）

來源 build `0d5722d541d8d338b2050cb23ce7835cce1538fbcd99f1be8a66680549f1edb9`。沿用 `core.py`，將來源讀取／SHA 檢查與 Parquet 解析拆開。報表命令每次先校驗所有實際 bytes；以 metadata 檢查結構、引用、條件與成功指紋，只有查詢未命中才建立實際 executor。需要解析時使用同次已校驗 bytes，不重新開啟路徑。計算指標仍每次實際驗證，新增／更新書籤仍使用實際資料，空報表仍解析以保持來源檢查；worker cached 模式不啟用成功指紋重用。快取只有最多 256 筆成功摘要，不保存原始 bytes、DataFrame 或結果。

23 項聚焦測試通過（19.90 秒，`.artifacts/lazy-validation-focused.xml`）。初次完整回歸 287 通過／1 失敗（233.37 秒，`.artifacts/lazy-validation-regression.xml`）；失敗是新增檔案替換測試只提供 process_move 來源，卻使用依賴其他來源的完整 Fab 報表。將該測試限定為它實際建立的 KPI 後，loader／stored 兩個替換案例通過（2.31 秒，`.artifacts/lazy-validation-byte-race.xml`）；沒有修改應用程式邏輯來迎合測試。修正後完整 API 回歸 **288 項通過，463.20 秒**，程序 exit 0；證據 `.artifacts/lazy-validation-regression-confirmed.xml`。此較長耗時如實保留，不當成效能改善證據。

`.artifacts/lazy-validation-million/evidence.json` **complete=true、程序 exit 0**。既有六圖 fixture：1,000,000 列、22 欄、唯一 move_id、600 列模式擴展，Parquet 5,731,682 bytes。首次 96,077.87 ms（解析 69,283.73 ms、讀檔驗 SHA 30.87 ms，六圖結果逐群核對 pandas oracle）；後續只改標題 43.15／36.67 ms（讀檔驗 SHA 34.55／31.99 ms，解析與查詢各零次）。保留三次、180 秒上限，未放寬。峰值工作集 3,317,518,336 bytes，峰值 commit 3,710,148,608 bytes；首次轉列及記憶體仍不符合流暢大資料互動目標。此為後端驗證樣本，不是 HTTP 或瀏覽器 p95；不能推廣成所有命令都只需數十毫秒。

同版建置通過，來源 E2E **1 通過／1 失敗**：聚焦互動 19.6 秒通過，完整流程於發布版本套用 Etch cross-filter 後等待 KPI 100（`workspace.spec.ts:706`）達 180 秒總上限。`.artifacts/lazy-validation-browser-failure/` 保存 trace、報告、evidence 及去識別的耗時摘要。87 次 commands 中位數 273.51 ms；51 個完成任務的 worker imports 中位數 1,838.81 ms、實際執行 479.20 ms。時間可能重疊，不以加總當作獨占流程耗時。仍須定位 worker 啟動及完整流程成本；未生成新 wheel／NativeApp 包，不勾選完整產品或交付 gate。

## 已校驗來源的報表驗證（2026-09-06）

來源 build `c1cd36f8b0849896292147e36149b7dde22f999ecdc2cb8b056cc86591936cf9`。既有 `core.py` 加入封閉的 `validate_stored_report`，由 Store metadata 載入並校驗實際 Parquet bytes，再以來源 SHA、完整契約／條件形成成功指紋，避免第二次逐列摘要。不能由瀏覽器提供成功證明；直接呼叫 mutable inline validator 仍摘要完整 records。沒有保存 DataFrame 或結果，也沒有跳過每次來源檢查。書籤初次聚焦測試發現空資料契約不足以完成核心條件查詢，已改為在同一份已校驗資料範圍內處理新增／更新書籤。

21 項聚焦測試通過（16.85 秒，`.artifacts/stored-validation-focused.xml`），涵蓋標題重用、資料／契約／參數／作用範圍失效、損壞及偽造來源版本拒絕，以及書籤與請求內單次載入。完整 API **285 項通過，236.00 秒**（`.artifacts/stored-validation-regression.xml`），`build_app.py --skip-web` 通過，前端未修改。

百萬列／六圖使用既有 `benchmark_queries.fixture` 建立唯一 move_id，每次实际查詢結果逐群與 pandas oracle 核對。首次完整驗證 96,857.75 ms（載入 69,516.58 ms，六圖實際執行）；只改標題再次驗證 69,247.84 ms（載入 68,024.50 ms，零次圖表查詢）。規劃三次、180 秒上限，但第三次未完成，程序 exit 1，未輸出最終 evidence；精確終止原因尚未證明。保留 `.artifacts/stored-validation-million/measure.py` 與 `partial-evidence.json`，**整批未通過**。此數字包含載入和驗證，不能直接與以前只算指紋的 45.27 秒比較，也不是 HTTP／瀏覽器 p95；仍需解決 API 列物件載入成本。

同版來源真實瀏覽器 **1 通過／1 失敗**：單圖更新、全頁失效與 Plotly 縮放保留案例 19.3 秒通過；完整流程於副本頁清除 cross-filter 後等待 KPI 恢復 600（`workspace.spec.ts:691`）達 180 秒總上限。未放寬測試門檻。trace、報告及範圍摘要保存於 `.artifacts/stored-validation-browser-failure/`。本輪未重新生成／安裝 App wheel 或 NativeApp 包，最近已驗證交付仍為 a2341d；完整產品、效能及交付 gate 保持未完成。

日期：2026-09-05。狀態：**部分完成**。本文件維護 P00 實際證據與限制；架構、契約及分期仍以 [實作計畫](../implementation-plan.md) 為權威。

## 已確認產品方向

- 半導體工程師為首版主要驗收對象；零售與 CV 用於檢查通用性。
- 首次交付先完成匯入、建圖、聯動、NL 修改、Undo、保存與重開。
- 本機瀏覽器與 NativeApp 優先；遠端多人另一期。
- 保留核心分析語義，重新設計 React 工作流與視覺。

## 來源與保護

固定提交：`d9fa0a08147bbb2d0eee10b11ea4c34f5ac9d051`。

來源的 `docs/goal.md` 已修改，`requirements.lock.txt` 與一個暫存 Python 檔未追蹤。本次使用 `git archive` 只提取固定提交；不把 dirty／untracked 混入基準。記錄差異及未追蹤檔案 hash，執行後來源狀態與內容 hash 未改變。

來源 snapshot、log、JUnit、wheel 與環境記錄位於 `.artifacts/p00-baseline/`，不作維護來源或正式發布物。沒有修改、提交或推送舊 repository。

| 身分 | SHA-256 |
|---|---|
| tracked diff | `064dea2852eef177cb7df1da2890b6c22f2cab48d658cd9644cf3635b4043344` |
| 固定提交 tar | `2c9a25d75864be15711b9dfa2d1eb5133ecb5c34bdeda7e1b77be182b8f7bd68` |
| 本次生成的 wheel | `f235a498a1af7d2272b35f0a4da70931684ab54a9029da085c4973f0f7692558` |

wheel hash 是本次產物識別，不宣稱跨機／跨時間 bit-for-bit 可重現；build backend 尚未釘選為正式 lock。

## 執行結果

| 驗證 | 結果與限制 |
|---|---|
| 舊版非 E2E pytest | **1,250 passed，181.24 秒**；mock 模式，停用第三方 pytest 自動載入 |
| 固定 snapshot 建 wheel | 成功；pip 隔離 build，未安裝／更新來源 venv 的 build 套件 |
| wheel 安裝至另一 venv | 成功；使用 system-site-packages，共用本機第三方依賴，不是乾淨離線安裝 |
| headless 執行 | 成功；assert 實際 `ai4bi.__file__` 位於新 wheel venv |
| 原始碼讀取限制 | Python audit hook 拒絕 open 原 repository 與 snapshot；此為該 probe 範圍，不宣稱 OS 沙箱 |
| Streamlit 依賴測試 | import hook 拒絕 Streamlit；Executor 與 NL2ProposalService 仍可 import，查詢成功 |
| 資料 lineage | 回傳 blocks_used 為 `yield_fact` |
| 原來源保留 | 執行前後 tracked diff、status 與已記錄 untracked hash 一致 |

測試執行 Python 為 3.11.9 AMD64；這是 interpreter 架構，不等於已驗證 Windows ARM64 native wheel。當時第三方版本：pytest 9.0.3、DuckDB 1.5.3、Pandas 3.0.3、Pydantic 2.13.4、PyArrow 24.0.0、Streamlit 1.58.0、Plotly 6.7.0、SciPy 1.17.1。它們是本機觀察，不是最終相容性承諾。

原始整合流程的 `headless-wheel.log` 初次因本次 probe 錯用 `dtype` 而失敗；已依來源契約修為 `data_type`。修正後獨立重跑通過，保存在 `headless-wheel-corrected.log`。保留原 `evidence.json` 的失敗紀錄，不將其改成整輪一次通過。

### 可人工核算的良率 oracle

| tool | good | tested |
|---|---:|---:|
| A | 90 | 100 |
| A | 1 | 10 |
| B | 4 | 5 |

核心執行 `SUM(good) / NULLIF(SUM(tested), 0)`，A = `91/110 = 0.8272727272727273`；B = `4/5 = 0.8`，以絕對差 `< 1e-12` 驗證。A 不可算成 `(90%+10%)/2 = 50%`。此測試使用內嵌小資料，不依賴 repo 的 fixture 或外部服務。

## 實際發現與影響

1. **核心可先用既有 wheel 重用**：本次小型查詢不需要 Streamlit runtime，也能 import NL service。但沒有測試所有分析操作的 headless 閉包。
2. **wheel 不含 `data/semiconductor_demo` 與 `tests/fixtures`**：原 Executor 的預設 registry 仍指向套件外 `tests/fixtures/blocks`。Web adapter 必須明確提供資料／registry；正式 App 打包自己的必要 demo assets，不能依賴 checkout。
3. **依賴 metadata 仍強制要求 Streamlit**：執行邏輯不載入，不代表 pip 安裝會省掉 Streamlit。暫可沿用整包；後續需驗 optional UI 依賴拆分，不能未記錄地改原核心。
4. **來源未找到已追蹤 LICENSE／NOTICE**：本機開發驗證可繼續，但對外 wheel 再散布前須確定授權與第三方 notice。不能把沒有 license 文件解讀為可任意再散布。
5. **P00 尚未通過全部 gate**：前端圖表／拖拉／表格 spike、正式 lock、ARM64 ABI、完整 feature inventory 與效能 benchmark 未完成。

## 初始功能對照

以下是從現有程式與測試清單建立的功能群組，全部 Web 狀態均為 planned。它不是完整逐功能驗收矩陣，後續需繼續細分使用者可見操作。

| 功能群組 | 既有代表測試 | 遷移順序 |
|---|---|---|
| 半導體指標、join、良率 | test_semiconductor_data、test_fab_join_builder、test_grain_mismatch | P01–P03 |
| 上傳、JSON、編碼、資料檢視 | test_upload_encoding、test_json_ingest、test_data_inspector | P02–P03 |
| 報表、新圖、欄位配置 | test_report_draft、test_dynamic_canvas、test_field_well_apply | P02–P04 |
| 篩選、cross-filter、Undo 狀態 | test_global_filters、test_cross_filter_broadcast、test_state_manager | P02–P04 |
| NL 回答、修改與上下文 | test_nl2proposal、test_nl2_answer、test_followup_scope | P02／P05 |
| 圖表、格式、地圖、pivot | test_chart_format、test_pie_scatter、test_geo_map、test_pivot | P04 |
| 多頁、書籤、drill、What-if | test_multipage、test_bookmarks、test_drillthrough、test_what_if | P04 |
| 日期比較與計算指標 | test_calendar_yoy、test_time_intelligence、test_derived_metrics | P04 |
| 產能、SPC、commonality | test_capacity_dynamics、test_spc_commonality、test_crossfact | P05 |
| 零售與 CV 通用性 | test_rfm、test_cohort、test_basket、test_cv_dataset | P05 |
| 匯出、發布、權限 | test_pdf_export、test_excel_export、test_publication_gate、test_rls | P04／P06 |

## 重跑方式

使用已具原專案測試依賴的 Python 3.11；以下命令在 `AI4BI_Web` 根目錄執行。output 必須是 `.artifacts` 內尚不存在的新目錄，避免覆寫證據。

```powershell
& C:\code\claude\AI4BI\.venv\Scripts\python.exe scripts/validate_core_baseline.py --source C:\code\claude\AI4BI --output .artifacts/p00-repeat
```

工具會固定當時 HEAD、保存 diff hash、測試 snapshot、建 wheel 並驗證 headless 查詢。pip build 可能需要網路取得隔離 build 依賴；此工具不宣稱離線，且不修改來源程式。

只重跑已安裝 wheel 的 probe：

```powershell
& .artifacts/p00-baseline/wheel-env/Scripts/python.exe -I scripts/probe_core_wheel.py --expected-package-root .artifacts/p00-baseline/wheel-env --forbid-source C:\code\claude\AI4BI --forbid-source .artifacts/p00-baseline/source
```

來源路徑只由工具 CLI 接收，用於基準／讀取限制，不是 Web 產品 runtime 依賴。

## 套件與授權證據盤點（2026-09-06）

新增 `scripts/collect_dependency_notices.py`，讀取已驗證離線包的 wheel、雜湊鎖與安裝證據，以及目前專案 npm lock 的 production entries。來源版本及 wheel hash 必須與安裝證據完全一致；npm package.json 的名稱／版本須符合 lock。收集工具不查網路、不安裝套件、不修改來源，不替缺少授權的套件指定授權。

```powershell
& .venv/Scripts/python.exe scripts/collect_dependency_notices.py `
  --release .artifacts/release/offline-windows-x64 `
  --output .artifacts/dependency-notices-audit
```

output 必須尚未存在，重跑時另指定 `.artifacts/` 下的新目錄。最新已完成證據位於 `.artifacts/dependency-notices-audit/`，包含 `inventory.json`、閱讀索引及逐字節保存的 notice 副本。

| 項目 | 實際證據 |
|---|---|
| Python | 既有離線包的 66 個 wheel，逐一核對版本及 SHA-256 |
| npm 執行期 | React、React DOM、Scheduler、Plotly.js，共 4 個；記錄 lock integrity、package.json 與已安裝檔案 SHA-256 |
| 授權／通知檔 | 107 份，共 615,296 bytes，副本全部與 inventory 雜湊一致 |
| inventory SHA-256 | `ef94ef461ddbd938b0cae7e889e0e1e4a4be8206d49c36831fe6342a13fae561` |
| npm lock SHA-256 | `578f3ed3d7cef5414b9f672f579887a6b6477458704007bbd31fb33f502f6c74` |
| wheel 包對應 build | `6669889c192d1e348c9cec7214b4f1dfb3be0b5351c6e2701f0cda255cd9d775`，是先前版本，非最新 Web 功能建置 |
| 工具測試 | `tests/tooling/test_dependency_notices.py`：7 項通過，0.21 秒；JUnit `.artifacts/dependency-notices-tests.xml` |

仍缺的證據：`ai4bi` 與 `ai4bi-web-api` wheel 沒有授權宣告／授權文字；Streamlit metadata 宣告 `Apache-2.0`，但實際 wheel 未找到隨附 LICENSE／NOTICE。此處只記錄套件提供的資料，不作法律判定或再散布批准。npm integrity 是 lock 中的 tarball 身分，尚未下載 registry tarball 核對；本輪檔案雜湊辨識的是本機已安裝內容。套件內嵌供應商程式、字型及外部 runtime 的完整 attribution 仍需獨立確認，不能僅靠檔名掃描宣稱閉包完成。這批清單尚未自動加入最新 wheel 或 NativeApp 接入包。

初次真實掃描因 email metadata 的非 ASCII Header 不能序列化而失敗，`.artifacts/dependency-notices/` 是未完成診斷；改用 email policy 並在寫檔前完成序列化。之後補上 Plotly 的 `*.js.LICENSE.txt`，從 105 份增為 107 份。`dependency-notices-python-npm/` 與 `dependency-notices-bundled/` 為中途產物，最新證據以上述 audit 目錄為準。測試涵蓋 Unicode、逐字節副本、重跑穩定性、缺少宣告檔、wheel／lock／npm 版本不符、路徑穿越、缺 wheel，以及拒絕覆寫既有證據。

## 六圖大資料後端基準（2026-09-06）

工具為 `scripts/benchmark_queries.py`，數值驗證測試在 `tests/tooling/test_query_benchmark.py`；產物集中於忽略的 `.artifacts/performance-query-baseline/`。不新增 API 功能、不修改核心或使用者資料。命令：

```powershell
& .venv/Scripts/python.exe scripts/benchmark_queries.py --output .artifacts/performance-query-run --source-mode inline
```

資料由半導體移動資料的固定 600 列模式擴充到精確 100,000／1,000,000 列，22 欄，`move_id` 重新生成唯一值。六圖為移動總數、平均等待、按製程／機台／產品／優先序分組平均等待；完整輸出共 27 列。每次結果都逐組與 pandas 的獨立 SUM／MEAN 參考核對，不將漏圖、截斷、錯誤或少群組視為成功。

量測直接呼叫 App 的 `run_query`，包括版本校驗、Parquet 載入、六圖核心執行與回傳資料建立，另記錄 JSON bytes。首次指同一新 interpreter 的第一次查詢，後續仍完整重跑，只有 OS／import 快取可能暖起來；沒有宣稱結果快取命中，也不是使用者操作到可互動的端到端時間。不包含 HTTP、任務佇列、瀏覽器繪圖、高基數／寬表或快速連續操作壓測，三次樣本不發布 p95。

硬體：Snapdragon X X126100／Oryon，8 核／8 邏輯處理器，16,758,542,336 bytes 實體 RAM；Python 3.11.9 AMD64 在 ARM64 Windows 模擬執行。`host.json` 與 `build.json` 記錄現場配置與已驗證 App build `aeb886da3f0d3561881a3981ae3480db48ebb8ecc792ca798c3bd54860d48531`。後續工具會直接把 build 身分寫入 `evidence.json`。

| 規模 | 六圖各次計算 | 資料載入 | 峰值工作集 | 結果 |
|---|---|---|---|---|
| 100,000 列 | 7,214.34／7,097.93／7,282.74 ms | 5,574.92／5,508.35／5,653.65 ms | 507,006,976 bytes（483.52 MiB） | 三次數值核對通過；不代表效能目標通過 |
| 1,000,000 列 | 69,447.26／68,941.64 ms | 55,567.41／55,707.09 ms | 3,276,795,904 bytes（3,125 MiB） | 兩次數值通過，第三次達整組 180 秒診斷上限而中止 |

每次回傳約 9.1 KB，沒有把百萬列結果送前端；但後端仍將整張 Parquet 轉為 `InlineDataSource.records`，資料載入與第一張圖的 Arrow 轉換占大部分時間。暖快取六圖端到端 p95 ≤ 800 ms 的 gate 尚未證明，必須優化資料路徑後重測。既有核心有 `CachedDataSource`／DataFrame 介面，但套用前須驗證型別、資料版本、權限、跨工作區隔離與生命週期，不能改用無上限常駐快取。

Windows venv `python.exe` 是啟動器。首次 600 列 smoke 的約 11 MiB 只量到啟動器，不作記憶體證據；正式基準透過專屬輸出目錄中的 worker PID，開啟實際 interpreter handle，取 Windows peak working set／commit counters。診斷保護為每組 180 秒或 4 GiB private bytes，僅中止所屬計算程序，保留已完成 samples 與失敗狀態；這些是工具保護上限，不是產品效能驗收門檻。

本次已啟動的舊工具主程序在子案例失敗後仍 exit 0；以 evidence 的百萬列 `exit_code=1`／`stopped` 判定不通過。工具已補成任一子案例失敗便整體非零，另有測試驗證證據保留。完整交付工具測試 **45 項通過（0.69 秒）**；初次此測試的 subprocess mock 意外影響平台資訊取得，已隔離平台資訊後全套通過。API／React 執行程式未變，本輪未重跑其回歸。

## Worker DataFrame 優化與重測（2026-09-06）

來源變更集中於既有 `core.py`／`worker.py`。短生命週期 worker 讀取任務後，啟用核心公開的 CachedDataSource／DataFrame store；查詢、AI、匯出與發布驗證共用此程序內資料介面，程序結束後回收。長生命週期 API 不啟用此模式，仍用原本 inline 路徑，避免把核心無 eviction 的全域 store 當成服務快取。資料載入仍核對 snapshot 的 SHA-256，且 Parquet 解析改讀已通過核對的同一份 bytes；不在校驗後重新讀取可能被替換的檔案。

新增測試放在既有 `test_report_extensions.py`：保留 nullable Int64／Float64、大於 JS 安全整數、前置零字串與 datetime；inline／DataFrame 五圖跨資料區塊結果一致；已載入過的資料若檔案變更仍拒絕；模擬校驗後替換檔案，解析仍使用已核對 bytes。三項聚焦測試通過（1.70 秒），完整 API 回歸 **245 項通過（137.40 秒）**，完整工具測試 **45 項通過（0.70 秒）**。OpenAPI 型別產生與靜態 manifest 重建完成；React 原始碼未修改，沿用已建置資產。

同樣的 22 欄、六圖、27 列輸出基準重跑，產物 `.artifacts/performance-worker-dataframes/`，build `1f886a7124e689d60a309ec63309a1cdc4c99ca0fcdfeff14f13083c9b84d710`：

| 規模 | 三次六圖計算 | 三次資料載入 | 峰值工作集 |
|---|---|---|---|
| 100,000 列 | 545.45／454.29／460.66 ms | 333.89／273.62／272.10 ms | 302,907,392 bytes（288.88 MiB） |
| 1,000,000 列 | 3,341.88／3,407.84／3,367.29 ms | 3,095.68／3,159.75／3,101.88 ms | 1,233,063,936 bytes（1,175.94 MiB） |

兩種規模各三次全部完成並通過獨立數值核對，回傳仍約 9.1 KB。相較前段 inline 基準，主要改善来自避免全表 row-dict 建立、遞迴清理、Pydantic records 驗證及再次 row-to-Arrow 轉換。沒有新增查詢結果快取、放寬 timeout 或省略完整計算。

工具預設 `--source-mode worker-dataframes` 模擬 worker；可用 `--source-mode inline` 重現另一條資料介面。重跑使用新的 output，保留失敗與先前基準。三次不是 p95；backend 小於 800 ms 不代表「操作到可互動」達標。程序啟動、HTTP、排隊、JSON 解析、繪圖、高基數、寬表、真正篩選變更與快速連續互動仍待端到端量測。API 報表編輯／書籤等同步驗證路徑仍有 inline 成本，尚未宣稱全產品效能完成。

上述 `1f886...` 是加入碰撞保護前的中間版本。補查發現固定核心的 dataframe hash 不包含完整 dtype 身分：實際整數 `1/0` 與布林 `True/False` 可得相同 key。載入端現在比較 store 內實際 DataFrame 與來源 frame，型別或內容不一致便回退原 inline 路徑，不修改核心 store 或錯用資料；新增真實碰撞測試，不以 mocked hash 代替。

中間 source build `c980923de8335a1a7bfb4cad471decc1d5e667c166dfa10f5fb6aabeb9c23411`：四項聚焦測試通過（1.94 秒），**246 項完整 API 回歸通過（144.73 秒）**。`.artifacts/performance-verified-dataframes/` 的 100k 三次六圖為 **538.92／463.46／451.36 ms**，資料載入 328.60／277.74／269.57 ms，峰值工作集 296,198,144 bytes；1M 三次六圖為 **3,468.38／3,505.42／3,465.81 ms**，載入 3,228.24／3,246.34／3,226.64 ms，峰值工作集 1,258,438,656 bytes。全部數值核對成功，沒有觸及診斷上限。

該中間版本 wheel 已建置並通過來源／manifest／封裝完整集合核對，1,372,754 bytes，SHA-256 `971322189bc46b842c8f45369348c48c10d7b40383848a117fe4ca6552ab6f20`。先前離線與 NativeApp 包 build 為 `aeb886...`，不包含本次優化；新版獨立安裝與交付結果仍須另外記錄，不能沿用舊證據。

該中間 build 的真實瀏覽器回歸 **尚未通過**：連續兩次達 180 秒總上限。第一次停在跨頁書籤（test 第 504 行），trace 中相關 API 約 240 ms；完成任務的 worker import 曾達約 8.9 秒。第二次停在較早的重做等待（第 96 行），觀察到 import 約 5–15 秒。沒有放寬總流程或 45 秒查詢門檻、刪除測試步驟或把重跑視為通過。失敗 trace／截圖分別保存在 `.artifacts/worker-dataframe-e2e-timeout/` 與 `.artifacts/worker-dataframe-e2e-repeat-timeout/`。中間版本曾完成流程，不當成最終版本驗收。

檢查未发现明顯持續 Plotly 重繪迴圈；這是程式檢查，尚非瀏覽器 profiler 證明。已核對先前基準 interpreter 不在執行、已知 Playwright worker 沒有遺留直接子程序；未終止無關程序。下一步須處理整條流程的載入與排程延遲，不能只以直接 `run_query` 的改善解除這個失敗 gate。

## 後續剩餘工作

### 有上限的查詢驗證成功紀錄（2026-09-06）

build `9a42697a5506ce113e9a3bf7e64b5211a258da5b33fc3172d5ab4edca0a57ba0` 在 App lifespan 建立最多 256 個 SHA-256 成功指紋的 LRU；只有驗證圖表 query 的完全相同輸入會命中，不保存資料或計算結果。來源每個請求仍讀取及驗 SHA，報表結構／引用／計算指標每次仍檢查；實際查詢、AI、匯出與發布不使用這份紀錄代替執行。指紋含工作區／報表身分、完整 inline records 與契約、參數、全域與適用持久條件、實際鑽取 query。外部及 cached core source 不適用，App 重啟清空。

271 項完整 API 回歸通過（496.14 秒），證據 `.artifacts/validation-proof-regression.xml`；新增十個案例涵蓋只改標題的命中、資料／公式／參數／篩選／查詢／作用範圍變更重驗、非法佈局／指標拒絕，以及失敗不保存與 LRU 回收。較早聚焦測試 9 項通過（6.96 秒），之後增加非法佈局案例並納入完整回歸。

`.artifacts/validation-proof-benchmark/evidence.json` 使用真實 Parquet 讀取與 SHA 校驗，交替比較同一五圖 Fab 報表的標題編輯。第一次 uncached 892.57 ms、首次建立成功紀錄 767.23 ms；後續三次 uncached 為 530.76／538.84／388.86 ms，有成功紀錄為 180.60／184.78／193.84 ms。均確認返回的新標題，沒有省略資料校驗。這是少量後端樣本，不是 HTTP、瀏覽器或 p95；指紋仍序列化完整 records，大資料的暫存記憶體與成本尚未量測，不能宣稱百萬列編輯 gate 通過。

同 build 完整 E2E 仍達 180 秒上限，停在 discount 0.5 後等待 KPI 300（第 414 行），當時畫面仍為 540。不是單次 45 秒查詢完整等待後的獨立失敗；不能從這個截點推論驗證成功紀錄改寫了查詢數值，實際工作程序沒有使用該紀錄。`.artifacts/validation-proof-browser-timeout/` 保存報告、trace、48 個任務的 timings 與 HTTP 摘要。該次 36 個 commands 中位數 450.66 ms、合計 15,880.95 ms、最大 2,472.83 ms；因只執行部分流程、操作組合和執行條件不同，不能直接與先前 71 次合計值相比宣稱全流程加速。測試資料根此時累積 59 個工作區；尚未據此認定超時原因。沒有放寬門檻或標記 E2E 通過。

### 指紋記憶體與百萬列成本（2026-09-06）

後續 build `c7d0d7530c158ce27a5eb3d1eaf9a041050846e46fc7695817f1f44644ae340a` 改為逐列摘要，不再建立整表暫存 JSON。273 項 API 回歸通過（477.94 秒），證據 `.artifacts/streamed-validation-regression.xml`。10k × 22 的 tracemalloc 額外配置峰值由 25,199,787 降至 46,727 bytes；輸入先配置，追蹤器開啟，不能当成程序 RSS。

`.artifacts/validation-fingerprint-million/evidence.json` 已完成：1,000,000 個不同 move_id、22 欄，指紋耗時 113,362.4 ms，輸入建構 1,924.22 ms。整個程序峰值工作集從指紋前 1,061,908,480 至指紋後 1,062,068,224 bytes；峰值 commit 1,314,664,448 bytes。峰值包含直譯器與完整輸入，不以兩個峰值的差宣稱精確額外配置。這只驗證指紋建構，不包含完整報表驗證、查詢、HTTP 或瀏覽器；百萬列互動 gate 未通過。

後續 `e6072c6dad18157f8010229c6ab08ed72841c98579005d4ecf6cf6ab8f4e76d6` 在 clean 加入精確基本型別快速路徑，保留非有限值、大整數及特殊型別語意。13 項聚焦、274 項完整 API 回歸通過，後者 300.53 秒（`.artifacts/primitive-clean-regression.xml`）。相同百萬列資料的指紋為 45,274.5 ms，SHA-256 與前版一致，程序峰值工作集 1,063,223,296 bytes（`.artifacts/primitive-clean-million/evidence.json`）。這是不同時間各一次的單程序樣本，不是 p95，也仍不符合即時編輯要求；完整瀏覽器另外驗證。

同版完整瀏覽器流程仍在 180 秒總上限失敗，第 547 行等待選取頁名稱由「新分析頁」變為「驗證頁」。這是整體截止，不把當時文字直接認定為持久化錯誤。測試期間沒有修改來源，未放寬門檻；`.artifacts/primitive-clean-browser-timeout/` 保存報告、trace 及對應 build 的 evidence.json。擷取的 71 次 commands HTTP 中位數 354.15 ms、合計 32,521.93 ms、最大 2,761.03 ms；這些時間可能重疊，且每輪完成的流程不同，不用合計值替代全流程效能驗收。最新離線及 NativeApp 包仍為 022786，不能套用至本版。

### 單圖查詢與未變動圖表保留（2026-09-06）

分析 e6072c trace 的 41 個成功任務，worker 匯入中位數 2,054.02 ms，實際執行中位數 540.06 ms，結果在 `.artifacts/primitive-clean-browser-timeout/job-timings.json`。預載時間可與其他工作重疊；本次未據此改成長生命週期、無界資料快取的 worker。

App 改為按目前頁面的共用輸入及各圖 query／extra／drill 分別判斷變更，只對失效圖表派發查詢；資料／全域條件／參數改變仍使全頁失效。沒有跨頁歷史，取消與錯誤結果不會成為成功紀錄。中間 build `3759eacebff73f8cfe0e332e26d3987b743f110ad04c80362a55267e74fff6d9` 完整流程通過單圖鑽取請求斷言，但於多指標表格等待時達 180 秒總上限，第 528 行；`.artifacts/visual-query-browser-timeout/` 保留當時報告與 trace。

聚焦瀏覽器案例確認單圖請求和數值後，發現未變動圖表的 DOM 仍被移除：報表命令反序列化會重建 visual 物件，觸發 Plotly effect 清理。VisualChart 現以設定內容指紋判斷變更，資料結果仍是依賴；事件 callback 仍透過 ref 更新。失敗證據 `.artifacts/visual-query-plot-rebuild/`。

最新 build `8cd810186f496b7dee46243d2e865c71bf72c766ae704ef322ffa0978dbdf51d` TypeScript／Vite 建置通過，聚焦瀏覽器案例 1 項通過（測試 18.5 秒，總計 25.6 秒），證據 `.artifacts/visual-query-focused/`。確認只查 kpi_moves、新增平均指標後的 600 與 2.642166 數值、其他 Plotly DOM 仍連接，以及新增全域參數後五圖重新查詢並返回相同數值。首次聚焦案例把 KPI 說明文字也算入精確文字比較，已修正測試選取，數值與門檻不變。完整兩項瀏覽器回歸已結束，結果見下段；此局部通過不等於全產品完成。

本版完整兩案例回歸已結束：1 項通過、1 項失敗。聚焦案例 19.3 秒通過；完整工作區案例通過多指標與表格分頁數值後，在點擊新增頁面時達 180 秒總上限（目前第 585 行），不是獨立查詢逾時或已證實的錯誤數值。證據 `.artifacts/retained-plot-browser-timeout/`。新測試與原流程共用一個 API 程序；首次一起執行時第二個案例重用一次性配對碼而被拒絕，已改為只在測試程序記憶體中沿用首個案例透過 UI 建立的 session cookie，產品認證規則未改。完整效能及交付 gate 仍未完成。

### 圖表重新計算後保留縮放（2026-09-06）

build `60076247ad9ce8a01a374235f17f4f279dcbb9ba056550d1fe2b89cc8e393ab7` 將 Plotly purge 從每次 effect 更新改為圖表 DOM 移除／替換時執行，避免同一組座標的資料更新清空縮放。更新仍使用 Plotly.react；uirevision 含全部維度與指標設定、component_id 及圖表種類。元件切換成表格、錯誤或空資料時會釋放舊圖，舊 ResizeObserver 與事件完成回呼依生命週期清理。

TypeScript／Vite 建置通過。聚焦案例測試 19.8 秒、總計 25.4 秒通過（`.artifacts/plot-zoom-focused/`）：實際滑鼠拖曳改變 xaxis.range；全域參數變動引發五圖後端計算，確認 Plotly 接到新的 data 物件後 range 仍等於使用者縮放範圍；轉為表格後舊圖 DOM 不再連接且 Plotly data 被清除，切回長條圖恢復。首次案例在類型選單定位失敗，已改用 combobox 的無障礙名稱，沒有改數值或放寬門檻。後續補上更換指標重設 range 的斷言，完整回歸結果見下段。

最新兩案例回歸完成：聚焦案例 21.4 秒通過，亦包含更換指標後恢復原始 xaxis.range；完整工作區案例在刪除待修復情境時達 180 秒總上限（第 593 行）。證據 `.artifacts/plot-zoom-browser-timeout/`，不將此截點當成獨立情境刪除錯誤或效能 gate 已通過。期間另記錄一個 worker handoff 清理警告；測試退出後檢查該明確目錄，仍有 32 bytes 的 assignment 檔案，未擅自刪除。原因尚待補充診斷，不能直接歸因為本次圖表修改。Python 程式未變，274 項 API 回歸證據仍適用；最新前端未納入離線／NativeApp 包。

### Worker 交接檔清理重試（2026-09-06）

原始警告後殘留 assignment 的事實已保存；當時未記錄 OSError 類型，原因仍無法回溯確定。Jobs 改為記錄錯誤碼，並對可能暫時性的檔案權限／分享鎖失敗採取最多三次、五秒間隔的延後重試。記錄上限 64 目錄，不遞迴清理、不掃描其他工作者或舊目錄；每次檢查 Store 下實際落點、固定名稱與無重導。未知檔案或非暫時性錯誤只記錄及保留。正常關閉再嘗試已追蹤目錄，未清完明確記錄。

15 項生命週期測試通過（21.06 秒；`.artifacts/handoff-cleanup-focused.xml`），包含 CreateFileW 開啟真正不可刪除的測試交接檔，第一次清理失敗，CloseHandle 後下一次排程成功。之後增加 65 個失敗目錄驗證上限 64、關閉清理與第 65 個目錄保留，相關 5 項通過（4.21 秒）。完整 API 回歸 278 項通過（265.25 秒；`.artifacts/handoff-cleanup-regression.xml`），重建為 `a2341d2d380fbb75af66023e5453e4fbf490900329b8b97d3d496abe7cecfead`，未另打包或重跑瀏覽器；此變更不代表完整效能／恢復 gate 已通過。

### 同版離線與 NativeApp 交付更新（2026-09-06）

a2341d 的 wheel SHA-256 為 `481ba0514fe3df9ddf65dd5e4269248f9df2398b9dba8df0919939c9978dc567`，1,376,039 bytes。`.artifacts/release/offline-interaction-cleanup/evidence.json` complete=true：建立環境 20.16 秒、離線安裝 182.61 秒、pip check 2.22 秒、HTTP／worker／匯出／保存／重啟 probe 32.44 秒，全部 exit 0；新環境位於 checkout 外，執行時拒絕兩個來源專案。第三方依賴從舊閉包驗證雜湊後重用，核心與 App 使用本次指定 wheel。notice 收集 70 套件，三項既有證據問題仍待補齊。

同版 NativeApp zip `2bdd4b257b018c8c90955ea4ff648c959c50df8042b3c6c27d5d47925da25870` 有 181 檔，Kit 格式／內容及來源集合核對通過。`.artifacts/nativeapp/host-interaction-cleanup/evidence.json` complete=true、provisioned_from_archive=true：新 Store 環境建立 298.55 秒、啟動 23.52 秒，其餘 import／prepare／resolve／stop／running 均 exit 0。核對新環境綁定、ready build、Store 資料庫與停止後空清單；不是附掛先前 venv。仍依賴既有基礎 CPython 與發布 Kit，不代表 runtime-free 新機安裝、WebView、身分 bootstrap 或更新回復完成。此後的安裝版瀏覽器結果見下段。

安裝版瀏覽器回歸已結束，1 項通過／1 項失敗：聚焦案例 23.8 秒通過；完整案例第 479 行新增 discount 後 5 秒內未見輸入欄位，並非 180 秒總逾時。最後一個 commands 請求 4,867.732 ms、HTTP 200，回應含 discount；原門檻保留，延遲仍待改善。`.artifacts/installed-interaction-browser-failure/evidence.json` 綁定實際使用的安裝 Python、build 與 trace，與開發環境的總逾時分開記錄。本輪另實際記錄交接檔 winerror 32／attempt 1／retry true，結束後該目錄不存在；原先未帶錯誤碼的舊警告仍不能溯及斷定原因。

### 單次編輯、renderer 指標與工作區查詢（2026-09-06）

對前版 `.artifacts/prewarm-chart-browser-timeout/` 的 HTTP trace 作摘要，71 次 commands 合計 44,247.14 ms、中位數 609.27 ms、最大 1,943.71 ms；552 次 jobs GET 中位數約 9 ms。摘要在該目錄 `http-summary.json`，不含 headers／body；請求時間可能重疊，不當成整條流程的獨占時間。`app.py` 篩選及保存書籤原本在同一 transform 內兩次載入資料，現改為請求內 lazy 共用，保留完整校驗與核心查詢。兩項專項通過（5.23 秒），261 項完整 API 回歸通過（361.57 秒），證據 `.artifacts/command-source-reuse.xml`、`.artifacts/command-source-regression.xml`。

首輪 renderer 診斷 `.artifacts/command-browser-diagnostics/` 在保存鑽取層級後的 5 秒導覽斷言失敗，最後保存 HTTP 為 200、1,219.72 ms。`renderer-metrics.json` 的最終 renderer ScriptDuration 2.249 秒、LayoutDuration 0.239 秒、RecalcStyleDuration 0.401 秒、TaskDuration 8.549 秒、JS heap 18,817,088 bytes、DOM 4,428 個；其 NavigationStart 至取樣約 49.73 秒，中間曾重新整理，不能用這些值推論完整瀏覽器程序樹或全流程累計。這份樣本未支持以大量前端排版作為已證實主因。

鑽取導覽原本依賴第一個查詢回傳，現依已保存層級先顯示等待狀態、停用點選，查詢完成後才使用含欄位型別的結果。受控延遲測試首次在解除 route 時失敗，保存在 `.artifacts/drill-pending-route-race/`；已改為等待 handler 完成後再移除。下一次則在建立工作區後發現不相符 wid／report_id 的查詢 404，保存在 `.artifacts/workspace-query-race/`；App 現加入報表工作區一致性檢查與報表身分依賴。

最終來源 build `6ae8c9fc551aa42c7347399e852a699228ed6ccd16ee69dbf8d8c18e7d367fdb` 的型別檢查與正式前端建置通過。最新 E2E 越過初始工作區查詢檢查、圖表節點保留，以及攔住查詢時的鑽取待命／禁止點選檢查，並執行後續鑽取／AI 分析；完整流程仍在重新載入報表頁面時達 180 秒上限（第 563 行）。報告、trace、截圖與 renderer 起訖指標保存在 `.artifacts/command-drill-workspace-browser-timeout/`，沒有放寬任何時間門檻。後端回歸通過不代表本 E2E gate 已解除；離線／NativeApp 仍維持先前 022786 包。

### 待命程序與圖表重建診斷（2026-09-06）

既有 jobs／worker 新增最多一個一次性待命程序，合計仍最多兩個 worker，60 秒閒置回收；預先載入核心但不讀資料。12 項生命週期測試通過（10.55 秒），259 項完整 API 回歸通過（145 秒），證據為 `.artifacts/prewarm-lifetime.xml`、`.artifacts/prewarm-regression.xml`。API 來源其後未變更。worker timing 分開記錄 imports、standby_wait 與 execution；worker_total 排除待命時間，不當成接受請求至可互動時間。

僅加入預載的 build `7faa60ce52b9fc875e377f975022253b6384c63d63fae730f505c1e915d52f73` 的完整 E2E 仍達 180 秒上限，停在第二次發布版本等待（當時第 609 行）。trace 保存 `.artifacts/prewarm-browser-timeout/`。發布相關查詢的等待約 10–16 秒；部分實際 worker import 達 15–20 秒，核心查詢也變慢。這說明預載不是已證實充分的解法，不能只因流程到達較晚步驟宣稱提速。

檢查另發現 `DrillChart` 在每次 render 都複製有效 query 物件，令 `VisualChart` 的 effect 因參照改變執行 purge／重建。新增瀏覽器檢查：記錄已繪圖的 SVG，鍵盤選取另一張卡片後確認該節點仍連接。修正前 5.8 秒明確失敗，證據 `.artifacts/chart-selection-rebuild/`。以 useMemo 保留未改變的 visual／query 物件後，該檢查通過，TypeScript 與正式 Vite 建置通過。

目前 build `d5bfa78653a36fd319f6d7b2a0ebb36b3b8b8f8dd69327ed367eba7e6caa9d80` 的完整 E2E 仍未通過：180 秒上限停在參數更新後等待表格回第一頁（新增檢查後第 495 行）。沒有放寬 timeout 或刪除流程。`.artifacts/prewarm-chart-browser-timeout/` 保存 trace／截圖與本次工作區 68 個任務的 `job-timings.json`；待命與取消的任務都有保留。下一步須量測瀏覽器繪圖／排版、資源消耗與實際任務等待，不能以 DOM 保留或 API 通過宣稱全流程效能達標。當前來源未重建離線／NativeApp 交付，先前包仍為 022786 版本。

### 先前相容性修正與交付基準

目前相容性補正版 build `02278626f9259cccb54929e1487ead56d64493e4f0671ca28d1f4f339144ec1a`：新增快速路徑適用性檢查，含無限值、Decimal、時區日期或其他需 legacy clean 的來源保留 inline 語意。11 項聚焦案例及 253 項完整 API 回歸通過，完整回歸 430.58 秒；45 項工具測試 0.82 秒通過。結果分別保存於 `.artifacts/worker-dataframe-focused.xml`、`.artifacts/worker-dataframe-regression.xml` 與 `.artifacts/worker-dataframe-tooling.xml`。

`.artifacts/performance-compatible-dataframes/` 為同 build 的最新基準：100k 六圖 703.01／652.07／574.62 ms，資料載入 432.59／393.36／353.69 ms，峰值工作集 287,297,536 bytes；1M 六圖 4,395.80／4,354.00／4,416.63 ms，資料載入 4,090.59／4,066.57／4,149.20 ms，峰值工作集 1,250,877,440 bytes、峰值 commit 1,662,451,712 bytes。各三次完成且數值核對通過。相容性檢查有成本，不能再把 c980 的較快數字當成本版本效能。

基準記錄的模組載入為 848.21／922.93 ms；另以新程序 `-X importtime` 載入 worker 所需 core／storage，exit 0、含程序啟動總計 982.06 ms，原始分解在 `.artifacts/worker-compatible-importtime.log`。這次單次 profile 未重現先前瀏覽器 trace 的 5–15 秒載入；不能據此宣稱端到端延遲已解除。仍須改善並驗證實際任務派發與瀏覽器完整流程。

新版交付補充：`.artifacts/release/offline-clean-build/third-party-notices/` 已自動收集對應新版 build `aeb886da3f0d3561881a3981ae3480db48ebb8ecc792ca798c3bd54860d48531` 的 70 套件、107 份 notice（615,296 bytes），副本、receipt 與 npm lock 的雜湊核對通過。此處保留原盤點的歷史數字；新版安裝與交付證據見 [App release](app-release.md#新版交付驗證追蹤2026-09-06)。三個套件缺少授權文字、內嵌供應商與 runtime／字型等未完成項目仍然存在；新版 NativeApp 接入包已納入此 inventory，並逐項核對封裝完整性；詳見 [NativeApp 驗證](../../integrations/nativeapp/README.md)。

完成 P00 剩餘 spike、完整功能盤點及版本 lock 後，再將符合全部條件的待辦勾選。最初的 P00 盤點未包含 React、Python API 或 NativeApp 接入實作；後續已完成的實作與驗證以本文件各版本紀錄、實作計畫第 16 節及 App／NativeApp 交付文件為準。真實 WebView 與 live LLM 等未通過項目不能由早期基準或目前 mock 測試代替。
## Worker 致命錯誤診斷與檔案鎖（2026-09-06）

來源建置 `052f8f040e1b111b34f05b4fcd7427a301ab574a85abe1bded68dd7a636b38ce` 已加入有限致命錯誤診斷及 assignment 刪檔重試；API 建置成功，證據 `.artifacts/worker-lock-build.log`。此版尚未重新離線封裝或 NativeApp 驗收。

- 診斷專項 `.artifacts/worker-diagnostic-focused.xml`：3 通過，涵蓋真實子程序 job-decode 失敗、診斷清理後仍可讀取、下一任務成功，以及輸出隱私／大小限制。
- 診斷版 `14beb89a12bcede8067b6ae6646f36819d5dc904a82de5353b0734f42f9a8460`：兩項 KPI 真實瀏覽器案例各重複三次，6 通過，3.5 分鐘。證據 `.artifacts/worker-diagnostic-browser/evidence.json` 與 `run.log`；這一版尚無刪檔重試，也未重現先前偶發退出。
- 真實 Windows CreateFileW handle 允許讀写、禁止刪除 assignment：修正前 `.artifacts/worker-lock-before.xml` 為 1 通過／1 失敗。持續鎖定可保存 assignment-remove／PermissionError／winerror 32 診斷；暫時鎖定於 ready 後 0.2 秒解除，worker 已退出而無 result.json。
- 修正只重試這個已重現的錯誤碼與刪檔動作，最多 1 秒；不將此注入案例宣稱為先前瀏覽器 exit 1 的根因。worker 生命週期及任務接受回歸 **43 通過，72.76 秒**，證據 `.artifacts/worker-lock-regression.xml`；包含短暫鎖定恢復、持續鎖定失敗診斷、程序上限、工作區綁定、取消與父程序退出。後續完整 API **448 通過，539.92 秒**，證據 `.artifacts/worker-lock-api.xml`；同版瀏覽器 2 通過／1 完整流程達 180 秒總時限。

診斷檔限 4 KiB，採固定欄位校驗並排除例外訊息、資料值及完整路徑；寫入失敗採 best effort。此機制不涵蓋 os._exit 或原生崩潰。所有輸出沿用已排除版本控制的 `.artifacts/`，測試資料使用獨立 UUID 目錄，沒有新增維護模組或變更資料夾責任。
