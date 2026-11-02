import { useEffect, useRef, useState } from 'react';
import { api, ApiError, downloadArtifact, key, pair, pollJob } from '../lib/api';
import type { CommandKind } from '../lib/api';
import { ChartBoundary, DataTable } from '../components/VisualChart';
import { Modal } from '../components/Modal';
import { ScenarioEditor } from '../components/ScenarioEditor';
import { BookmarkPanel } from '../components/BookmarkPanel';
import { DrillChart, DrillEditor } from '../components/DrillControls';
import { FilterPanel } from '../components/FilterPanel';
import { AggregateFilterEditor } from '../components/AggregateFilterEditor';
import { DatasetPreview } from '../components/DatasetPreview';
import { PublicationPanel } from '../components/PublicationPanel';
import { KpiSettings } from '../components/KpiSettings';
import { SpcPanel } from '../components/SpcPanel';
import { CommonalityPanel } from '../components/CommonalityPanel';
import { CrossFactPanel } from '../components/CrossFactPanel';
import { ChangeAnalysisPanel } from '../components/ChangeAnalysisPanel';
import { RfmPanel } from '../components/RfmPanel';
import type { Dataset, DrillState, ExplorationView, Filter, Page, Report, ReportState, Result, Visual, Workspace } from '../types';

type Draft = {import_id:string; revision:number; name:string; status:string;
  config:{encoding:string;delimiter:string;sheet:string|number;column_types:Record<string,string>};
  details:{rows?:Result['rows'];columns?:{name:string;dtype:string}[];row_count?:number;error?:string}};
type Answer = {message:string;context_key?:string;drill_context?:DrillState&{visual_id:string}|null;disambiguation?:string;trust_notes?:string[];
  direct_answer?:{sentence:string};result_table?:Result;candidate_report?:Report;
  conversation?:Record<string,unknown>;configured_mode:string};
const CHARTS = {kpi_card:'指標卡',bar_chart:'長條圖',line_chart:'趨勢線',pie_chart:'圓環圖',scatter:'散點圖',table:'明細表',small_multiples:'小倍數圖',pivot:'樞紐表',map:'地圖',histogram:'直方圖'};
const THEMES = {ocean:'海洋藍',forest:'森林綠',slate:'石墨灰',plum:'紫羅蘭',copper:'暖銅色',teal:'青綠色'};
const clone = <T,>(value:T):T => structuredClone(value);

