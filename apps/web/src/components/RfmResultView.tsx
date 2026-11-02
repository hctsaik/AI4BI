import {useLayoutEffect,useState} from 'react';
import type {RfmResult} from '../types';

export function RfmResultView({result,title}:{result:RfmResult;title?:string}){
  const [offset,setOffset]=useState(0);
  useLayoutEffect(()=>setOffset(0),[result]);
  return <section aria-label="RFM 分析結果">{title&&<h4>{title}</h4>}<p role="status">{result.customer_count?'RFM 分析完成':'目前範圍沒有可分析客戶'}</p>
      <p>截止日：{result.anchor}（UTC）；共 {result.customer_count} 位客戶，納入 {result.included_rows}／{result.source_rows} 筆交易。</p>
      <p>缺少客戶或日期：{result.excluded_missing_identity_or_date} 筆；晚於截止日：{result.excluded_after_anchor} 筆。</p>
      <details><summary>RFM 資料版本</summary><p>報表版本：{result.revision}</p>{Object.entries(result.data_versions).map(([id,version])=><p key={id}>{id}：{version}</p>)}</details>
      <div className="table-scroll"><table aria-label="RFM 客群結果"><thead><tr>{['客戶','最近購買','距截止日天數','購買日數','累計淨額','R','F','M','分群','相對流失風險'].map(label=><th key={label}>{label}</th>)}</tr></thead>
        <tbody>{result.rows.slice(offset,offset+100).map((row,index)=><tr key={offset+index}>{[row.customer,row.last_purchase,row.recency_days,row.frequency,row.monetary,row.r,row.f,row.m,row.segment,row.at_risk?'是':'否'].map((value,i)=><td key={i}>{String(value)}</td>)}</tr>)}</tbody></table></div>
      {result.customer_count>100&&<nav aria-label="RFM 結果分頁"><button disabled={!offset} onClick={()=>setOffset(offset-100)}>上一頁</button>
        <span>{offset+1}–{Math.min(offset+100,result.customer_count)}／{result.customer_count}</span><button disabled={offset+100>=result.customer_count} onClick={()=>setOffset(offset+100)}>下一頁</button></nav>}
    </section>;
}
