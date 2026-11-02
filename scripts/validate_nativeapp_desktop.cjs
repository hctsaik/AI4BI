/* Exercise the real external Electron shell against an installed App and public Kit API.
 * Source-shell evidence only: this does not certify a released desktop distribution.
 */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const net = require('node:net');
const {spawn} = require('node:child_process');
const {_electron, expect} = require('@playwright/test');
const root = path.resolve(__dirname, '..');
const args = Object.fromEntries(process.argv.slice(2).reduce((pairs, value, i, all) => {
  if (i % 2 === 0) pairs.push([value.replace(/^--/, ''), all[i + 1]]);
  return pairs;
}, []));
const hash = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const inside = (parent, child) => {const rel = path.relative(parent, child); return rel && !rel.startsWith('..') && !path.isAbsolute(rel);};
const endpointClosed = port => new Promise((resolve,reject) => {
  const socket=net.createConnection({host:'127.0.0.1',port:Number(port)});
  socket.once('connect',()=>{socket.destroy();resolve(false);});
  socket.once('error',error=>{socket.destroy();error.code==='ECONNREFUSED'?resolve(true):reject(error);});
  socket.setTimeout(1000,()=>{socket.destroy();reject(new Error('Endpoint observation timed out'));});
});

async function main() {
  for (const name of ['kit', 'desktop', 'host-validation', 'output']) {
    if (!args[name]) throw new Error(`Required --${name}`);
    args[name] = path.resolve(args[name]);
  }
  const output = args.output;
  const runId = crypto.randomUUID();
  const workspaceTitle = 'Electron validation ' + runId;
  const visualTitle = 'Saved yield ' + runId;
  if (!inside(path.join(root, '.artifacts'), output) || fs.existsSync(output)) throw new Error('Output must be new and inside .artifacts');
  const validated = args['host-validation'];
  if (!inside(path.join(root, '.artifacts'), validated)) throw new Error('Only test-owned Store is allowed');
  const receipt = JSON.parse(fs.readFileSync(path.join(validated, 'evidence.json')));
  if (receipt.complete !== true || typeof receipt.provisioned_from_archive !== 'boolean') throw new Error('Require validated Host installation');
  const store = path.join(validated, 'store');
  const resolved = JSON.parse(fs.readFileSync(path.join(validated, 'resolve.json')));
  if (!/^web-query-v\d+$/.test(receipt.execution_contract || '')) {
    throw new Error('Host receipt lacks its validated release execution contract; rerun Host validation');
  }
  const expectedExecutionContract = receipt.execution_contract;
  const grace = resolved.launch?.stop?.grace_s ?? 5;
  if (!Number.isFinite(grace) || grace < 0 || grace > 60) throw new Error('Invalid stop grace');
  const stopWaitMs = (grace+5)*1000;
  const kitPython = path.join(args.kit, 'python-runtime', 'python.exe');
  const executablePath = path.join(args.desktop, 'node_modules', 'electron', 'dist', 'electron.exe');
  for (const file of [kitPython, executablePath, path.join(args.desktop, 'main.js')]) {
    if (!fs.statSync(file).isFile()) throw new Error('Missing runtime');
  }
  fs.mkdirSync(output, {recursive: true});
  fs.copyFileSync(__filename, path.join(output, 'driver.cjs'));
  const shellFiles = ['main.js', 'preload.js', 'renderer/app.js', 'renderer/host-bridge.js', 'renderer/index.html'];
  const shellHashes = Object.fromEntries(shellFiles.map(name => [name, hash(path.join(args.desktop, name))]));
  const evidence = {complete: false, passed: false, build_id: receipt.build_id,
    stop_ui_timeout_ms: stopWaitMs,
    environment_provisioned_from_archive: receipt.provisioned_from_archive,
    host_receipt_sha256: hash(path.join(validated, 'evidence.json')), shell_hashes: shellHashes,
    electron_sha256: hash(executablePath), driver_sha256: hash(__filename), steps: [],
    limitations: ['External source Electron shell; not a released desktop package.',
      'Manual pairing UI driven with a test-owned launch code; not secure automatic bootstrap.',
      'Download destination assigned with setSavePath; native Save As dialog UI is not exercised.',
      'Reuses a previously validated test Store and its installed environment.']};
  if (args['cookie-experiment']) throw new Error('Cookie interception experiments are not allowed in product validation');
  const save = () => fs.writeFileSync(path.join(output, 'evidence.json'), JSON.stringify(evidence, null, 2));
  save();
  const env = {...process.env, PYTHONIOENCODING: 'utf-8'};
  for (const name of ['PYTHONPATH', 'PYTHONHOME', 'ELECTRON_RUN_AS_NODE', 'ANTHROPIC_API_KEY', 'OPENAI_API_KEY']) delete env[name];
  const host = spawn(kitPython, ['-m', 'nativeapp_platform', '--store', store, 'serve', '--host', '127.0.0.1', '--port', '0'],
    {cwd: args.kit, env, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe']});
  let announcement = '', apiUrl = '', desktop, page, launch, ownsApp = false;
  host.stdout.on('data', chunk => {announcement += chunk.toString();});
  // Platform stderr is intentionally not persisted: no raw session or request traces.
  host.stderr.resume();
  const request = async (route, body) => {
    const response = await fetch(apiUrl + route, body === undefined ? {} : {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body), signal: AbortSignal.timeout(20000)});
    const result = await response.json();
    if (!response.ok || result.code) throw new Error(`Host request failed: ${route}`);
    return result;
  };
  try {
    for (let i = 0; i < 100 && !apiUrl; i++) {
      for (const line of announcement.split('\n')) {
        try {const parsed = JSON.parse(line); if (parsed.url && path.resolve(parsed.store) === store) apiUrl = parsed.url;} catch {}
      }
      if (!apiUrl) await sleep(200);
    }
    if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(apiUrl)) throw new Error('Host announcement missing or invalid');
    if ((await request('/running')).instances.length) throw new Error('Test Store already has a running App');
    desktop = await _electron.launch({executablePath, args: [args.desktop], env: {...env,
      NATIVEAPP_API: apiUrl, NATIVEAPP_USER_DATA: path.join(output, 'profile')}, timeout: 30000});
    page = await desktop.firstWindow();
    page.setDefaultTimeout(20000);
    const network = await page.context().newCDPSession(page);
    await network.send('Network.enable');
    evidence.blocked_cookie_reasons = [];
    network.on('Network.responseReceivedExtraInfo', event => {
      for (const cookie of event.blockedCookies || []) {
        evidence.blocked_cookie_reasons.push(cookie.blockedReasons);
      }
    });
    // This isolated Store was observed idle; subsequent launches belong to this run.
    ownsApp = true;
    await page.locator('#sheets button[data-app="ai4bi-web"]').click();
    evidence.steps.push('selected-ai4bi-sheet'); save();
    const apiResponses = [];
    const requestedPaths = new Set();
    page.on('request', request => {if(request.method()==='POST')requestedPaths.add(new URL(request.url()).pathname);});
    page.on('response', response => {
      const url = new URL(response.url());
      if (url.pathname.startsWith('/api/v1/')) apiResponses.push({path: url.pathname, status: response.status()});
    });
    evidence.api_responses = apiResponses;
    const frame = page.frameLocator('iframe.app-view[data-app="ai4bi-web"]');
    await expect(frame.getByLabel('本次啟動配對碼')).toBeVisible({timeout: 70000});
    const appFrame = page.frames().find(item => item !== page.mainFrame() && /^http:\/\/127\.0\.0\.1:/.test(item.url()));
    if (!appFrame) throw new Error('App iframe unavailable');
    const appNetwork = await page.context().newCDPSession(appFrame);
    await appNetwork.send('Network.enable');
    appNetwork.on('Network.responseReceivedExtraInfo', event => {
      for (const cookie of event.blockedCookies || []) evidence.blocked_cookie_reasons.push(cookie.blockedReasons);
    });
    evidence.steps.push('real-electron-iframe-loaded'); save();
    launch = (await request('/running')).instances.find(item => item.app_id === 'ai4bi-web');
    if (!launch) throw new Error('No running AI4BI');
    evidence.launch = {pid:launch.pid,port:launch.port,instance_id:launch.instance_id}; save();
    const ready = await (await fetch(launch.url + '/ready')).json();
    if (ready.build_id !== receipt.build_id) throw new Error('Desktop App build mismatch');
    evidence.steps.push('installed-build-matched'); save();
    const logBytes = fs.readFileSync(path.join(store, 'data', 'ai4bi-web', 'logs', 'http.log'));
    // The Kit cleans child environments; Windows CP950 may replace the host UTF-8 setting.
    const codes = ['utf-8', 'big5'].flatMap(encoding => [...new TextDecoder(encoding).decode(logBytes)
      .matchAll(/本次啟動配對碼（僅供本機使用）：([^\r\n]+)/g)]);
    if (!codes.length) throw new Error('Test launch pairing code unavailable');
    await frame.getByLabel('本次啟動配對碼').fill(codes.at(-1)[1].trim());
    await frame.getByRole('button', {name: '連接工作區 →', exact: true}).click();
    evidence.steps.push('submitted-pairing'); save();
    await expect(frame.getByRole('button', {name: '新增工作區', exact: true})).toBeVisible();
    evidence.cookie_metadata_after_pairing = (await page.context().cookies()).map(cookie => ({
      name: cookie.name, domain: cookie.domain, httpOnly: cookie.httpOnly, secure: cookie.secure,
      sameSite: cookie.sameSite, partitionKey: cookie.partitionKey}));
    evidence.steps.push('paired-in-embedded-frame'); save();
    await frame.getByRole('button', {name: '新增工作區', exact: true}).click();
    await frame.getByLabel('工作區名稱').fill(workspaceTitle);
    const createdResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/workspaces'
      && response.request().method() === 'POST' && response.status() === 200);
    await frame.getByRole('button', {name: '建立工作區', exact: true}).click();
    const createdIds = await (await createdResponse).json();
    const workspaceId = createdIds.workspace_id;
    await expect(frame.getByRole('dialog', {name:'建立工作區',exact:true})).toHaveCount(0);
    await expect(frame.getByLabel('選擇工作區')).toHaveValue(workspaceId);
    await expect(frame.getByLabel('選擇工作區').locator('option:checked')).toHaveText(workspaceTitle);
    await expect.poll(()=>requestedPaths.has(`/api/v1/workspaces/${workspaceId}/reports/${createdIds.report_id}/queries`),{timeout:45000}).toBe(true);
    await expect(frame.locator('.kpi-value').filter({hasText: '600'})).toBeVisible({timeout: 45000});
    await expect(frame.locator('.visual-card')).toHaveCount(5);
    evidence.workspace_id = workspaceId;
    evidence.visual_title = visualTitle;
    await page.screenshot({path: path.join(output, 'desktop-workspace.png')});
    evidence.steps.push('real-worker-query-five-visuals'); save();
    await frame.locator('.visual-card').first().click();
    await frame.getByLabel('圖表標題').fill(visualTitle);
    await frame.getByLabel('圖表標題').blur();
    await expect(frame.getByRole('heading', {name: visualTitle, exact: true})).toBeVisible();
    await frame.locator('.visual-card').nth(3).getByRole('button', {name:/^編輯 /}).click();
    await frame.getByText('SPC 跨實體離群掃描', {exact:true}).click();
    await frame.getByRole('combobox', {name:'SPC 資料來源',exact:true}).selectOption('fab_process_move');
    await frame.getByRole('combobox', {name:'SPC 實體欄位',exact:true}).selectOption('tool_id');
    await frame.getByRole('combobox', {name:'SPC 數值欄位',exact:true}).selectOption('queue_time_hr');
    await frame.getByLabel('SPC 標準差倍數', {exact:true}).fill('1.5');
    await frame.getByLabel('SPC 設定名稱', {exact:true}).fill('Desktop SPC');
    const spcSavedResponse = page.waitForResponse(response => response.request().method()==='POST'
      && new URL(response.url()).pathname.endsWith('/commands') && response.request().postDataJSON().command_type==='save_spc_analysis');
    await frame.getByRole('button', {name:'另存 SPC 設定',exact:true}).click();
    const spcSaved = await spcSavedResponse;
    if (spcSaved.status()!==200) throw new Error('SPC settings save failed');
    const spcDefinition = (await spcSaved.json()).report.web_extensions.spc_analyses[0];
    evidence.spc_definition = spcDefinition;
    evidence.steps.push('spc-settings-saved-in-frame'); save();
    await frame.getByText('共同性分析', {exact:true}).click();
    for (const [name,value] of [['共同性曝光來源','fab_process_move'],['共同性實體欄位','tool_id'],
      ['曝光群體識別欄位','wafer_id'],['共同性結果來源','fab_wafer_yield'],
      ['結果群體識別欄位','wafer_id'],['共同性結果數值欄位','yield_pct']]) {
      await frame.getByRole('combobox', {name,exact:true}).selectOption(value);
    }
    await frame.getByLabel('共同性門檻', {exact:true}).fill('80');
    await frame.getByLabel('共同性設定名稱', {exact:true}).fill('Desktop Commonality');
    const cmSavedResponse = page.waitForResponse(response => response.request().method()==='POST'
      && new URL(response.url()).pathname.endsWith('/commands') && response.request().postDataJSON().command_type==='save_commonality_analysis');
    await frame.getByRole('button', {name:'另存共同性設定',exact:true}).click();
    const cmSaved = await cmSavedResponse;
    if (cmSaved.status()!==200) throw new Error('Commonality settings save failed');
    const cmDefinition = (await cmSaved.json()).report.web_extensions.commonality_analyses[0];
    evidence.commonality_definition = cmDefinition;
    evidence.steps.push('commonality-settings-saved-in-frame'); save();
    await frame.getByText('跨資料表分析', {exact:true}).click();
    for (const [name,value] of [['A 資料來源','fab_process_move'],['A 共同鍵','lot_id'],['A 數值欄位','queue_time_hr'],['A 聚合','AVG'],
      ['B 資料來源','fab_wafer_yield'],['B 共同鍵','lot_id'],['B 指標方式','weighted_ratio'],['B 分子欄位','good_die'],['B 分母欄位','tested_die']]) {
      await frame.getByRole('combobox', {name,exact:true}).selectOption(value);
    }
    await frame.getByLabel('跨表分析設定名稱', {exact:true}).fill('Desktop Crossfact');
    const cfSavedResponse = page.waitForResponse(response => response.request().method()==='POST'
      && new URL(response.url()).pathname.endsWith('/commands') && response.request().postDataJSON().command_type==='save_crossfact_analysis');
    await frame.getByRole('button', {name:'另存跨表分析設定',exact:true}).click();
    const cfSaved = await cfSavedResponse;
    if (cfSaved.status()!==200) throw new Error('Crossfact settings save failed');
    const cfDefinition = (await cfSaved.json()).report.web_extensions.crossfact_analyses[0];
    evidence.crossfact_definition = cfDefinition;
    evidence.steps.push('crossfact-settings-saved-in-frame'); save();
    await frame.getByText('變化拆解', {exact:true}).click();
    for (const [name,value] of [['變化拆解來源','fab_wafer_yield'],['變化拆解指標','weighted_yield_pct'],
      ['變化拆解日期欄位','test_date'],['變化拆解維度','product_family'],['變化拆解期間','week']]) {
      await frame.getByRole('combobox', {name,exact:true}).selectOption(value);
    }
    await frame.getByLabel('變化拆解設定名稱', {exact:true}).fill('Desktop Change');
    const changeSavedResponse = page.waitForResponse(response => response.request().method()==='POST'
      && new URL(response.url()).pathname.endsWith('/commands') && response.request().postDataJSON().command_type==='save_change_analysis');
    await frame.getByRole('button', {name:'另存變化拆解設定',exact:true}).click();
    const changeSaved = await changeSavedResponse;
    if (changeSaved.status()!==200) throw new Error('Change settings save failed');
    const changeDefinition = (await changeSaved.json()).report.web_extensions.change_analyses[0];
    evidence.change_definition = changeDefinition;
    evidence.steps.push('change-settings-saved-in-frame'); save();
    await frame.getByRole('button', {name: '保存報表', exact: true}).click();
    await expect(frame.getByText('所有變更已保存', {exact: true})).toBeVisible();
    evidence.steps.push('edited-and-saved-report'); save();
    page.once('dialog', dialog => dialog.accept());
    await page.locator('#btn-reload').click();
    await expect(frame.getByLabel('選擇工作區')).toBeEnabled();
    await frame.getByLabel('選擇工作區').selectOption(workspaceId);
    await expect(frame.getByRole('heading', {name: visualTitle, exact: true})).toBeVisible();
    await expect(frame.locator('.kpi-value').filter({hasText: '600'})).toBeVisible({timeout: 45000});
    evidence.steps.push('edit-save-host-reload-reopen-retains-session'); save();
    await frame.getByText('SPC 跨實體離群掃描', {exact:true}).click();
    await frame.getByRole('combobox', {name:'本頁 SPC 設定',exact:true}).selectOption(spcDefinition.analysis_id);
    await frame.getByRole('button', {name:'套用 SPC 設定',exact:true}).click();
    await expect(frame.getByRole('combobox', {name:'SPC 實體欄位',exact:true})).toHaveValue('tool_id');
    await expect(frame.getByLabel('SPC 標準差倍數', {exact:true})).toHaveValue('1.5');
    await frame.getByRole('button', {name:'執行 SPC 掃描',exact:true}).click();
    const spcResult = frame.getByRole('region', {name:'SPC 分析結果',exact:true});
    await expect(spcResult.getByRole('status')).toHaveText('掃描完成', {timeout:45000});
    await expect(spcResult).toContainText('使用 600／600 列');
    await spcResult.screenshot({path:path.join(output,'desktop-spc.png')});
    evidence.steps.push('spc-settings-reopened-and-scanned'); save();
    await frame.getByText('共同性分析', {exact:true}).click();
    await frame.getByRole('combobox', {name:'本頁共同性設定',exact:true}).selectOption(cmDefinition.analysis_id);
    await frame.getByRole('button', {name:'套用共同性設定',exact:true}).click();
    await expect(frame.getByLabel('共同性門檻', {exact:true})).toHaveValue('80');
    await frame.getByRole('button', {name:'執行共同性分析',exact:true}).click();
    const cmResult = frame.getByRole('region', {name:'共同性分析結果',exact:true});
    await expect(cmResult.getByRole('status')).toHaveText('共同性分析完成', {timeout:45000});
    await expect(cmResult).toContainText('母體 100；符合門檻 11；對照 89');
    await cmResult.screenshot({path:path.join(output,'desktop-commonality.png')});
    evidence.steps.push('commonality-settings-reopened-and-scanned'); save();
    await frame.getByText('跨資料表分析', {exact:true}).click();
    await frame.getByRole('combobox', {name:'本頁跨表分析設定',exact:true}).selectOption(cfDefinition.analysis_id);
    await frame.getByRole('button', {name:'套用跨表分析設定',exact:true}).click();
    await expect(frame.getByRole('combobox', {name:'B 指標方式',exact:true})).toHaveValue('weighted_ratio');
    await expect(frame.getByLabel('B 比率倍率', {exact:true})).toHaveValue('100');
    await frame.getByRole('button', {name:'執行跨表分析',exact:true}).click();
    const cfResult = frame.getByRole('region', {name:'跨表分析結果',exact:true});
    await expect(cfResult.getByRole('status')).toHaveText('跨表分析完成', {timeout:45000});
    await expect(cfResult).toContainText('對齊 20 群；有效配對 20');
    await expect(cfResult).toContainText('來源 A：600 列');
    await cfResult.getByRole('status').scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(output,'desktop-crossfact.png')});
    evidence.steps.push('crossfact-settings-reopened-and-scanned'); save();
    await frame.getByText('變化拆解', {exact:true}).click();
    await frame.getByRole('combobox', {name:'本頁變化拆解設定',exact:true}).selectOption(changeDefinition.analysis_id);
    await frame.getByRole('button', {name:'套用變化拆解設定',exact:true}).click();
    await expect(frame.getByRole('combobox', {name:'變化拆解指標',exact:true})).toHaveValue('weighted_yield_pct');
    await frame.getByRole('button', {name:'執行變化拆解',exact:true}).click();
    const changeView = frame.getByRole('region', {name:'變化拆解結果',exact:true});
    await expect(changeView.getByRole('status')).toHaveText('變化拆解完成',{timeout:45000});
    await expect(changeView.getByRole('table').locator('tbody tr')).toHaveCount(5);
    await changeView.scrollIntoViewIfNeeded();await page.screenshot({path:path.join(output,'desktop-change.png')});
    evidence.steps.push('change-settings-reopened-and-scanned'); save();
    evidence.exports = {};
    async function downloadExport(format, filename, selector, entry=format) {
    const exportPath = path.join(output, filename);
    // Electron's native download event owns Save As. Automate only the test
    // destination; do not intercept requests or replace the downloaded bytes.
    await desktop.evaluate(({BrowserWindow}, target) => {
      globalThis.__ai4biDownload = {state: 'waiting'};
      BrowserWindow.getAllWindows()[0].webContents.session.once('will-download', (_event, item) => {
        globalThis.__ai4biDownload = {state: 'started', filename: item.getFilename(), scheme: new URL(item.getURL()).protocol};
        item.setSavePath(target);
        item.once('done', (_event, state) => {
          Object.assign(globalThis.__ai4biDownload,{state,received_bytes:item.getReceivedBytes(),total_bytes:item.getTotalBytes()});
        });
      });
    }, exportPath);
    await selector.selectOption(format);
    let downloaded;
    for (let i = 0; i < 300; i++) {
      downloaded = await desktop.evaluate(() => globalThis.__ai4biDownload);
      if (!['waiting', 'started'].includes(downloaded.state)) break;
      await sleep(200);
    }
    evidence.download_transport = {event: 'electron-will-download', save_path_assigned_by_test: true,
      native_save_dialog_exercised: false, ...downloaded};
    if (downloaded.state !== 'completed' || !downloaded.filename.endsWith(path.extname(filename))) throw new Error('Desktop download failed');
    const bytes = fs.readFileSync(exportPath);
    if (!bytes.length || downloaded.received_bytes !== bytes.length) throw new Error('Desktop download length mismatch');
    if (['xlsx','csv'].includes(format) && bytes.subarray(0,4).toString('hex') !== '504b0304') throw new Error('Invalid archive');
    if (format === 'pdf' && bytes.subarray(0,5).toString() !== '%PDF-') throw new Error('Invalid PDF');
    if (format === 'json' && (!JSON.parse(bytes.toString()) || typeof JSON.parse(bytes.toString()) !== 'object')) throw new Error('Invalid JSON');
    evidence.exports[entry] = {filename,bytes:bytes.length,sha256:hash(exportPath),transport:{...downloaded}};
    evidence.steps.push('native-frame-'+entry+'-download'); save();
    return bytes;
    }
    for (const [format, filename] of [['xlsx','report.xlsx'],['csv','report.csv.zip'],['pdf','report.pdf'],['json','report.json']]) {
      await downloadExport(format,filename,frame.getByLabel('匯出報表', {exact:true}));
    }
    const exportedAnalysis = JSON.parse(fs.readFileSync(path.join(output,'report.json'),'utf-8')).analysis;
    const exportedSpc = exportedAnalysis.spc_analyses[spcDefinition.analysis_id];
    expect(exportedSpc.settings).toEqual(spcDefinition);
    expect(exportedSpc.input_rows).toBe(600);
    expect(exportedSpc.entity_count).toBe(12);
    expect(exportedAnalysis.execution_contract).toBe(expectedExecutionContract);
    evidence.spc_export = {analysis_id:spcDefinition.analysis_id,input_rows:exportedSpc.input_rows,
      entity_count:exportedSpc.entity_count,execution_contract:exportedAnalysis.execution_contract};
    evidence.steps.push('spc-export-matches-saved-definition'); save();
    const exportedCm = exportedAnalysis.commonality_analyses[cmDefinition.analysis_id];
    expect(exportedCm.settings).toEqual(cmDefinition);
    expect(exportedCm.population_count).toBe(100);
    expect(exportedCm.qualifying_count).toBe(11);
    expect(exportedCm.rows[0]).toMatchObject({entity:'ETCH-02',lift:1.82,p_value:0.0008});
    evidence.commonality_export = {analysis_id:cmDefinition.analysis_id,population_count:100,qualifying_count:11};
    evidence.steps.push('commonality-export-matches-saved-definition'); save();
    const exportedCf = exportedAnalysis.crossfact_analyses[cfDefinition.analysis_id];
    expect(exportedCf.settings).toEqual(cfDefinition);
    expect(exportedCf.rows).toHaveLength(20);
    expect(exportedCf.sources.a.input_rows).toBe(600);
    expect(exportedCf.correlation).toMatchObject({r:-0.716,n:20});
    expect(exportedCf.cohorts.reduce((n,row)=>n+row.count,0)).toBe(20);
    evidence.crossfact_export = {analysis_id:cfDefinition.analysis_id,aligned_count:20,input_rows:600};
    evidence.steps.push('crossfact-export-matches-saved-definition'); save();
    const exportedChange = exportedAnalysis.change_analyses[changeDefinition.analysis_id];
    expect(exportedChange.settings).toEqual(changeDefinition);
    expect(exportedChange.rows).toHaveLength(5);expect(exportedChange.additive).toBe(false);
    expect(exportedChange.analysis_contract).toBe('change-v2');
    evidence.change_export = {analysis_id:changeDefinition.analysis_id,group_count:5};
    evidence.steps.push('change-export-matches-saved-definition'); save();
    await frame.getByRole('button', {name:'發布與版本',exact:true}).click();
    const publication = frame.getByRole('dialog', {name:'發布與版本',exact:true});
    await publication.getByRole('button', {name:/發布目前草稿/}).click();
    const publishedSpc = publication.getByRole('region', {name:'SPC 分析結果：Desktop SPC',exact:true});
    await expect(publishedSpc.getByRole('status')).toHaveText('掃描完成',{timeout:45000});
    await expect(publishedSpc).toContainText('使用 600／600 列');
    await publishedSpc.screenshot({path:path.join(output,'desktop-spc-publication.png')});
    const publishedBytes = await downloadExport('json','published-report.json',
      publication.getByRole('combobox', {name:'匯出發布版本',exact:true}),'published_json');
    const publishedDocument = JSON.parse(publishedBytes.toString('utf-8'));
    const publishedCmView = publication.getByRole('region', {name:'共同性分析結果：Desktop Commonality',exact:true});
    await expect(publishedCmView.getByRole('status')).toHaveText('共同性分析完成');
    await expect(publishedCmView).toContainText('母體 100；符合門檻 11；對照 89');
    const publishedCm = publishedDocument.analysis.commonality_analyses[cmDefinition.analysis_id];
    expect(publishedCm.settings).toEqual(cmDefinition);
    expect(publishedCm.rows).toEqual(exportedCm.rows);
    expect(publishedCm.data_versions).toEqual(exportedCm.data_versions);
    await publishedCmView.screenshot({path:path.join(output,'desktop-commonality-publication.png')});
    evidence.commonality_publication = {analysis_id:cmDefinition.analysis_id,population_count:100,qualifying_count:11};
    evidence.steps.push('commonality-published-replay-and-download'); save();
    const publishedCfView = publication.getByRole('region', {name:'跨表分析結果：Desktop Crossfact',exact:true});
    await expect(publishedCfView.getByRole('status')).toHaveText('跨表分析完成');
    await expect(publishedCfView).toContainText('對齊 20 群；有效配對 20');
    const publishedCf = publishedDocument.analysis.crossfact_analyses[cfDefinition.analysis_id];
    expect(publishedCf.settings).toEqual(cfDefinition);
    for (const field of ['rows','correlation','cohorts','data_versions']) expect(publishedCf[field]).toEqual(exportedCf[field]);
    await publishedCfView.getByText('跨表計算設定', {exact:true}).click();
    await publishedCfView.getByRole('heading', {name:'Desktop Crossfact',exact:true}).scrollIntoViewIfNeeded();
    await expect(publishedCfView.getByText(/SUM\(good_die\) ÷ SUM\(tested_die\) × 100/)).toBeVisible();
    await page.screenshot({path:path.join(output,'desktop-crossfact-publication.png')});
    evidence.crossfact_publication = {analysis_id:cfDefinition.analysis_id,aligned_count:20,read_only:true};
    evidence.steps.push('crossfact-published-replay-and-download'); save();
    const publishedChangeView = publication.getByRole('region', {name:'變化拆解結果',exact:true});
    await expect(publishedChangeView.getByRole('status')).toHaveText('變化拆解完成');
    await expect(publishedChangeView.getByRole('table').locator('tbody tr')).toHaveCount(5);
    const publishedChange = publishedDocument.analysis.change_analyses[changeDefinition.analysis_id];
    expect(publishedChange.settings).toEqual(changeDefinition);
    for (const field of ['rows','overall_current','overall_previous','overall_delta','data_versions']) {
      expect(publishedChange[field]).toEqual(exportedChange[field]);
    }
    await publishedChangeView.scrollIntoViewIfNeeded();await page.screenshot({path:path.join(output,'desktop-change-publication.png')});
    evidence.change_publication = {analysis_id:changeDefinition.analysis_id,group_count:5,read_only:true};
    evidence.steps.push('change-published-replay-and-download'); save();
    const publishedAnalysis = publishedDocument.analysis.spc_analyses[spcDefinition.analysis_id];
    expect(publishedDocument.report.read_only).toBe(true);
    expect(publishedAnalysis.settings).toEqual(spcDefinition);
    expect(publishedAnalysis.points).toEqual(exportedSpc.points);
    expect(publishedAnalysis.data_versions).toEqual(exportedSpc.data_versions);
    evidence.spc_publication = {analysis_id:spcDefinition.analysis_id,input_rows:publishedAnalysis.input_rows,
      entity_count:publishedAnalysis.entity_count,read_only:true};
    evidence.steps.push('published-spc-replayed-and-downloaded'); save();
    await publication.getByRole('button', {name:'關閉發布檢視',exact:true}).click();
    page.once('dialog', dialog => dialog.dismiss());
    await page.locator('#btn-stop').click();
    await expect(frame.getByRole('heading', {name: visualTitle, exact: true})).toBeVisible();
    if (!(await request('/running')).instances.some(item => item.pid === launch.pid)) throw new Error('Cancel closed App');
    evidence.steps.push('host-close-cancel-keeps-app'); save();
    page.once('dialog', dialog => dialog.accept());
    await page.locator('#btn-stop').click();
    await expect(page.locator('#status')).toHaveText('Closed ai4bi-web',{timeout:stopWaitMs});
    if ((await request('/running')).instances.some(item => item.app_id === 'ai4bi-web')) throw new Error('Stop left registry entry');
    evidence.steps.push('host-close-confirmed-registry-empty'); save();
    let exited = false, closed = false;
    const deadline = Date.now()+5000;
    do {
      try {process.kill(launch.pid, 0);} catch (error) {if (error.code === 'ESRCH') exited = true; else throw error;}
      // A fresh TCP socket avoids reusing an HTTP keep-alive connection after stop.
      closed = await endpointClosed(launch.port);
      if (exited && closed) break;
      await sleep(100);
    } while(Date.now()<deadline);
    evidence.stop_verification = {launcher_exited: exited, endpoint_closed: closed}; save();
    if (!exited || !closed) throw new Error('Stop left live App');
    evidence.steps.push('host-stop-launcher-exited-endpoint-closed');
    evidence.stop_verification = {launcher_exited: exited, endpoint_closed: closed};
    evidence.passed = true;
  } catch (error) {
    // Avoid locator call logs: they can contain the pairing input value.
    evidence.failure = {type: error.name, code: error.code, step: evidence.steps.at(-1) || 'startup',
      location: error.stack?.match(/validate_nativeapp_desktop\.cjs:\d+:\d+/)?.[0]};
    if (page) {
      // Never capture a pairing form that may contain its secret.
      const form = page.frameLocator('iframe.app-view[data-app="ai4bi-web"]').getByLabel('本次啟動配對碼');
      await form.fill('', {timeout: 1000}).catch(() => {});
      await page.screenshot({path: path.join(output, 'failure.png')}).catch(() => {});
    }
  } finally {
    if (desktop) await desktop.close().catch(() => {});
    if (apiUrl && ownsApp) await request('/stop', {app_id: 'ai4bi-web'}).catch(() => {evidence.cleanup_error = true;});
    host.kill();
    if (host.exitCode === null) await Promise.race([new Promise(resolve => host.once('exit', resolve)), sleep(5000)]);
    evidence.shell_unchanged = shellFiles.every(name => hash(path.join(args.desktop, name)) === shellHashes[name]);
    evidence.complete = true;
    evidence.passed = evidence.passed && evidence.shell_unchanged && !evidence.cleanup_error;
    save();
  }
  console.log(JSON.stringify({passed: evidence.passed, steps: evidence.steps, output}));
  process.exitCode = evidence.passed ? 0 : 1;
}
main().catch(error => {console.error(error.name + ': desktop validation setup failed'); process.exitCode = 1;});
