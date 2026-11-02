# NativeApp 接入

## 2026-10-05 當前 v7 開發接入結果

目前來源 package **195 檔**，Build ID `c4dd0f19dbb839cc70b6311846520c033b6d32e1b31f05d4fad38098489e3bd5`，SHA-256 `34634045ff77c53228859b448beab92df7c286db882fa339c6d94ffd23cb9cb1`；`web-query-v7`。既有正式 builder 透過 Kit validate／pack，無手改 archive。package、Host 與 Electron evidence 位於 `.artifacts/nativeapp/package-v7-quick/`、`host-v7-quick/` 與 `electron-v7-quick/`。桌面 driver 按 release receipt 驗 execution contract，不再鎖定 v6；此版來源殼 **32 項通過**，步驟含五圖工作區、四種分析保存／重開／計算、四格式下載、發布重播、關窗和程序回收。

當前 App wheel SHA-256 `2af212902c38fb8b1dfe0cf34fe2252e64ea0ad1c4096689a10b7cb67165c443`。輪子由 stage 中目前 Python／靜態資產建立，與受驗 wheel manifest 完全相符；離線 closure 重用既有經驗證 wheels。在新 venv 來源隔離 probe 的離線安裝 **246.69 秒**、pip check **4.06 秒**，loopback 功能與重啟 readback 亦通過。75 套件 notice 收集有 **2 個證據項待複核**；詳見 `.artifacts/release/offline-nativeapp-v7-quick/evidence.json`。重跑桌面案例前直接使用既有 Host Store，不要重裝 closure：

```powershell
node scripts/validate_nativeapp_desktop.cjs --kit .artifacts/nativeapp/kit-spc-delivery --desktop C:/code/claude/nativeApp_v2/apps/desktop --host-validation .artifacts/nativeapp/host-v7-quick --output .artifacts/nativeapp/electron-v7-quick-repeat
```

這是 Electron 開發來源殼與附掛已裝 Python 環境的 Host 驗證。Host receipt `provisioned_from_archive=false`；未涵蓋正式 Setup／一包新機 Runtime、自動 Host 身分綁定、安全配對、OS 另存對話框或更新／回退。它也不代表 RFM 完整桌面操作，RFM 是 v7 的另一驗收範圍。較早各版以下保留為版本歷史，不能覆寫本節結果。


發布版平台驗證（0.1.8，AI4BI build `b0b32e45…`）：`scripts/validate_nativeapp_runtime.cjs` 實際啟動發布 ZIP 內的 WebView2 EXE，由同包 Host 載入 AI4BI；目前 **14 步驟通過**。首次啟動手動配對、建立工作區、修改圖表標題並保存，再原生關窗；確認全部退出後，以新的 WebView 設定目錄及新程序重啟、重新配對、開啟原工作區，保存標題及五圖查詢皆恢復。兩輪各 **20 個程序全部退出**，Host／App 連接埠皆關閉，未使用強制清理；發布檔案及 driver 副本雜湊已核對，重啟畫面已檢視。證據 `.artifacts/nativeapp/webview2-change-restart/evidence.json`、同目錄 `runtime-workspace-initial.png`／`runtime-workspace-restart.png` 與 driver 副本。先前單次啟動的 6 步紀錄保留於 `webview2-change-smoke`。

此測試組合未修改的 `NativeApp-Platform-0.1.8.zip` **57 檔**與發布 Integration Kit 的內嵌 Python **34 檔**；`.artifacts/nativeapp/runtime-platform-0.1.8/provenance.json` 記錄 ZIP／成員 SHA-256，實際 import 指向發布平台目錄。沿用既有 Host 驗證工具，以該 Python／Host 從 AI4BI 接入包建立獨立 Store：環境安裝 **99.09 秒**、launch **1.81 秒**、stop **5.19 秒**，見 `.artifacts/nativeapp/host-runtime-change/evidence.json`。基礎 CPython 仍由本機提供；這是發布元件組合驗證，尚未完成整套 Setup、新機、發布版完整分析／下載矩陣、自動配對、原生另存或升級回滾。

重跑發布版桌面測試（輸出目錄必須不存在；只能使用 `.artifacts/` 下的測試 Runtime 與已完成 Host 驗證的 Store）：

```powershell
node scripts/validate_nativeapp_runtime.cjs --runtime .artifacts/nativeapp/runtime-platform-0.1.8 --host-validation .artifacts/nativeapp/host-runtime-change --output .artifacts/nativeapp/webview2-change-repeat
```

舊 `nativeapp-runtime.zip` 是 0.1.0 產物，內含固定平台開發目錄及 LV Python 路徑的啟動器，不作為可攜交付證據。以下為較早的 Electron 來源殼與封裝驗證紀錄；其中「Runtime 待驗」已由上述基礎測試部分推進，完整交付 gate 仍未通過。

新版 v6 接入驗證完成（build `b0b32e45c68bff975b72517b6782ce5686ffd6cfbc0fe4b094b6ff5a7cfe8983`）：`.artifacts/nativeapp/package-change-delivery/ai4bi-web-0.1.0.napkg.zip`，**195 檔、168,518,139 bytes**，SHA-256 `c4913b85fc7d2010109a7f1723191b42ca5707646c9386f9949760f65e5af838`。本輪重新核對發布 Kit 原 ZIP 與既有解壓目錄的 87 個成員，SHA 仍為 `6c08dd026190fc45aa6eb93f273376439a6d57bdae33f8ac853b68a07a63a554`；未修改 Kit 或外部平台來源。

`.artifacts/nativeapp/host-change-delivery/evidence.json` complete=true、provisioned_from_archive=true：指定相容 CPython，從包內 wheelhouse／lock 建立全新 Store 環境 **101.02 秒**，Host API launch **1.80 秒**、stop **5.19 秒**；ready build 一致，launcher_exited／endpoint_closed 皆 true。仍不是無 runtime 新機安裝證據。

