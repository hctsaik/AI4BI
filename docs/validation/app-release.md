# App wheel 與離線安裝驗證

發布版桌面保存／重啟已補驗，**14 步通過**：保存圖表修改、原生關窗、新 WebView 設定目錄重啟與重新配對後，原工作區標題和五圖查詢皆恢復；兩次各 20 個程序退出、Host／App 埠關閉。證據 `.artifacts/nativeapp/webview2-change-restart/evidence.json`，無強制清理，driver 副本及發布檔案雜湊一致。這是下段基礎測試的擴充；完整安裝與升級驗收仍待完成。

發布版平台補驗：同一 v6 接入包使用 NativeApp 0.1.8 發布 Host 建立新 Store 並通過啟停；發布 WebView2 EXE 的 6 步基礎流程通過，涵蓋配對、工作區／五圖查詢、原生關窗後 20 個程序與兩個服務埠回收。`.artifacts/nativeapp/webview2-change-smoke/evidence.json` passed=true、runtime_unchanged=true，無強制清理。發布平台 ZIP＋Kit Python 的組合及限制見 [NativeApp 接入](../../integrations/nativeapp/README.md)；完整 Setup／新機、發布版完整功能矩陣、原生另存、自動配對與升級回滾仍待完成，不把本測試當作完整發布驗收。

同一 b0b32e45／v6 wheel 已完成 NativeApp 新封裝、從包內依賴建立全新 Store 環境、Host 啟停，以及 Electron 來源殼 **32 步驟**驗證。桌面下載五份文件（工作四格式及發布 JSON）已讀回核對，四種分析在發布保留相同設定／資料列／版本，變化拆解五群完整，PDF **35 頁**。接入包與 Host／桌面證據見 integrations/nativeapp/README.md；正式 Runtime、新機、自動配對、原生存檔及升級回滾仍待完成，下方「新版 NativeApp 尚未更新」為先前中途狀態。

v6 安裝版瀏覽器驗證已完成（取代下段「驗證中」）：`.artifacts/installed-change-browser/evidence.json` 首輪 exit_code=1，**33 通過／1 失敗，7.0 分鐘**；圖表格式案例建立工作區後過早操作，尚未取得新工作區的指標編輯器。改用既有等待新工作區查詢 helper，`.artifacts/installed-change-format-retry/evidence.json` exit_code=0，**1 通過，14.5 秒（runner 18.5 秒）**。兩輪皆 fresh_report／drivers_unchanged=true，使用同一專案外環境與 b0b32e45 build，其餘 33 案測試不變，未放寬 timeout。注意此腳本的 complete 表示證據收集完成，通過須另核對 exit_code，不能把首輪 complete=true 當作全綠。

`.artifacts/release/offline-change-delivery/browser-coverage.json` 綁定首輪、補驗、driver 與文件雜湊，明確記錄 34 案分次完成。安裝版實際 JSON／CSV／Excel 五群、設定及資料版本讀回一致，PDF 11 頁包含所有群組、分析 ID 與 v6；發布畫面已檢視。wheel 大小 **2,091,972 bytes**，下方 SHA 不變；安裝探測副本雜湊與維護 scripts/probe_app_wheel.py 一致。新版 NativeApp 尚未更新，不以安裝瀏覽器驗證代替桌面殼驗收。

變化拆解 v6 新版離線安裝已通過（安裝版瀏覽器仍在驗證）：build `b0b32e45c68bff975b72517b6782ce5686ffd6cfbc0fe4b094b6ff5a7cfe8983`，wheel `.artifacts/release/change-delivery-wheels/ai4bi_web_api-0.1.0-py3-none-any.whl`，SHA-256 `09c2a932137d6081e176d2b757c1503e29841464ed4fc4a55989220be14d7c14`。`.artifacts/release/offline-change-delivery/evidence.json` complete=true：建立環境 9.22 秒、離線安裝 88.56 秒、pip check 1.14 秒、HTTP probe 24.44 秒，均 exit 0。專案外環境 `C:/Users/hctsa/AppData/Local/Temp/ai4bi-release-n2g0nx1z`，禁止讀取 AI4BI_Web 與舊 AI4BI 原始碼目錄；保存變化拆解、五群加權結果、CSV 全列、固定發布與重啟後刪除草稿再重播均通過。75 套件授權清單仍有原先兩項證據待補。新版 NativeApp 尚未更新，下方 v5 仍是最近已完成桌面驗證的歷史版本。

最新離線與安裝瀏覽器驗證為 `9b5ef22386ad3942202c88f62c5a688b755a9f7a1d9b80d8ffae3d258f297e76`（SPC／共同性／跨表交付，`web-query-v5`）。wheel `.artifacts/release/crossfact-delivery-wheels/ai4bi_web_api-0.1.0-py3-none-any.whl` 為 **2,081,001 bytes**，SHA-256 `a7fc6c6f371d7816850d1bd88de42b132f9c386bf4872c91ca93147990e69a48`。`.artifacts/release/offline-crossfact-delivery/evidence.json` complete=true：環境建立 9.41 秒、離線安裝 89.56 秒、pip check 1.12 秒、HTTP probe 23.83 秒，全部 exit 0；外部環境 `C:/Users/hctsa/AppData/Local/Temp/ai4bi-release-a0zo9t4x`。probe 實測保存加權跨表設定、200 列來源／20 組配對、CSV 全列數值及三種分析發布；服務重啟後刪除跨表草稿設定，固定發布仍重播相同設定、數值與資料版本。使用的 probe 副本與維護來源雜湊一致，證據 `probe-source.json`。

`.artifacts/installed-crossfact-browser/evidence.json` complete=true、exit_code=0、fresh_report=true、drivers_unchanged=true，**11 個案例通過，3.0 分鐘**；完整報表約 1.4 分鐘。實際跨表 JSON／CSV／Excel／PDF 下載已讀回核對 20 組完整結果、統計、設定、篩選與版本，PDF **16 頁**，證據在該目錄的 `playwright-results/workspace-Crossfact-public-bd624--and-downloads-every-format/download-verification.json`，發布畫面已檢視。同一版 NativeApp 新環境啟停及 Electron 來源殼 28 步驟亦通過，詳見接入文件。現有 75 套件的 notice 收集仍有 2 項來源授權證據待補；正式 Runtime、新機與完整升級回滾等 P06 項目未完成。下方 43275411 與更早版本皆為歷史證據。

