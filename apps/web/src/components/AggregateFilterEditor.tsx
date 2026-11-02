import {useEffect,useState} from 'react';
import type {AggregateFilter,Visual} from '../types';

const operators={gt:'大於',gte:'大於或等於',lt:'小於',lte:'小於或等於',eq:'等於',neq:'不等於',between:'介於（含端點）'};
export function AggregateFilterEditor({visual,busy,onChange}:{visual:Visual;busy:boolean;onChange:(filters:AggregateFilter[])=>void}){
  const stored=JSON.stringify(visual.query.having??[]);
  const [items,setItems]=useState<AggregateFilter[]>(JSON.parse(stored));
  const [metric,setMetric]=useState(''),[operator,setOperator]=useState<AggregateFilter['operator']>('gt');
  const [value,setValue]=useState(''),[upper,setUpper]=useState(''),[error,setError]=useState('');
  useEffect(()=>{setItems(JSON.parse(stored));setError('');},[stored,visual.component_id]);
  useEffect(()=>{setMetric('');setValue('');setUpper('');},[visual.component_id]);
  const metrics=visual.query.metrics.filter(m=>visual.query.metrics.filter(n=>n.block_id===m.block_id&&n.metric_name===m.metric_name).length===1);
  function add(){
    setError('');
    try{
      const chosen=metrics.find(m=>JSON.stringify([m.block_id,m.metric_name])===metric);
      const lower=Number(value),high=Number(upper);
      if(!chosen)throw new Error('請選擇圖表中的指標。');
      if(!value.trim()||!Number.isFinite(lower)||(operator==='between'&&(!upper.trim()||!Number.isFinite(high)||lower>high)))throw new Error('請輸入有限數值；區間須由小至大。');
      setItems([...items,{block_id:chosen.block_id,metric_name:chosen.metric_name,operator,value:operator==='between'?[lower,high]:lower}]);
    }catch(e){setError(e instanceof Error?e.message:String(e));}
  }
  return <details className="aggregate-filter-editor"><summary>聚合後指標篩選（{(visual.query.having??[]).length}）</summary>
    <p>先依目前資料條件計算每組指標，再保留符合門檻的組。各項須同時符合；設定只作用於此圖，不先刪除來源明細。</p>
    <ol>{items.map((item,index)=><li key={index}>
      {visual.query.metrics.find(m=>m.block_id===item.block_id&&m.metric_name===item.metric_name)?.alias||item.metric_name} {operators[item.operator]} {Array.isArray(item.value)?item.value.join(' 至 '):item.value}
      <button type="button" disabled={busy} aria-label={`移除聚合條件 ${index+1}`} onClick={()=>setItems(items.filter((_,i)=>i!==index))}>移除</button>
    </li>)}</ol>
    <label>聚合指標<select aria-label="聚合指標" value={metric} disabled={busy} onChange={e=>setMetric(e.target.value)}>
      <option value="">選擇已使用的指標</option>{metrics.map(m=><option key={JSON.stringify([m.block_id,m.metric_name])} value={JSON.stringify([m.block_id,m.metric_name])}>{m.alias||m.metric_name}</option>)}
    </select></label>
    <label>聚合比較<select aria-label="聚合比較" value={operator} disabled={busy} onChange={e=>setOperator(e.target.value as AggregateFilter['operator'])}>{Object.entries(operators).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label>
    <label>{operator==='between'?'聚合下限':'聚合門檻'}<input aria-label="聚合門檻" type="number" step="any" value={value} disabled={busy} onChange={e=>setValue(e.target.value)}/></label>
    {operator==='between'&&<label>聚合上限<input aria-label="聚合上限" type="number" step="any" value={upper} disabled={busy} onChange={e=>setUpper(e.target.value)}/></label>}
    <button type="button" disabled={busy||items.length>=50} onClick={add}>加入聚合條件</button>
    <button type="button" disabled={busy||JSON.stringify(items)===stored} onClick={()=>onChange(items)}>保存聚合篩選</button>
    <button type="button" disabled={busy||JSON.stringify(items)===stored} onClick={()=>{setItems(JSON.parse(stored));setError('');}}>放棄聚合修改</button>
    <p>先移除並保存相關條件，才能更換或移除該指標。鑽取時會針對目前層級重新計算門檻。</p>
    {error&&<p role="alert">{error}</p>}
  </details>;
}