`.artifacts/nativeapp/electron-change-delivery/evidence.json` complete=true、passed=true、**32 步驟通過**、shell_unchanged=true；四種分析包含新增變化拆解，在 iframe 保存、Host 重載後套用、執行、工作報表四格式下載、固定發布及發布 JSON 皆通過，並驗證關閉取消／確認及程序／埠回收。`download-verification.json` 確認四種分析的保存設定、完整資料列及版本在工作／發布 JSON 一致；變化拆解 CSV／Excel 五群數值與 JSON 相同，PDF **35 頁**包含全部分析 ID、變化拆解群組與 v6，發布畫面已檢視。

這是外部 Electron **來源殼**、手動配對與測試指定下載路徑的驗證。正式發布 Runtime、新機、自動配對／Host 身分、OS 另存對話框與升級回滾仍待驗證，完整產品未完成。下方 v5 及更早紀錄保留為歷史。

最新接入包為 `9b5ef223…`（SPC、共同性、跨表交付，`web-query-v5`）：`.artifacts/nativeapp/package-crossfact-delivery/ai4bi-web-0.1.0.napkg.zip`，**195 檔、168,507,214 bytes**，SHA-256 `e831dc6ab9282c1cbc12fb31c0cf9fe3d5a41c1c0dc3e939301c51c1c09f9366`。本輪重新核對發布 Kit 的 87 個成員與既有解壓目錄逐檔相同，原 zip SHA-256 仍為 `6c08dd026190fc45aa6eb93f273376439a6d57bdae33f8ac853b68a07a63a554`。Kit validate／pack 與接入包內容核對通過，舊包保留。

`.artifacts/nativeapp/host-crossfact-delivery/evidence.json` complete=true、provisioned_from_archive=true：由指定相容 CPython 及包內 wheelhouse／lock 在新 Store 建立獨立環境（98.73 秒），prepare／resolve／Host API launch 通過，ready build 與套件相同。停止 5.20 秒，實際 launcher_exited=true、endpoint_closed=true。

`.artifacts/nativeapp/electron-crossfact-delivery/evidence.json` complete=true、passed=true、**28 steps**，5 份外部殼來源雜湊前後一致。實測 iframe 配對、SPC／共同性／加權跨表設定保存、Host 重載後套用與計算、四格式下載、固定發布與發布 JSON、關閉取消／確認及實際程序退出／埠關閉。跨表為 600 列來源、20 組配對；SPC 600 列／12 實體；共同性 100 群體／11 目標。`download-verification.json` 核對 JSON、CSV、Excel 的完整資料表與發布 JSON 相同，PDF **29 頁**保留跨表數值、三種分析 ID、實體及資料版本；跨表發布摘要截圖已檢視。driver 副本保留於同目錄。

本輪使用 Electron **來源殼**及手動配對測試；will-download 的存檔位置由測試指定，未操作 OS 另存對話框。正式發布 Runtime／新機、自動配對與 Host 身分綁定、升級回滾仍是獨立待辦，不能因本輪通過而標示全產品完成。下方 43275411 與更早版本均為歷史證據。

目前接入包為 `43275411…`（共同性發布／四格式匯出、`web-query-v4`）：`.artifacts/nativeapp/package-commonality-delivery/ai4bi-web-0.1.0.napkg.zip`，195 檔，SHA-256 `3e710112f9e3f2edcd293c51a58416d6f7462460c6f97f27e55f66872286df21`，Kit validate／pack 與完整內容核對通過。發布 Kit ZIP SHA-256 `6c08dd026190fc45aa6eb93f273376439a6d57bdae33f8ac853b68a07a63a554`；本輪重新核對 87 個成員與既有解壓目錄完全相同。

`.artifacts/nativeapp/host-commonality-delivery/evidence.json` complete=true、provisioned_from_archive=true：全新 Store 從封存檔建立環境 119.24 秒，Host API launch 1.81 秒、stop 5.28 秒；ready build 相符，實際 launcher 退出與連接埠關閉。仍使用指定的既有相容 CPython，沒有據此宣稱新機 Runtime 交付完成。下方 b5 與更早紀錄為歷史證據。

`.artifacts/nativeapp/electron-commonality-delivery/evidence.json` complete／passed=true、24 項流程通過，包含 SPC／共同性保存、Host 重載後重開、重新計算、四格式原生下載、固定發布重播與發布 JSON 下載、關閉取消／確認及程序／埠停止。5 個被監測的平台來源檔案未變。download-verification.json 另外核對實際下載：SPC 600 列／12 實體，共同性母體 100／目標 11／11 實體；JSON、CSV、Excel 的所有實體列、完整設定與資料版本相符，發布 JSON 保持相同分析，PDF 18 頁含分析 ID、數值與 v4。已檢視共同性發布截圖。Excel 20,544 bytes、CSV ZIP 9,834 bytes、PDF 85,618 bytes、工作 JSON 37,055 bytes、發布 JSON 37,051 bytes。

本輪使用 Electron **來源殼**及自動指定下載路徑（will-download／setSavePath），尚未驗正式發布 Runtime、新機安裝、自動配對、Host 身分綁定、原生存檔對話框或升級／回退。既有 Kit Host receipt 的「No Tauri WebView」為工具歷史措辭；平台 D27 正式殼為 Electron，該 Host receipt 不代表任何殼的驗收，殼內證據以本段獨立紀錄為準。

前版接入包為 `b5dd13a3…`（SPC 發布／匯出、web-query-v3）：`.artifacts/nativeapp/package-spc-delivery/ai4bi-web-0.1.0.napkg.zip`，195 檔、168,486,268 bytes，SHA-256 `2760e91d31ec54ed4eae19048277a800bb1ab39590d2608069eab1cac4d961d1`。本輪使用發布版 Integration Kit 解壓於 `.artifacts/nativeapp/kit-spc-delivery`；原封存檔 87 項、SHA-256 `6c08dd026190fc45aa6eb93f273376439a6d57bdae33f8ac853b68a07a63a554`，來源 receipt 另存 kit-spc-delivery-receipt.json。