最近已驗證的離線安裝為 `43275411…`（共同性發布／匯出、`web-query-v4`）。新版 wheel 位於 `.artifacts/release/commonality-delivery-wheels/ai4bi_web_api-0.1.0-py3-none-any.whl`，2,069,317 bytes，SHA-256 `d5211bb217638706a65fc87ed8af5476bda9f6fbb287c8eb4e2bff7ba4cea185`。`.artifacts/release/offline-commonality-delivery/evidence.json` complete=true：建立環境 10.00 秒、離線安裝 92.64 秒、pip check 1.39 秒、HTTP probe 22.23 秒，全部 exit 0；專案外環境 `C:/Users/hctsa/AppData/Local/Temp/ai4bi-release-89ro06np`。共同性保存、100 群體／11 目標、CSV、發布及服務重啟後固定設定與數值重播通過。

`.artifacts/installed-commonality-browser/evidence.json` complete=true、exit_code=0、fresh_report=true、drivers_unchanged=true，核心／App 從上述安裝環境載入，build 相符。8 個案例全部通過（runner 約 2.8 分鐘，完整報表約 1.7 分鐘），包含共同性掃描、保存重開、發布／四格式下載，以及 SPC 三流程、舊執行契約拒絕與完整報表。未放寬原 180／45 秒限制。新版 NativeApp 包、Host 從封存檔建立環境及啟停、Electron 來源殼 24 項流程與實際下載內容核對均通過，詳見接入文件；完整 P06 仍未完成。下方 b5 及更早版本均為歷史證據，不能代替本版驗收。

前版來源與安裝包為 `b5dd13a3…`（SPC 發布／匯出、web-query-v3）。App wheel 位於 `.artifacts/release/spc-delivery-wheels/ai4bi_web_api-0.1.0-py3-none-any.whl`，2,060,065 bytes，SHA-256 `f6d9855a0100d460f82efa7057b92d2acd9ecc5cd4a971c1a293cccff56ec5c4`。`.artifacts/release/offline-spc-delivery/evidence.json` complete=true，工具 exit 0：建立環境 9.50 秒、離線安裝 91.16 秒、pip check 1.14 秒、HTTP probe 14.88 秒；checkout 外環境 `C:/Users/hctsa/AppData/Local/Temp/ai4bi-release-zm6bojpt`。重用已驗證依賴 wheel，核心與 App 使用本次指定內容；來源隔離及 SPC 200 列／4 實體、保存／CSV／發布／服務重啟重播均通過。

安裝版瀏覽器 `.artifacts/installed-spc-delivery-browser/evidence.json` complete=true、exit_code=0、fresh_report=true、drivers_unchanged=true，核心／App 載入位置與 build 核對成立。5 項通過（SPC 8.0 秒、保存 5.4 秒、發布／下載 12.3 秒、舊契約 4.8 秒、完整報表約 1.4 分鐘，runner 約 2 分鐘）；使用原 180／45 秒限制。四份實際下載內容另外讀回核對 100 列／2 實體、資料版本及 PDF 12 頁，結果在該目錄 download-verification.json。

新版 195 檔 NativeApp 包與發布 Kit 的全新 Store 環境建立、持續 Host API 啟停已通過；Electron 來源殼 20 項流程及工作／發布 SPC 下載讀回通過，詳見接入文件。以上是目前安裝證據；下方 ef4e0b16 與其他版本保留作歷史。75 個套件的 notice inventory 仍列 ai4bi／streamlit 缺 license text，封裝成功不代表授權證據已補齊。

前版已驗證安裝包 ef4e0b16（2026-09-06）：前端受認證 artifact 下載已完成 34 項前端測試、正式建置與來源完整瀏覽器流程（2.0 分鐘）驗證。wheel 已通過內容校驗，位於 `.artifacts/release/authenticated-download-wheels/ai4bi_web_api-0.1.0-py3-none-any.whl`，2,049,447 bytes，SHA-256 `b34ba7f306840b0e1d2c60efe99732d9cf8019a0556255211fbfb80dfe005804`。獨立離線驗證 `.artifacts/release/offline-authenticated-download/evidence.json` complete=true：建環境 19.09 秒、安裝 188.70 秒、pip check 3.05 秒、HTTP probe 28.36 秒，全部 exit 0；專案外環境 ai4bi-release-u92vp064，來源隔離與查詢／匯出／重啟檢查通過。

新版 NativeApp 包 `.artifacts/nativeapp/package-authenticated-download/ai4bi-web-0.1.0.napkg.zip` 為 195 檔，SHA-256 `ea0af1f3f5d5c33b3c317e1c83a527934f9039c98698d3a35123f82415549c30`，Kit validate／pack 與內容核對通過。`.artifacts/nativeapp/host-authenticated-download/evidence.json` 已通過，launch 1.66 秒、stop 5.31 秒，程序／埠消失；provisioned_from_archive=false，明確接用本輪已驗證的獨立安裝環境，沒有重算成從包建環境證據。

真正 Electron 來源殼驗證 `.artifacts/nativeapp/electron-download-lifecycle/` passed=true、runner exit 0、shell_unchanged=true：配對、五圖查詢、唯一工作區／圖表編輯保存、重載後重開、Excel／CSV ZIP／PDF／JSON 四種下載，以及關閉取消／確認均通過。實際 PID 36684 退出、51762 埠拒絕連線。content-validation.json 已讀回四檔內容並核對 receipt SHA：JSON 保存標題、KPI 600、CSV ZIP CRC／數值、Excel 數值與契約、PDF 五頁／契約皆成立。這是來源殼與接用環境的指定流程；不代表發布殼、自動 bootstrap、協作式儲存關閉或整個 P06 已完成。

