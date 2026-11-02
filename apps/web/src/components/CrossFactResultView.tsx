import {useLayoutEffect,useState} from 'react';
import type {CrossFactResult} from '../types';

const stateLabel:Record<string,string>={ready:'可計算',insufficient_pairs:'有效配對不足',constant_metric:'指標為常數，無法比較'};
const numberFormat=new Intl.NumberFormat('zh-TW',{maximumSignificantDigits:12});
const display=(value:number|string|null)=>value===null?'—':typeof value==='number'?numberFormat.format(value):value;

export function CrossFactResultView({result,title}:{result:CrossFactResult;title?:string}){
  const [offset,setOffset]=useState(0);
  useLayoutEffect(()=>setOffset(0),[result]);
  const settings=result.settings;
  const metric=(value:NonNullable<CrossFactResult['settings']>['metric_a'])=>value.kind==='aggregate'?
    `${value.aggregation??'SUM'}(${value.column})`:`SUM(${value.numerator_column}) ÷ SUM(${value.denominator_column}) × ${value.scale??100}`;
  return <section aria-label={title?`跨表分析結果：${title}`:'跨表分析結果'}>{title&&<h3>{title}</h3>}<p role="status">{result.status==='empty'?'沒有可對齊的群體':'跨表分析完成'}</p>
      {settings&&<details><summary>跨表計算設定</summary>
        <p>A：{settings.block_a} · {settings.key_a} · {metric(settings.metric_a)}</p>
        <p>B：{settings.block_b} · {settings.key_b} · {metric(settings.metric_b)}</p>
        <p>計算：{{ratio:'A ÷ B',diff:'A − B',margin_pct:'(A − B) ÷ A × 100'}[settings.operation]}；分位組數 {settings.quantiles}</p>
      </details>}
      <p>對齊 {result.aligned_count} 群；有效配對 {result.paired_count}；缺值配對 {result.missing_pair_count}；計算零分母 {result.zero_denominator_count}。</p>
      {(['a','b'] as const).map(side=><p key={side}>來源 {side.toUpperCase()}：{result.sources[side].input_rows} 列；排除缺鍵 {result.sources[side].excluded_key_rows} 列；缺指標 {result.sources[side].missing_measure_rows} 列；未匹配 {result.sources[side].unmatched_groups} 群。</p>)}
      <p>{result.notice}</p><p>Pearson：{result.correlation?`r = ${result.correlation.r}，n = ${result.correlation.n}`:stateLabel[result.correlation_status]}</p>
      <p>分位群組：{stateLabel[result.cohort_status]}；要求 {result.requested_quantiles} 組，實際 {result.actual_quantiles} 組。</p>
      {result.cohorts.length>0&&<table aria-label="跨表分位群組"><thead><tr>{['組別','A 範圍','群體數','平均 B'].map(h=><th key={h}>{h}</th>)}</tr></thead>
        <tbody>{result.cohorts.map(row=><tr key={row.bucket}><td>{row.bucket}</td><td>{row.range}</td><td>{row.count}</td><td>{row.mean_b}</td></tr>)}</tbody></table>}
      <p>對齊資料每頁 100 列；{result.rows.length?`${offset+1}–${Math.min(offset+100,result.rows.length)}`:'0'}／{result.rows.length} 列。空值以「—」呈現。</p>
      <button type="button" disabled={offset===0} onClick={()=>setOffset(Math.max(0,offset-100))}>跨表上一頁</button>
      <button type="button" disabled={offset+100>=result.rows.length} onClick={()=>setOffset(offset+100)}>跨表下一頁</button>
      <table aria-label="跨表對齊資料"><thead><tr>{['共同鍵','A','B','計算結果'].map(h=><th key={h}>{h}</th>)}</tr></thead>
        <tbody>{result.rows.slice(offset,offset+100).map((row,i)=><tr key={offset+i}><td>{String(row.key)}</td>{[row.a,row.b,row.result].map((value,j)=><td key={j} title={value===null?'缺值':String(value)}>{display(value)}</td>)}</tr>)}</tbody></table>
    </section>;
}
