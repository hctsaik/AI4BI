import {useMemo,useState} from 'react';
import type {Field,Filter,Result,Row,Visual} from '../types';
import {pivotMatrix} from './pivotMatrix';

export function PivotTable({visual,result,onFilter,interactionDisabled=false,interactionLabel='篩選'}:{
  visual:Visual;result:Result;onFilter:(filter:Filter)=>void;interactionDisabled?:boolean;interactionLabel?:string}) {
  const [position,setPosition]=useState({result,row:0,column:0});
  const model=useMemo(()=>{try{return {matrix:pivotMatrix(result),error:null};}catch(error){return {matrix:null,error:String(error instanceof Error?error.message:error)};}},[result]);
  if(!model.matrix)return <p role="alert">{model.error}</p>;
  const m=model.matrix,p=position.result===result?position:{result,row:0,column:0};
  const rowPages=Math.max(1,Math.ceil(m.rows.length/50)),columnPages=Math.max(1,Math.ceil(m.columns.length/8));
  const rows=m.rows.slice(p.row*50,(p.row+1)*50),columns=m.columns.slice(p.column*8,(p.column+1)*8);
  const metrics=m.spec.metrics;
  const content=(row:Row|undefined,key:string)=>row===undefined?'—':row[key]===null?'（空值）':String(row[key]);
  const header=(field:Field,axis:{key:string;value:Row[string];label:string})=><button className="dimension-filter"
    disabled={interactionDisabled||!!field.truncate_date_to} aria-label={`${interactionLabel} ${field.column_name}：${axis.label}`}
    onClick={()=>onFilter({source_visual_id:visual.component_id,block_id:field.block_id,column_name:field.column_name,
      operator:axis.value===null?'is_null':'eq',value:axis.value})}>{axis.label}</button>;
  return <div className="pivot-view">
    <p className="muted">總計依完整篩選資料計算，不受畫面分頁或查詢列數限制；聚合門檻分別套用於儲存格與各層總計。</p>
    <p className="muted">「—」表示未回傳該組合或總計；「空值」表示核心回傳空值。</p>
    {result.truncated&&<p role="status">部分查詢資料超過載入上限，請縮小篩選範圍。</p>}
    <div className="table-scroll"><table aria-label="樞紐分析表"><thead><tr>
      <th scope="col" rowSpan={2}>{m.spec.row_field.key} {m.spec.column_field&&`／ ${m.spec.column_field.key}`}</th>
      {columns.map(c=><th scope="colgroup" colSpan={metrics.length} key={c.key}>{m.spec.column_field?header(m.spec.column_field,c):'指標'}</th>)}
      <th scope="colgroup" colSpan={metrics.length}>列總計</th></tr><tr>
      {[...columns.map(c=>c.key),'total'].flatMap(c=>metrics.map(metric=><th scope="col" key={`${c}:${metric.key}`}>{metric.key}</th>))}
    </tr></thead><tbody>{rows.map(r=><tr key={r.key}><th scope="row">{header(m.spec.row_field,r)}</th>
      {columns.flatMap(c=>metrics.map(metric=><td key={`${c.key}:${metric.key}`}>{content(m.cells.get(r.key)?.get(c.key),metric.key)}</td>))}
      {metrics.map(metric=><td key={`total:${metric.key}`}>{content(m.rowTotals.get(r.key),metric.key)}</td>)}
    </tr>)}</tbody><tfoot><tr><th scope="row">欄總計／總計</th>
      {columns.flatMap(c=>metrics.map(metric=><td key={`${c.key}:${metric.key}`}>{content(m.spec.column_field?m.columnTotals.get(c.key):m.grand,metric.key)}</td>))}
      {metrics.map(metric=><td key={`total:${metric.key}`}>{content(m.grand,metric.key)}</td>)}
    </tr></tfoot></table></div>
    {(rowPages>1||columnPages>1)&&<nav aria-label="樞紐分頁" className="table-pagination">
      <button disabled={!p.row} onClick={()=>setPosition({...p,row:p.row-1})}>上一組列</button>
      <span role="status">列第 {p.row+1}／{rowPages} 頁 · 共 {m.rows.length} 列</span>
      <button disabled={p.row+1>=rowPages} onClick={()=>setPosition({...p,row:p.row+1})}>下一組列</button>
      <button disabled={!p.column} onClick={()=>setPosition({...p,column:p.column-1})}>上一組欄</button>
      <span role="status">欄第 {p.column+1}／{columnPages} 頁 · 共 {m.columns.length} 欄</span>
      <button disabled={p.column+1>=columnPages} onClick={()=>setPosition({...p,column:p.column+1})}>下一組欄</button>
    </nav>}
  </div>;
}