來源更新（2026-09-06）：build 1363c750 已加入 NativeApp 分區 session cookie 模式，完整 API 回歸 486 通過（206.86 秒，一項刻意退化 OLS 警告），正式建置與 wheel 內容校驗通過。新 wheel 位於 `.artifacts/release/partitioned-session-wheels/ai4bi_web_api-0.1.0-py3-none-any.whl`，2,049,301 bytes，SHA-256 `6ead36ce7f92d859910be2bec76f4c3748a46480efcd2991e49d85e9ee618ba7`；日誌 `.artifacts/partitioned-session-wheel.log`。以下 46dffae6 安裝與桌面證據僅適用該版，不包含此修正。

1363c750 獨立安裝已通過，`.artifacts/release/offline-partitioned-session/evidence.json` complete=true：建立環境 9.06 秒、離線安裝 91.39 秒、pip check 1.36 秒、installed HTTP probe 15.48 秒，皆 exit 0。專案外 `ai4bi-release-ddql55xf` 核對來源隔離、build、六個資產、查詢／CSV／Excel／PDF 與發布重啟契約；此 probe 使用預設 strict 模式，不能取代桌面 partitioned 驗證。新版接入包位於 `.artifacts/nativeapp/package-partitioned-session/`，195 檔，SHA-256 `0d7a7472edcd223c07ab156b76fd3011366dc94afa11a88ff7b2e50abd4ac2ad`，Kit validate／pack 與完整內容核對通過；`.artifacts/nativeapp/host-partitioned-session/` 正從封存檔建立新 Store 環境驗啟停。

桌面補充驗證：同一 46dffae6 安裝 App 在外部 Electron 來源殼已成功配對／查詢，但殼內重載後 session 401，`.artifacts/nativeapp/electron-report-flow/` passed=false、runner exit 1。這不撤回以下獨立瀏覽器及公開 Host API 的有限範圍成功，也不代表發布殼、自動 bootstrap 或完整桌面交付通過；詳見 NativeApp 接入文件。

## 46dffae6 安裝驗證結果（2026-09-06）

`.artifacts/release/offline-execution-contract/evidence.json` 已確認 complete=true：建立環境 9.27 秒、離線安裝 91.17 秒、pip check 1.22 秒、installed HTTP probe 14.45 秒，全部 exit 0。專案外環境 `ai4bi-release-0yryaqxx` 使用指定 App／核心 wheel 與 69 個已核對相依 wheel；probe 禁止讀取本專案、舊 AI4BI 與 NativeApp 來源，核對 build、六個靜態資產、KPI 600、分組篩選 200、HAVING Etch、CSV／Excel／PDF、ready 身分及重啟保存。新增查詢與 CSV 的 web-query-v2，以及真實發布後重啟並查詢原發布契約，均已通過。

安裝版六項瀏覽器案例已通過（2.2 分鐘），證據 `.artifacts/installed-execution-contract-browser/`：不相容提示 6.0 秒、日期粒度 7.8 秒、KPI 日趨勢 9.2 秒、期間比較 9.1 秒、目標 9.3 秒、完整報表流程 1.4 分鐘。runner 與驗證器 exit_code 均為 0，fresh_report／drivers_unchanged 皆 true，Playwright passed 且 failedTests 為空；18 份本輪下載已保存與計算雜湊。receipt 綁定 SHA-256 `d3866c623f1b5fda0c399bbb430877db48ad6e4a1d6657713cb0264b5132cd50`。未放寬 180 秒總流程與 45 秒查詢限制；本輪通過不取代高負載／恢復或真實 WebView 驗收。

同版 NativeApp 包已完成，195 檔，SHA-256 `7d986b0695927d30e68b78f302b58c42c5e62d3cd1488590ede560761b576408`，位於 `.artifacts/nativeapp/package-execution-contract/`；公開 Kit validate／pack 與完整集合／內容雜湊核對通過。`.artifacts/nativeapp/host-execution-contract/evidence.json` 已確認 complete=true、provisioned_from_archive=true：匯入 2.47 秒、新環境建立 101.19 秒、prepare 1.31 秒、resolve 0.25 秒、持續 Host API launch 2.45 秒、stop 5.22 秒，全部 exit 0。ready 核對同版 build，資料庫位於隔離 Store；實際 launcher PID 13252 退出、61437 埠關閉，stop_verification 兩項皆 true。這是既有 CPython 3.11 與發布 Kit 上的新 App 環境驗證，不包含基礎 runtime 新機安裝、WebView、自動配對、Host 啟動身分綁定或協作式關閉。下方「執行中／尚未建立」為本輪結果之前的歷史紀錄，以本節為準。

46dffae6 完整 API 回歸已完成：483 通過、260.25 秒，一項刻意退化 OLS 警告。wheel 已通過建置與內容校驗，位於 `.artifacts/release/execution-contract-wheels/ai4bi_web_api-0.1.0-py3-none-any.whl`，2,049,019 bytes，SHA-256 `fa61893f0a710ae6d418d5886440ce804d98716f8fe302d82d6e598edfca4576`，日誌 `.artifacts/execution-contract-wheel.log`。`.artifacts/release/offline-execution-contract/` 正執行新的專案外環境離線安裝，日誌 `.artifacts/execution-contract-offline.log`；重用 offline-worker-read-lock 已逐一核對的 69 個相依 wheel，App／核心使用指定 wheel。安裝驗證器已增加查詢／CSV execution_contract 核對，以及真實發布後重啟、以原契約查詢發布資料；結果尚未回傳，這些新檢查不算已通過。

目前來源為 `46dffae6f2b9e5c3cd23de143e84bb4bbaaacf69416e63867f53e9f0b60ea71d`，已加入 Web 執行契約與匯出追溯。73 項相關回歸、正式建置與瀏覽器不相容提示專項通過；完整 API 回歸執行中。新 wheel 尚未建立，下方 e9fe06de 離線／Host 證據只適用舊版；完整流程 be016e34 證據亦不得套用至新來源。

be016e34 的來源完整報表流程已通過（2.8 分鐘，未改 180 秒限制），證據 `.artifacts/date-dimensions-full-browser/`。新版 wheel／安裝與發布執行契約相容性仍未完成；不將來源瀏覽器通過等同安裝交付。