`.artifacts/nativeapp/host-spc-delivery/evidence.json` complete=true、provisioned_from_archive=true：由指定 CPython 基礎執行檔，透過公開 Kit 從封存檔在全新 Store 建立獨立環境（97.95 秒），不是接用已安裝 App venv。prepare／resolve／launch／ready build 核對通過；同一持續 Host API 停止後 registry 清空，launcher_exited=true、endpoint_closed=true。

最新桌面證據 `.artifacts/nativeapp/electron-spc-transport/evidence.json` complete=true、passed=true、20 steps，runner exit 0；實際 Electron iframe 配對、五圖查詢、SPC 保存、Host 重載後重開／套用／掃描、四格式下載、發布後重播及發布 JSON 下載、關閉取消／確認及實際退出均通過。所核對的五份殼來源檔前後雜湊相同。工作／發布 SPC 均為 600 列／12 實體，設定、數值、資料版本相同；CSV、Excel、PDF／JSON 讀回及檔案雜湊在 download-verification.json，PDF 12 頁。

限制：使用外部 Electron **來源殼**，不宣稱正式發布的 Electron Runtime 或另一台新機已驗；手動配對由測試輸入啟動碼，不是自動 bootstrap／Host 身分綁定。真實 Electron will-download 事件由測試 setSavePath 指定目的地，native_save_dialog_exercised=false，未操作 OS 另存對話框。升級／回滾與完整 P02／P06 仍待完成。以下 ef4e0b16 與其他版本為歷史證據。

前版已驗證安裝包 ef4e0b16（2026-09-06）已將工作／發布報表匯出改為認證 fetch 後下載 blob。34 項前端測試、建置、完整來源瀏覽器流程、專案外離線安裝與指定 Electron 來源殼流程已通過。最新接入包 `.artifacts/nativeapp/package-authenticated-download/ai4bi-web-0.1.0.napkg.zip` 為 195 檔，SHA-256 `ea0af1f3f5d5c33b3c317e1c83a527934f9039c98698d3a35123f82415549c30`；公開 Kit 與內容核對成立。Host 驗證接用本輪已驗證的安裝環境，provisioned_from_archive=false，從封存檔另建環境的最近證據仍為下方 1363c750。

`.artifacts/nativeapp/electron-download-lifecycle/` 已確認 passed=true／exit 0／shell_unchanged=true：配對、五图查詢、唯一工作區／圖表編輯保存、重載後重開、四格式下載、「關閉應用」取消及確認通過；launcher PID 36684 退出、51762 埠關閉。Excel 8,515 bytes、CSV ZIP 5,315 bytes、PDF 28,324 bytes、JSON 27,107 bytes，均由 Electron 原生 will-download 收到實際 blob 內容；自動設定的測試存檔路徑不是原生存檔對話框操作驗收。content-validation.json 另讀回四檔，確認保存標題、KPI 600、web-query-v2、PDF 五頁與 CSV ZIP CRC。完整 Host 自動配對／身分、發布殼、App 協作式關閉及完整桌面範圍仍未完成。

測試工具修正歷史：electron-authenticated-download、electron-download-stop-verification 與 electron-workspace-identity 已完成四格式下載，但關閉狀態斷言在預設 5 秒逾時；平台 stop.grace_s 即 5 秒，實際回應約 5.3 秒，不能據此判定 App 未退出。現依已驗證 launch 設定加 5 秒 UI 餘裕（本輪 10 秒）等候狀態，另以程序存活與全新 TCP 連線驗停止，沒有放寬查詢或完整瀏覽器時限。electron-stop-diagnostics 另捕捉測試過早取得舊工作區 ID 的競態；現從本輪 create 回應取 ID，等待對話框關閉與選取名稱／ID 相符後再操作。上述失敗保留，不改寫為成功。

1363c750 接入包 `.artifacts/nativeapp/package-partitioned-session/ai4bi-web-0.1.0.napkg.zip`：195 檔、SHA-256 `0d7a7472edcd223c07ab156b76fd3011366dc94afa11a88ff7b2e50abd4ac2ad`，公開 Kit 與完整內容驗證通過。`.artifacts/nativeapp/host-partitioned-session/evidence.json` complete／provisioned_from_archive 皆 true，環境建立 97.64 秒、launch 1.81 秒、stop 5.20 秒，launcher 退出與埠關閉均確認。

`.artifacts/nativeapp/electron-partitioned-product/` 是未攔截回應的真實來源 Electron 殼測試：配對、五圖查詢、編輯保存、殼內重載及依 ID 重新開啟本輪唯一工作區／圖表均通過；cookie metadata 確認 HttpOnly／Secure／SameSite=None、partitionKey=file://。後續 report.xlsx 的原生 will-download 事件 state=interrupted，整輪 passed=false／exit 1，關閉取消／停止未執行。這將舊版重載 401 修復與未完成下載分開記錄；新的 ef4e0b16 下載修正尚待桌面驗收。工具只自動選擇測試下載位置，不替換輸出內容或修改平台來源。

交付進度更新（2026-09-06）：46dffae6 新版已通過專案外離線安裝、發布契約重啟與安裝版六項瀏覽器案例（2.2 分鐘，完整報表 1.4 分鐘）。新包 `.artifacts/nativeapp/package-execution-contract/ai4bi-web-0.1.0.napkg.zip` 已通過公開 Kit validate／pack、195 檔完整集合與內容雜湊核對，SHA-256 `7d986b0695927d30e68b78f302b58c42c5e62d3cd1488590ede560761b576408`；綁定 release receipt SHA-256 `d3866c623f1b5fda0c399bbb430877db48ad6e4a1d6657713cb0264b5132cd50`。`.artifacts/nativeapp/host-execution-contract/evidence.json` 已通過，complete／provisioned_from_archive 皆 true：從封存檔建立全新 Store 環境 101.19 秒，持續 Host API launch 2.45 秒、stop 5.22 秒，ready 核對同版 build，實際 launcher 退出與監聽埠關閉。這次使用既有相容 CPython 3.11 和發布 Kit，未驗基礎 runtime 新機交付、WebView、安全 bootstrap、Host 啟動身分綁定或協作式關閉。此狀態取代下方同版較早敘述。

