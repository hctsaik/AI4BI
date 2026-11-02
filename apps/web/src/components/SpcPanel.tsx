import {useEffect,useLayoutEffect,useRef,useState} from 'react';
import {api,key,pollJob} from '../lib/api';
import type {Dataset,DrillState,Filter,SpcResult,SavedSpcAnalysis} from '../types';
import type {CommandKind} from '../lib/api';
import {SpcResultView} from './SpcResultView';

export function SpcPanel({base,revision,datasets,selected,bookmark,drill,filters,pageId,definitions,disabled,onCommand,onSelect}:{base:string;revision:number;
  datasets:Dataset[];selected:string;bookmark:string|null;drill:Record<string,DrillState>;filters:Filter[];pageId:string;
  definitions:SavedSpcAnalysis[];disabled:boolean;onCommand:(kind:CommandKind,payload:Record<string,unknown>)=>void;onSelect:(id:string)=>void}) {
  const sources=datasets.filter(d=>d.status==='ready'&&['fact','snapshot_fact','target_fact'].includes(d.contract.block_type??''));
  const [block,setBlock]=useState(sources[0]?.contract.block_id??'');
  const columns=sources.find(d=>d.contract.block_id===block)?.contract.columns??[];
  const [entity,setEntity]=useState('');
  const [value,setValue]=useState('');
  const [aggregation,setAggregation]=useState('mean');
  const [k,setK]=useState('3');
  const [name,setName]=useState('');
  const [savedId,setSavedId]=useState('');
  const saved=definitions.find(item=>item.analysis_id===savedId&&item.page_id===pageId);
  const [result,setResult]=useState<SpcResult|null>(null);
  const [error,setError]=useState('');
  const [busy,setBusy]=useState(false);
  const task=useRef<{abort:AbortController;id:string}|null>(null);
  function cancel(){const current=task.current;if(!current)return;current.abort.abort();
    if(current.id)void api(`/jobs/${current.id}/cancel`,{}).catch(()=>{});task.current=null;}
  useEffect(()=>()=>cancel(),[]);
  function reset(){cancel();setBusy(false);setResult(null);setError('');}
  const contextScope=JSON.stringify([revision,pageId,selected,bookmark,drill,filters]);
  useLayoutEffect(()=>{reset();},[contextScope]);
  function applySaved(){if(!saved)return;reset();setBlock(saved.block_id);setEntity(saved.entity_column);
    setValue(saved.value_column);setAggregation(saved.aggregation);setK(String(saved.k));setName(saved.name);
    onSelect(saved.selected_component_id??'');}
  const validSettings=!!block&&!!entity&&!!value&&Number.isFinite(Number(k))&&Number(k)>0&&Number(k)<=10;
  const settings={block_id:block,entity_column:entity,value_column:value,aggregation,k:Number(k)};
  function saveSettings(update=false){reset();onCommand(update?'update_spc_analysis':'save_spc_analysis',{
    ...(update?{analysis_id:saved!.analysis_id}:{name:name.trim()}),settings,page_id:pageId,selected_component_id:selected||null});}
  async function run(){
    if(task.current)return;
    const current={abort:new AbortController(),id:''};task.current=current;setBusy(true);setResult(null);setError('');
    try{
      const accepted=await api<{job_id:string}>(`${base}/analyses/spc`,{idempotency_key:key(),base_revision:revision,
        block_id:block,entity_column:entity,value_column:value,k:Number(k),aggregation,
        selected_component_id:selected||null,filter_bookmark_id:bookmark,drill_state:drill,filters,exploration_page_id:pageId});
      current.id=accepted.job_id;
      if(current.abort.signal.aborted){void api(`/jobs/${current.id}/cancel`,{}).catch(()=>{});return;}
      const next=await pollJob<SpcResult>(current.id,current.abort.signal);
      if(task.current===current)setResult(next);
    }catch(e){if(task.current===current)setError(e instanceof Error?e.message:'SPC 分析未完成。');}
    finally{if(task.current===current){task.current=null;setBusy(false);}}
  }
  return <details className="spc-panel"><summary>SPC 跨實體離群掃描</summary>
    <p>依實體聚合後，以 μ±kσ 掃描離群值。使用目前頁面、報表、書籤及選取圖表的保存篩選與鑽取範圍，並套用選取資料來源的臨時跨圖篩選。</p>
    {filters.length>0&&<p>目前有 {filters.length} 個跨圖條件；掃描會套用其中屬於選取資料來源的條件，包括從選取圖表點選的分類。</p>}
    <fieldset><legend>保存 SPC 設定</legend>
      <p>保存欄位、聚合、倍數及本頁圖表範圍。套用後使用目前探索條件重新掃描；臨時篩選與鑽取可另存為書籤。</p>
      <label>本頁 SPC 設定<select value={saved?.analysis_id??''} onChange={e=>{setSavedId(e.target.value);setName(definitions.find(item=>item.analysis_id===e.target.value)?.name??'');}}>
        <option value="">選擇已保存設定</option>{definitions.filter(item=>item.page_id===pageId).map(item=><option key={item.analysis_id} value={item.analysis_id}>{item.name}</option>)}</select></label>
      <button type="button" disabled={!saved} onClick={applySaved}>套用 SPC 設定</button>
      <label>SPC 設定名稱<input maxLength={80} value={name} onChange={e=>setName(e.target.value)}/></label>
      <button type="button" disabled={disabled||!validSettings||!name.trim()} onClick={()=>saveSettings()}>另存 SPC 設定</button>
      <button type="button" disabled={disabled||!saved||!validSettings} onClick={()=>saveSettings(true)}>更新 SPC 設定</button>
      <button type="button" disabled={disabled||!saved||!name.trim()} onClick={()=>onCommand('rename_spc_analysis',{analysis_id:saved!.analysis_id,name:name.trim()})}>重新命名 SPC 設定</button>
      <button type="button" disabled={disabled||!saved} onClick={()=>onCommand('delete_spc_analysis',{analysis_id:saved!.analysis_id})}>刪除 SPC 設定（可復原）</button>
    </fieldset>
    <form onSubmit={e=>{e.preventDefault();void run();}}>
      <label>SPC 資料來源<select value={block} onChange={e=>{reset();setBlock(e.target.value);setEntity('');setValue('');}}>
        {sources.map(d=><option key={d.dataset_id} value={d.contract.block_id}>{d.contract.description||d.contract.block_id}</option>)}</select></label>
      <label>SPC 實體欄位<select value={entity} onChange={e=>{reset();setEntity(e.target.value);}} required><option value="">選擇機台、批次等實體</option>
        {columns.filter(c=>c.name!==value).map(c=><option key={c.name}>{c.name}</option>)}</select></label>
      <label>SPC 數值欄位<select value={value} onChange={e=>{reset();setValue(e.target.value);}} required><option value="">選擇量測數值</option>
        {columns.filter(c=>c.name!==entity&&/^(integer|int|int32|int64|float|float32|float64|double|number|numeric|decimal)$/i.test(c.data_type)).map(c=><option key={c.name}>{c.name}</option>)}</select></label>
      <label>SPC 聚合方式<select value={aggregation} onChange={e=>{reset();setAggregation(e.target.value);}}><option value="mean">平均</option><option value="sum">合計</option></select></label>
      <label>SPC 標準差倍數<input type="number" min="0.01" max="10" step="any" required value={k} onChange={e=>{reset();setK(e.target.value);}}/></label>
      <button className="primary" disabled={busy||!block||!entity||!value||!Number.isFinite(Number(k))||Number(k)<=0||Number(k)>10}>{busy?'SPC 分析中…':'執行 SPC 掃描'}</button>
      {busy&&<button type="button" onClick={reset}>取消 SPC 分析</button>}
    </form>
    {error&&<p role="alert">{error}</p>}
    {result&&<SpcResultView result={result}/>}
  </details>;
}
