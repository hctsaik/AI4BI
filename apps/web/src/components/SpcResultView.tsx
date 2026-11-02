import type {SpcResult,Visual,Result} from '../types';
import {DataTable,VisualChart} from './VisualChart';

/** Read-only rendering shared by live exploration and fixed publications. */
export function SpcResultView({result,title}:{result:SpcResult;title?:string}) {
  const limits=result.limits;
  const id=result.analysis_id??'spc-preview';
  const visual:Visual={component_id:id,col_span:12,
    query:{spec_id:id,block_refs:[],dimensions:[{block_id:result.block_id,column_name:'entity'}],
      metrics:['value',...(limits?['mean','ucl','lcl']:[])].map(name=>({block_id:result.block_id,metric_name:name})),filters:[],sort:[]},
    visualization:{visual_type:'line_chart',title:'跨實體數值與界限',height_px:320,show_legend:true,extra:{}}};
  const plotted:Result={status:'ready',columns:['entity','value','mean','ucl','lcl'],
    rows:result.points.map(p=>({...p,...(limits?{mean:limits.mean,ucl:limits.ucl,lcl:limits.lcl}:{})}))};
  return <section aria-label={title?`SPC 分析結果：${title}`:'SPC 分析結果'}>
    {title&&<h3>SPC · {title}</h3>}
    <p>{result.entity_column} · {result.value_column} · {result.aggregation==='mean'?'平均':'合計'} · k={result.k}</p>
    <p role="status">{({ready:'掃描完成',empty:'沒有可分析的數值',insufficient_groups:'實體不足 3 組，無法計算界限',zero_variance:'各實體數值相同，無法判斷離群'})[result.status]}</p>
    <p>{result.entity_count} 個實體 · 使用 {result.used_rows}／{result.input_rows} 列 · 排除 {result.excluded_rows} 列缺值 · 報表版本 {result.revision}</p>
    {limits&&<p>μ = {limits.mean} · σ = {limits.sigma} · UCL = {limits.ucl} · LCL = {limits.lcl}</p>}
    <p>{result.notice}</p>
    {result.points.length>0&&<VisualChart visual={visual} result={plotted} onFilter={()=>{}} interactionDisabled/>}
    <h3>離群實體</h3>{result.outliers.rows.length?<DataTable result={{status:'ready',...result.outliers}}/>:<p>{result.status==='ready'?'沒有實體超出界限。':'目前不能判定離群。'}</p>}
    <details><summary>查看全部實體數值</summary><DataTable result={{status:'ready',columns:['entity','value'],rows:result.points}}/></details>
  </section>;
}