目前來源為 Web 執行契約版 `46dffae6…`，完整 API 483 通過，新 wheel 已完成，獨立離線驗證中。下方 e9fe06de 是目前已驗證離線安裝與持續 Host API 啟停的包，並不包含日期分組或執行契約新功能。新版回歸與交付進度見 P00／app-release。

be016e34 的來源完整瀏覽器流程本輪通過（2.8 分鐘）；目前 NativeApp 包仍為 e9fe06de，日期分組尚未納入安裝包。發布執行契約、真正 WebView、安全 bootstrap 與完整離線交付仍待完成。

目前來源已更新至日期分組 `be016e34…`，尚未建立新包。現有 e9fe06de 包透過修正的持續 Host API 驗證，證據 `.artifacts/nativeapp/host-worker-read-lock-api/evidence.json`：launch 4.44 秒、stop 5.41 秒，確認實際 launcher PID 退出與埠關閉，complete=true；使用既有安裝環境，provisioned_from_archive=false。獨立 CLI 的停止紀錄無效，詳見下段更正。日期功能與完整流程進度以 P00 為準，不能把 e9fe06de 的交付證據套用至新來源。

停止驗證更正（2026-09-06）：host-worker-read-lock 的獨立環境建立與 ready build 核對成立，但原工具用不同 CLI 程序呼叫 launch／stop，Kit 的記憶體啟動登錄未共享；stop 回報成功後 PID 10184／35908 與 57441 埠仍存在。已將該 evidence.complete 改為 false，保留 cli-evidence.json 原紀錄及 stop_audit，並核對本輪命令路徑後清理程序與監聽埠。先前相同工具的停止成功紀錄也不足以證明實際退出。須改用同一持續 Host API、檢查真實程序與埠，再重新驗證；不得引用清空 running 清單宣稱停止通過。

最新來源（2026-09-06，`e9fe06de…`）：Windows assignment 讀取拒絕已加入 1 秒有限重試，45 項相關回歸與獨立離線安裝／HTTP 查詢／匯出／重啟驗證通過。安裝版瀏覽器 3 通過／1 失敗：完整流程已走過原讀檔失敗位置，但在發布報表時達 180 秒總時限；98 個工作沒有 failed。新版 195 檔 NativeApp 包已通過 Kit validate／pack 與雜湊核對，從封存檔建立新 Store 環境及啟停驗證正在執行。完整互動、真實 WebView 與全產品交付尚未完成，詳見 P00 與 app-release。

新版接入包（2026-09-06）：`.artifacts/nativeapp/package-worker-read-lock/ai4bi-web-0.1.0.napkg.zip` 已通過發布 Kit validate／pack 及完整集合與雜湊驗證，195 檔，SHA-256 `84f2b2fc52889118c29bd2b8f7f37e459140b6f5f9ab1f7c0732d955fb48e9d9`，build `e9fe06de4179508631907a9901d1730115c9be647710e0701e1e12d28ce5abec`。證據 `.artifacts/nativeapp/package-worker-read-lock/evidence.json`，綁定本版獨立離線安裝 receipt。`host-worker-read-lock/` 正透過既有公開 Kit 與 CPython 3.11 從封存檔建立全新 Store 環境，再執行 prepare／resolve／launch／ready／stop；結果待定。這不包含真實 WebView、安全 bootstrap、更新／回退或基礎 runtime 新機交付。前版 package-sparkline 與更早紀錄保留作歷史證據。

來源更新（2026-09-06，`666431ce…`）：KPI 逐日趨勢小圖已接入設定、受治理日聚合、SVG／原值表、PDF 趨勢頁與 Excel 序列；9 項 API／匯出專項、31 項前端測試（含 4 項小圖邊界呈現）及 TypeScript／正式建置通過；瀏覽器專項通過（18.0 秒），PDF 已讀回核對。主數字仍由原純量查詢計算。完整 API 回歸 459 通過（369.70 秒，一項刻意退化 OLS warning）；新版已通過獨立離線安裝、HTTP／查詢／匯出／重啟驗證，195 檔 NativeApp 接入包亦已通過封装完整性驗證，安裝版瀏覽器 3 通過／1 工作失敗，後續修正見最新紀錄，詳見 P00「KPI 逐日趨勢小圖」。

來源增補（2026-09-06，`d633ea9a…`）：期間比較已改為保留大整數與 Decimal 的原查詢表格；兩項轉接層回歸先重現 null 遺失，修正後報表／匯出回歸 253 通過（137.90 秒，一項刻意退化 OLS warning）。下方 448 項完整 API 與瀏覽器 2 通過／1 逾時屬前一版 052f8f04。新版尚未離線封裝，詳見 P00「期間比較保留精確原值」。

來源更新 `052f8f04…`（2026-09-06）：worker 致命錯誤診斷及 Windows assignment 刪檔有限重試已建置，43 項 worker／任務接受與 448 項完整 API 回歸通過。同版瀏覽器 2 通過／1 完整流程達 180 秒總時限，尚未重新建立 NativeApp 接入包；下方既有包與 Kit 證據不涵蓋本次來源，也不代表真實 WebView 驗收。詳見 P00「Worker 致命錯誤診斷與檔案鎖」。

最新建置 `bd4feb55…`（2026-09-06）已加入 KPI 固定天數／日曆期間比較、前期值及絕對／百分比差異。查詢保留 RLS 與作用範圍，提供日期條件保留／取代策略，混合 OR 明確拒絕；UTC 日界、閏日、缺期與零分母均有專項。23 項隔離後相關測試、27 項既有前端呈現回歸與正式建置通過；同版兩個 KPI 瀏覽器案例重跑通過（21.4／18.7 秒），PDF／Excel 內容已核對。完整 API 回歸 443 通過（663.56 秒，一項刻意退化 OLS 測試 warning），詳細結果見 P00；此耗時不是效能 gate 通過。首輪瀏覽器曾遇到 worker exit 1，隔離重播與同版重跑成功仍不足以定因，穩定性問題維持待辦。sparkline、其他日期／分析／圖表主題、真正 NativeApp、安全 bootstrap、完整效能／恢復及新版離線交付仍未完成；該輪最近已驗證安裝包為 a2341d，後續版本見本文最新紀錄。

