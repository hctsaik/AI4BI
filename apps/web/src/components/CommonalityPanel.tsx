import {CommonalityResultView} from './CommonalityResultView';
import {useEffect,useLayoutEffect,useRef,useState} from 'react';
import {api,key,pollJob} from '../lib/api';
import type {Dataset,DrillState,Filter,SavedCommonalityAnalysis,CommonalityResult} from '../types';
import type {CommandKind} from '../lib/api';


export function CommonalityPanel({base,revision,datasets,selected,bookmark,drill,filters,pageId,definitions,disabled,onCommand,onSelect}:{
  base:string;revision:number;datasets:Dataset[];selected:string;bookmark:string|null;
  drill:Record<string,DrillState>;filters:Filter[];pageId:string;definitions:SavedCommonalityAnalysis[];disabled:boolean;
  onCommand:(kind:CommandKind,payload:Record<string,unknown>)=>void;onSelect:(id:string)=>void}){
  const sources=datasets.filter(d=>d.status==='ready'&&['fact','snapshot_fact','target_fact'].includes(d.contract.block_type??''));
  const [settings,setSettings]=useState({block_id:'',outcome_block_id:'',entity_column:'',group_column:'',
    outcome_group_column:'',value_column:'',threshold:'',aggregation:'mean',comparison:'lt'});
  const [result,setResult]=useState<CommonalityResult|null>(null);
  const [error,setError]=useState('');
  const [busy,setBusy]=useState(false);
  const [name,setName]=useState('');
  const [savedId,setSavedId]=useState('');
  const saved=definitions.find(item=>item.analysis_id===savedId&&item.page_id===pageId);
  const task=useRef<{abort:AbortController;id:string}|null>(null);
  function cancel(){const current=task.current;if(!current)return;current.abort.abort();
    if(current.id)void api(`/jobs/${current.id}/cancel`,{}).catch(()=>{});task.current=null;}
  useEffect(()=>()=>cancel(),[]);
  function reset(){cancel();setBusy(false);setResult(null);setError('');}
  const scope=JSON.stringify([revision,pageId,selected,bookmark,drill,filters]);
  useLayoutEffect(()=>{reset();},[scope]);
  function change(field:keyof typeof settings,value:string){reset();setSettings(previous=>({...previous,[field]:value,
    ...(field==='block_id'?{entity_column:'',group_column:''}:{}),
    ...(field==='outcome_block_id'?{value_column:'',outcome_group_column:''}:{})}));}
  const detailColumns=sources.find(d=>d.contract.block_id===settings.block_id)?.contract.columns??[];
  const outcomeColumns=sources.find(d=>d.contract.block_id===settings.outcome_block_id)?.contract.columns??[];
  const valid=Object.values(settings).every(Boolean)&&Number.isFinite(Number(settings.threshold))&&
    settings.entity_column!==settings.group_column&&settings.outcome_group_column!==settings.value_column;
  function save(update=false){reset();onCommand(update?'update_commonality_analysis':'save_commonality_analysis',{
    ...(update?{analysis_id:saved!.analysis_id}:{name:name.trim()}),
    settings:{...settings,threshold:Number(settings.threshold)},page_id:pageId,selected_component_id:selected||null});}
  function apply(){if(!saved)return;reset();setName(saved.name);
    setSettings({block_id:saved.block_id,outcome_block_id:saved.outcome_block_id,entity_column:saved.entity_column,
      group_column:saved.group_column,outcome_group_column:saved.outcome_group_column,value_column:saved.value_column,
      threshold:String(saved.threshold),aggregation:saved.aggregation,comparison:saved.comparison});
    onSelect(saved.selected_component_id??'');}
  async function run(){if(task.current||!valid)return;
    const current={abort:new AbortController(),id:''};task.current=current;setBusy(true);setResult(null);setError('');
    try{const accepted=await api<{job_id:string}>(`${base}/analyses/commonality`,{
      ...settings,threshold:Number(settings.threshold),idempotency_key:key(),base_revision:revision,
      selected_component_id:selected||null,filter_bookmark_id:bookmark,drill_state:drill,filters,exploration_page_id:pageId});
      current.id=accepted.job_id;
      if(current.abort.signal.aborted){void api(`/jobs/${current.id}/cancel`,{}).catch(()=>{});return;}
      const next=await pollJob<CommonalityResult>(current.id,current.abort.signal);
      if(task.current===current)setResult(next);
    }catch(e){if(task.current===current)setError(e instanceof Error?e.message:'共同性分析未完成。');}
    finally{if(task.current===current){task.current=null;setBusy(false);}}
  }
  function sourceSelect(field:'block_id'|'outcome_block_id',label:string){return <label>{label}<select required value={settings[field]} onChange={e=>change(field,e.target.value)}>
    <option value="">選擇來源</option>{sources.map(d=><option key={d.dataset_id} value={d.contract.block_id}>{d.contract.description||d.contract.block_id}</option>)}</select></label>;}
  function columnSelect(field:'entity_column'|'group_column'|'outcome_group_column'|'value_column',label:string,columns:Dataset['contract']['columns']){
    return <label>{label}<select required value={settings[field]} onChange={e=>change(field,e.target.value)}><option value="">選擇欄位</option>
      {columns.map(c=><option key={c.name}>{c.name}</option>)}</select></label>;}
  return <details className="commonality-panel"><summary>共同性分析</summary>
    <p>比較低良率等目標群體共同經過的機台。兩個來源使用同一種批號或晶圓識別欄位，各自套用目前頁面、保存篩選與探索條件，再取可對齊群體。</p>
    <fieldset><legend>保存共同性設定</legend>
      <p>保存來源、群體鍵、門檻及本頁圖表範圍。套用時使用目前探索條件；臨時篩選與鑽取請另存書籤。</p>
      <label>本頁共同性設定<select value={saved?.analysis_id??''} onChange={e=>{setSavedId(e.target.value);setName(definitions.find(item=>item.analysis_id===e.target.value)?.name??'');}}>
        <option value="">選擇已保存設定</option>{definitions.filter(item=>item.page_id===pageId).map(item=><option key={item.analysis_id} value={item.analysis_id}>{item.name}</option>)}</select></label>
      <button type="button" disabled={!saved} onClick={apply}>套用共同性設定</button>
      <label>共同性設定名稱<input maxLength={80} value={name} onChange={e=>setName(e.target.value)}/></label>
      <button type="button" disabled={disabled||!valid||!name.trim()} onClick={()=>save()}>另存共同性設定</button>
      <button type="button" disabled={disabled||!saved||!valid} onClick={()=>save(true)}>更新共同性設定</button>
      <button type="button" disabled={disabled||!saved||!name.trim()} onClick={()=>onCommand('rename_commonality_analysis',{analysis_id:saved!.analysis_id,name:name.trim()})}>重新命名共同性設定</button>
      <button type="button" disabled={disabled||!saved} onClick={()=>onCommand('delete_commonality_analysis',{analysis_id:saved!.analysis_id})}>刪除共同性設定（可復原）</button>
    </fieldset>
    <form onSubmit={e=>{e.preventDefault();void run();}}>
      {sourceSelect('block_id','共同性曝光來源')}
      {columnSelect('entity_column','共同性實體欄位',detailColumns.filter(c=>c.name!==settings.group_column))}
      {columnSelect('group_column','曝光群體識別欄位',detailColumns.filter(c=>c.name!==settings.entity_column))}
      {sourceSelect('outcome_block_id','共同性結果來源')}
      {columnSelect('outcome_group_column','結果群體識別欄位',outcomeColumns.filter(c=>c.name!==settings.value_column))}
      {columnSelect('value_column','共同性結果數值欄位',outcomeColumns.filter(c=>c.name!==settings.outcome_group_column&&/^(integer|int|int32|int64|float|float32|float64|double|number|numeric|decimal)$/i.test(c.data_type)))}
      <label>共同性聚合方式<select value={settings.aggregation} onChange={e=>change('aggregation',e.target.value)}><option value="mean">平均</option><option value="sum">合計</option></select></label>
      <label>目標群體條件<select value={settings.comparison} onChange={e=>change('comparison',e.target.value)}><option value="lt">小於</option><option value="lte">小於等於</option><option value="gt">大於</option><option value="gte">大於等於</option></select></label>
      <label>共同性門檻<input required type="number" step="any" value={settings.threshold} onChange={e=>change('threshold',e.target.value)}/></label>
      <p>門檻使用來源欄位的原始單位。例如 yield_pct 為 0–100 時，80% 請輸入 80。</p>
      <button className="primary" disabled={busy||!valid}>{busy?'共同性分析中…':'執行共同性分析'}</button>
      {busy&&<button type="button" onClick={reset}>取消共同性分析</button>}
    </form>
    {error&&<p role="alert">{error}</p>}
    {result&&<CommonalityResultView result={result}/>}
  </details>;
}