export function App() {
  const [connected,setConnected] = useState(false);
  const [pairCode,setPairCode] = useState('');
  const [workspaces,setWorkspaces] = useState<Workspace[]>([]);
  const [wid,setWid] = useState('');
  const [report,setReport] = useState<ReportState|null>(null);
  const reportRef = useRef<ReportState|null>(null);
  const [sourceDatasets,setDatasets] = useState<Dataset[]>([]);
  const datasets=sourceDatasets.map(ds=>({...ds,contract:{...ds.contract,metrics:[...ds.contract.metrics,
    ...(report?.report.web_extensions?.calculated_metrics??[]).filter(m=>m.block_id===ds.contract.block_id).map(m=>({name:m.name,formula:m.formula}))]}}));
  const [pageId,setPageId] = useState('main');
  const [selected,setSelected] = useState('');
  const [mode,setMode] = useState<'explore'|'data'>('explore');
  const [theme,setTheme] = useState('ocean');
  const [results,setResults] = useState<Record<string,Result>>({});
  // Only the currently displayed page, never a history of results or snapshots.
  const verifiedResults = useRef<Record<string,{fingerprint:string;result:Result}>>({});
  const resultScope = useRef('');
  const [drillState,setDrillState] = useState<Record<string,DrillState>>({});
  const [filters,setFilters] = useState<Filter[]>([]);
  const [filterBookmark,setFilterBookmark] = useState<string|null>(null);
  const activeFilterBookmark=report?.report.web_extensions?.bookmarks?.find(b=>b.bookmark_id===filterBookmark);
  const filterBookmarkId=activeFilterBookmark?.bookmark_id??null;
  useEffect(()=>{if(filterBookmark&&!filterBookmarkId)setFilterBookmark(null);},[filterBookmark,filterBookmarkId]);
  const filterReport=report&&activeFilterBookmark?.persistent_filters!=null?{...report.report,read_only:true,
    web_extensions:{...report.report.web_extensions!,persistent_filters:activeFilterBookmark.persistent_filters}}:report?.report;
  const explorationRef = useRef('');
  explorationRef.current=JSON.stringify({pageId,selected,filters,filterBookmarkId,drillState});
  const [busy,setBusy] = useState(false);
  const [querying,setQuerying] = useState(false);
  const [error,setError] = useState('');
  const [notice,setNotice] = useState('');
  const [prompt,setPrompt] = useState('');
  const [answer,setAnswer] = useState<Answer|null>(null);
  const [answerJob,setAnswerJob] = useState('');
  const [asking,setAsking] = useState(false);
  const [exporting,setExporting] = useState(false);
  const [showPublications,setShowPublications] = useState(false);
  const [draft,setDraft] = useState<Draft|null>(null);
  const [importDrafts,setImportDrafts] = useState<Pick<Draft,'import_id'|'name'|'revision'|'status'>[]>([]);
  const [preview,setPreview] = useState<string|null>(null);
  const [showNew,setShowNew] = useState(false);
  const [newTitle,setNewTitle] = useState('製程探索工作區');
  const [newTemplate,setNewTemplate] = useState('fab');
  const [adding,setAdding] = useState(false);
  const [newBlock,setNewBlock] = useState('');
  const [newMetric,setNewMetric] = useState('');
  const [newDim,setNewDim] = useState('');
  const [newKind,setNewKind] = useState('bar_chart');
  const queue = useRef(Promise.resolve());
  const dragged = useRef('');
  const fileInput = useRef<HTMLInputElement>(null);
  const scope = useRef(''); scope.current = wid;
  const announceError = (e:unknown) => setError(e instanceof Error ? e.message : String(e));
  const installReport = (next:ReportState) => {reportRef.current=next;setReport(next);};

  async function list() {
    const value = await api<Workspace[]>('/workspaces');setWorkspaces(value);setConnected(true);return value;
  }
  useEffect(() => {void list().then(ws => {if(ws[0]) setWid(ws[0].workspace_id);}).catch(e => {
    if (!(e instanceof ApiError && e.status===401)) announceError(e);
  });},[]);
  useEffect(() => {
    if (!wid) return;
    let alive=true; setResults({});setFilters([]);setDrillState({});setFilterBookmark(null);setAnswer(null);setSelected('');setPreview(null);
    reportRef.current=null;setReport(null);setDraft(null);setImportDrafts([]);
    void Promise.all([api<Workspace>(`/workspaces/${wid}`),api<Dataset[]>(`/workspaces/${wid}/datasets`),api<typeof importDrafts>(`/workspaces/${wid}/imports`)])
      .then(async ([ws,ds,imports]) => {
        const next = await api<ReportState>(`/workspaces/${wid}/reports/${ws.report_ids[0]}`);
        if(!alive) return;
        setDatasets(ds);setImportDrafts(imports);installReport(next);setPageId(next.report.web_extensions?.page_order?.[0]??Object.keys(next.report.pages)[0]);
      }).catch(announceError);
    return () => {alive=false;};
  },[wid]);
  const pageIds=report?.report.web_extensions?.page_order??Object.keys(report?.report.pages??{});
  const page = report?.report.pages[pageId];
  useEffect(()=>{
    if(report&&!report.report.pages[pageId]){setPageId(pageIds[0]);setSelected('');setFilters([]);}
  },[report,pageId]);
  const visual = page?.visuals[selected];
  const sharedQueryContext = JSON.stringify({wid,reportId:report?.report_id,pageId,
    filters,filterBookmarkId,bookmarkConditions:activeFilterBookmark?.persistent_filters,globals:report?.report.global_filters,parameters:report?.report.web_extensions?.parameters,
    calculations:report?.report.web_extensions?.calculated_metrics,persistentFilters:report?.report.web_extensions?.persistent_filters,datasets:sourceDatasets});
  const visualFingerprints = Object.fromEntries((page?.visual_order??[]).map(id=>[id,JSON.stringify({
    context:sharedQueryContext,query:page!.visuals[id].query,extra:page!.visuals[id].visualization.extra,
    sparkline:page!.visuals[id].visualization.show_sparkline===true,
    cartesian:['bar_chart','line_chart'].includes(page!.visuals[id].visualization.visual_type)?[page!.visuals[id].visualization.visual_type,page!.visuals[id].visualization.x_axis_label,page!.visuals[id].visualization.y_axis_label,page!.visuals[id].visualization.show_legend]:null,
    pivot:page!.visuals[id].visualization.visual_type==='pivot',geo:page!.visuals[id].visualization.visual_type==='map',scatter:page!.visuals[id].visualization.visual_type==='scatter',pie:page!.visuals[id].visualization.visual_type==='pie_chart',drill:drillState[id]})]));
  const queryFingerprint = JSON.stringify(visualFingerprints);
  useEffect(() => {
    if (!report || report.workspace_id!==wid || !page) return;
    const retained:typeof verifiedResults.current = {};
    for(const id of page.visual_order){
      const entry=verifiedResults.current[id];
      if(entry?.fingerprint===visualFingerprints[id])retained[id]=entry;
    }
    verifiedResults.current=retained;
    const retainedResults=Object.fromEntries(Object.entries(retained).map(([id,entry])=>[id,entry.result]));
    const nextScope=JSON.stringify([wid,report.report_id,pageId]);
    const sameScope=resultScope.current===nextScope;
    resultScope.current=nextScope;
    // Keep existing cards visible during a refresh, but never treat stale rows
    // as verified results or carry them across workspace/report/page boundaries.
    setResults(previous=>sameScope?Object.fromEntries(page.visual_order.filter(id=>previous[id]).map(id=>[id,previous[id]])):retainedResults);
    const changedIds=page.visual_order.filter(id=>!retained[id]);
    if (!changedIds.length) {setQuerying(false);return;}
    const abort = new AbortController();setQuerying(true);
    let activeJob='';
    const cancel=()=>{if(activeJob)void api(`/jobs/${activeJob}/cancel`,{}).catch(()=>{});};
    const target = `/workspaces/${wid}/reports/${report.report_id}`;
    void api<{job_id:string}>(target+'/queries',{idempotency_key:key(),base_revision:report.revision,
      visual_ids:changedIds,filters,exploration_page_id:pageId,filter_bookmark_id:filterBookmarkId,drill_state:drillState})
      .then(job=>{activeJob=job.job_id;if(abort.signal.aborted)cancel();return pollJob<{visuals:Record<string,Result>}>(job.job_id,abort.signal);})
      .then(result=>{
        if(abort.signal.aborted)return;
        for(const id of changedIds){
          const value=result.visuals[id];
          if(value?.status==='ready')verifiedResults.current[id]={fingerprint:visualFingerprints[id],result:value};
        }
        setResults({...retainedResults,...result.visuals});
      })
      .catch(e=>{if(!abort.signal.aborted)announceError(e);})
      .finally(()=>{if(!abort.signal.aborted)setQuerying(false);});
    return ()=>{abort.abort();cancel();};
  },[wid,report?.workspace_id,report?.report_id,pageId,queryFingerprint]);
  useEffect(()=>{
    const handler = (event:BeforeUnloadEvent) => {if(busy){event.preventDefault();event.returnValue='';}};
    window.addEventListener('beforeunload',handler);return()=>window.removeEventListener('beforeunload',handler);
  },[busy]);

  function edit(transform:(r:Report)=>void, kind:CommandKind='replace_report', extra?:Record<string,unknown>, after?:(next:ReportState)=>void) {
    const workspaceId=wid;setBusy(true);setError('');
    queue.current=queue.current.then(async()=>{
      if(scope.current!==workspaceId) return;
      const current=reportRef.current;if(!current)return;
      if(current.report.read_only)throw new Error('此報表為唯讀，無法修改或建立保存點。');
      const updated=clone(current.report);transform(updated);
      const requestKey=key();
      const next=await api<ReportState>(`/workspaces/${workspaceId}/reports/${current.report_id}/commands`,{
        request_id:requestKey,idempotency_key:requestKey,base_revision:current.revision,
        command_type:kind,payload:extra??(kind==='replace_report'?{report:updated}:{})});
      if(scope.current===workspaceId){installReport(next);after?.(next);if(kind==='save')setNotice('已保存目前報表版本');}
    }).catch(announceError).finally(()=>setBusy(false));
  }
  function updateVisual(update:(v:Visual)=>void) {
    const pid=pageId,id=selected;edit(r=>{const v=r.pages[pid]?.visuals[id];if(v)update(v);});
  }
  async function createWorkspace() {
    setBusy(true);setError('');
    try {
      const created=await api<{workspace_id:string}>('/workspaces',{title:newTitle,template:newTemplate,idempotency_key:key()});
      await list();setWid(created.workspace_id);setShowNew(false);setMode('explore');
    } catch(e){announceError(e);}finally{setBusy(false);}
  }
  async function ask() {
    if(!prompt.trim()||!report||asking)return;
    const originalWid=wid;setAsking(true);setError('');
    const contextKey=JSON.stringify({selected,filterBookmarkId,drill:drillState[selected]??null,revision:report.revision});
    try{
      const job=await api<{job_id:string}>(`/workspaces/${wid}/reports/${report.report_id}/assistant`,{
        idempotency_key:key(),base_revision:report.revision,prompt,selected_component_id:selected||null,
        conversation:answer?.context_key===contextKey?answer.conversation??{}:{},filter_bookmark_id:filterBookmarkId,
        drill_state:Object.hasOwn(drillState,selected)?{[selected]:drillState[selected]}:{}});
      const result=await pollJob<Answer>(job.job_id);
      if(scope.current===originalWid){setAnswer({...result,context_key:contextKey});setAnswerJob(job.job_id);}
    }catch(e){announceError(e);}finally{setAsking(false);}
  }
  async function upload(file:File) {
    setBusy(true);setError('');
    try{const form=new FormData();form.append('file',file);setDraft(await api<Draft>(`/workspaces/${wid}/imports`,form));
      setImportDrafts(await api<typeof importDrafts>(`/workspaces/${wid}/imports`));}
    catch(e){announceError(e);}finally{setBusy(false);}
  }
  async function exportReport(format:'xlsx'|'pdf'|'json'|'csv') {
    if(!report||exporting)return;
    setExporting(true);setError('');
    try {
      const job=await api<{job_id:string}>(`/workspaces/${wid}/reports/${report.report_id}/exports`,{
        idempotency_key:key(),base_revision:report.revision,format,filters,exploration_page_id:pageId,filter_bookmark_id:filterBookmarkId,drill_state:drillState});
      const result=await pollJob<{artifact_id:string;filename:string}>(job.job_id);
      await downloadArtifact(result.artifact_id,result.filename);
      setNotice('匯出完成，已開始下載。');
    }catch(e){announceError(e);}finally{setExporting(false);}
  }
  async function confirmImport() {
    if(!draft)return;setBusy(true);
    try{
      await api(`/workspaces/${wid}/imports/${draft.import_id}/commit`,{idempotency_key:key(),draft_revision:draft.revision});
      setDatasets(await api<Dataset[]>(`/workspaces/${wid}/datasets`));setImportDrafts(items=>items.filter(item=>item.import_id!==draft.import_id));setDraft(null);setNotice('資料已驗證並匯入，可開始建立圖表。');
    }catch(e){announceError(e);}finally{setBusy(false);}
  }
  async function validateDraft() {
    if(!draft)return;setBusy(true);setError('');
    try{
      const next=await api<Draft>(`/workspaces/${wid}/imports/${draft.import_id}/validate`,draft.config);
      setDraft(next);setImportDrafts(items=>items.map(item=>item.import_id===next.import_id?next:item));
    }catch(e){announceError(e);}finally{setBusy(false);}
  }
  function startAdd() {
    const ds=datasets[0];setNewBlock(ds?.contract.block_id??'');setNewMetric(ds?.contract.metrics[0]?.name??'');setNewDim('');setAdding(true);
  }
  function addVisual() {
    const id='visual_'+key().replaceAll('-','').slice(0,10);
    edit(r=>{const p=r.pages[pageId];p.visuals[id]={component_id:id,col_span:newKind==='kpi_card'?4:6,
      query:{spec_id:id,block_refs:[{block_id:newBlock}],metrics:newKind==='histogram'?[]:[{block_id:newBlock,metric_name:newMetric,alias:newMetric}],
        dimensions:newDim?[{block_id:newBlock,column_name:newDim,alias:newDim}]:[],filters:[],sort:[]},
      visualization:{visual_type:newKind==='histogram'?'bar_chart':newKind,title:newKind==='histogram'?`${newDim} 分布`:newMetric,height_px:300,show_legend:true,extra:newKind==='histogram'?{chart_mode:'histogram',bins:20}:{}}};p.visual_order.push(id);});
    setSelected(id);setAdding(false);
  }
  function move(id:string, offset:number) {
    edit(r=>{const ids=r.pages[pageId].visual_order;const at=ids.indexOf(id),to=at+offset;
      if(at>=0&&to>=0&&to<ids.length)[ids[at],ids[to]]=[ids[to],ids[at]];});
  }
  async function applyBookmark(id:string) {
    if(!report||busy)return;
    const workspaceId=wid,revision=report.revision,previousView=explorationRef.current;
    setBusy(true);setError('');
    try{
      const resolved=await api<{revision:number;view:ExplorationView}>(`/workspaces/${wid}/reports/${report.report_id}/bookmarks/${encodeURIComponent(id)}?base_revision=${revision}`);
      if(scope.current!==workspaceId||explorationRef.current!==previousView)return;
      if(reportRef.current?.revision!==resolved.revision)throw new Error('報表已變更，請重新套用書籤。');
      setPageId(resolved.view.page_id);setSelected(resolved.view.selected_visual_id??'');setFilters(resolved.view.filters);setDrillState(resolved.view.drill_state??{});setFilterBookmark(resolved.view.filter_bookmark_id??null);setMode('explore');
      setNotice('已套用探索書籤，報表編輯紀錄未變更');
    }catch(e){if(scope.current===workspaceId&&explorationRef.current===previousView)announceError(e);}finally{setBusy(false);}
  }
  function pageOrder(r:Report){
    r.web_extensions??={version:1,parameters:{},calculated_metrics:[]};
    r.web_extensions.page_order??=Object.keys(r.pages);
    return r.web_extensions.page_order;
  }
  function movePage(offset:number){
    const id=pageId;edit(r=>{const order=pageOrder(r),index=order.indexOf(id),target=index+offset;
      if(index>=0&&target>=0&&target<order.length)[order[index],order[target]]=[order[target],order[index]];});
  }

  if(!connected) return <main className="pair-page"><div className="brand-mark">A<span>4</span></div><div className="pair-card">
    <p className="eyebrow">AI4BI WORKSPACE</p><h1>讓資料，成為下一步。</h1><p>連接本機分析引擎，開始探索製程與良率。</p>
    <form onSubmit={e=>{e.preventDefault();void pair(pairCode).then(list).then(ws=>{if(ws[0])setWid(ws[0].workspace_id);}).catch(announceError);}}>
      <label>本次啟動配對碼<input autoComplete="off" type="password" value={pairCode} onChange={e=>setPairCode(e.target.value)} placeholder="輸入啟動視窗顯示的配對碼"/></label>
      <button className="primary">連接工作區 →</button></form>{error&&<p role="alert" className="error">{error}</p>}
    <small>資料與計算保留在這台電腦。配對碼不會儲存在瀏覽器。</small></div></main>;

  return <div className={`app theme-${theme}`}>
    <aside className="sidebar"><a className="brand" href="#"><span className="brand-mark">A<span>4</span></span><b>AI4BI</b><small>ANALYTICS STUDIO</small></a>
      <div className="workspace-label">工作區 <button aria-label="新增工作區" onClick={()=>setShowNew(true)}>＋</button></div>
      <select aria-label="選擇工作區" value={wid} onChange={e=>!busy&&setWid(e.target.value)} disabled={busy}>
        {!workspaces.length&&<option value="">尚無工作區</option>}{workspaces.map(w=><option key={w.workspace_id} value={w.workspace_id}>{w.title}</option>)}</select>
      <nav><button className={mode==='explore'?'active':''} onClick={()=>setMode('explore')}>◫ <span>探索與報表</span></button>
        <button className={mode==='data'?'active':''} onClick={()=>setMode('data')}>▦ <span>資料工作區</span><i>{datasets.length}</i></button></nav>
      <div className="sidebar-section">報表頁面</div><div className="page-list">{pageIds.map(id=>report!.report.pages[id]).map(p=><button key={p.page_id}
        className={p.page_id===pageId?'selected-page':''} onClick={()=>{setPageId(p.page_id);setFilters([]);setSelected('');setMode('explore');}}>▤　{p.display_name||p.title}</button>)}</div>
      {report&&<button className="new-page" disabled={busy||report.report.read_only} onClick={()=>{const id='page_'+key().slice(0,8);
        edit(r=>{const order=pageOrder(r);r.pages[id]={page_id:id,title:'新分析頁',visuals:{},visual_order:[]};order.push(id);},'replace_report',undefined,()=>{setPageId(id);setSelected('');setFilters([]);});}}>＋ 新增頁面</button>}
      {page&&<details className="page-controls"><summary>管理目前頁面</summary><fieldset disabled={busy||report?.report.read_only}>
        <label>頁面名稱<input key={pageId+report?.revision} maxLength={150} defaultValue={page.display_name||page.title} onBlur={e=>{const value=e.target.value.trim(),id=pageId;
          if(value&&value!==(page.display_name||page.title))edit(r=>{r.pages[id].title=value;r.pages[id].display_name=value;});}}/></label>
        <button disabled={pageIds.indexOf(pageId)===0} onClick={()=>movePage(-1)}>頁面上移</button>
        <button disabled={pageIds.indexOf(pageId)===pageIds.length-1} onClick={()=>movePage(1)}>頁面下移</button>
        <button onClick={()=>{const id=pageId;edit(()=>{},'duplicate_page',{page_id:id},next=>{
          const order=next.report.web_extensions?.page_order??Object.keys(next.report.pages);
          setPageId(order[order.indexOf(id)+1]);setSelected('');setFilters([]);
        });}}>複製目前頁面</button>
        <button disabled={pageIds.length<=1} onClick={()=>{const id=pageId;edit(r=>{if(Object.keys(r.pages).length<=1)return;
          const order=pageOrder(r);delete r.pages[id];r.web_extensions!.page_order=order.filter(key=>key!==id);});}}>刪除目前頁面（可復原）</button>
      </fieldset></details>}
      <div className="sidebar-bottom"><span className="online-dot"/> 本機分析引擎已連線<p>PYTHON · DUCKDB · REACT</p></div>
    </aside>
    <div className="main-area"><header className="topbar"><div className="breadcrumbs">工作區 <span>/</span> {mode==='data'?'資料管理':'分析報表'}</div>
      <div className="top-actions"><select aria-label="主題" value={theme} onChange={e=>setTheme(e.target.value)}>{Object.entries(THEMES).map(([id,title])=><option key={id} value={id}>{title}</option>)}</select><span className="avatar">BI</span></div></header>
      {error&&<div role="alert" className="banner error">{error}<button onClick={()=>setError('')} aria-label="關閉錯誤">×</button></div>}
      {notice&&<div role="status" className="banner success">{notice}<button onClick={()=>setNotice('')} aria-label="關閉通知">×</button></div>}
      {!wid?<section className="welcome"><p className="eyebrow">YOUR NEXT INSIGHT STARTS HERE</p><h1>從一個問題開始，<br/>看見資料裡的答案。</h1><p>選擇製程示範，或帶入自己的資料，建立可追溯的分析報表。</p><button className="primary" onClick={()=>setShowNew(true)}>＋ 建立第一個工作區</button></section>:
      <><section className="report-heading"><div><div className="eyebrow">{mode==='data'?'DATA WORKSPACE':'OVERVIEW / 即時探索'}</div>
        <h1>{mode==='data'?'你的資料，清楚可見。':report?.report.title??'正在開啟工作區…'}</h1>
        <p>{mode==='data'?'檢視來源、確認欄位，再將資料帶入分析。':`${datasets.length} 個資料來源 · ${page?.visual_order.length??0} 個視覺元件 · 每個數字都有依據`}</p></div>
        <div className="report-actions">{mode==='explore'&&report&&<><span className="save-state">{busy?'正在同步…':report.dirty?'草稿已恢復保存 · 尚未建立保存點':'所有變更已保存'}</span>
          <button disabled={!report.can_undo||busy||report.report.read_only} onClick={()=>edit(()=>{},'undo')} title="復原">↶</button><button disabled={!report.can_redo||busy||report.report.read_only} onClick={()=>edit(()=>{},'redo')} title="重做">↷</button>
          {report.report.read_only&&<span>唯讀報表</span>}
          <button className="primary" disabled={busy||report.report.read_only} onClick={()=>edit(()=>{},'save')}>保存報表</button>
          <button disabled={busy} onClick={()=>setShowPublications(true)}>發布與版本</button>
          <select aria-label="匯出報表" value="" disabled={busy||exporting} onChange={e=>void exportReport(e.target.value as 'xlsx'|'pdf'|'json'|'csv')}>
            <option value="" disabled>{exporting?'正在匯出…':'匯出報表'}</option><option value="csv">CSV (ZIP)</option><option value="xlsx">Excel</option><option value="pdf">PDF</option><option value="json">JSON</option>
          </select></>}</div></section>
      {mode==='data'?<section className="data-workspace"><div className="section-title"><h2>資料來源 <span>{datasets.length}</span></h2>
        <button className="primary" disabled={busy} onClick={()=>fileInput.current?.click()}>＋ 匯入資料</button>
        <input ref={fileInput} type="file" hidden accept=".csv,.json,.xlsx,.xls" disabled={busy} onChange={e=>{if(e.target.files?.[0])void upload(e.target.files[0]);e.target.value='';}}/></div>
        {importDrafts.length>0&&<section className="import-drafts"><h2>待確認的匯入</h2>{importDrafts.map(item=><button key={item.import_id} disabled={busy}
          onClick={()=>void api<Draft>(`/workspaces/${wid}/imports/${item.import_id}`).then(setDraft).catch(announceError)}>
          繼續匯入 {item.name} · {item.status==='validated'?'可確認':item.status==='invalid'?'需修正':'待驗證'}</button>)}</section>}
        <div className="source-grid">{datasets.map(ds=><button key={ds.dataset_id} className="source-card" onClick={()=>setPreview(ds.dataset_id)}>
          <span className="source-icon">▦</span><h3>{ds.contract.description||ds.contract.block_id}</h3><p>{ds.contract.columns.length} 個欄位 · {ds.contract.metrics.length} 個指標</p><small>{ds.status==='ready'?'● 已就緒':ds.status} · {ds.version.slice(0,8)}</small></button>)}</div>
        {!datasets.length&&<div className="empty-state">匯入 CSV、Excel 或 JSON，開始建立分析。</div>}
        {preview&&<DatasetPreview key={wid+preview} workspaceId={wid} datasetId={preview}/>}</section>:
      <div className="explore-body"><section className="canvas-area"><div className="canvas-toolbar"><div><span className="live-pill">{querying?'◌ 更新分析中':'● 資料探索'}</span>{querying&&Object.keys(results).length>0&&<small>暫時顯示上次結果</small>}</div>
        <button disabled={busy||!datasets.length||report?.report.read_only} onClick={startAdd}>＋ 新增圖表</button></div>
        {filterBookmarkId&&<p role="status">正在使用書籤「{activeFilterBookmark?.name}」的持久篩選。<button onClick={()=>setFilterBookmark(null)}>回到報表條件</button></p>}
        {Object.keys(drillState).length>0&&<p><button onClick={()=>setDrillState({})}>清除全部鑽取</button></p>}
        {report&&filterReport&&page&&<FilterPanel key={'filters-'+report.report_id} report={filterReport} datasets={sourceDatasets} pageId={pageId} selectedId={selected}
          busy={busy} onCommand={(kind,payload)=>edit(()=>{},kind,payload)}/>}
        {report&&page&&<BookmarkPanel key={'bookmarks-'+report.report_id} report={report.report} datasets={sourceDatasets}
          view={{page_id:pageId,selected_visual_id:page.visuals[selected]?selected:null,filters,filter_bookmark_id:filterBookmarkId,drill_state:Object.fromEntries(Object.entries(drillState).filter(([id])=>Object.hasOwn(page.visuals,id)))}} busy={busy}
          onCommand={(kind,payload)=>edit(()=>{},kind,payload)} onApply={id=>void applyBookmark(id)}/>}
        {report&&<SpcPanel key={JSON.stringify([wid,report.report_id,sourceDatasets.map(d=>d.version)])}
          base={`/workspaces/${wid}/reports/${report.report_id}`} revision={report.revision} datasets={sourceDatasets}
          selected={selected} bookmark={filterBookmarkId} pageId={pageId} filters={filters}
          definitions={report.report.web_extensions?.spc_analyses??[]} disabled={busy||report.report.read_only}
          onCommand={(kind,payload)=>edit(()=>{},kind,payload)} onSelect={setSelected}
          drill={Object.fromEntries(Object.entries(drillState).filter(([id])=>page&&Object.hasOwn(page.visuals,id)))}/>}
        {report&&<CommonalityPanel key={'commonality-'+JSON.stringify([wid,report.report_id,sourceDatasets.map(d=>d.version)])}
          base={`/workspaces/${wid}/reports/${report.report_id}`} revision={report.revision} datasets={sourceDatasets}
          selected={selected} bookmark={filterBookmarkId} pageId={pageId} filters={filters}
          definitions={report.report.web_extensions?.commonality_analyses??[]} disabled={busy||report.report.read_only}
          onCommand={(kind,payload)=>edit(()=>{},kind,payload)} onSelect={setSelected}
          drill={Object.fromEntries(Object.entries(drillState).filter(([id])=>page&&Object.hasOwn(page.visuals,id)))}/>}
        {report&&<CrossFactPanel key={'crossfact-'+JSON.stringify([wid,report.report_id,sourceDatasets.map(d=>d.version)])}
          base={`/workspaces/${wid}/reports/${report.report_id}`} revision={report.revision} datasets={sourceDatasets}
          definitions={report.report.web_extensions?.crossfact_analyses??[]} disabled={busy||report.report.read_only}
          onCommand={(kind,payload)=>edit(()=>{},kind,payload)} onSelect={setSelected}
          selected={selected} bookmark={filterBookmarkId} pageId={pageId} filters={filters}
          drill={Object.fromEntries(Object.entries(drillState).filter(([id])=>page&&Object.hasOwn(page.visuals,id)))}/>}
        {report&&page&&<ChangeAnalysisPanel key={'change-'+JSON.stringify([wid,report.report_id])}
          base={`/workspaces/${wid}/reports/${report.report_id}`} revision={report.revision}
          datasets={datasets.filter(d=>Object.values(page.visuals).some(v=>v.query.block_refs.some(b=>b.block_id===d.contract.block_id)))}
          definitions={report.report.web_extensions?.change_analyses??[]} disabled={busy||report.report.read_only}
          onCommand={(kind,payload)=>edit(()=>{},kind,payload)} onSelect={setSelected}
          selected={selected} bookmark={filterBookmarkId} pageId={pageId} filters={filters}
          drill={Object.fromEntries(Object.entries(drillState).filter(([id])=>Object.hasOwn(page.visuals,id)))}/>}
        {report&&page&&<RfmPanel key={'rfm-'+JSON.stringify([wid,report.report_id])}
          definitions={report.report.web_extensions?.rfm_analyses??[]} readOnly={report.report.read_only}
          onCommand={(kind,payload)=>edit(()=>{},kind,payload)} onSelect={setSelected}
          base={`/workspaces/${wid}/reports/${report.report_id}`} revision={report.revision}
          datasets={datasets.filter(d=>Object.values(page.visuals).some(v=>v.query.block_refs.some(b=>b.block_id===d.contract.block_id)))}
          disabled={busy} selected={selected} bookmark={filterBookmarkId} pageId={pageId} filters={filters}
          drill={Object.fromEntries(Object.entries(drillState).filter(([id])=>Object.hasOwn(page.visuals,id)))}/>}
        {report&&<ScenarioEditor key={report.report_id} value={report.report.web_extensions} datasets={sourceDatasets}
          disabled={busy||report.report.read_only} onChange={value=>edit(r=>{r.web_extensions=value;})}
          onScenario={(kind,payload)=>edit(()=>{},kind,payload)}/>}
        {filters.length>0&&<div className="filter-strip"><span>目前選取</span>{filters.map((f,i)=><button key={i} onClick={()=>setFilters(filters.filter((_,j)=>i!==j))}>{f.column_name}：{String(f.value)} ×</button>)}<button onClick={()=>setFilters([])}>清除全部</button></div>}
        <div className="canvas-grid">{page?.visual_order.map((id,index)=>{const v=page.visuals[id];return <article key={id} tabIndex={0}
          className={`visual-card ${selected===id?'is-selected':''}`} style={{gridColumn:`span ${v.col_span}`}} onClick={()=>setSelected(id)}
          onKeyDown={e=>{if(e.target===e.currentTarget&&(e.key==='Enter'||e.key===' ')){e.preventDefault();setSelected(id);}}}
          onDragOver={e=>e.preventDefault()} onDrop={e=>{e.preventDefault();const from=page.visual_order.indexOf(dragged.current);if(from>=0&&from!==index)move(dragged.current,index-from);}}>
          <div className="visual-title"><button className="drag-handle" disabled={busy||report?.report.read_only} draggable={!busy&&!report?.report.read_only} onDragStart={()=>dragged.current=id} aria-label="拖曳圖表">⠿</button><h3>{v.visualization.title||v.query.metrics[0]?.metric_name}</h3>
            <button onClick={()=>setSelected(id)} aria-label={`編輯 ${v.visualization.title}`}>···</button></div>
          <ChartBoundary key={id+v.visualization.visual_type}><DrillChart visual={v} result={results[id]} state={drillState[id]} busy={busy||querying} onChange={value=>setDrillState(previous=>{if(value)return {...previous,[id]:value};const next={...previous};delete next[id];return next;})} onFilter={f=>setFilters(prev=>[...prev.filter(x=>x.source_visual_id!==f.source_visual_id),f])}/></ChartBoundary>
          {results[id]?.truncated&&<p className="muted">結果已達顯示上限，請縮小分析範圍。</p>}
        </article>;})}</div>
        {page&&!page.visual_order.length&&<div className="empty-state"><div>◫</div><h2>建立你的第一張圖表</h2><p>從想觀察的指標開始，挑選拆解角度。</p><button disabled={!datasets.length} onClick={datasets.length?startAdd:()=>setMode('data')}>{datasets.length?'＋ 選擇指標':'先匯入資料'}</button></div>}
        <section className="assistant-card"><div className="assistant-heading"><span>✧</span><div><h2>用一句話，深入資料</h2><p>詢問原因、比較差異，或調整選取的圖表。</p></div><small>{selected?'作用範圍：選取圖表':'作用範圍：目前報表'}</small></div>
          {Object.hasOwn(drillState,selected)&&<p>AI 將套用選取圖表的鑽取條件：全部{drillState[selected].path.map(step=>` › ${step.value==null?'（空值）':String(step.value)}`).join('')}。</p>}
          {Object.hasOwn(drillState,selected)&&<small>作用來源：{sourceDatasets.find(d=>d.contract.block_id===drillState[selected].block_id)?.contract.description||drillState[selected].block_id}</small>}
          <form onSubmit={e=>{e.preventDefault();void ask();}}><textarea aria-label="分析問題" placeholder="例如：哪台設備的等待時間最長？" value={prompt} onChange={e=>setPrompt(e.target.value)} rows={2}/>
            <button className="primary" disabled={asking||!prompt.trim()}>{asking?'正在分析…':'開始分析 →'}</button></form>
          <div className="suggestions">{['各設備的平均等待時間','良率最低的產品','把圖表改成折線圖'].map(text=><button key={text} onClick={()=>setPrompt(text)}>{text}</button>)}</div>
          {answer&&<div className="answer"><p>{answer.direct_answer?.sentence||answer.message}</p>{answer.disambiguation&&<p>{answer.disambiguation}</p>}
            {answer.drill_context&&<p>這次回答使用路徑：全部{answer.drill_context.path.map(step=>` › ${step.value==null?'（空值）':String(step.value)}`).join('')} · {answer.drill_context.hierarchy[answer.drill_context.path.length]}</p>}
            {answer.drill_context&&<small>路徑作用來源：{sourceDatasets.find(d=>d.contract.block_id===answer.drill_context!.block_id)?.contract.description||answer.drill_context.block_id}</small>}
            {answer.result_table&&<DataTable result={answer.result_table}/>}<small>{answer.trust_notes?.join(' · ')}</small>
            {answer.candidate_report&&<button disabled={busy||report?.report.read_only} onClick={()=>edit(()=>{},'apply_proposal',{job_id:answerJob})}>套用此變更</button>}</div>}</section>
      </section><aside className="inspector"><div className="inspector-title"><h2>視覺設定</h2><span>◫</span></div>
        {!visual?<div className="inspector-empty">選取圖表，調整指標、外觀與排列。</div>:<>
          <fieldset className="visual-controls" disabled={busy||report?.report.read_only}>
          <label>圖表標題<input key={selected+'title'+report?.revision} defaultValue={visual.visualization.title} onBlur={e=>{const value=e.target.value;if(value!==visual.visualization.title)updateVisual(v=>v.visualization.title=value);}}/></label>
          <label>圖表類型<select value={visual.visualization.extra.chart_mode==='histogram'?'histogram':visual.visualization.visual_type} onChange={e=>{const value=e.target.value;
            const source=datasets.find(d=>d.contract.block_id===visual.query.block_refs[0]?.block_id);
            const numeric=source?.contract.columns.filter(c=>['integer','float','number','decimal','double'].includes(c.data_type)&&c.name!=='__row_count');
            const field=numeric?.find(c=>visual.query.dimensions.some(d=>d.column_name===c.name))??numeric?.[0];
            if(value==='histogram'&&!field){setError('此資料來源沒有可用的數值欄位。');return;}
            updateVisual(v=>{v.visualization.visual_type=value==='histogram'?'bar_chart':value;
              if(value==='histogram'){v.visualization.extra.chart_mode='histogram';v.visualization.extra.bins=20;delete v.visualization.extra.postprocess;delete v.visualization.extra.drill_hierarchy;
                v.query.metrics=[];v.query.dimensions=[{block_id:source!.contract.block_id,column_name:field!.name,alias:field!.name}];v.query.sort=[];v.query.having=[];
              }else if(v.visualization.extra.chart_mode==='histogram'){delete v.visualization.extra.chart_mode;if(!v.query.metrics.length&&source?.contract.metrics[0]){
                const metric=source.contract.metrics[0];let alias=metric.name;while(v.query.dimensions.some(d=>(d.alias??d.column_name)===alias))alias+='_metric';
                v.query.metrics=[{block_id:source.contract.block_id,metric_name:metric.name,alias}];}}
            });}}>{Object.entries(CHARTS).map(([id,name])=><option value={id} key={id}>{name}</option>)}</select></label>
          <div className="field-well"><span>觀察指標</span>{visual.query.metrics.map((m,index)=><div key={index}>
            <select aria-label={`指標 ${index+1}`} value={m.metric_name} disabled={busy||visual.query.having?.some(h=>h.block_id===m.block_id&&h.metric_name===m.metric_name)} title="有聚合篩選的指標須先移除相關條件" onChange={e=>{const value=e.target.value;updateVisual(v=>{
              v.query.metrics[index]={...v.query.metrics[index],metric_name:value,alias:value};v.query.sort=[];
            });}}>{datasets.find(d=>d.contract.block_id===m.block_id)?.contract.metrics.map(metric=><option key={metric.name} value={metric.name}>{metric.name}</option>)}</select>
            <button aria-label={`移除指標 ${index+1}`} disabled={busy||visual.query.metrics.length<=1||visual.query.having?.some(h=>h.block_id===m.block_id&&h.metric_name===m.metric_name)} onClick={()=>updateVisual(v=>{v.query.metrics.splice(index,1);v.query.sort=[];})}>×</button>
          </div>)}
          <select aria-label="新增指標" value="" disabled={busy} onChange={e=>{const [block_id,metric_name]=JSON.parse(e.target.value) as string[];updateVisual(v=>v.query.metrics.push({block_id,metric_name,alias:metric_name}));}}>
            <option value="">＋ 新增指標</option>{datasets.filter(d=>visual.query.block_refs.some(b=>b.block_id===d.contract.block_id)).flatMap(d=>d.contract.metrics.filter(m=>!visual.query.metrics.some(x=>x.block_id===d.contract.block_id&&x.metric_name===m.name)).map(m=><option key={d.dataset_id+m.name} value={JSON.stringify([d.contract.block_id,m.name])}>{m.name}</option>))}
          </select></div>
          <div className="field-well"><span>拆解維度</span>{visual.query.dimensions.map((d,index)=><div key={index}>◇　{d.alias||d.column_name}
            {datasets.some(source=>source.contract.block_id===d.block_id&&source.contract.columns.some(c=>c.name===d.column_name&&['date','datetime','timestamp'].includes(c.data_type.toLowerCase())))&&<label>日期粒度<select aria-label={`日期粒度 ${index+1}`} disabled={busy} value={d.truncate_date_to?.toLowerCase()??''} onChange={e=>{const grain=e.target.value;updateVisual(v=>{v.query.dimensions[index].truncate_date_to=grain||null;});}}>
              <option value="">原始日期／時間</option><option value="day">日</option><option value="week">週（週一開始）</option><option value="month">月</option><option value="quarter">季</option><option value="year">年</option><option value="weekday">星期</option><option value="hour">一天中的小時</option>
              {['dow','dayofweek'].includes(d.truncate_date_to?.toLowerCase()??'')&&<option value={d.truncate_date_to?.toLowerCase()}>星期</option>}
            </select><small>以 UTC 分組；分組值暫不支援點選篩選。</small></label>}
            <button aria-label={`移除維度 ${index+1}`} disabled={busy} onClick={()=>updateVisual(v=>{v.query.dimensions.splice(index,1);v.query.sort=[];})}>×</button></div>)}
          <select aria-label="新增維度" value="" disabled={busy} onChange={e=>{const [block_id,column_name]=JSON.parse(e.target.value) as string[];updateVisual(v=>v.query.dimensions.push({block_id,column_name,alias:column_name}));}}>
            <option value="">＋ 新增維度</option>{datasets.filter(d=>visual.query.block_refs.some(b=>b.block_id===d.contract.block_id)).flatMap(d=>d.contract.columns.filter(c=>c.name!=='__row_count'&&!visual.query.dimensions.some(x=>x.block_id===d.contract.block_id&&x.column_name===c.name)).map(c=><option key={d.dataset_id+c.name} value={JSON.stringify([d.contract.block_id,c.name])}>{c.name}</option>))}
          </select></div>
          <AggregateFilterEditor visual={visual} busy={busy} onChange={filters=>updateVisual(v=>v.query.having=filters)}/>
          <DrillEditor visual={visual} datasets={sourceDatasets} busy={busy} onChange={hierarchy=>{updateVisual(v=>v.visualization.extra.drill_hierarchy=hierarchy);setDrillState(previous=>{const next={...previous};delete next[selected];return next;});}}/>
          {visual.visualization.visual_type==='kpi_card'&&<KpiSettings key={selected+'kpi'+report?.revision} visual={visual} datasets={datasets} onSave={(extra,sparkline)=>updateVisual(v=>{v.visualization.extra=extra;v.visualization.show_sparkline=sparkline;})}/>}
          <label>圖表高度<input type="number" min={120} max={1600} step={20} key={selected+'height'+report?.revision} defaultValue={visual.visualization.height_px}
            onBlur={e=>{const height=Number(e.target.value);if(height!==visual.visualization.height_px&&height>=120&&height<=1600)updateVisual(v=>v.visualization.height_px=height);}}/></label>
          <label>圖表寬度<select value={visual.col_span} onChange={e=>{const value=Number(e.target.value);updateVisual(v=>v.col_span=value);}}><option value={4}>三分之一</option><option value={6}>二分之一</option><option value={12}>整列</option></select></label>
          <label>圖表顏色<input type="color" value={String(visual.visualization.extra.color??'#2874a6')} onChange={e=>{const value=e.target.value;updateVisual(v=>v.visualization.extra.color=value);}}/></label>
          {['bar_chart','line_chart'].includes(visual.visualization.visual_type)&&visual.visualization.extra.chart_mode!=='histogram'&&<>
            {visual.visualization.visual_type==='bar_chart'&&<>
              <label>長條方向<select value={String(visual.visualization.extra.orientation??'vertical')} onChange={e=>{const value=e.target.value;updateVisual(v=>v.visualization.extra.orientation=value);}}><option value="vertical">直向</option><option value="horizontal">橫向</option></select></label>
              <label>長條排列<select value={String(visual.visualization.extra.bar_mode??(visual.query.dimensions.length>1?'stack':'group'))} onChange={e=>{const value=e.target.value;updateVisual(v=>v.visualization.extra.bar_mode=value);}}><option value="group">並排</option><option value="stack">堆疊</option><option value="overlay">重疊</option></select></label>
              {visual.visualization.extra.orientation==='horizontal'&&<p className="muted">橫向長條會交換兩軸：下列縱軸標題、刻度與上下限套用於數值橫軸，橫軸標題套用於分類縱軸。</p>}
            </>}
            <label>橫軸標題<input key={selected+'x-title'+report?.revision} defaultValue={String(visual.visualization.x_axis_label??'')} onBlur={e=>{const value=e.target.value;if(value!==String(visual.visualization.x_axis_label??''))updateVisual(v=>v.visualization.x_axis_label=value);}}/></label>
            <label>縱軸標題<input key={selected+'y-title'+report?.revision} defaultValue={String(visual.visualization.y_axis_label??'')} onBlur={e=>{const value=e.target.value;if(value!==String(visual.visualization.y_axis_label??''))updateVisual(v=>v.visualization.y_axis_label=value);}}/></label>
            <label>縱軸刻度<select value={String(visual.visualization.extra.y_scale??'linear')} onChange={e=>{const value=e.target.value;updateVisual(v=>v.visualization.extra.y_scale=value);}}><option value="linear">線性</option><option value="log">對數</option></select></label>
            {(['y_min','y_max'] as const).map(field=><label key={field}>{field==='y_min'?'縱軸下限':'縱軸上限'}<input type="number" step="any" placeholder="自動" key={selected+field+report?.revision} defaultValue={String(visual.visualization.extra[field]??'')} onBlur={e=>{const raw=e.target.value,value=raw===''?null:Number(raw);if(value!==null&&!Number.isFinite(value)){setError('軸界限須為有限數字。');return;}if(value!==(visual.visualization.extra[field]??null))updateVisual(v=>{if(value===null)delete v.visualization.extra[field];else v.visualization.extra[field]=value;});}}/></label>)}
            <label>圖例位置<select value={String(visual.visualization.extra.legend_position??'')} onChange={e=>{const value=e.target.value;updateVisual(v=>{if(value)v.visualization.extra.legend_position=value;else delete v.visualization.extra.legend_position;});}}><option value="">自動</option><option value="top">上方</option><option value="bottom">下方</option><option value="left">左側</option><option value="right">右側</option><option value="hide">隱藏</option></select></label>
            <label><input type="checkbox" checked={visual.visualization.extra.data_labels===true} onChange={e=>{const value=e.target.checked;updateVisual(v=>v.visualization.extra.data_labels=value);}}/>顯示資料標籤</label>
            <label>資料標籤格式<input key={selected+'number-format'+report?.revision} defaultValue={String(visual.visualization.extra.number_format??',.0f')} onBlur={e=>{const value=e.target.value;if(value!==String(visual.visualization.extra.number_format??',.0f'))updateVisual(v=>v.visualization.extra.number_format=value);}}/></label>
            <label>基準線<select value={String(visual.visualization.extra.baseline??'')} onChange={e=>{const value=e.target.value;updateVisual(v=>{if(value){v.visualization.extra.baseline=value;if(value==='custom'&&v.visualization.extra.baseline_value==null)v.visualization.extra.baseline_value=0;}else delete v.visualization.extra.baseline;});}}><option value="">不顯示</option><option value="mean">第一指標平均值</option><option value="custom">自訂數值</option></select></label>
            {visual.visualization.extra.baseline==='custom'&&<label>自訂基準值<input type="number" step="any" key={selected+'baseline-value'+report?.revision} defaultValue={Number(visual.visualization.extra.baseline_value??0)} onBlur={e=>{const value=Number(e.target.value);if(e.target.value===''||!Number.isFinite(value)){setError('自訂基準值須為有限數字。');return;}if(value!==visual.visualization.extra.baseline_value)updateVisual(v=>v.visualization.extra.baseline_value=value);}}/></label>}
          </>}
          {visual.visualization.visual_type==='small_multiples'&&<>
            <label>每列分面數<select value={Number(visual.visualization.extra.facet_wrap??3)} onChange={e=>{const value=Number(e.target.value);updateVisual(v=>v.visualization.extra.facet_wrap=value);}}>{[1,2,3,4,5,6].map(n=><option key={n} value={n}>{n}</option>)}</select></label>
            <label><input type="checkbox" checked={visual.visualization.extra.facet_shared_y===true} onChange={e=>{const value=e.target.checked;updateVisual(v=>v.visualization.extra.facet_shared_y=value);}}/>共用分面縱軸</label>
          </>}
          <div className="inline-actions"><button disabled={busy} onClick={()=>move(selected,-1)}>↑ 上移</button><button disabled={busy} onClick={()=>move(selected,1)}>↓ 下移</button></div>
          {visual.visualization.visual_type==='map'&&<label>地圖範圍<select value={String(visual.visualization.extra.map_view??'auto')} onChange={e=>{const value=e.target.value;updateVisual(v=>v.visualization.extra.map_view=value);}}><option value="auto">符合資料範圍</option><option value="taiwan">台灣周邊</option><option value="world">世界</option></select></label>}
          {visual.visualization.visual_type==='scatter'&&<label>散點大小欄位<select value={String(visual.visualization.extra.size_col??'')} onChange={e=>{const value=e.target.value;updateVisual(v=>{if(value)v.visualization.extra.size_col=value;else delete v.visualization.extra.size_col;});}}><option value="">固定大小</option>{visual.query.metrics.map(m=><option key={m.alias??m.metric_name} value={m.alias??m.metric_name}>{m.alias??m.metric_name}</option>)}</select></label>}
          {visual.visualization.visual_type==='scatter'&&<label>散點趨勢線<select value={String(visual.visualization.extra.trendline??'')} onChange={e=>{const value=e.target.value;updateVisual(v=>{if(value)v.visualization.extra.trendline=value;else delete v.visualization.extra.trendline;});}}><option value="">不顯示</option><option value="ols">OLS 線性迴歸</option><option value="lowess">LOWESS 局部平滑</option></select></label>}
          {visual.visualization.visual_type==='pie_chart'&&<>
            <label>圓環內徑<input type="number" min={0} max={.9} step={.05} key={selected+'hole'+report?.revision} defaultValue={Number(visual.visualization.extra.hole??.4)} onBlur={e=>{const hole=Number(e.target.value);if(!Number.isFinite(hole)||hole<0||hole>.9){setError('圓環內徑須介於 0 與 0.9。');return;}if(hole!==visual.visualization.extra.hole)updateVisual(v=>v.visualization.extra.hole=hole);}}/></label>
            <label><input type="checkbox" checked={visual.visualization.extra.show_percent!==false} onChange={e=>{const value=e.target.checked;updateVisual(v=>v.visualization.extra.show_percent=value);}}/>顯示切片百分比</label>
            <label><input type="checkbox" checked={visual.visualization.extra.data_labels===true} onChange={e=>{const value=e.target.checked;updateVisual(v=>v.visualization.extra.data_labels=value);}}/>顯示切片數值</label>
            <label>圓餅圖例位置<select value={String(visual.visualization.extra.legend_position??(visual.visualization.show_legend?'right':'hide'))} onChange={e=>{const value=e.target.value;updateVisual(v=>v.visualization.extra.legend_position=value);}}><option value="top">上方</option><option value="bottom">下方</option><option value="left">左側</option><option value="right">右側</option><option value="hide">隱藏</option></select></label>
          </>}
          {visual.visualization.extra.chart_mode==='histogram'&&<>
            <label>分布數值欄位<select value={visual.query.dimensions[0]?.column_name??''} onChange={e=>{const column_name=e.target.value;updateVisual(v=>{v.query.dimensions=[{block_id:v.query.block_refs[0].block_id,column_name,alias:column_name}];v.query.sort=[];});}}>{datasets.find(d=>d.contract.block_id===visual.query.block_refs[0]?.block_id)?.contract.columns.filter(c=>c.name!=='__row_count'&&['integer','float','number','decimal','double'].includes(c.data_type)).map(c=><option value={c.name} key={c.name}>{c.name}</option>)}</select></label>
            <label>直方圖分箱數<input type="number" min={1} max={200} step={1} key={selected+'bins'+report?.revision} defaultValue={Number(visual.visualization.extra.bins??20)} onBlur={e=>{const bins=Number(e.target.value);if(Number.isInteger(bins)&&bins>=1&&bins<=200&&bins!==visual.visualization.extra.bins)updateVisual(v=>v.visualization.extra.bins=bins);}}/></label>
          </>}
          <button className="danger-link" disabled={busy} onClick={()=>{edit(r=>{delete r.pages[pageId].visuals[selected];r.pages[pageId].visual_order=r.pages[pageId].visual_order.filter(id=>id!==selected);});setSelected('');}}>刪除此圖表</button>
          </fieldset><details className="lineage"><summary>數字從哪裡來？</summary><p>{results[selected]?.metadata?.blocks_used.join('、')}</p><pre>{JSON.stringify(results[selected]?.metadata?.metrics_used,null,2)}</pre></details>
        </>}<div className="inspector-note"><span>◇</span><p>查詢經資料契約驗證。調整外觀不會改變分析數字。</p></div></aside></div>}</>}
      <footer>AI4BI · 可信任的資料探索 <span>Local-first analytics</span></footer>
    </div>
    {showNew&&<Modal title="建立工作區" busy={busy} onClose={()=>setShowNew(false)}><h2>開始新的探索</h2><label>工作區名稱<input value={newTitle} onChange={e=>setNewTitle(e.target.value)}/></label><label>起始資料<select value={newTemplate} onChange={e=>setNewTemplate(e.target.value)}><option value="fab">半導體製程示範</option><option value="retail">零售分析示範</option><option value="cv">CV 資料集示範</option><option value="blank">空白工作區</option></select></label>{busy&&<p role="status">{newTemplate==='blank'?'正在建立工作區…':'正在準備示範資料並建立工作區…'}</p>}<div className="modal-actions"><button disabled={busy} onClick={()=>setShowNew(false)}>取消</button><button className="primary" disabled={busy||!newTitle.trim()} onClick={()=>void createWorkspace()}>建立工作區</button></div></Modal>}
    {adding&&<Modal title="新增圖表" busy={busy} onClose={()=>setAdding(false)}><h2>把資料變成圖表</h2>
      <label>資料來源<select value={newBlock} onChange={e=>{setNewBlock(e.target.value);setNewMetric(datasets.find(d=>d.contract.block_id===e.target.value)?.contract.metrics[0]?.name??'');setNewDim('');}}>{datasets.map(d=><option key={d.dataset_id} value={d.contract.block_id}>{d.contract.description||d.contract.block_id}</option>)}</select></label>
      {newKind!=='histogram'&&<label>觀察指標<select value={newMetric} onChange={e=>setNewMetric(e.target.value)}>{datasets.find(d=>d.contract.block_id===newBlock)?.contract.metrics.map(m=><option key={m.name} value={m.name}>{m.name}</option>)}</select></label>}
      <label>拆解維度<select value={newDim} onChange={e=>setNewDim(e.target.value)}><option value="">不拆解（整體）</option>{datasets.find(d=>d.contract.block_id===newBlock)?.contract.columns.filter(c=>c.name!=='__row_count'&&(newKind!=='histogram'||['integer','float','number','decimal','double'].includes(c.data_type))).map(c=><option key={c.name} value={c.name}>{c.name}</option>)}</select></label>
      <label>呈現方式<select value={newKind} onChange={e=>{const kind=e.target.value;setNewKind(kind);if(kind==='histogram'&&!datasets.find(d=>d.contract.block_id===newBlock)?.contract.columns.some(c=>c.name===newDim&&['integer','float','number','decimal','double'].includes(c.data_type)))setNewDim('');}}>{Object.entries(CHARTS).map(([id,name])=><option value={id} key={id}>{name}</option>)}</select></label>
      {newKind==='small_multiples'&&!newDim&&<p>小倍數圖需要選擇一個拆解維度作為分面。</p>}
      {newKind==='pivot'&&!newDim&&<p>樞紐表需要選擇一個拆解維度作為列。</p>}
      {newKind==='map'&&!newDim&&<p>地圖需要選擇地點維度，例如城市或縣市。</p>}
      {newKind==='histogram'&&<p>請選擇數值拆解維度；頻數由篩選後的原始資料計算。</p>}
      <div className="modal-actions"><button disabled={busy} onClick={()=>setAdding(false)}>取消</button><button className="primary" disabled={newKind!=='histogram'&&!newMetric||busy||['small_multiples','pivot','map','histogram'].includes(newKind)&&!newDim} onClick={addVisual}>加入報表</button></div></Modal>}
    {draft&&<Modal title="確認匯入" busy={busy} onClose={()=>setDraft(null)} wide><h2>確認資料 · {draft.name}</h2><p>{draft.details.row_count??0} 列 · {draft.status==='validated'?'全表解析已完成':'需要修正解析設定'}</p>
      {draft.details.error&&<p className="error">{draft.details.error}</p>}<label>文字編碼<select value={draft.config.encoding} onChange={e=>setDraft({...draft,config:{...draft.config,encoding:e.target.value},status:'pending'})}>{['utf-8-sig','utf-8','big5','cp950','latin-1'].map(x=><option key={x}>{x}</option>)}</select></label>
      <div className="column-settings">{draft.details.columns?.map(c=><label key={c.name}>{c.name}<select aria-label={c.name} value={draft.config.column_types[c.name]??''} onChange={e=>{const types={...draft.config.column_types};if(e.target.value)types[c.name]=e.target.value;else delete types[c.name];setDraft({...draft,status:'pending',config:{...draft.config,column_types:types}});}}><option value="">自動：{c.dtype}</option><option value="string">文字</option><option value="number">數值</option><option value="integer">整數</option><option value="date">日期</option></select></label>)}</div>
      {draft.details.rows&&<DataTable result={{columns:draft.details.columns?.map(c=>c.name),rows:draft.details.rows,status:'ready',row_count:draft.details.row_count}}/>}
      <div className="modal-actions"><button disabled={busy} onClick={()=>setDraft(null)}>稍後處理</button><button disabled={busy} onClick={()=>void validateDraft()}>重新驗證</button><button className="primary" disabled={busy||draft.status!=='validated'} onClick={()=>void confirmImport()}>確認匯入</button></div></Modal>}
    {showPublications&&report&&<PublicationPanel key={wid+report.report_id} wid={wid} rid={report.report_id} revision={report.revision}
      canPublish={!busy&&!report.report.read_only} onClose={()=>setShowPublications(false)}/>}
  </div>;
}
