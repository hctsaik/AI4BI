import {RfmResultView} from './RfmResultView';
import type {RfmResult} from '../types';
import {ChangeResultView} from './ChangeResultView';
import {CrossFactResultView} from './CrossFactResultView';
import {CommonalityResultView} from './CommonalityResultView';
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { api, downloadArtifact, key, pollJob } from '../lib/api';
import type { DrillState, ExplorationView, Filter, Report, Result, SpcResult, CommonalityResult, CrossFactResult, ChangeResult } from '../types';
import { SpcResultView } from './SpcResultView';
import { BookmarkPanel } from './BookmarkPanel';
import { DrillChart } from './DrillControls';
import { FilterPanel } from './FilterPanel';
import { Modal } from './Modal';
import { ChartBoundary } from './VisualChart';

type PublicationSummary = {publication_id:string;published_revision:number;source_revision:number;created_at:string;runtime_compatible?:boolean;runtime_message?:string|null};
type Publication = PublicationSummary & {report:Report;as_of:string;data_versions:Record<string,string>;runtime_compatible:boolean;runtime_message:string|null;
  checks:{visual_count:number;checked_at:string;truncated_visuals:string[];spc_analyses?:Record<string,unknown>;commonality_analyses?:Record<string,unknown>;crossfact_analyses?:Record<string,unknown>;change_analyses?:Record<string,unknown>}};