目前來源為日期分組版 `be016e34…`，41 項相關回歸、快照 Excel 與瀏覽器專項通過，尚未封裝；下方 e9fe06de 證據仍只適用該版。修正後的 Host 驗證工具使用 `serve` 公開入口建立持續 API，透過同一 API 執行 launch／running／stop，停止後檢查實際 launcher PID 與 TCP 埠。`.artifacts/nativeapp/host-worker-read-lock-api/evidence.json` 已通過：launch 4.44 秒、stop 5.41 秒，stop_verification 的 launcher_exited 與 endpoint_closed 皆 true；這輪連接已安裝環境，provisioned_from_archive=false。19 項工具回歸通過（0.77 秒），含真實程序存活及殘留監聽埠拒絕。沒有修改發布 Kit 或平台原始碼；真實 WebView 與完整交付仍未完成。

停止驗證更正（2026-09-06）：host-worker-read-lock 的獨立環境建立與 ready build 核對成立，但原工具用不同 CLI 程序呼叫 launch／stop，Kit 的記憶體啟動登錄未共享；stop 回報成功後 PID 10184／35908 與 57441 埠仍存在。已將該 evidence.complete 改為 false，保留 cli-evidence.json 原紀錄及 stop_audit，並核對本輪命令路徑後清理程序與監聽埠。先前相同工具的停止成功紀錄也不足以證明實際退出。須改用同一持續 Host API、檢查真實程序與埠，再重新驗證；不得引用清空 running 清單宣稱停止通過。

## Assignment 讀鎖修正版交付（2026-09-06，執行中）

安裝版四案例結果已確認為 3 通過／1 失敗：完整流程於發布報表階段達 180 秒總時限，沒有重現 worker 失敗；詳見 P00 最新紀錄。`.artifacts/installed-worker-read-lock-browser/evidence.json` 綁定本 release receipt SHA-256 `21e4c8e9588c311e73b62535460abac486c8fdfd51832811a56fa53d5a0cb14e`，fresh_report 與 drivers_unchanged 都為 true，15 份下載已保存與計算雜湊，但 exit_code=1。交付工具的真實收集流程已執行，完整產品瀏覽器驗收仍未通過。

交付工具邊界測試：`tests/tooling/test_release_inputs.py` 合計 9 通過（0.71 秒），其中 3 項新增模擬 runner 成功但報告陳舊／driver 中途變更的情境，驗證工具會拒絕假成功，且只複製本輪新增的下載，保留相符檔案內容。既有 6 項 wheel 重用校驗亦通過。證據 `.artifacts/installed-browser-evidence-tests.xml`；此為工具控制流程測試，沒有取代真實 Playwright 或安裝驗證。

來源 build `e9fe06de4179508631907a9901d1730115c9be647710e0701e1e12d28ce5abec` 的 wheel 已通過完整 manifest／檔案集合校驗，位於 `.artifacts/release/worker-read-lock-wheels/ai4bi_web_api-0.1.0-py3-none-any.whl`，2,047,127 bytes，SHA-256 `036cd526fc340192fdea8a5dd17b93d8ede41b3a7ed01002b7847f3843bd9bcd`。45 項 worker／任務接受回歸通過。

獨立驗證已通過，證據 `.artifacts/release/offline-worker-read-lock/evidence.json` 的 complete=true：建立環境 17.74 秒、離線安裝 178.50 秒、pip check 2.56 秒、installed HTTP probe 22.64 秒，全部 exit 0。使用 --dependency-release 重用已逐一核對版本與雜湊的 69 個相依 wheel；App／核心使用本輪指定 wheel。新環境位於專案外 `ai4bi-release-1f3gjkdk`，probe 核對 build e9fe06de、六個靜態資產、查詢、匯出、ready 身分及重啟保存，並禁止讀取三個專案來源。安裝版完整互動另於 `.artifacts/installed-worker-read-lock-browser/` 驗證，尚不能以 HTTP probe 代替瀏覽器驗收。

安裝版瀏覽器工具另補上本輪下載保存、每檔 SHA-256、測試／設定／工具本身前後雜湊核對，以及拒絕將未更新的舊 HTML 報告當成新結果。本輪真實執行已收集 15 份下載，確認報告更新與 driver 未變更，並保留 runner 失敗狀態。輸出位於每輪既有結果目錄的 downloads/；沒有新增產品模組或修改 App wheel。

e9fe06de 已重新封裝為 `.artifacts/nativeapp/package-worker-read-lock/ai4bi-web-0.1.0.napkg.zip`，195 檔，SHA-256 `84f2b2fc52889118c29bd2b8f7f37e459140b6f5f9ab1f7c0732d955fb48e9d9`，Kit validate／pack 與完整集合、逐檔雜湊皆通過。`.artifacts/nativeapp/host-worker-read-lock/` 正從封存內容建立新的 Store 環境並驗證公開 Kit 啟停，結果待定。安裝版完整互動及 NativeApp WebView 驗收仍未完成。

## 趨勢小圖版本交付驗證（2026-09-06，離線驗證通過）

已使用同一 release receipt 建立 NativeApp 接入包（195 檔，Kit validate／pack 與內容雜湊通過），證據 `.artifacts/nativeapp/package-sparkline/evidence.json`，包與限制見 integrations/nativeapp/README.md。安裝版瀏覽器四案例（日趨勢、期間比較、固定目標、完整報表）已啟動，輸出 `.artifacts/installed-sparkline-browser/`；結果 3 通過／1 失敗，完整流程捕捉 assignment-read PermissionError，詳見 P00 最新段落。

安裝版瀏覽器驗證已整理為維護工具 `scripts/validate_installed_browser.py`，歸屬既有交付驗證 scripts，不另建測試框架。工具要求 release 完成獨立安裝與 HTTP probe，先以安裝環境的 `python -I` 核對 core／App 載入位置及 build，再指定 AI4BI_E2E_PYTHON、清除 PYTHONPATH／PYTHONHOME，執行明確的 --grep 選擇。證據綁定 release receipt、E2E／設定／啟動 harness 雜湊、結果與報告；Windows 直接呼叫 Node 的 npm CLI，不把 grep 拼入 shell。未完成 release 的拒絕已實測（`.artifacts/installed-browser-rejection.log`），且沒有建立輸出目錄。本次 HTTP probe 已通過，安裝版瀏覽器接續執行。