前次來源已建置為 `e917d03d…`，包含預載備援、閒置計時修正、CLI 提前拒絕與分析依賴延後載入。聚焦測試 9 通過／1 項 CLI 逾時，該 CLI 單獨重跑通過；瀏覽器 1 通過／1 項完整流程逾時，完整驗收未完成。尚未重新封裝或交付，以下 a2341d 證據只對應既有安裝包；詳見 [P00 最新紀錄](../../docs/validation/p00-baseline.md)。

目前已完成發布版 Kit 的 manifest 驗證、打包、從包內 wheel 建立新環境、HTTP loader 啟動與停止。**仍不是可直接交付的完整 NativeApp 整合**：尚未完成 Tauri WebView、通用 session bootstrap、host 預期 build／instance 驗證與包含基礎 runtime 的新機自動安裝。

最新已驗證接入包為 `a2341d2d380fbb75af66023e5453e4fbf490900329b8b97d3d496abe7cecfead`，已包含待命 worker、交接檔清理重試、查詢驗證重用、單圖更新與 Plotly 縮放保留。封存檔在 `.artifacts/nativeapp/package-interaction-cleanup/ai4bi-web-0.1.0.napkg.zip`，181 檔完整集合與 SHA-256 核對通過，zip SHA-256 為 `2bdd4b257b018c8c90955ea4ff648c959c50df8042b3c6c27d5d47925da25870`。

`.artifacts/nativeapp/host-interaction-cleanup/evidence.json` complete=true、provisioned_from_archive=true。透過發布 Kit，從包內 wheel 與雜湊鎖建立全新 Store 環境；import-package 17.22 秒、create-environment 298.55 秒、prepare 2.38 秒、resolve 0.53 秒、launch 23.52 秒、stop 1.17 秒、running 0.97 秒，全部 exit 0。解析到的 Python 確實位於新 Store，HTTP `/ready` build 與包一致，資料庫位於該 Store 的 data 目錄，停止後 instances 為空。

本次仍使用機器既有的相容 CPython 3.11 與發布 Kit，因此不是無基礎 runtime 的全新機安裝。尚未完成 Tauri WebView、host 身分綁定、安全 session bootstrap、更新／回復及完整產品交付。下方 022786 與更早紀錄保留作版本追溯；不可與本次數字混用。

## 維護與產物

此目錄只維護 `app.json`、`launch.json`、`sheet.json` 與 `launcher.py`。App 的 Python／React 內容來自已通過獨立安裝驗證的 wheel，不複製核心來源或平台私有模組。

`scripts/build_nativeapp_package.py` 明確收集這些來源、已驗證的 66 個 wheel、雜湊鎖與 notice 證據。它以發布版 Integration Kit 的公開 CLI 驗證及打包，檢查 lock／wheel／版本一致，最後將封存檔、Kit 清單與全部輸入檔案作完整集合及內容雜湊核對。即使 Kit 清單內部一致，遺漏 wheel 或 notice 也會拒絕。Kit 必須在本專案之外取得，解開到任意明確指定的位置；不需 clone 平台。

目前 Kit 的 public `pack` 只複製固定允許路徑，根目錄 `launcher.py` 會被略過。因此產物將入口放在 `app/scripts/launcher.py`；維護來源仍只有此目錄的一份 launcher，不採名為 `main.py` 的特殊入口。

## 建立接入包

```powershell
& .venv/Scripts/python.exe scripts/build_nativeapp_package.py `
  --kit C:/Tools/NativeApp-Integration-Kit `
  --release .artifacts/release/offline-clean-build `
  --output .artifacts/nativeapp/build
```

Kit 路徑請換成實際位置；output 必須尚未存在，release 必須是 `validate_app_release.py` 已完整驗證且成功收集 `third-party-notices/` 的產物。Builder 核對 inventory 與 release receipt／build／Python 套件版本和 wheel 雜湊的綁定，再核對每份 notice 的路徑、大小及雜湊；缺少、修改、路徑穿越或重複引用都拒絕。授權缺失記錄保留，不因封裝成功而視為已補齊。

輸出包含 `application/`、`integration/`、`ai4bi-web-0.1.0.napkg.zip` 與驗證證據。所有相依 wheel 都在接入包的 `integration/runtime/wheelhouse/`；鎖檔為 `integration/runtime/requirements.lock`。Kit 的 package metadata 雖帶 `offline=true`，仍須另行準備及綁定 managed environment，不能把這個欄位當作自動安裝已完成。

`integration/runtime/third-party-notices/` 保存 inventory、說明與逐位元組原樣的 notice 副本；`integration/runtime/release-evidence.json` 保存對应的安裝驗證紀錄。這些生成檔只存於 `.artifacts/` 的封裝產物，不建立第二份人工維護的第三方文字。驗證紀錄含測試機環境與安裝路徑，屬本機驗證來源資訊。

## 目前已驗證的啟動流程

先依 [App 交付驗證](../../docs/validation/app-release.md) 安裝乾淨 Python 環境，將下列變數改成實際位置：

```powershell
$kitPython = 'C:/Tools/NativeApp-Integration-Kit/python-runtime/python.exe'
$appPython = 'C:/BI/runtime/Scripts/python.exe'
$store = 'C:/BI/NativeApp-Store'
$bundle = 'C:/BI/AI4BI-package'
$record = & $kitPython -m nativeapp_platform --store $store register-environment `
  --python $appPython --lock-file "$bundle/integration/runtime/requirements.lock" --attach | ConvertFrom-Json
& $kitPython -m nativeapp_platform --store $store prepare `
  --integration-root "$bundle/integration" --source-root "$bundle/application" --environment-id $record.environment_id
