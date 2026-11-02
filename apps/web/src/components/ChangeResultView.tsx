import {useLayoutEffect,useState} from 'react';
import type {ChangeResult} from '../types';

const format=new Intl.NumberFormat('zh-TW',{maximumSignificantDigits:12});
const display=(value:string|number|boolean|null)=>value===null?'—':typeof value==='number'?format.format(value):String(value);

export function ChangeResultView({result,title}:{result:ChangeResult;title?:string}){
  const [offset,setOffset]=useState(0);
  useLayoutEffect(()=>setOffset(0),[result]);
    return <section aria-label="變化拆解結果">{title&&<h4>{title}</h4>}<p role="status">{result.status==='empty'?'目前範圍沒有可比較資料':'變化拆解完成'}</p>
      <p>整體本期：{display(result.overall_current)} {result.metric_unit}；前期：{display(result.overall_previous)} {result.metric_unit}；變化：{display(result.overall_delta)} {result.metric_unit==='%'?'百分點':result.metric_unit}</p>
      {result.windows&&<p>本期 {result.windows.current.join(' 至 ')}；前期 {result.windows.previous.join(' 至 ')}（起訖日皆含，UTC）。</p>}
      <p>{result.notice}</p><p>共 {result.group_count} 群；{result.filter_policy==='keep'?'保留日期條件':'比較視窗取代日期條件'}。</p>
      <details><summary>變化拆解計算設定</summary><p>{result.settings.block_id} · {result.settings.metric_name} · {result.metric_formula}</p>
        <p>日期：{result.settings.date_column}；維度：{result.settings.dimension_column}；報表版本：{result.revision}</p>
        {Object.entries(result.data_versions).map(([id,version])=><p key={id}>{id}：{version}</p>)}</details>
      <div className="table-scroll"><table aria-label="變化拆解群組"><thead><tr>{['群組','本期','前期',result.metric_unit==='%'?'變化（百分點）':'變化','變化 %','貢獻 %'].map(label=><th key={label}>{label}</th>)}</tr></thead>
        <tbody>{result.rows.slice(offset,offset+100).map((row,index)=><tr key={offset+index}>{[row.group,row.current,row.previous,row.delta,row.delta_pct,row.contribution_pct].map((value,i)=><td key={i} title={value===null?'缺值或未定義':String(value)}>{display(value)}</td>)}</tr>)}</tbody></table></div>
      {result.group_count>100&&<nav aria-label="變化拆解分頁"><button disabled={offset===0} onClick={()=>setOffset(offset-100)}>上一頁</button>
        <span>{offset+1}–{Math.min(offset+100,result.group_count)}／{result.group_count}</span><button disabled={offset+100>=result.group_count} onClick={()=>setOffset(offset+100)}>下一頁</button></nav>}
    </section>;
}