首輪 `.artifacts/release/offline-sparkline/` 已結束：離線安裝 185.81 秒、pip check 2.61 秒，皆通過；HTTP probe 4.86 秒失敗。原因是驗證器把 `application/json` 靜態資產解析為物件，再交給 hashlib.sha256，觸發 TypeError，尚未走到查詢／匯出驗證。已在 `scripts/probe_app_wheel.py` 增加 raw_response 選項，資產雜湊一律校驗原始回應位元組，API 回應仍保留 JSON 解析。App wheel 與產品 build 未改動。

修正後另啟全新驗證 `.artifacts/release/offline-sparkline-verified/`，日誌 `.artifacts/sparkline-offline-verified.log`。使用已逐檔核對的本地 wheelhouse，PIP_NO_INDEX=1 且 PIP_FIND_LINKS 指向首輪 wheelhouse，重新建立獨立環境與安裝，不覆寫首輪失敗證據。新一輪已通過：離線安裝 174.39 秒、pip check 2.44 秒、HTTP／查詢／匯出／重啟 probe 21.44 秒，皆 exit 0、receipt complete=true。6 個靜態資產包含 maps/world_50m.json 的原始 HTTP 位元組雜湊全部符合。來源讀取 audit 拒絕三個 checkout；安裝根為 ai4bi-release-a6zauq5k。收集 75 個 Python／npm 套件、116 份 notice，ai4bi 與 Streamlit 仍缺授權文字證據。NativeApp 封裝／WebView／新機 runtime 驗收另計。

收集後的 wheelhouse 已額外逐一校驗：71 個套件的名稱／版本／SHA-256 與 evidence 完全一致，沒有重複或缺件，requirements.lock 內容逐行符合套件與雜湊集合。證據 `.artifacts/sparkline-wheelhouse-check.json`，lock SHA-256 `30d9fb4cd7edf4b56ab69989ef470babcad02865ea15a873a0a44a768dd6e675`。這項檢查不代表獨立安裝或 HTTP probe 已通過。新安裝根目錄為系統暫存 `ai4bi-release-wnatuor6`，實際完整路徑由 release receipt 記錄。

依賴差異已核對：Python 閉包由 66 增為 71，新增 formulaic 1.2.2、interface-meta 2.0.1、patsy 1.0.3、statsmodels 0.15.0、wrapt 2.4.0，沒有移除或變更其他版本。差異快照 `.artifacts/sparkline-dependency-diff.json`；執行狀態以 release/evidence.json 為準。下載 30.52 秒、建立獨立環境 20.55 秒，皆 exit 0；首輪離線安裝後續已通過，但 HTTP probe 因靜態 JSON 雜湊讀取方式失敗；修正後的全新驗證仍在執行，詳見本節首段。

build `666431ce815259d71664dd4c15c5bf06061a141fb583c16c526b33f76840e5e7` 已完成 459 項完整 API、31 項前端及小圖瀏覽器專項。新 wheel 位於 `.artifacts/release/sparkline-verified-wheels/ai4bi_web_api-0.1.0-py3-none-any.whl`，2,047,037 bytes，SHA-256 `12dd944449218207e1e664a89c0bb5c139b0ff5424d7274dc257f37e829f408f`；既有 verify_wheel 已核對 manifest、完整檔案集合及每檔雜湊。

首次自訂封裝呼叫錯把 verify_manifest 的身分摘要作為完整 manifest 傳入 build_wheel，遭完整性检查拒絕（`.artifacts/sparkline-wheel-build.log`）。改為先驗身分，再讀完整 manifest，封裝通過（`.artifacts/sparkline-wheel-verified.log`）；沒有修改封裝器或放寬檢查，也沒有覆蓋原已驗證 wheel。

`scripts/validate_app_release.py` 已對新 wheel 啟動獨立驗證，輸出 `.artifacts/release/offline-sparkline/`，頂層日誌 `.artifacts/sparkline-offline.log`。此輪使用目前安裝套件的完整依賴集合，包含新加入的 statsmodels 閉包，不沿用舊版缺少相依套件的成功證據。安裝環境在 checkout 外，HTTP probe 禁止引用本專案、舊 AI4BI 與 nativeApp_v2 來源。首輪收集／離線安裝／pip check 已通過，HTTP 驗證器失敗已定位並修正；新一輪結果待定，目前不能宣稱新版已離線交付或 NativeApp 已驗收。

來源更新（2026-09-06，`666431ce…`）：KPI 逐日趨勢小圖已接入設定、受治理日聚合、SVG／原值表、PDF 趨勢頁與 Excel 序列；9 項 API／匯出專項、31 項前端測試（含 4 項小圖邊界呈現）及 TypeScript／正式建置通過；瀏覽器專項通過（18.0 秒），PDF 已讀回核對。主數字仍由原純量查詢計算。完整 API 回歸 459 通過（369.70 秒，一項刻意退化 OLS warning）；新版已通過獨立離線安裝、HTTP／查詢／匯出／重啟驗證，195 檔 NativeApp 接入包亦已通過封装完整性驗證，安裝版瀏覽器 3 通過／1 工作失敗，後續修正見最新紀錄，詳見 P00「KPI 逐日趨勢小圖」。

來源增補（2026-09-06，`d633ea9a…`）：期間比較已改為保留大整數與 Decimal 的原查詢表格；兩項轉接層回歸先重現 null 遺失，修正後報表／匯出回歸 253 通過（137.90 秒，一項刻意退化 OLS warning）。下方 448 項完整 API 與瀏覽器 2 通過／1 逾時屬前一版 052f8f04。新版尚未離線封裝，詳見 P00「期間比較保留精確原值」。

目前來源已更新為 `052f8f04…`，詳見本文「Worker 來源更新」；下方 bd4feb55 為期間比較版本紀錄。最近已驗證離線包仍為 a2341d。