& $kitPython -m nativeapp_platform --store $store launch --app-id ai4bi-web
& $kitPython -m nativeapp_platform --store $store stop --app-id ai4bi-web
```

`prepare` 使用 builder 的 application／integration 目錄；不是直接把 zip 當成已綁定環境的完整安裝器。`--attach` 指向已驗證的獨立 App 環境，不修改其他 App 共用環境。

HTTP loader 提供 `--host`、`--port`、`--root`。launcher 僅轉接至已安裝的 `ai4bi_web_api` CLI；資料根必須由公開 `managed_env` 的 `{data_dir}/workspace` 傳入，缺失、非絕對路徑或位於 App 安裝目錄時拒絕啟動。原始碼位置不作為使用者資料位置。

## App 端的啟動身分契約

目前來源的 launcher 可轉交 `AI4BI_INSTANCE_ID` 與 `AI4BI_EXPECTED_BUILD_ID`，分別對應 App CLI 的 `--instance-id`／`--expected-build-id`。instance 必須是每次啟動新產生的 1 至 100 字元英數、底線或連字號識別碼；build 必須是發布證據中的 64 字元小寫 SHA-256。兩者都不是授權憑證，不能代替 session 配對。

CLI 先獨占綁定指定 loopback port，再檢查預期建置，之後才啟動資料庫生命週期。綁定失敗或建置不符時，以非零狀態退出，不建立資料根、不輸出配對碼。Windows 使用 `SO_EXCLUSIVEADDRUSE`，交給 Uvicorn 的是同一個已綁定 socket，不先釋放再重新綁定。`localhost` 明確對應 `127.0.0.1`；IPv6 使用 `::1`。

Host 可請求 `/ready?expected_instance_id=<本次識別碼>&expected_build_id=<預期雜湊>`；不符時回 409／`READY_IDENTITY_MISMATCH`，成功仍須核對 JSON 中的 `app_id`、`instance_id` 與 `build_id`，並確認自己啟動的程序尚存活。請求沒有預期值時保留既有就緒行為。若啟動時指定的建置後來被另一個有效建置取代，普通 `/ready` 也回 `BUILD_ID_MISMATCH`；完整性損壞仍回 503。

目前維護的 launch profile 沒有硬編碼 instance，也未宣稱 Kit 會展開不存在的每次啟動變數。Kit 尚須提供新 instance、動態探測路徑及回應比對；僅 App 端拒絕錯誤請求不能防止 loader 誤認另一個完全不檢查 query 的服務。新版離線 wheel 與下述接入包已包含 App 端契約，仍不能宣稱 host 已注入或驗證每次啟動身分。

## 驗證紀錄

2026-09-06 相容性補正版 build `02278626f9259cccb54929e1487ead56d64493e4f0671ca28d1f4f339144ec1a` 已更新至 `.artifacts/nativeapp/package-compatible-dataframes/`。來源是同 build 已通過乾淨離線安裝與 HTTP probe 的 release；Kit validate／pack 及 181 檔完整集合核對通過，ZIP SHA-256 為 `b472293a490f6d736bc779ee0b0f4ab5f43119891cf0a16108b7a6e8d36a9109`。

`.artifacts/nativeapp/host-compatible-dataframes/` 的 register-environment 0.36 秒、prepare 0.45 秒、resolve 0.24 秒、launch 2.76 秒、stop 0.23 秒與 running 0.20 秒全部成功；ready 確認相同 build、資料庫位於隔離 Store，停止後無執行中實例。本次使用新 release 的已安裝環境（`provisioned_from_archive=false`），從包建立環境的先前成功紀錄仍只適用其記錄版本。沒有修改平台，也沒有據此勾選真實 WebView、host 身分綁定、安全 session bootstrap 或完整 P06。

2026-09-05 使用本機發布的 `NativeApp-Integration-Kit.zip`，Kit CLI 回報版本 0.1.0。未修改 NativeApp 原始碼或其使用者 Store。

- 初次 Kit 驗證／打包返回成功，但檢查發現入口遭允許清單略過，舊 `.artifacts/nativeapp/package-check/` 僅保留失敗診斷，不可使用。
- 修正入口後 71 個檔案完整入包，Kit prepare 確認複製 1 個 App 來源檔。
- `.artifacts/nativeapp/host-entry-check/` 為獨立測試 Store；Kit 實際 launch 成功，`/ready` 回 `ai4bi-web` 與 build ID `6669889c192d1e348c9cec7214b4f1dfb3be0b5351c6e2701f0cda255cd9d775`。
- 資料庫實際位於 Store 的 `data/ai4bi-web/workspace/metadata.sqlite`，不在 App 程式目錄。
- Kit stop 回成功，running 清單為空；結果在 `.artifacts/nativeapp/launch-result.json`、`ready-result.json`、`stop-result.json`。
- 補上 lock 一致性檢查後再次打包通過，產物在 `.artifacts/nativeapp/package-lock-check/`。包 SHA-256：`47d488476140ab11012d29fda09ef00dcfb8c1a91f9f4b57771c3691513054df`。

## 新版封裝與 HTTP loader 驗證（2026-09-06）

`.artifacts/nativeapp/package-feature-release/` 已通過 Kit validate／pack 與完整檔案集合核對，共 181 個檔案，包括 66 wheel、107 notice、副本 inventory／README、release receipt、鎖檔與四個入口設定來源。包 SHA-256 `a5c5bf9bf51b010a3649310a730133870f2cf0c4641eabdb5568455409ccf48d`；build ID `aeb886da3f0d3561881a3981ae3480db48ebb8ecc792ca798c3bd54860d48531`。13 項新增 notice／封裝完整性測試連同既有工具测试共 33 項通過（0.68 秒）。

新增維護工具 `scripts/validate_nativeapp_host.py`，透過公開 Kit CLI 在全新 Store 執行 register-environment、prepare、launch、HTTP `/ready`、stop 與 running。核對包／release 關聯、build ID、Store 資料庫位置與停止後清單，並用 finally 執行停止。可重跑命令：

```powershell
& .venv/Scripts/python.exe scripts/validate_nativeapp_host.py `
  --kit .artifacts/nativeapp/kit `
  --package .artifacts/nativeapp/package-feature-release `
  --release .artifacts/release/offline-clean-build `
  --output .artifacts/nativeapp/host-check-run
