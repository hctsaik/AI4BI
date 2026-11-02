/* Released WebView2 executable smoke test. No platform source checkout is used. */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const net = require('node:net');
const {spawn, execFileSync} = require('node:child_process');
const {chromium, expect} = require('@playwright/test');
const root = path.resolve(__dirname, '..');
const hash = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const list = value => Array.isArray(value) ? value : [value];
const inside = value => {const rel = path.relative(path.join(root, '.artifacts'), value); return rel && !rel.startsWith('..') && !path.isAbsolute(rel);};
const args = Object.fromEntries(process.argv.slice(2).reduce((a, v, i, all) => {
  if (!(i % 2)) a.push([v.replace(/^--/, ''), all[i + 1]]); return a;
}, []));
const freePort = () => new Promise((resolve, reject) => {
  const server = net.createServer(); server.on('error', reject);
  server.listen(0, '127.0.0.1', () => {const port = server.address().port; server.close(() => resolve(port));});
});
const closed = port => new Promise((resolve, reject) => {
  const socket = net.createConnection({host:'127.0.0.1', port});
  socket.on('connect', () => {socket.destroy(); resolve(false);});
  socket.on('error', e => e.code === 'ECONNREFUSED' ? resolve(true) : reject(e));
  socket.setTimeout(1000, () => {socket.destroy(); reject(new Error('Port observation timed out'));});
});
function powershell(code, env = {}) {
  return execFileSync('powershell.exe', ['-NoProfile', '-Command', code], {
    windowsHide:true, timeout:30000, encoding:'utf8', env:{...process.env, ...env}}).trim();
}
async function main() {
  for (const name of ['runtime', 'host-validation', 'output']) {
    if (!args[name]) throw new Error(`Required --${name}`);
    args[name] = path.resolve(args[name]);
    if (!inside(args[name])) throw new Error('Only test artifacts may be used');
  }
  const output = args.output, runtime = args.runtime;
  if (fs.existsSync(output)) throw new Error('Output must be new');
  const hostFile = path.join(args['host-validation'], 'evidence.json');
  const receipt = JSON.parse(fs.readFileSync(hostFile));
  if (receipt.complete !== true || receipt.provisioned_from_archive !== true) throw new Error('Require provisioned Host validation');
  const provenance = JSON.parse(fs.readFileSync(path.join(runtime, 'provenance.json')));
  if (provenance.complete !== true) throw new Error('Missing release provenance');
  const members = Object.assign({}, ...provenance.archives.map(a => a.files));
  const verify = () => Object.entries(members).every(([name, sha]) => hash(path.join(runtime, name)) === sha);
  if (!verify()) throw new Error('Released runtime bytes changed');
  const exe = path.join(runtime, 'bin/nativeapp-desktop.exe');
  const store = path.join(args['host-validation'], 'store');
  const python = path.join(runtime, 'python-runtime/python.exe');
  fs.mkdirSync(output, {recursive:true});
  fs.copyFileSync(__filename, path.join(output, 'driver.cjs'));
  const evidence = {complete:false, passed:false, build_id:receipt.build_id, host_receipt_sha256:hash(hostFile),
    executable_sha256:hash(exe), driver_sha256:hash(__filename), steps:[],
    limitations:['Released platform + Kit Python composition; not full Setup or a clean machine.',
      'Manual pairing, no native Save As, upgrade/rollback or full analysis matrix in this smoke test.']};
  const save = () => fs.writeFileSync(path.join(output, 'evidence.json'), JSON.stringify(evidence, null, 2));
  let phase;
  const step = name => {const value = phase + ':' + name; evidence.steps.push(value); save(); console.log('PASS ' + value);};
  let workspaceId;
  const visualTitle = 'Persisted Runtime yield ' + crypto.randomUUID();
  evidence.cycles = [];
  save();
  for (phase of ['initial', 'restart']) {
  let phasePassed = false;
  const cdp = await freePort(), api = await freePort();
  if (cdp === api) throw new Error('Port allocation collision');
  const env = Object.fromEntries(Object.entries(process.env).filter(([k]) => !k.startsWith('NATIVEAPP_') && !k.startsWith('WEBVIEW2_') && !['PYTHONPATH','PYTHONHOME','OPENAI_API_KEY','ANTHROPIC_API_KEY'].includes(k)));
  Object.assign(env, {NATIVEAPP_STORE:store, NATIVEAPP_REPO:runtime, NATIVEAPP_PROTOCOL:path.join(runtime, 'packages/protocol'),
    NATIVEAPP_PLATFORM_PYTHON:python, PYTHONPATH:path.join(runtime, 'python'), NATIVEAPP_API_PORT:String(api),
    WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS:`--remote-debugging-port=${cdp}`,
    WEBVIEW2_USER_DATA_FOLDER:path.join(output, 'profile-' + phase), HF_HUB_OFFLINE:'1', PIP_NO_INDEX:'1'});
  const proc = spawn(exe, [], {cwd:runtime, env, windowsHide:true, stdio:'ignore'});
  let spawnError, browser, page, launch, owned = [];
  proc.on('error', error => {spawnError = error;});
  const snapshot = () => JSON.parse(powershell(`$ErrorActionPreference='Stop'; $items=Get-CimInstance Win32_Process; $ids=@([int]$env:TEST_OWNER_PID); do { $added=@($items | Where-Object { $ids -contains $_.ParentProcessId -and $ids -notcontains $_.ProcessId } | ForEach-Object { [int]$_.ProcessId }); $ids += $added } while ($added.Count); @($ids | ForEach-Object { $p=Get-Process -Id $_ -ErrorAction SilentlyContinue; if($p){ @{pid=$p.Id; created=$p.StartTime.ToUniversalTime().ToString('o')} } }) | ConvertTo-Json -Compress`, {TEST_OWNER_PID:String(proc.pid)}) || '[]');
  const survivors = () => list(JSON.parse(powershell(`$ErrorActionPreference='Stop'; @((ConvertFrom-Json $env:TEST_OWNED) | Where-Object { $p=Get-Process -Id $_.pid -ErrorAction SilentlyContinue; $p -and $p.StartTime.ToUniversalTime().ToString('o') -eq $_.created }) | ConvertTo-Json -Compress`, {TEST_OWNED:JSON.stringify(owned)}) || '[]'));
  try {
    for (let i=0; i<80 && !browser; i++) {
      if (spawnError) throw spawnError;
      if (proc.exitCode !== null) throw new Error(`Runtime exited: ${proc.exitCode}`);
      try {browser = await chromium.connectOverCDP(`http://127.0.0.1:${cdp}`, {timeout:1000});} catch {await sleep(250);}
    }
    if (!browser) throw new Error('Released WebView2 CDP unavailable');
    owned = list(snapshot());
    page = browser.contexts()[0].pages()[0];
    page.setDefaultTimeout(25000);
    step('released-webview2-connected');
    await page.locator('#sheets button[data-app="ai4bi-web"]').click();
    const frame = page.frameLocator('iframe.app-view[data-app="ai4bi-web"]');
    await expect(frame.getByLabel('本次啟動配對碼')).toBeVisible({timeout:70000});
    step('released-host-loaded-app-iframe');
    const response = await fetch(`http://127.0.0.1:${api}/running`, {signal:AbortSignal.timeout(5000)});
    if (!response.ok) throw new Error('Host running query failed');
    launch = (await response.json()).instances.find(item => item.app_id === 'ai4bi-web');
    if (!launch) throw new Error('AI4BI instance missing');
    const ready = await (await fetch(launch.url + '/ready', {signal:AbortSignal.timeout(5000)})).json();
    if (ready.build_id !== receipt.build_id) throw new Error('Installed build mismatch');
    evidence.launch = {pid:launch.pid, port:launch.port};
    step('installed-build-matched');
    const bytes = fs.readFileSync(path.join(store, 'data/ai4bi-web/logs/http.log'));
    const codes = ['utf-8','big5'].flatMap(encoding => [...new TextDecoder(encoding).decode(bytes).matchAll(/本次啟動配對碼（僅供本機使用）：([^\r\n]+)/g)]);
    if (!codes.length) throw new Error('Test launch pairing code unavailable');
    await frame.getByLabel('本次啟動配對碼').fill(codes.at(-1)[1].trim());
    await frame.getByRole('button', {name:'連接工作區 →', exact:true}).click();
    await expect(frame.getByRole('button', {name:'新增工作區', exact:true})).toBeVisible();
    step('paired-in-released-webview2');
    if (phase === 'initial') {
    await frame.getByRole('button', {name:'新增工作區', exact:true}).click();
    const title = 'Runtime verification ' + crypto.randomUUID();
    await frame.getByLabel('工作區名稱').fill(title);
    const created = page.waitForResponse(r => new URL(r.url()).pathname === '/api/v1/workspaces' && r.request().method() === 'POST' && r.status() === 200);
    await frame.getByRole('button', {name:'建立工作區', exact:true}).click();
    const ids = await (await created).json();
    workspaceId = ids.workspace_id;
    evidence.workspace_id = workspaceId;
    evidence.visual_title = visualTitle;
    await expect(frame.getByLabel('選擇工作區')).toHaveValue(ids.workspace_id);
    } else {
      await frame.getByLabel('選擇工作區').selectOption(workspaceId);
      await expect(frame.getByRole('heading', {name:visualTitle, exact:true})).toBeVisible();
      step('saved-title-restored-after-full-process-restart');
    }
    await expect(frame.locator('.kpi-value').filter({hasText:'600'})).toBeVisible({timeout:45000});
    await expect(frame.locator('.visual-card')).toHaveCount(5);
    if (phase === 'initial') {
      await frame.locator('.visual-card').first().click();
      await frame.getByLabel('圖表標題').fill(visualTitle);
      await frame.getByLabel('圖表標題').blur();
      await expect(frame.getByRole('heading', {name:visualTitle, exact:true})).toBeVisible();
      await frame.getByRole('button', {name:'保存報表', exact:true}).click();
      await expect(frame.getByText('所有變更已保存', {exact:true})).toBeVisible();
      step('edited-and-saved-report');
    }
    await page.screenshot({path:path.join(output, 'runtime-workspace-' + phase + '.png')});
    step('real-worker-query-five-visuals');
    owned = snapshot();
    if (!Array.isArray(owned)) owned = [owned];
    evidence.owned_processes = owned; save();
    const accepted = powershell(`$p=Get-Process -Id ([int]$env:TEST_OWNER_PID) -ErrorAction Stop; $p.CloseMainWindow()`, {TEST_OWNER_PID:String(proc.pid)});
    if (accepted !== 'True') throw new Error('Native close was not accepted');
    await browser.close(); browser = undefined;
    for (let i=0; i<20; i++) {if (!survivors().length) break; await sleep(1000);}
    evidence.survivors = survivors();
    evidence.api_closed = await closed(api);
    evidence.app_closed = await closed(Number(launch.port));
    if (evidence.survivors.length || !evidence.api_closed || !evidence.app_closed) throw new Error('Runtime native close left processes or endpoints alive');
    step('native-close-reclaims-processes-and-endpoints');
    evidence.runtime_unchanged = verify();
    if (!evidence.runtime_unchanged) throw new Error('Released runtime changed');
    evidence.cycles.push({phase, launch:evidence.launch, owned_processes:owned,
      survivors:evidence.survivors, api_closed:evidence.api_closed, app_closed:evidence.app_closed});
    phasePassed = true;
  } catch (error) {
    evidence.error = error.message;
    process.exitCode = 1;
  } finally {
    if (browser) await browser.close().catch(() => {});
    if (proc.pid && !phasePassed) {
      if (proc.exitCode === null) {owned = snapshot(); if (!Array.isArray(owned)) owned=[owned];}
      if (owned.length) {
        evidence.forced_cleanup = true;
        powershell(`(ConvertFrom-Json $env:TEST_OWNED) | ForEach-Object { $p=Get-Process -Id $_.pid -ErrorAction SilentlyContinue; if($p -and $p.StartTime.ToUniversalTime().ToString('o') -eq $_.created) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } }`, {TEST_OWNED:JSON.stringify(owned)});
        evidence.cleanup_survivors = survivors();
      }
    }
    save();
  }
  if (!phasePassed) break;
  }
  evidence.complete = true;
  evidence.passed = evidence.cycles.length === 2 && !evidence.error;
  save();
  console.log(JSON.stringify({passed:evidence.passed, steps:evidence.steps, error:evidence.error}));
}
main().catch(error => {console.error(error.message); process.exitCode=1;});