最新建置 `bd4feb55…`（2026-09-06）已加入 KPI 固定天數／日曆期間比較、前期值及絕對／百分比差異。查詢保留 RLS 與作用範圍，提供日期條件保留／取代策略，混合 OR 明確拒絕；UTC 日界、閏日、缺期與零分母均有專項。23 項隔離後相關測試、27 項既有前端呈現回歸與正式建置通過；同版兩個 KPI 瀏覽器案例重跑通過（21.4／18.7 秒），PDF／Excel 內容已核對。完整 API 回歸 443 通過（663.56 秒，一項刻意退化 OLS 測試 warning），詳細結果見 P00；此耗時不是效能 gate 通過。首輪瀏覽器曾遇到 worker exit 1，隔離重播與同版重跑成功仍不足以定因，穩定性問題維持待辦。sparkline、其他日期／分析／圖表主題、真正 NativeApp、安全 bootstrap、完整效能／恢復及新版離線交付仍未完成；該輪最近已驗證安裝包為 a2341d，後續版本見本文最新紀錄。

前次來源已建置為 `e917d03d…`，包含預載備援、閒置計時修正、CLI 提前拒絕與分析依賴延後載入。聚焦測試 9 通過／1 項 CLI 逾時，該 CLI 單獨重跑通過；瀏覽器 1 通過／1 項完整流程逾時，完整驗收未完成。尚未重新封裝或交付，以下 a2341d 證據只對應既有安裝包；詳見 [P00 最新紀錄](p00-baseline.md)。

範圍是目前 App 建置的 Windows x64／CPython 3.11 安裝閉包及實際 HTTP 執行，不代表完整產品、NativeApp WebView 或所有作業系統驗收。

最近已驗證交付建置為 `a2341d2d380fbb75af66023e5453e4fbf490900329b8b97d3d496abe7cecfead`，包含查詢與圖表互動改進、worker handoff 診斷與有限延後清理；278 項完整 API 回歸通過（265.25 秒）。前端沿用此前型別／正式建置及聚焦瀏覽器證據；較早來源的完整瀏覽器 gate 仍未通過，該版新安裝環境的瀏覽器結果見下段。

本版 wheel 已完成獨立離線安裝與實際 HTTP／worker／匯出／保存／重啟驗證，證據 `.artifacts/release/offline-interaction-cleanup/evidence.json`，complete=true。建立環境 20.16 秒、離線安裝 182.61 秒、pip check 2.22 秒、HTTP probe 32.44 秒，全部 exit 0。新環境為 `C:/Users/hctsa/AppData/Local/Temp/ai4bi-release-vwu_vege/venv`；執行時拒絕讀取 Web 與舊核心 checkout。66 個 Python wheel 使用固定版本及 SHA-256，第三方依賴從已驗證閉包重用；70 套件 notice 收集完成，三項授權證據問題未消失。

App wheel 大小 1,376,039 bytes，SHA-256 `481ba0514fe3df9ddf65dd5e4269248f9df2398b9dba8df0919939c9978dc567`，建置輸出在 `.artifacts/release/wheels/`，本次驗證副本保存在 `offline-interaction-cleanup/wheelhouse/`。前版 022786 的 wheel 仍保存在其原驗證目錄 `offline-compatible-dataframes/wheelhouse/`，重建前已核對雜湊。

相同 build 的 NativeApp 包已通過 Kit validate／pack 與完整 181 檔集合／雜湊核對：`.artifacts/nativeapp/package-interaction-cleanup/ai4bi-web-0.1.0.napkg.zip`，SHA-256 `2bdd4b257b018c8c90955ea4ff648c959c50df8042b3c6c27d5d47925da25870`。從封存包建立全新 Store 環境與 HTTP 啟停驗證亦通過（`.artifacts/nativeapp/host-interaction-cleanup/evidence.json`，complete=true、provisioned_from_archive=true）。仍需既有 CPython 與 Kit；詳細步驟見 NativeApp 文件。本節不代表 Tauri WebView、安全 bootstrap、無基礎 runtime 的新機安裝或完整產品交付完成。

本次用 `AI4BI_E2E_PYTHON` 指向上述專案外的新安裝環境，清除 PYTHONPATH 後執行完整瀏覽器回歸：1 項通過、1 項失敗。聚焦互動案例 23.8 秒通過；完整流程在新增 discount 參數後的獨立 5 秒可見性斷言失敗（第 479 行），不是 180 秒總截止。trace 最後的編輯請求 HTTP 200、4,867.732 ms，回應確實含 discount；目前證據支持回應延遲接近 UI 門檻，未斷定其全部原因。沒有放寬門檻。證據 `.artifacts/installed-interaction-browser-failure/`。同輪捕捉 worker 交接檔 PermissionError／errno 13／winerror 32，第一次失敗排入重試；測試結束後該明確目錄已不存在，補上延後清理的真實執行證據。

版本範圍更新：下方先前成功離線交付紀錄的 build 為 `aeb886...`。中間版本 `c980923de8335a1a7bfb4cad471decc1d5e667c166dfa10f5fb6aabeb9c23411` 已完成 `.artifacts/release/offline-dataframe-build/` 獨立安裝驗證：建立環境 43.06 秒、離線安裝 519.67 秒、pip check 7.83 秒、HTTP／worker／重啟 probe 173.62 秒，全部 exit 0。其 246 項 API 回歸及後端基準只適用該中間版本；該版本瀏覽器完整流程兩次達 180 秒上限，尚未通過。

先前版本補上無限值、Decimal 與日期時區的舊版語意相容保護，build 為 `02278626f9259cccb54929e1487ead56d64493e4f0671ca28d1f4f339144ec1a`。11 項聚焦測試通過（43.26 秒），完整 API 回歸 253 項通過（430.58 秒），工具測試 45 項通過（0.82 秒）；新 wheel 建置成功，大小 1,373,087 bytes，SHA-256 `cb624d0ff0c6b19f66c54b94c3ac6cca2b7baa8c56ab15b6425239e4cfe1b2e5`。本版本後端基準已通過，獨立安裝已在 `.artifacts/release/offline-compatible-dataframes/` 通過驗證；不能沿用 c980 的成功紀錄，也不能把離線安裝成功當成完整互動驗收。

## 可重跑流程

