import {ChangeResultView} from './ChangeResultView';
import {useEffect,useLayoutEffect,useRef,useState} from 'react';
import {api,key,pollJob} from '../lib/api';
import type {CommandKind} from '../lib/api';
import type {ChangeResult,Dataset,DrillState,Filter,SavedChangeAnalysis} from '../types';

export function ChangeAnalysisPanel({base,revision,datasets,selected,bookmark,drill,filters,pageId,definitions,disabled,onCommand,onSelect}:{
  base:string;revision:number;datasets:Dataset[];selected:string;bookmark:string|null;
  drill:Record<string,DrillState>;filters:Filter[];pageId:string;definitions:SavedChangeAnalysis[];disabled:boolean;
  onCommand:(kind:CommandKind,payload:Record<string,unknown>)=>void;onSelect:(id:string)=>void}){
  const sources=datasets.filter(d=>d.status==='ready'&&['fact','snapshot_fact','target_fact'].includes(d.contract.block_type??''));
  const [settings,setSettings]=useState({block_id:'',metric_name:'',date_column:'',dimension_column:'',period:'month',filter_policy:'replace',anchor:''});
  const [result,setResult]=useState<ChangeResult|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const [savedId,setSavedId]=useState(''),[name,setName]=useState('');
  const saved=definitions.find(item=>item.analysis_id===savedId&&item.page_id===pageId);
  const task=useRef<{abort:AbortController;id:string}|null>(null);
  function cancel(){const current=task.current;if(!current)return;current.abort.abort();
    if(current.id)void api(`/jobs/${current.id}/cancel`,{}).catch(()=>{});task.current=null;}
  function reset(){cancel();setBusy(false);setResult(null);setError('');}
  useEffect(()=>()=>cancel(),[]);
  const scope=JSON.stringify([base,revision,pageId,selected,bookmark,drill,filters,datasets.map(d=>[d.dataset_id,d.version,d.status,d.contract.metrics])]);
  useLayoutEffect(()=>{reset();},[scope]);
  const source=sources.find(d=>d.contract.block_id===settings.block_id);
  const dates=source?.contract.columns.filter(c=>/^(date|datetime|timestamp)$/i.test(c.data_type))??[];
  const groups=source?.contract.columns.filter(c=>c.name!==settings.date_column&&/^(string|str|object|integer|int|int32|int64|boolean|bool)$/i.test(c.data_type))??[];
  const valid=source?.contract.metrics.some(m=>m.name===settings.metric_name)&&dates.some(c=>c.name===settings.date_column)&&groups.some(c=>c.name===settings.dimension_column);
  function change(field:keyof typeof settings,value:string){reset();setSettings(previous=>({...previous,[field]:value,
    ...(field==='block_id'?{metric_name:'',date_column:'',dimension_column:''}:{})}));}
  function save(update=false){reset();onCommand(update?'update_change_analysis':'save_change_analysis',{
    ...(update?{analysis_id:saved!.analysis_id}:{name:name.trim()}),page_id:pageId,selected_component_id:selected||null,
    settings:{...settings,anchor:settings.anchor||null}});}
  function apply(){if(!saved)return;reset();setName(saved.name);
    setSettings({block_id:saved.block_id,metric_name:saved.metric_name,date_column:saved.date_column,
      dimension_column:saved.dimension_column,period:saved.period,filter_policy:saved.filter_policy,anchor:saved.anchor??''});
    onSelect(saved.selected_component_id??'');}
  async function run(){if(task.current||!valid)return;
    const current={abort:new AbortController(),id:''};task.current=current;setBusy(true);setResult(null);setError('');
    try{const accepted=await api<{job_id:string}>(`${base}/analyses/change`,{...settings,anchor:settings.anchor||null,
      idempotency_key:key(),base_revision:revision,selected_component_id:selected||null,filter_bookmark_id:bookmark,
      drill_state:drill,filters,exploration_page_id:pageId});
      current.id=accepted.job_id;
      if(current.abort.signal.aborted){void api(`/jobs/${current.id}/cancel`,{}).catch(()=>{});return;}
      const next=await pollJob<ChangeResult>(current.id,current.abort.signal);if(task.current===current)setResult(next);
    }catch(e){if(task.current===current)setError(e instanceof Error?e.message:'變化拆解未完成。');}
    finally{if(task.current===current){task.current=null;setBusy(false);}}
  }
  return <details className="change-analysis-panel"><summary>變化拆解</summary>
    <fieldset><legend>保存變化拆解設定</legend>
      <p>保存指標、期間與本頁圖表範圍；臨時篩選及鑽取請另存書籤。發布與匯出會重新執行全部保存設定，保留完整分析結果。</p>
      <label>本頁變化拆解設定<select value={saved?.analysis_id??''} onChange={e=>{setSavedId(e.target.value);setName(definitions.find(item=>item.analysis_id===e.target.value)?.name??'');}}>
        <option value="">選擇已保存設定</option>{definitions.filter(item=>item.page_id===pageId).map(item=><option key={item.analysis_id} value={item.analysis_id}>{item.name}</option>)}</select></label>
      <button type="button" disabled={!saved} onClick={apply}>套用變化拆解設定</button>
      <label>變化拆解設定名稱<input maxLength={80} value={name} onChange={e=>setName(e.target.value)}/></label>
      <button type="button" disabled={disabled||!valid||!name.trim()} onClick={()=>save()}>另存變化拆解設定</button>
      <button type="button" disabled={disabled||!valid||!saved} onClick={()=>save(true)}>更新變化拆解設定</button>
      <button type="button" disabled={disabled||!saved||!name.trim()} onClick={()=>onCommand('rename_change_analysis',{analysis_id:saved!.analysis_id,name:name.trim()})}>重新命名變化拆解設定</button>
      <button type="button" disabled={disabled||!saved} onClick={()=>onCommand('delete_change_analysis',{analysis_id:saved!.analysis_id})}>刪除變化拆解設定（可復原）</button>
    </fieldset>
    <p>比較兩個等長期間，依類別查看增減。使用本頁保存條件、所選圖表條件及目前探索／鑽取範圍；HAVING、Top-N 與圖表後處理不裁切分析群體。</p>
    <form onSubmit={e=>{e.preventDefault();void run();}}>
      <label>變化拆解來源<select required value={settings.block_id} onChange={e=>change('block_id',e.target.value)}>
        <option value="">選擇來源</option>{sources.map(d=><option key={d.dataset_id} value={d.contract.block_id}>{d.contract.description||d.contract.block_id}</option>)}</select></label>
      <label>變化拆解指標<select required value={settings.metric_name} onChange={e=>change('metric_name',e.target.value)}>
        <option value="">選擇指標</option>{source?.contract.metrics.map(m=><option key={m.name} value={m.name}>{m.description||m.name}</option>)}</select></label>
      <label>變化拆解日期欄位<select required value={settings.date_column} onChange={e=>change('date_column',e.target.value)}>
        <option value="">選擇日期</option>{dates.map(c=><option key={c.name}>{c.name}</option>)}</select></label>
      <label>變化拆解維度<select required value={settings.dimension_column} onChange={e=>change('dimension_column',e.target.value)}>
        <option value="">選擇類別</option>{groups.map(c=><option key={c.name}>{c.name}</option>)}</select></label>
      <label>變化拆解期間<select value={settings.period} onChange={e=>change('period',e.target.value)}>
        <option value="week">最近 7 天與前 7 天</option><option value="month">最近 30 天與前 30 天</option>
        <option value="quarter">最近 90 天與前 90 天</option><option value="year">最近 365 天與前 365 天</option></select></label>
      <label>變化拆解日期篩選<select value={settings.filter_policy} onChange={e=>change('filter_policy',e.target.value)}>
        <option value="replace">比較視窗取代日期條件</option><option value="keep">保留日期條件並與視窗取交集</option></select></label>
      <label>變化拆解截止日（留空使用篩選內最新日期）<input type="date" value={settings.anchor} onChange={e=>change('anchor',e.target.value)}/></label>
      <p>日期以 UTC 日界計算；30／90／365 天是等長視窗。比率與平均值以整體指標重新計算，缺期顯示「—」。</p>
      <button disabled={!valid||busy}>執行變化拆解</button>{busy&&<button type="button" onClick={reset}>取消變化拆解</button>}
    </form>
    {error&&<p role="alert">{error}</p>}{busy&&<p role="status">變化拆解執行中…</p>}
    {result&&<ChangeResultView result={result}/>}
  </details>;
}
