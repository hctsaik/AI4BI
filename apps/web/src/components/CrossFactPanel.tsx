import {CrossFactResultView} from './CrossFactResultView';
import {useEffect,useLayoutEffect,useRef,useState} from 'react';
import {api,key,pollJob} from '../lib/api';
import type {CommandKind} from '../lib/api';
import type {Dataset,DrillState,Filter,SavedCrossFactAnalysis,CrossFactResult} from '../types';

type Metric={kind:'aggregate'|'weighted_ratio';column:string;aggregation:string;numerator_column:string;denominator_column:string;scale:string};
const emptyMetric=():Metric=>({kind:'aggregate',column:'',aggregation:'SUM',numerator_column:'',denominator_column:'',scale:'100'});

export function CrossFactPanel({base,revision,datasets,selected,bookmark,drill,filters,pageId,definitions,disabled,onCommand,onSelect}:{
  base:string;revision:number;datasets:Dataset[];selected:string;bookmark:string|null;
  drill:Record<string,DrillState>;filters:Filter[];pageId:string;definitions:SavedCrossFactAnalysis[];disabled:boolean;
  onCommand:(kind:CommandKind,payload:Record<string,unknown>)=>void;onSelect:(id:string)=>void}){
  const sources=datasets.filter(d=>d.status==='ready'&&d.contract.block_type==='fact');
  const [a,setA]=useState({block:'',key:'',metric:emptyMetric()});
  const [b,setB]=useState({block:'',key:'',metric:emptyMetric()});
  const [operation,setOperation]=useState('ratio'),[quantiles,setQuantiles]=useState('5');
  const [result,setResult]=useState<CrossFactResult|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const [savedId,setSavedId]=useState(''),[name,setName]=useState('');
  const saved=definitions.find(item=>item.analysis_id===savedId&&item.page_id===pageId);
  const task=useRef<{abort:AbortController;id:string}|null>(null);
  function cancel(){const current=task.current;if(!current)return;current.abort.abort();
    if(current.id)void api(`/jobs/${current.id}/cancel`,{}).catch(()=>{});task.current=null;}
  function reset(){cancel();setBusy(false);setResult(null);setError('');}
  useEffect(()=>()=>cancel(),[]);
  const scope=JSON.stringify([base,revision,pageId,selected,bookmark,drill,filters,datasets.map(d=>[d.dataset_id,d.version,d.status])]);
  useLayoutEffect(()=>{reset();},[scope]);
  function validSide(side:typeof a){const columns=sources.find(d=>d.contract.block_id===side.block)?.contract.columns??[];
    const numeric=(name:string)=>name!==side.key&&columns.some(c=>c.name===name&&/^(integer|int|int32|int64|float|float32|float64|double|number|numeric|decimal)$/i.test(c.data_type));
    return columns.some(c=>c.name===side.key)&&(side.metric.kind==='aggregate'?numeric(side.metric.column):
      numeric(side.metric.numerator_column)&&numeric(side.metric.denominator_column)&&side.metric.scale.trim()!==''&&Number.isFinite(Number(side.metric.scale)));}
  const keyType=(side:typeof a)=>sources.find(d=>d.contract.block_id===side.block)?.contract.columns.find(c=>c.name===side.key)?.data_type;
  const valid=validSide(a)&&validSide(b)&&a.block!==b.block&&keyType(a)===keyType(b)&&Number.isInteger(Number(quantiles))&&Number(quantiles)>=2&&Number(quantiles)<=10;
  const metricPayload=(m:Metric)=>m.kind==='aggregate'?{kind:m.kind,column:m.column,aggregation:m.aggregation}:
    {kind:m.kind,numerator_column:m.numerator_column,denominator_column:m.denominator_column,scale:Number(m.scale)};
  function save(update=false){reset();onCommand(update?'update_crossfact_analysis':'save_crossfact_analysis',{
    ...(update?{analysis_id:saved!.analysis_id}:{name:name.trim()}),page_id:pageId,selected_component_id:selected||null,
    settings:{block_a:a.block,block_b:b.block,key_a:a.key,key_b:b.key,metric_a:metricPayload(a.metric),metric_b:metricPayload(b.metric),operation,quantiles:Number(quantiles)}});}
  function apply(){if(!saved)return;reset();setName(saved.name);
    const draft=(m:SavedCrossFactAnalysis['metric_a']):Metric=>m.kind==='weighted_ratio'?
      {...emptyMetric(),kind:'weighted_ratio',numerator_column:m.numerator_column,denominator_column:m.denominator_column,scale:String(m.scale??100)}:
      {...emptyMetric(),kind:'aggregate',column:m.column,aggregation:m.aggregation??'SUM'};
    setA({block:saved.block_a,key:saved.key_a,metric:draft(saved.metric_a)});setB({block:saved.block_b,key:saved.key_b,metric:draft(saved.metric_b)});
    setOperation(saved.operation);setQuantiles(String(saved.quantiles));onSelect(saved.selected_component_id??'');}
  async function run(){if(task.current||!valid)return;
    const current={abort:new AbortController(),id:''};task.current=current;setBusy(true);setResult(null);setError('');
    try{const accepted=await api<{job_id:string}>(`${base}/analyses/crossfact`,{block_a:a.block,block_b:b.block,key_a:a.key,key_b:b.key,
      metric_a:metricPayload(a.metric),metric_b:metricPayload(b.metric),operation,quantiles:Number(quantiles),
      idempotency_key:key(),base_revision:revision,selected_component_id:selected||null,filter_bookmark_id:bookmark,
      drill_state:drill,filters,exploration_page_id:pageId});
      current.id=accepted.job_id;
      if(current.abort.signal.aborted){void api(`/jobs/${current.id}/cancel`,{}).catch(()=>{});return;}
      const next=await pollJob<CrossFactResult>(current.id,current.abort.signal);if(task.current===current)setResult(next);
    }catch(e){if(task.current===current)setError(e instanceof Error?e.message:'跨表分析未完成。');}
    finally{if(task.current===current){task.current=null;setBusy(false);}}
  }
  function editor(side:typeof a,setSide:typeof setA,label:'A'|'B'){
    const columns=sources.find(d=>d.contract.block_id===side.block)?.contract.columns??[];
    const numeric=columns.filter(c=>c.name!==side.key&&/^(integer|int|int32|int64|float|float32|float64|double|number|numeric|decimal)$/i.test(c.data_type));
    function metric(field:keyof Metric,value:string){reset();setSide(previous=>({...previous,metric:{...previous.metric,[field]:value}}));}
    function column(field:'column'|'numerator_column'|'denominator_column',text:string){return <label>{label} {text}<select required value={side.metric[field]} onChange={e=>metric(field,e.target.value)}>
      <option value="">選擇數值欄位</option>{numeric.map(c=><option key={c.name}>{c.name}</option>)}</select></label>;}
    return <fieldset><legend>資料來源 {label}</legend>
      <label>{label} 資料來源<select required value={side.block} onChange={e=>{reset();setSide({block:e.target.value,key:'',metric:emptyMetric()});}}>
        <option value="">選擇來源</option>{sources.map(d=><option key={d.dataset_id} value={d.contract.block_id}>{d.contract.description||d.contract.block_id}</option>)}</select></label>
      <label>{label} 共同鍵<select required value={side.key} onChange={e=>{reset();setSide({...side,key:e.target.value});}}>
        <option value="">選擇共同鍵</option>{columns.map(c=><option key={c.name}>{c.name}</option>)}</select></label>
      <label>{label} 指標方式<select value={side.metric.kind} onChange={e=>metric('kind',e.target.value)}><option value="aggregate">欄位聚合</option><option value="weighted_ratio">加權比率（總分子／總分母）</option></select></label>
      {side.metric.kind==='aggregate'?<>{column('column','數值欄位')}<label>{label} 聚合<select value={side.metric.aggregation} onChange={e=>metric('aggregation',e.target.value)}>
        {['SUM','AVG','COUNT','MIN','MAX'].map(op=><option key={op}>{op}</option>)}</select></label></>:<>{column('numerator_column','分子欄位')}{column('denominator_column','分母欄位')}
        <label>{label} 比率倍率<input type="number" step="any" required value={side.metric.scale} onChange={e=>metric('scale',e.target.value)}/></label></>}
    </fieldset>;
  }
  return <details className="crossfact-panel"><summary>跨資料表分析</summary>
    <fieldset><legend>保存跨表分析設定</legend>
      <p>保存來源、鍵、指標與本頁圖表範圍；臨時篩選與鑽取請另存書籤。</p>
      <label>本頁跨表分析設定<select value={saved?.analysis_id??''} onChange={e=>{setSavedId(e.target.value);setName(definitions.find(item=>item.analysis_id===e.target.value)?.name??'');}}>
        <option value="">選擇已保存設定</option>{definitions.filter(item=>item.page_id===pageId).map(item=><option key={item.analysis_id} value={item.analysis_id}>{item.name}</option>)}</select></label>
      <button type="button" disabled={!saved} onClick={apply}>套用跨表分析設定</button>
      <label>跨表分析設定名稱<input maxLength={80} value={name} onChange={e=>setName(e.target.value)}/></label>
      <button type="button" disabled={disabled||!valid||!name.trim()} onClick={()=>save()}>另存跨表分析設定</button>
      <button type="button" disabled={disabled||!valid||!saved} onClick={()=>save(true)}>更新跨表分析設定</button>
      <button type="button" disabled={disabled||!saved||!name.trim()} onClick={()=>onCommand('rename_crossfact_analysis',{analysis_id:saved!.analysis_id,name:name.trim()})}>重新命名跨表分析設定</button>
      <button type="button" disabled={disabled||!saved} onClick={()=>onCommand('delete_crossfact_analysis',{analysis_id:saved!.analysis_id})}>刪除跨表分析設定（可復原）</button>
    </fieldset>
    <p>兩側各自套用本頁保存篩選與探索條件，先按共同鍵聚合，再取交集。每側最多 10,000 個群體；HAVING 與 Top-N 不裁切分析母體。加權比率請選分子與分母，勿以平均百分比替代。</p>
    <form onSubmit={e=>{e.preventDefault();void run();}}>{editor(a,setA,'A')}{editor(b,setB,'B')}
      <label>跨表計算方式<select value={operation} onChange={e=>{reset();setOperation(e.target.value);}}><option value="ratio">A ÷ B</option><option value="diff">A − B</option><option value="margin_pct">(A − B) ÷ A × 100</option></select></label>
      <label>跨表分位組數<input type="number" min={2} max={10} step={1} value={quantiles} onChange={e=>{reset();setQuantiles(e.target.value);}}/></label>
      <button disabled={!valid||busy}>執行跨表分析</button>{busy&&<button type="button" onClick={reset}>取消跨表分析</button>}
    </form>
    {a.key&&b.key&&keyType(a)!==keyType(b)&&<p role="alert">兩側共同鍵型別必須一致。</p>}
    {error&&<p role="alert">{error}</p>}{busy&&<p role="status">跨表分析執行中…</p>}
    {result&&<CrossFactResultView result={result}/>}
  </details>;
}