先前 `022786...` 獨立安裝已完成，證據在 `.artifacts/release/offline-compatible-dataframes/evidence.json`：create-env 9.72 秒、offline-install 79.16 秒、pip-check 1.16 秒、installed-http-probe 21.31 秒，全部 exit 0、complete=true，probe build 與來源一致。環境位於 `C:/Users/hctsa/AppData/Local/Temp/ai4bi-release-6k40ju1j/venv`，執行時拒絕讀取 Web 與舊核心來源；固定依賴重用前已驗證版本與 SHA-256。70 套件 notice 盤點完成，三項既有證據缺失仍保留。

同版 `.artifacts/nativeapp/package-compatible-dataframes/` 已通過 Kit validate／pack 與全部 181 個輸入檔案核對；`.artifacts/nativeapp/host-compatible-dataframes/` 已通過公開 Kit 的 register-environment、prepare、resolve、launch、ready 身分讀取、stop 與 running 空集合檢查。本次綁定上述已安裝環境，沒有重驗從封存檔建立環境；也不是 Tauri WebView 或完整安全 bootstrap 驗收。

先在已通過回歸的開發環境建置 App wheel，再提供固定核心 wheel：

```powershell
& .venv/Scripts/python.exe scripts/build_app.py --wheel
& .venv/Scripts/python.exe scripts/validate_app_release.py `
  --core-wheel .artifacts/p00-baseline/wheels/ai4bi-0.1.0-py3-none-any.whl `
  --app-wheel .artifacts/release/wheels/ai4bi_web_api-0.1.0-py3-none-any.whl `
  --output .artifacts/release/offline-check `
  --forbid-source C:/code/claude/AI4BI
```

輸出目錄必須尚未存在；需要重跑時使用另一個驗證目錄，保留先前失敗證據。核心來源路徑只用於驗證期間拒絕讀取，不是執行依賴。

若已有驗證成功的離線閉包，可加上 `--dependency-release .artifacts/release/offline-windows-x64`。工具先核對來源 receipt、lock、每個所需 wheel 的版本與 SHA-256，再複製 64 個第三方依賴；核心與 App 仍使用本次指定 wheel。資料不符就拒絕，不自動改成網路下載。這不代表建置 wheel 所需的隔離建置依賴也已離線配送。

App wheel 現在從 `.artifacts/release/` 下全新的短期 staging 目錄建置，只複製目前 package 來源與 `pyproject.toml`，不沿用 setuptools 的 `build/lib`。產出的 wheel 須符合目前 manifest 的完整檔案集合與 SHA-256，才可取代輸出 wheel。舊資產、已移除 Python 模組、漏檔、內容變更、錯誤 manifest 與重複封存項目都會拒絕。Staging 用完即清除；先前驗證目錄保留。

安裝與 HTTP probe 全部成功後，工具會在該次 release 的 `third-party-notices/` 收集 Python／npm notice 證據。`evidence.json` 的 `complete` 表示安裝與 probe 成功；notice 收集在其後執行，須另外核對工具正常結束及 `inventory.json`，不能只憑 `complete` 宣稱 notice 完整。缺少授權證據仍由 P00 追蹤。

## 新版交付驗證追蹤（2026-09-06）

`.artifacts/release/offline-feature-update/` 保留第一次新版驗證失敗證據。離線安裝與 `pip check` 成功，但 `/ready` 前的 manifest 核對失敗：wheel 混入先前 `build/lib` 的 `index-B9C5rpie.js` 與 `index-DD5K6xDj.css`，目前 API 與前端檔案內容本身沒有差異。修正建置隔離並增加封裝後驗證，沒有放寬 runtime 完整性要求。

修正後建置成功，App wheel 為 1,372,353 bytes、SHA-256 `19b23fd191ea77802b5e102c45f882d9a5b648f5a7c3cc6b9bbb188e211aaa91`，build ID `aeb886da3f0d3561881a3981ae3480db48ebb8ecc792ca798c3bd54860d48531`。交付工具測試共 20 項通過（0.51 秒），包括新建置隔離及拒絕錯誤封裝時保留舊輸出。

新的完整安裝驗證 `.artifacts/release/offline-clean-build/` 已完成：建立環境 8.55 秒、離線安裝 72.55 秒、`pip check` 1.09 秒、HTTP probe 20.42 秒，全部 exit 0。擴充 probe 核對啟動身分、OR 條件群組結果 200、HAVING 保留 Etch、CSV ZIP 4,801 bytes、Excel 8,438 bytes、PDF 28,698 bytes，以及重啟後報表與匯出資料保留。初始無篩選 KPI 為 600。測試仍使用 mock LLM；PDF 僅核對格式與基本大小，未代表完整字型與視覺驗收。

`third-party-notices/inventory.json` 收集 70 套件、107 份 notice，SHA-256 `290354e3f109d98958e426997b1d421eac96bd80b37dc5b12391663cf9241d96`，綁定本次 release receipt、build ID 與 npm lock。核心、App 與 Streamlit 的三項授權證據缺口仍存在。先前 P00 inventory 屬於舊 Python release；本次新 inventory 不回寫或取代它。

本次安裝位於系統暫存的 `ai4bi-release-tkwik6hp/venv`，完整位置由 receipt 記錄。使用此 interpreter 的 Playwright 完整主流程 **1 項通過，總計 174.44 秒**，沒有 unexpected、flaky 或 skipped；未放寬 180 秒流程與 45 秒查詢門檻。`browser-report/` 保存當次 HTML 報告，`browser-evidence.json` 綁定 release receipt、App build、interpreter、測試結果與 HTML SHA-256。測試 driver 與啟動 harness 仍來自開發目錄，API／核心與前端靜態檔案使用新安裝 wheel；此瀏覽器驗證沒有施加 HTTP probe 的 checkout 讀取 audit，亦不是 Tauri WebView 驗收。

`validate_app_release.py` 依已安裝且通過回歸的套件版本收集相依閉包，先確認所有版本滿足宣告限制，再下載二進位 wheel；不把其他無關開發套件全部帶入。固定核心與 App wheel 直接取自指定檔案。它產生附每個 wheel SHA-256 的 `requirements.lock`，在 checkout 之外建立不共用 system site-packages 的全新 venv，以 `--no-index --require-hashes` 安裝，再執行 `pip check` 與 HTTP probe。