export function PublicationPanel({wid,rid,revision,canPublish,onClose}: {
  wid:string;rid:string;revision:number;canPublish:boolean;onClose:()=>void;
}) {
  const base=`/workspaces/${wid}/reports/${rid}/publications`;
  const [items,setItems]=useState<PublicationSummary[]>([]);
  const [selected,setSelected]=useState('');
  const [publication,setPublication]=useState<Publication|null>(null);
  const [pageId,setPageId]=useState('');
  const [drillState,setDrillState] = useState<Record<string,DrillState>>({});
  const [filters,setFilters]=useState<Filter[]>([]);
  const [filterBookmarkId,setFilterBookmark] = useState<string|null>(null);
  const [results,setResults]=useState<Record<string,Result>>({});
  const [commonalityResults,setCommonalityResults]=useState<Record<string,CommonalityResult>>({});
  const [crossfactResults,setCrossfactResults]=useState<Record<string,CrossFactResult>>({});
  const [rfmResults,setRfmResults]=useState<Record<string,RfmResult>>({});
  const [changeResults,setChangeResults]=useState<Record<string,ChangeResult>>({});
  const [spcResults,setSpcResults]=useState<Record<string,SpcResult>>({});
  const [loading,setLoading]=useState(false);
  const [publishing,setPublishing]=useState(false);
  const [exporting,setExporting]=useState(false);
  const [jobId,setJobId]=useState('');
  const [error,setError]=useState('');
  const [applyingBookmark,setApplyingBookmark]=useState(false);
  const viewRef=useRef('');
  viewRef.current=JSON.stringify({selected,pageId,filters,filterBookmarkId,drillState});
  const alive=useRef(true);
  const lifecycle=useRef(new AbortController());
  const fail=(e:unknown)=>{if(alive.current&&!(e instanceof DOMException&&e.name==='AbortError'))setError(e instanceof Error?e.message:String(e));};
  useEffect(()=>{
    alive.current=true;lifecycle.current=new AbortController();
    void api<PublicationSummary[]>(base,undefined,undefined,lifecycle.current.signal).then(value=>{
      if(alive.current){setItems(value);setSelected(value[0]?.publication_id??'');}
    }).catch(fail);
    return()=>{alive.current=false;lifecycle.current.abort();};
  },[base]);
  useEffect(()=>{
    setPublication(null);setResults({});setSpcResults({});setCommonalityResults({});setCrossfactResults({});setChangeResults({});setRfmResults({});setFilters([]);setDrillState({});setFilterBookmark(null);
    if(!selected)return;
    const abort=new AbortController();
    void api<Publication>(`${base}/${selected}`,undefined,undefined,abort.signal).then(value=>{
      if(!abort.signal.aborted){setPublication(value);setPageId(value.report.web_extensions?.page_order?.[0]??Object.keys(value.report.pages)[0]);}
    }).catch(e=>{if(!abort.signal.aborted)fail(e);});
    return()=>abort.abort();
  },[base,selected]);
  const page=publication?.report.pages[pageId];
  const bookmarkConditions=publication?.report.web_extensions?.bookmarks?.find(b=>b.bookmark_id===filterBookmarkId)?.persistent_filters;
  const filterReport=publication&&bookmarkConditions!=null?{...publication.report,
    web_extensions:{...publication.report.web_extensions!,persistent_filters:bookmarkConditions}}:publication?.report;
  useLayoutEffect(()=>{
    setResults({});setSpcResults({});setCommonalityResults({});setCrossfactResults({});setChangeResults({});setRfmResults({});
    if(!publication||!page||!publication.runtime_compatible){setLoading(false);return;}
    if(!page.visual_order.length&&!publication.report.web_extensions?.spc_analyses?.length&&!publication.report.web_extensions?.commonality_analyses?.length&&!publication.report.web_extensions?.crossfact_analyses?.length&&!publication.report.web_extensions?.change_analyses?.length&&!publication.report.web_extensions?.rfm_analyses?.length){setLoading(false);return;}
    const abort=new AbortController();let queryJob='';setLoading(true);
    const cancel=()=>{if(queryJob)void api(`/jobs/${queryJob}/cancel`,{}).catch(()=>{});};
    void api<{job_id:string}>(`${base}/${publication.publication_id}/queries`,{
      idempotency_key:key(),base_revision:publication.source_revision,visual_ids:page.visual_order,filters,exploration_page_id:pageId,filter_bookmark_id:filterBookmarkId,drill_state:drillState,include_spc:true,include_commonality:true,include_crossfact:true,include_change:true,include_rfm:true})
      .then(job=>{queryJob=job.job_id;if(abort.signal.aborted)cancel();return pollJob<{visuals:Record<string,Result>;spc_analyses:Record<string,SpcResult>;commonality_analyses:Record<string,CommonalityResult>;crossfact_analyses:Record<string,CrossFactResult>;change_analyses:Record<string,ChangeResult>;rfm_analyses:Record<string,RfmResult>}>(job.job_id,abort.signal);})
      .then(value=>{if(!abort.signal.aborted){setResults(value.visuals);setSpcResults(value.spc_analyses??{});setCommonalityResults(value.commonality_analyses??{});setCrossfactResults(value.crossfact_analyses??{});setChangeResults(value.change_analyses??{});setRfmResults(value.rfm_analyses??{});}})
      .catch(e=>{if(!abort.signal.aborted)fail(e);})
      .finally(()=>{if(!abort.signal.aborted)setLoading(false);});
    return()=>{abort.abort();cancel();};
  },[base,publication,pageId,filters,filterBookmarkId,drillState]);
  async function publish() {
    if(publishing||!canPublish)return;
    setPublishing(true);setError('');
    try {
      const job=await api<{job_id:string}>(base,{idempotency_key:key(),base_revision:revision});
      if(alive.current)setJobId(job.job_id);
      const result=await pollJob<{publication_id:string}>(job.job_id,lifecycle.current.signal);
      const next=await api<PublicationSummary[]>(base,undefined,undefined,lifecycle.current.signal);
      if(alive.current){setItems(next);setSelected(result.publication_id);}
    }catch(e){fail(e);}finally{if(alive.current){setPublishing(false);setJobId('');}}
  }
  async function download(format:string) {
    if(!publication||!publication.runtime_compatible||exporting)return;
    setExporting(true);setError('');
    try{
      const job=await api<{job_id:string}>(`${base}/${publication.publication_id}/exports`,{
        idempotency_key:key(),base_revision:publication.source_revision,format,filters,exploration_page_id:pageId,filter_bookmark_id:filterBookmarkId,drill_state:drillState});
      const result=await pollJob<{artifact_id:string;filename:string}>(job.job_id,lifecycle.current.signal);
      if(!alive.current)return;
      await downloadArtifact(result.artifact_id,result.filename,lifecycle.current.signal);
    }catch(e){fail(e);}finally{if(alive.current)setExporting(false);}
  }
  async function applyBookmark(id:string) {
    if(!publication||!publication.runtime_compatible||applyingBookmark)return;
    const previous=viewRef.current;
    setApplyingBookmark(true);setError('');
    try{
      const resolved=await api<{revision:number;view:ExplorationView}>(`${base}/${publication.publication_id}/bookmarks/${encodeURIComponent(id)}?base_revision=${publication.source_revision}`,undefined,undefined,lifecycle.current.signal);
      if(alive.current&&viewRef.current===previous){setPageId(resolved.view.page_id);setFilters(resolved.view.filters);setDrillState(resolved.view.drill_state??{});setFilterBookmark(resolved.view.filter_bookmark_id??null);}
    }catch(e){if(viewRef.current===previous)fail(e);}finally{if(alive.current)setApplyingBookmark(false);}
  }
  return <Modal title="發布與版本" wide onClose={onClose}>
    <section className="publication-panel"><div className="section-title"><h2>發布與版本</h2><button onClick={onClose}>關閉發布檢視</button></div>
      <p>將目前草稿建立為本機唯讀版本，固定全部頁面與資料。發布前會驗證全部圖表；關閉視窗後已接受的發布任務仍會繼續。</p>
      <div className="inline-actions"><button className="primary" disabled={publishing||!canPublish} onClick={()=>void publish()}>
        {publishing?'正在驗證與發布…':`發布目前草稿（修訂 ${revision}）`}</button>
        {publishing&&jobId&&<button onClick={()=>void api(`/jobs/${jobId}/cancel`,{}).catch(fail)}>取消發布</button>}</div>
      {error&&<p role="alert" className="error">{error}</p>}
      <label>已發布版本<select aria-label="已發布版本" value={selected} onChange={e=>{setError('');setSelected(e.target.value);}}>
        {!items.length&&<option value="">尚無發布版本</option>}
        {items.map(item=><option key={item.publication_id} value={item.publication_id}>版本 {item.published_revision} · 來源修訂 {item.source_revision} · {new Date(item.created_at).toLocaleString()}{item.runtime_compatible===false?' · 執行環境不相容':''}</option>)}
      </select></label>
      {publication&&<><h3>{publication.report.title} · 發布版本 {publication.published_revision}</h3>
        {!publication.runtime_compatible&&<p role="alert" className="error">{publication.runtime_message}</p>}
        <p className="muted">唯讀版本 · {publication.checks.visual_count} 個圖表、{Object.keys(publication.checks.spc_analyses??{}).length} 組 SPC 通過檢查 · {Object.keys(publication.data_versions).length} 個固定資料版本</p>
        {Object.keys(publication.checks.commonality_analyses??{}).length>0&&<p>共同性分析 {Object.keys(publication.checks.commonality_analyses??{}).length} 組通過檢查</p>}
        {Object.keys(publication.checks.crossfact_analyses??{}).length>0&&<p>跨表分析 {Object.keys(publication.checks.crossfact_analyses??{}).length} 組通過檢查</p>}
        <div className="inline-actions"><label>發布頁面<select aria-label="發布頁面" value={pageId} onChange={e=>{setPageId(e.target.value);setFilters([]);}}>
          {(publication.report.web_extensions?.page_order??Object.keys(publication.report.pages)).map(id=><option key={id} value={id}>{publication.report.pages[id].display_name||publication.report.pages[id].title}</option>)}</select></label>
          <label>匯出發布版本<select aria-label="匯出發布版本" value="" disabled={exporting||!publication.runtime_compatible} onChange={e=>void download(e.target.value)}>
            <option value="" disabled>{exporting?'正在匯出…':'選擇格式'}</option><option value="csv">CSV (ZIP)</option><option value="xlsx">Excel</option><option value="pdf">PDF</option><option value="json">JSON</option>
          </select></label></div>
        {filters.length>0&&<div className="filter-bar"><span>探索篩選：{filters.map(f=>`${f.column_name} = ${String(f.value)}`).join('、')}</span><button onClick={()=>setFilters([])}>清除發布檢視篩選</button></div>}
        {filterBookmarkId&&<p role="status">正在使用書籤的持久篩選。<button onClick={()=>setFilterBookmark(null)}>回到報表條件</button></p>}
        {Object.keys(drillState).length>0&&<p><button onClick={()=>setDrillState({})}>清除全部鑽取</button></p>}
        {page&&filterReport&&<FilterPanel key={'filters-'+publication.publication_id} report={filterReport} datasets={[]} pageId={pageId} selectedId="" busy={loading} onCommand={()=>{}}/>}
        {page&&<BookmarkPanel key={publication.publication_id} report={publication.report}
          view={{page_id:pageId,selected_visual_id:null,filters,filter_bookmark_id:filterBookmarkId,drill_state:Object.fromEntries(Object.entries(drillState).filter(([id])=>Object.hasOwn(page.visuals,id)))}} busy={loading||applyingBookmark||!publication.runtime_compatible}
          onCommand={()=>{}} onApply={id=>void applyBookmark(id)}/>}
        {loading&&<p role="status">正在查詢固定版本…</p>}
        <div className="canvas-grid">{publication.runtime_compatible&&page?.visual_order.map(id=>{
          const visual=page.visuals[id];return <article className="visual-card" key={publication.publication_id+id} style={{gridColumn:`span ${visual.col_span}`}}>
            <h3>{visual.visualization.title||id}</h3><ChartBoundary key={id+JSON.stringify(filters)}>
              <DrillChart visual={visual} result={results[id]} state={drillState[id]} busy={loading} onChange={value=>setDrillState(previous=>{if(value)return {...previous,[id]:value};const next={...previous};delete next[id];return next;})} onFilter={f=>setFilters([f])}/>
            </ChartBoundary>
          </article>;
        })}</div>
        {!loading&&publication.runtime_compatible&&Object.values(rfmResults).filter(result=>result.page_id===pageId).map(result=>
          <div className="rfm-panel" key={publication.publication_id+result.analysis_id}><RfmResultView result={result} title={result.name}/></div>)}
        {!loading&&publication.runtime_compatible&&Object.values(changeResults).filter(result=>result.page_id===pageId).map(result=>
          <div className="change-panel" key={publication.publication_id+result.analysis_id}><ChangeResultView result={result} title={result.name}/></div>)}
        {!loading&&publication.runtime_compatible&&Object.values(crossfactResults).filter(result=>result.page_id===pageId).map(result=>
          <div className="crossfact-panel" key={publication.publication_id+result.analysis_id}><CrossFactResultView result={result} title={result.name}/></div>)}
        {!loading&&publication.runtime_compatible&&Object.values(commonalityResults).filter(result=>result.page_id===pageId).map(result=>
          <div className="commonality-panel" key={publication.publication_id+result.analysis_id}><CommonalityResultView result={result} title={result.name}/></div>)}
        {!loading&&publication.runtime_compatible&&Object.values(spcResults).filter(result=>result.page_id===pageId).map(result=>
          <div className="spc-panel" key={publication.publication_id+result.analysis_id}><SpcResultView result={result} title={result.name}/></div>)}
        <details><summary>發布檢查與資料版本</summary><p>快照時間：{new Date(publication.as_of).toLocaleString()}</p>
          <p>已通過全部圖表查詢與資料檔案校驗。{publication.checks.truncated_visuals.length>0?'部分圖表超過顯示筆數上限，檢視中會標明。':''}</p>
          <ul>{Object.entries(publication.data_versions).map(([id,hash])=><li key={id}>{id}：<code>{hash}</code></li>)}</ul></details>
      </>}
    </section>
  </Modal>;
}
