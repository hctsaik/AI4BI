import {RfmResultView} from './RfmResultView';
import type {RfmResult as Result} from '../types';
import {useEffect,useLayoutEffect,useRef,useState} from 'react';
import {api,key,pollJob} from '../lib/api';
import type {Dataset,DrillState,Filter,SavedRfmAnalysis} from '../types';
import type {CommandKind} from '../lib/api';
import type {components} from '../generated/api';

type Settings=Pick<components['schemas']['RfmRequest'],'block_id'|'customer_column'|'date_column'|'monetary_column'|'anchor'>;


export function RfmPanel({base,revision,datasets,selected,bookmark,drill,filters,pageId,disabled,readOnly,definitions,onCommand,onSelect}:{
  base:string;revision:number;datasets:Dataset[];selected:string;bookmark:string|null;
  drill:Record<string,DrillState>;filters:Filter[];pageId:string;disabled:boolean;readOnly:boolean;definitions:SavedRfmAnalysis[];
  onCommand:(kind:CommandKind,payload:Record<string,unknown>)=>void;onSelect:(id:string)=>void}){
  const [settings,setSettings]=useState<Settings>({block_id:'',customer_column:'',date_column:'',monetary_column:'',anchor:''});
  const [result,setResult]=useState<Result|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const task=useRef<{abort:AbortController;id:string}|null>(null);
  const [savedId,setSavedId]=useState(''),[name,setName]=useState('');
  const saved=definitions.find(item=>item.analysis_id===savedId&&item.page_id===pageId);
  function cancel(){const current=task.current;if(!current)return;current.abort.abort();
    if(current.id)void api(`/jobs/${current.id}/cancel`,{}).catch(()=>{});task.current=null;}
  function reset(){cancel();setBusy(false);setResult(null);setError('');}
  useEffect(()=>()=>cancel(),[]);
  const scope=JSON.stringify([base,revision,pageId,selected,bookmark,drill,filters,datasets]);
  useLayoutEffect(()=>{reset();},[scope]);
  const sources=datasets.filter(d=>d.status==='ready'&&['fact','snapshot_fact','target_fact'].includes(d.contract.block_type??''));
  const source=sources.find(d=>d.contract.block_id===settings.block_id);
  const fields={customer_column:source?.contract.columns.filter(c=>/^(string|str|object|integer|int|int32|int64)$/i.test(c.data_type))??[],
    date_column:source?.contract.columns.filter(c=>/^(date|datetime|timestamp)$/i.test(c.data_type))??[],
    monetary_column:source?.contract.columns.filter(c=>/^(number|numeric|decimal|float|float32|float64|double|integer|int|int32|int64)$/i.test(c.data_type))??[]};
  const valid=source&&settings.anchor&&Object.entries(fields).every(([field,columns])=>columns.some(c=>c.name===settings[field as keyof Settings]))
    &&new Set([settings.customer_column,settings.date_column,settings.monetary_column]).size===3;
  function change(field:keyof Settings,value:string){reset();setSettings(previous=>({...previous,[field]:value,
    ...(field==='block_id'?{customer_column:'',date_column:'',monetary_column:''}:{})}));}
  function save(update=false){reset();onCommand(update?'update_rfm_analysis':'save_rfm_analysis',{
    ...(update?{analysis_id:saved!.analysis_id}:{name:name.trim()}),page_id:pageId,selected_component_id:selected||null,settings});}
  function apply(){if(!saved)return;reset();setName(saved.name);setSettings({block_id:saved.block_id,
    customer_column:saved.customer_column,date_column:saved.date_column,monetary_column:saved.monetary_column,anchor:saved.anchor});
    onSelect(saved.selected_component_id??'');}
  async function run(){if(task.current||!valid||disabled)return;
    const current={abort:new AbortController(),id:''};task.current=current;setBusy(true);setResult(null);setError('');
    try{const accepted=await api<{job_id:string}>(`${base}/analyses/rfm`,{...settings,idempotency_key:key(),base_revision:revision,
      selected_component_id:selected||null,filter_bookmark_id:bookmark,drill_state:drill,filters,exploration_page_id:pageId});
      current.id=accepted.job_id;
      if(current.abort.signal.aborted){void api(`/jobs/${current.id}/cancel`,{}).catch(()=>{});return;}
      const next=await pollJob<Result>(current.id,current.abort.signal);if(task.current===current)setResult(next);
    }catch(e){if(task.current===current)setError(e instanceof Error?e.message:'RFM 分析未完成。');}
    finally{if(task.current===current){task.current=null;setBusy(false);}}
  }
  return <details className="rfm-panel"><summary>RFM 客群分析</summary>
    <fieldset><legend>保存 RFM 設定</legend>
      <label>本頁 RFM 設定<select value={saved?.analysis_id??''} onChange={e=>{setSavedId(e.target.value);setName(definitions.find(item=>item.analysis_id===e.target.value)?.name??'');}}>
        <option value="">選擇已保存設定</option>{definitions.filter(item=>item.page_id===pageId).map(item=><option key={item.analysis_id} value={item.analysis_id}>{item.name}</option>)}</select></label>
      <button type="button" disabled={!saved} onClick={apply}>套用 RFM 設定</button>
      <label>RFM 設定名稱<input maxLength={80} value={name} onChange={e=>setName(e.target.value)}/></label>
      <button type="button" disabled={disabled||readOnly||!valid||!name.trim()} onClick={()=>save()}>另存 RFM 設定</button>
      <button type="button" disabled={disabled||readOnly||!valid||!saved} onClick={()=>save(true)}>更新 RFM 設定</button>
      <button type="button" disabled={disabled||readOnly||!saved||!name.trim()} onClick={()=>onCommand('rename_rfm_analysis',{analysis_id:saved!.analysis_id,name:name.trim()})}>重新命名 RFM 設定</button>
      <button type="button" disabled={disabled||readOnly||!saved} onClick={()=>onCommand('delete_rfm_analysis',{analysis_id:saved!.analysis_id})}>刪除 RFM 設定（可復原）</button>
    </fieldset>
    <p>以客戶最近購買日、不同購買日數及累計淨額分群。使用本頁、所選圖表、探索篩選與鑽取範圍；圖表 Top-N 不限制客戶母體。</p>
    <form onSubmit={e=>{e.preventDefault();void run();}}>
      <label>RFM 資料來源<select required value={settings.block_id} onChange={e=>change('block_id',e.target.value)}>
        <option value="">選擇來源</option>{sources.map(d=><option key={d.dataset_id} value={d.contract.block_id}>{d.contract.description||d.contract.block_id}</option>)}</select></label>
      {(Object.keys(fields) as (keyof typeof fields)[]).map(field=><label key={field}>
        {{customer_column:'RFM 客戶欄位',date_column:'RFM 日期欄位',monetary_column:'RFM 金額欄位'}[field]}
        <select required value={settings[field]} onChange={e=>change(field,e.target.value)}><option value="">選擇欄位</option>
          {fields[field].map(c=><option key={c.name}>{c.name}</option>)}</select></label>)}
      <label>RFM 截止日<input required type="date" value={settings.anchor} onChange={e=>change('anchor',e.target.value)}/></label>
      <button disabled={!valid||busy||disabled}>執行 RFM 分析</button>{busy&&<button type="button" onClick={reset}>取消 RFM 分析</button>}
    </form>
    <p>以 UTC 日界計算，截止日之後的交易排除；退款計入淨額。流失風險是最近購買時間的相對分位，不是流失機率。</p>
    <p>設定會隨報表保存；臨時篩選與鑽取請另存書籤。發布與匯出會執行全部保存 RFM 設定，保留完整客戶結果。</p>
    {error&&<p role="alert">{error}</p>}{busy&&<p role="status">RFM 分析執行中…</p>}
    {result&&<RfmResultView result={result}/>}
  </details>;
}