產物在 `.artifacts/release/<驗證目錄>/`：

- `wheelhouse/`：全部相依 wheel，包含核心與 App。
- `requirements.lock`：精確版本與雜湊，和該次 wheelhouse 配套使用。
- `evidence.json`：版本、平台、來源雜湊、各步驟結果及實際安裝路徑。
- 各步驟 `.log`：下載、建立環境、離線安裝、相依檢查、HTTP probe 日誌。

隔離安裝保留在系統暫存目錄，位置記錄於 evidence；不自動刪除失敗環境或覆寫使用者資料。

## HTTP probe 的驗證範圍

`probe_app_wheel.py` 從獨立目錄、以新 venv 的 Python `-I` 執行。它確認 App 與核心都載入新 venv，拒絕主程序讀取 checkout，並限制主程序只能連到 loopback。

透過真實 HTTP 驗證 `/ready` 的 build ID、完整靜態資產雜湊、深層路由重新載入、API／靜態檔 404、配對、半導體工作區及真實子程序查詢的 600 筆結果；另外驗證 mock 模式的標題修改提案不自動套用、Excel 內容包含 600、PDF 可生成、報表保存後停止與重啟，並讀回相同報表及 Excel 檔案。

PDF probe 只驗證成功生成 PDF；中文字型、分頁與每個內容的驗收仍以專項測試及後續完整交付檢查為準。此 probe 是 HTTP 與安裝驗證，不代替 Playwright 或 NativeApp 實機測試。

## 本次證據

2026-09-05：`.artifacts/release/offline-windows-x64/evidence.json` 的 `complete=true`，各步驟全部 exit 0。66 個 wheel 共 157,801,897 bytes；平台為 Windows x64、CPython 3.11.9。這次 build ID 為 `6669889c192d1e348c9cec7214b4f1dfb3be0b5351c6e2701f0cda255cd9d775`。

主機實測為 Snapdragon X／ARM64，Windows 回報 `ARM 64-bit Processor`，PowerShell 架構為 ARM64；Python 與二進位 wheel 則為 AMD64。因此本次證明的是此主機上的 x64 模擬執行，不是原生 ARM64 Python 或 NativeApp host 的驗收。原始主機資訊保存在同目錄 `host.json`。

| 驗證步驟 | 結果 | 秒數 |
|---|---|---:|
| 精確版本 wheel 收集 | 通過 | 18.86 |
| 建立獨立 venv | 通過 | 10.91 |
| `--no-index --require-hashes` 安裝 | 通過 | 138.33 |
| `pip check` | 無相依衝突 | 4.05 |
| 安裝後 HTTP／worker／重啟 probe | 通過 | 35.73 |

主程序 App／核心來源都位於新 venv，`include-system-site-packages=false`，拒絕讀取 Web 與舊核心 checkout。實際查得 600，產生 8,336 bytes 的 Excel 及 28,165 bytes 的 PDF，mock AI 提案、保存與重啟讀回皆通過。

完整瀏覽器流程可選用同一個已驗證環境：

```powershell
$evidence = Get-Content -Raw .artifacts/release/offline-windows-x64/evidence.json | ConvertFrom-Json
$env:AI4BI_E2E_PYTHON = Join-Path $evidence.installation_root 'venv/Scripts/python.exe'
npm run test:e2e
Remove-Item Env:AI4BI_E2E_PYTHON
```

Playwright 仍由開發端提供測試驅動，API、工作程序與靜態介面由已安裝的 App wheel 提供；此流程不需要在離線目標安裝 Node。

本次選用乾淨安裝環境重跑 **1 項完整瀏覽器流程通過，39.6 秒，總計 46.2 秒**，涵蓋報表保存／復原、鍵盤對話框、匯入草稿恢復、Excel 下載、計算指標與參數重算、圖表寬度及類型編輯。報告已另存 `.artifacts/release/offline-windows-x64/browser-report/`，避免下一輪 Playwright 覆寫本次證據。未變更每次查詢的 45 秒門檻。

## 使用已驗證的離線包

將同一次驗證的 `wheelhouse/` 與 `requirements.lock` 一起複製至目標電腦。目標需先具備相同平台與架構的 CPython 3.11；Python 本身未包含在 wheelhouse。

在套件所在目錄使用 PowerShell：

```powershell
py -3.11 -m venv runtime
& runtime/Scripts/python.exe -m pip install --no-index --only-binary=:all: --find-links wheelhouse --require-hashes -r requirements.lock
& runtime/Scripts/python.exe -m pip check
& runtime/Scripts/python.exe -m ai4bi_web_api --data-root C:/BI/data
```

開啟終端顯示的網址，輸入本次配對碼。資料根是使用者選擇的位置，不放入 App 安裝目錄。App／核心或相依套件變動後必須重新建置及驗證，不能沿用舊清單宣稱新建置已通過。

## 尚未涵蓋

接入包後續驗證：新版 181 檔 NativeApp 包已通過完整封裝與 HTTP loader 檢查；另透過發布 Kit 從包內 wheelhouse 建立全新 Store venv，通過 pip check 與相同 HTTP／worker／匯出／重啟 probe，詳見 [NativeApp 環境準備證據](../../integrations/nativeapp/README.md#從接入包建立新的離線環境)。此流程仍需預先可用的基礎 Python 與 Kit。

完整斷網作業系統測試、其他平台／原生 ARM64、Python runtime 配送、NativeApp Kit 封裝與 WebView 啟停、真實 LLM 連線、全部圖表格式與中文字型閉包、更新與回退驗收仍依主實作計畫追蹤。
## Worker 來源更新（2026-09-06）

來源 `052f8f04…` 已建置，加入有限致命錯誤診斷及 Windows assignment 刪檔重試；worker／任務接受回歸 43 通過，完整 API 448 通過（539.92 秒）。測後 manifest 一致；瀏覽器 2 通過／1 完整流程達 180 秒總時限。本版尚未產生新的離線交付包，既有 a2341d 安裝證據不涵蓋本次變更。詳細測試及限制見 P00「Worker 致命錯誤診斷與檔案鎖」。