```

成功證據位於 `.artifacts/nativeapp/host-lifecycle-release/`；所有 CLI 返回成功，ready 回報本次 App build，資料庫在該 Store 的 `data/ai4bi-web/workspace/metadata.sqlite`，停止後 `instances=[]`。`host-feature-release/` 保留 Windows CP950 輸出解碼失敗；`host-utf8-release/` 保留將 `{"instances":[]}` 錯當非空 running 清單的驗證腳本失敗。均已執行 stop；修正後用新目錄完整重跑成功。

此工具以 `prepare` 綁定先前已驗證的 App 環境；不是單一 zip 匯入自動配置，不包含 WebView、自動配對、host 每次啟動身分或合作式停止驗收。核心、App、Streamlit 授權文字缺口仍保留。

## 從接入包建立新的離線環境

`validate_nativeapp_host.py` 可加上 `--provision-python C:/Python311/python.exe`，用相容的基礎 CPython 建立全新 Store 環境，不重用先前 App venv。其餘 `--kit`、`--package`、`--release` 為本次已核對的交付來源與證據，`--output` 仍必須是 `.artifacts/` 下新目錄。

工具先以公開 `import-package --no-activate` 匯入 zip，再將已核對的 zip 解開至該次輸出的 `archive-inputs/`，使用其中的鎖檔與 wheelhouse 呼叫 Kit `create-environment`。Kit 使用 `--no-index`；鎖檔列有每個套件的 SHA-256，pip 依雜湊模式驗證。環境必須是 `attached=false`、`complete=true`，Python 必須位於該次獨立 Store。然後 `prepare` 綁定、`resolve` 核對實際 interpreter，接續 launch／ready／stop／running 驗證。

這是交付驗收工具的一次指令流程，仍需要相容基礎 Python、發布版 Kit 與交付證據；不代表只靠一個 zip 即可在沒有 runtime 的新電腦完成產品安裝。沒有修改 Kit 私有模組、Store 格式或使用既有使用者 Store。

Kit 建環境會在 JSON 前輸出 pip 進度。工具分開保存原始 `.stdout.log`、`.stderr.log` 與解析後 `.json`；只接受最後完整 JSON 物件，若尾端還有錯誤文字便拒絕。含中文、pip 進度、無結果與尾端錯誤的測試已加入既有交付測試，共 38 項通過（0.68 秒）。

2026-09-06 實際證據在 `.artifacts/nativeapp/host-provision-release/`：匯入 2.34 秒、離線建環境 86.67 秒、prepare 0.89 秒、resolve 0.20 秒、launch 4.97 秒、stop 0.20 秒、running 0.19 秒，全部 exit 0。新環境回報 `attached=false`、`reused=false`、`install_strategy=venv-from-lock-offline`，CPython 3.11.9／AMD64，位於該次 Store 的 `environments/env_ade73fbbde26497c/venv`。App resolve 指向此 interpreter，停止後 `instances=[]`。

另使用新環境的 Python `-I` 執行 `pip check` 及既有 `probe_app_wheel.py`，兩者成功，結果記於 `provision-validation.json`。實測 KPI 600、OR 篩選 200、HAVING 留下 Etch、mock AI 提案、Excel／PDF／CSV 匯出與重啟保存。此 probe 拒絕讀取 Web 的 `services/`、`apps/` 和舊核心 checkout；因測試 Store 在 `.artifacts/`，沒有禁止整個 Web 根目錄讀取，不能混稱 checkout 外安裝測試。原始碼無關路徑的證據仍由先前獨立離線安裝提供。

本次執行期間將 CLI 日誌保存格式改為原始 stdout 與結構化 JSON 分開；已完成執行的原 stdout 保留至 `.stdout.log`，解析結果另存 `.json`。最終程式的既有 attach 模式再於 `host-cli-output-check/` 完整通過，用以核對日志輸出與 resolve 的回歸。建環境與 HTTP probe 不代表斷網 OS、字型完整性或真實 WebView 驗收。

## 尚待完成的最終接入契約

本輪完整回歸結果：`.artifacts/partitioned-session-api.xml`／`.log` **486 通過，206.86 秒**，僅刻意退化 OLS 警告。1363c750 wheel 已完成內容校驗，獨立離線安裝正在 `.artifacts/release/offline-partitioned-session/` 驗證，尚未通過新安裝版桌面流程。桌面工具已改用 Electron `will-download` 事件收集真正下載，僅自動指定測試 Save As 位置；沒有攔截 artifact 回應或替換檔案內容。此工具調整尚待下一輪驗證，不能先歸因原下載逾時。後續每輪也保存當輪 driver 原始碼，避免只留下 hash 卻無法重播。

Session 修正（2026-09-06，來源 build `1363c750e79c237bd781d552c9bb0c35d62885362e17b151c83b6cc808a0fae4`）：App CLI 新增 strict／partitioned cookie 模式，NativeApp launcher 固定選後者，設定 HttpOnly、Secure、SameSite=None、Partitioned、host-only 與 12 小時期限。API 來源精確比對、寫入 header、一次性配對與重啟失效未放寬。Python 3.11 以固定 Partitioned 後綴輸出，沒有建立新的 session 模組或 token 保存檔。四項相关測試通過（1.55 秒），正式建置通過（Vite 2.04 秒）；完整 API 回歸中，尚未封裝／安裝驗證本修正。自動 bootstrap、Host 身分綁定與祕密不落啟動日誌仍為獨立缺口。

真實診斷 `.artifacts/nativeapp/electron-frame-cookie-diagnostics/` 重現重載失敗，iframe CDP blocked_cookie_reasons 明確為 SameSiteStrict，配對後 cookie 清單為空。`.artifacts/nativeapp/electron-partitioned-cookie-spike/` 是測試攔截配對回應、改寫 cookie 屬性的可行性實驗：有 HttpOnly／Secure／SameSite=None cookie、保存後殼內重載可用，但後續 Excel download 等候逾時，整輪 passed=false／exit 1。它沒有修改安裝 App，不能算產品實作成功；維護工具已移除攔截功能，後續產品驗收拒絕 cookie-experiment 選項。分區模式參考 [Chromium CHIPS](https://privacysandbox.google.com/cookies/chips)，最終仍以實機結果為準。

平台方向更新（2026-09-06）：`nativeApp_v2/docs/product/06-decisions-and-open-questions.md` 的 D27 已指定 Electron 為正式殼，Tauri 為選配第二 Host，兩者共用 renderer 與平台 API，接入包不分支。此處之後的 Tauri 說明屬原先觀察；正式交付以 Electron 發布殼驗收為主。

新增 `scripts/validate_nativeapp_desktop.cjs`，歸屬既有跨專案驗證工具目錄。透過發布 Kit 公開 API、既有測試 Store 的獨立安裝環境，以及未修改的外部 Electron 來源殼執行；測試 profile、截圖與結果放在新的 `.artifacts/nativeapp/` 子目錄。`.artifacts/nativeapp/electron-pairing/evidence.json` 已通過真實 Sheet 選取、iframe 載入、build 46dffae6 核對、手動配對 UI、建立工作區與五圖查詢（KPI 600），shell_unchanged=true，runner exit 0；桌面截圖已檢視。此為來源殼與安裝 App 的相容性證據，不是發布殼、自動 bootstrap 或完整 P02／P06 驗收。

工具初輪未點選 Sheet，第二輪無法以 UTF-8 讀取 Kit 子程序的 CP950 配對日誌；兩輪失敗分別保留於 electron-execution-contract／electron-sheet-selection，未修改產品來繞過。工具現在明確點選 AI4BI，僅在記憶體解碼測試配對碼，不保存請求標頭、回應 token 或 Playwright trace；失敗截圖前清空配對欄位。原 App／Kit 日誌仍會記錄配對碼，是待解決的正式接入缺口。

`.artifacts/nativeapp/electron-report-flow/` 擴充流程失敗（passed=false、runner exit 1）：真實配對、五圖查詢與兩次編輯／保存 commands HTTP 200 成立，但使用殼的重新載入按鈕後，GET `/api/v1/workspaces` 回傳 401 並顯示配對頁；failure.png 已檢視。Excel 下載、關閉取消及 UI 停止尚未執行。前端 api.ts 在記憶體保存 bearer，重載會清空；HTTP cookie 為 SameSite=Strict，而 Electron renderer 為 file 頂層，這是應優先驗證的 cookie 接續限制，不能把首次配對可用視為重載相容。後續需可驗來源／身分、短效且不落日誌的公開 Host session 重建契約；不以持久保存 bearer、URL token 或放寬跨來源保護繞過。

此輪測試結束已關閉測試 Electron 與 Host。後續工具另區分「編輯保存完成」步驟、拒絕把 HTTP 逾時當成埠已關閉，且只有確認測試 Store 原本無執行中 App 後才取得停止清理責任；這些工具補強尚未重新跑完整桌面案例。現有 App wheel、平台來源與發布 Kit 均未修改。

平台來源現況核對（2026-09-06，唯讀）：`C:/code/claude/nativeApp_v2/apps/desktop/renderer/host-bridge.js` 已有通用 NATIVEAPP_READY、NATIVEAPP_CLOSE_REQUEST／RESULT 與 pickFolder 請求；Host 會核對 iframe 的 event.source 及來源，關閉確認最多等候 300 秒。這是平台來源中的關閉／選夾能力，尚未驗證 AI4BI 在發布桌面殼的接入，也不提供 App 自動 session 配對或預期 build／instance 啟動核對。後續優先使用相符發布版的公開契約，仍須確認 App 對 Host 的來源信任與草稿保存；不把橋接存在當作 bootstrap 已完成。本輪未修改平台來源或 Kit。

2026-09-06 本機來源重查：最初提供的 `C:\code\claude\nativeApp\_v2` 不存在，目前平台來源為 `C:\code\claude\nativeApp_v2`。此路徑僅供本機開發定位，不是 App 或安裝包依賴。已閱讀該專案 AGENTS／README，未修改平台或發布 Kit。

平台目前 `python/nativeapp_platform/http_loader.py::start_http_ui` 先選取連接埠、啟動程序，再呼叫 `streamlit_loader.py::wait_http`。後者對回應狀態成功分支直接返回，不解析 ready JSON，也未在返回前再次核對子程序存活；`packages/protocol/launch_profile.schema.json` 的 readiness 只有 http_path／timeout_s／ready_file_env，尚無預期 build／instance 或安全配對欄位。因此 App 已有的身分拒絕能力仍未形成完整 host 驗證。

後續須以可供所有 HTTP App 使用的公開契約完成：每次啟動生成獨立 instance、以已驗證包決定 expected build、在開啟 WebView 前核對精確就緒回應與程序存活；錯誤服務、redirect、舊程序及重複 port 都必須有失敗案例。自動配對另需短效一次性交換、主機與 App 身分綁定、祕密不進 URL／日誌，以及 WebView 實際 cookie／下載／換 port 驗證。上述仍是待實作及驗收，不能以本機瀏覽器或 Kit HTTP probe 替代。

目前沿用 App 配對 UI，CLI 會輸出一次性配對碼；NativeApp 會保存程序輸出日誌。這尚不符合最終自動配對與祕密不落啟動日誌的接入目標，須補通用 bootstrap 契約並驗證後才能交付。不可改成 URL query token 或放寬跨來源限制來繞過問題。

Kit 的 HTTP wait 只檢查可用性，未核對預期的 build／instance；port 搶占、錯服務及過期程序的拒絕尚未通過。停止目前是強制終止程序樹，`grace_s` 不代表已驗合作 shutdown。真實 Tauri iframe 的 Origin／cookie／CSRF／下載、Sheet 切換、崩潰恢復、單檔匯入環境準備與 NativeApp 更新回退仍依主實作計畫驗收。
