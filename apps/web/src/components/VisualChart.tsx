import { Component, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import type { Data, Layout, PlotlyHTMLElement } from 'plotly.js';
// The distributed browser bundle contains no server or CDN dependency.
// @ts-expect-error distribution package ships JavaScript; types come from @types/plotly.js
import Plotly from 'plotly.js-dist-min';
import type { Filter, Result, Visual } from '../types';
import {smallMultiples} from './smallMultiples';
import {PivotTable} from './PivotTable';
import {geographicMap} from './geographicMap';
import {KpiSparkline} from './KpiSparkline';
import {scatterChart} from './scatterChart';
import {pieChart,pieFilterValue} from './pieChart';
import {cartesianFormat} from './cartesianFormat';
import {barChart} from './barChart';

const COLORS = ['#2874a6', '#20a397', '#e7a645', '#735da8', '#c56574', '#5d8290'];
export function DataTable({result,visual,onFilter,interactionDisabled=false,interactionLabel='篩選'}: {result: Result;visual?:Visual;onFilter?:(filter:Filter)=>void;interactionDisabled?:boolean;interactionLabel?:string}) {
  const [position,setPosition]=useState({result,page:0});
  useEffect(()=>setPosition({result,page:0}),[result]);
  const rows=result.rows??[];
  const page=position.result===result?position.page:0;
  const pages=Math.max(1,Math.ceil(rows.length/100));
  return <div className="table-scroll"><table><thead><tr>{result.columns?.map(c => <th key={c}>{c}</th>)}</tr></thead>
    <tbody>{rows.slice(page*100,(page+1)*100).map((r,i) => <tr key={page*100+i}>{result.columns?.map(c => {
      const field=visual?.query.dimensions.find(d=>(d.alias??d.column_name)===c&&!d.truncate_date_to);
      const value=r[c];
      return <td key={c}>{field&&onFilter ? <button className="dimension-filter" disabled={interactionDisabled}
        aria-label={`${interactionLabel} ${field.column_name}：${value==null?'（空值）':String(value)}`} onClick={()=>onFilter({source_visual_id:visual?.component_id,
          block_id:field.block_id,column_name:field.column_name,operator:value==null?'is_null':'eq',value:value??null})}>{value==null?'（空值）':String(value)}</button> : String(value??'—')}</td>;
    })}</tr>)}</tbody></table>
    {pages>1&&<nav aria-label="表格分頁" className="table-pagination"><button disabled={page===0} onClick={()=>setPosition({result,page:page-1})}>上一頁</button>
      <span role="status">第 {page+1}／{pages} 頁 · 第 {page*100+1}–{Math.min((page+1)*100,rows.length)} 列</span>
      <button disabled={page+1>=pages} onClick={()=>setPosition({result,page:page+1})}>下一頁</button></nav>}
    {(result.row_count??0)>rows.length&&<p className="muted">已載入 {rows.length}／共 {result.row_count} 列</p>}</div>;
}
export function VisualChart({visual, result, onFilter,interactionDisabled=false,interactionLabel='篩選'}: {visual: Visual; result?: Result; onFilter: (filter: Filter)=>void;interactionDisabled?:boolean;interactionLabel?:string}) {
  const element = useRef<HTMLDivElement>(null);
  const bindElement = useCallback((node:HTMLDivElement|null)=>{
    // Data/style updates use Plotly.react and its uirevision. Release resources
    // only when React actually replaces/removes this plot's DOM container.
    if(element.current&&element.current!==node)Plotly.purge(element.current);
    element.current=node;
  },[]);
  const latest = useRef(onFilter); latest.current = onFilter;
  const disabled = useRef(interactionDisabled); disabled.current = interactionDisabled;
  const kind = visual.visualization.extra.chart_mode==='histogram'?'histogram':visual.visualization.visual_type;
  const rows = result?.rows ?? [];
  const metric = visual.query.metrics[0];
  const dim = visual.query.dimensions[0];
  const metricName = metric?.alias ?? metric?.metric_name;
  const dimensionName = dim?.alias ?? dim?.column_name;
  // Report commands deserialize every visual anew. Object identity alone must
  // not purge an unchanged plot (including its zoom and selection state).
  const renderFingerprint = JSON.stringify(visual);
  const [facetPosition,setFacetPosition]=useState({result,page:0});
  const facetPage=facetPosition.result===result?facetPosition.page:0;
  const facets=useMemo(()=>kind==='small_multiples'&&result?smallMultiples(visual,result,facetPage,
    String(visual.visualization.extra.color??COLORS[0])):null,[renderFingerprint,result,facetPage]);
  const map=useMemo(()=>{
    if(kind!=='map'||!result)return null;
    try{return {chart:geographicMap(visual,result),error:null};}
    catch(error){return {chart:null,error:error instanceof Error?error.message:String(error)};}
  },[renderFingerprint,result]);
  const [plotError,setPlotError]=useState<string|null>(null);
  const bar=useMemo(()=>{
    if(kind!=='bar_chart'||!result)return null;
    try{return {chart:barChart(visual,result),error:null};}
    catch(error){return {chart:null,error:error instanceof Error?error.message:String(error)};}
  },[renderFingerprint,result]);
  const pie=useMemo(()=>{
    if(kind!=='pie_chart'||!result)return null;
    try{return {chart:pieChart(result),error:null};}
    catch(error){return {chart:null,error:error instanceof Error?error.message:String(error)};}
  },[renderFingerprint,result]);
  const scatter=useMemo(()=>{
    if(kind!=='scatter'||!result)return null;
    try{return {chart:scatterChart(visual,result),error:null};}
    catch(error){return {chart:null,error:error instanceof Error?error.message:String(error)};}
  },[renderFingerprint,result]);
  useEffect(() => {
    setPlotError(null);
    if (!element.current || kind === 'kpi_card' || kind === 'table' || kind === 'pivot' || bar?.error || facets?.error || pie?.error || pie?.chart?.reason || scatter?.error || map?.error || map?.chart?.mapped===0 || !rows.length) return;
    const el = element.current;
    const x = rows.map(r => dimensionName ? r[dimensionName] : '全部');
    const histogram:Data[]|null=kind==='histogram'&&result?.histogram?[{type:'bar',
      x:rows.map(r=>Number(r.lower)+(Number(r.upper)-Number(r.lower))/2),y:rows.map(r=>r.count),
      width:rows.map(r=>(Number(r.upper)-Number(r.lower))*.95),
      customdata:result.histogram.filter_ranges,
      text:rows.map(r=>`[${r.lower}, ${r.upper}${r.right_inclusive?']':')'}：${r.count}`),hoverinfo:'text',textposition:'none',showlegend:false,
      marker:{color:String(visual.visualization.extra.color??visual.visualization.extra.bar_color??COLORS[0])}} as Data]:null;
    const traces: Data[] = histogram??bar?.chart?.traces??pie?.chart?.traces??scatter?.chart?.traces??map?.chart?.traces??facets?.traces??visual.query.metrics.map((m,i) => {
      const y = rows.map(r => r[m.alias ?? m.metric_name]);
      const color = String(visual.visualization.extra.color ?? COLORS[i%COLORS.length]);
      const labels=result?.chart_format?.data_labels?result.chart_format.labels[m.alias??m.metric_name]:undefined;
      return {type: kind === 'bar_chart' ? 'bar' : 'scatter', mode:labels?'lines+markers+text':'lines+markers',
        ...(labels?{text:labels,textposition:kind==='bar_chart'?'outside':'top center',cliponaxis:false}:{}),
        x, y, customdata:x, name:m.alias ?? m.metric_name, marker:{color, size:7}, line:{color,width:2.5},
        hovertemplate:'%{x}<br>%{y:,.3f}<extra></extra>'} as Data;
    });
    const layout: Partial<Layout> = {autosize:true, height:Math.max(180,visual.visualization.height_px-65),
      margin:{l:55,r:20,t:15,b:55}, paper_bgcolor:'transparent',plot_bgcolor:'transparent',
      font:{family:'Segoe UI, Microsoft JhengHei, sans-serif',size:12,color:'#576777'},
      showlegend:visual.visualization.show_legend && traces.length>1,
      xaxis:{gridcolor:'#edf1f4',zeroline:false},yaxis:{gridcolor:'#edf1f4',zeroline:false},
      ...facets?.layout,
      ...map?.chart?.layout,
      ...scatter?.chart?.layout,
      ...pie?.chart?.layout,
      ...(result?.chart_format&&['bar_chart','line_chart'].includes(kind)?cartesianFormat(result.chart_format):{}),
      ...bar?.chart?.layout,
      ...(histogram?{xaxis:{title:{text:String(visual.visualization.x_axis_label??result?.histogram?.field.key??'數值')}},yaxis:{title:{text:'筆數'},rangemode:'tozero' as const}}:{}),
      uirevision:JSON.stringify([visual.component_id,visual.query.dimensions,visual.query.metrics,kind,
        facets?.visible.map(f=>f.key),visual.visualization.extra.facet_shared_y,visual.visualization.extra.facet_wrap,visual.visualization.extra.map_view,
        result?.chart_format?[result.chart_format.y_scale,result.chart_format.y_min,result.chart_format.y_max]:null,result?.bar?.orientation,result?.bar?.mode])};
    let disposed = false;
    void Plotly.react(el, traces, layout, {responsive:true, displayModeBar:false,scrollZoom:kind==='map',topojsonURL:new URL('/maps/',window.location.href).href}).then(() => {
      if (disposed) return;
      const plot = el as unknown as PlotlyHTMLElement;
      plot.removeAllListeners?.('plotly_click');
      plot.on('plotly_click', (event) => {
        if (disabled.current || !dim || dim.truncate_date_to || !event.points.length) return;
        if(kind==='scatter'&&(event.points[0].data as {mode?:string}).mode==='lines')return;
        if(kind==='pie_chart'&&result){
          const selected=pieFilterValue(result,event.points[0]);
          if(selected)latest.current({source_visual_id:visual.component_id,block_id:dim.block_id,
            column_name:dim.column_name,operator:selected.value===null?'is_null':'eq',value:selected.value});
          return;
        }
        if(kind==='histogram'){
          const value=event.points[0].customdata;
          if(Array.isArray(value)&&value.length===2)latest.current({source_visual_id:visual.component_id,
            block_id:dim.block_id,column_name:dim.column_name,operator:'between',value});
          return;
        }
        const point = event.points[0];
        const value = point.customdata;
        latest.current({source_visual_id:visual.component_id,block_id:dim.block_id,
          column_name:dim.column_name,operator:value==null?'is_null':'eq',value:value??null});
      });
    }).catch(()=>{if(!disposed)setPlotError('圖表資源無法載入，請重試；分析數據仍可查看。');});
    const observer = new ResizeObserver(() => { if (el.clientWidth) Plotly.Plots.resize(el); });
    observer.observe(el);
    return () => {disposed=true;observer.disconnect();};
  },[renderFingerprint,result,facetPage]);
  if (result?.status === 'error') return <p role="alert" className="chart-error">{result.error?.message}</p>;
  if(bar?.error&&result)return <><p role="alert">{bar.error}</p><DataTable result={result} visual={visual} onFilter={onFilter} interactionDisabled={interactionDisabled}/></>;
  if (!result) return <div className="skeleton" aria-label="圖表載入中"/>;
  if (kind === 'pivot') return <PivotTable visual={visual} result={result} onFilter={onFilter} interactionDisabled={interactionDisabled} interactionLabel={interactionLabel}/>;
  if (!rows.length) return <div className="empty-chart">目前條件沒有可用資料{result.histogram&&`（排除 ${result.histogram.excluded_count} 筆空值或非有限值）`}</div>;
  if (facets?.error) return <><p role="alert" className="chart-error">{facets.error}</p><DataTable result={result} visual={visual} onFilter={onFilter} interactionDisabled={interactionDisabled} interactionLabel={interactionLabel}/></>;
  if (scatter?.error)return <><p role="alert">{scatter.error}</p><DataTable result={result} visual={visual} onFilter={onFilter} interactionDisabled={interactionDisabled}/></>;
  if(pie?.error||pie?.chart?.reason)return <><p role={pie.error?'alert':'status'}>{pie.error??pie.chart?.reason}</p><DataTable result={result} visual={visual} onFilter={onFilter} interactionDisabled={interactionDisabled}/></>;
  if(map?.error||map?.chart?.mapped===0)return <><p role={map.error?'alert':'status'}>{map.error??'目前地點無法對應座標。核心支援台灣縣市及部分國際城市；原始資料保留於下表。'}</p><DataTable result={result} visual={visual} onFilter={onFilter} interactionDisabled={interactionDisabled} interactionLabel={interactionLabel}/></>;
  if (kind === 'kpi_card'&&(result.kpi?.status==='table'||rows.length!==1||visual.query.metrics.length!==1||visual.query.dimensions.length>0))
    return <DataTable result={result} visual={visual} onFilter={onFilter} interactionDisabled={interactionDisabled} interactionLabel={interactionLabel}/>;
  if (kind === 'kpi_card'&&result.kpi) return <div className="kpi-display"><div className="kpi-value">{result.kpi.label}<span>{result.kpi.unit}</span><p>依目前資料與篩選計算</p></div>
    {result.kpi.reason&&<p role="status">{result.kpi.reason}</p>}
    {result.kpi.sparkline&&<KpiSparkline series={result.kpi.sparkline}/>}
    {result.kpi.comparison&&<div className="kpi-comparison" aria-label="期間比較結果">{result.kpi.comparison.captions.map((caption,i)=><p key={i}>{caption}</p>)}{result.kpi.comparison.reason&&<p role="status">{result.kpi.comparison.reason}</p>}</div>}
    {result.kpi.rag&&<p className={`kpi-status ${result.kpi.rag.state}`} role="status">{result.kpi.rag.label}</p>}
    {result.kpi.pacing&&<div className="kpi-pacing"><p>{result.kpi.pacing.label}</p>
      {result.kpi.pacing.status==='ready'&&<progress aria-label="目標進度" max={1} value={result.kpi.pacing.fraction??0}/>}
      {result.kpi.pacing.reason&&<p role="status">{result.kpi.pacing.reason}</p>}</div>}</div>;
  if (kind === 'kpi_card') return <div className="kpi-value">{typeof rows[0][metricName] === 'number' ?
    Number(rows[0][metricName]).toLocaleString('zh-TW',{maximumFractionDigits:2}) : String(rows[0][metricName] ?? '—')}
    <span>{String(visual.visualization.extra.unit ?? '')}</span><p>依目前資料與篩選計算</p></div>;
  if (kind === 'table') return <DataTable result={result} visual={visual} onFilter={onFilter} interactionDisabled={interactionDisabled} interactionLabel={interactionLabel}/>;
  // Grouped bars use one governed metric; additional metrics remain accessible.
  return <>{result.chart_format?.baseline&&<p className="baseline-caption" role="status">{result.chart_format.baseline.status==='ready'?result.chart_format.baseline.label:result.chart_format.baseline.reason}{result.chart_format.baseline.kind==='mean'&&` · 第一指標查詢結果：有效 ${result.chart_format.baseline.valid_count} 筆、排除 ${result.chart_format.baseline.excluded_count} 筆`}</p>}{result.bar?.grouped&&<p className="muted">依第二維度分系列；圖中使用第一指標，其餘指標保留於資料表。</p>}{pie?.chart&&<p className="muted">比例指標：{result.pie?.metric_key} · 排除 {result.pie?.excluded_count} 筆非有限權重。百分比依查詢權重計算，不因隱藏圖例改變；其餘指標保留於資料表。</p>}{plotError&&<p role="alert">{plotError}</p>}{scatter?.chart&&<><p className="muted">散點 {scatter.chart.count} 筆 · 排除 {scatter.chart.excluded} 筆非有限座標 · X 為第一指標，Y 為第二指標（未設定則為列序號）。</p>{!!result.scatter?.trendline&&<details><summary>趨勢擬合結果（{result.scatter.trendline.toUpperCase()}）</summary><ul>{result.scatter.trendlines?.map((fit,i)=><li key={i}>{result.scatter?.group_key?String(fit.group??'（空值）'):'全部'} · {fit.n} 筆 · {fit.status==='ready'?fit.method==='ols'?`斜率 ${fit.slope?.toPrecision(6)}，截距 ${fit.intercept?.toPrecision(6)}，R² ${fit.r_squared?.toPrecision(6)??'未定義'}`:'LOWESS 擬合完成':fit.reason}</li>)}</ul></details>}</>}{result.histogram&&kind==='histogram'&&<div className="map-caption">
    <p>有效 {result.histogram.valid_count} 筆 · 排除 {result.histogram.excluded_count} 筆 · {result.histogram.bins} 箱</p>
    <p className="muted">平均 {result.histogram.mean?.toLocaleString('zh-TW',{maximumFractionDigits:2})??'—'} · 中位數 {result.histogram.median?.toLocaleString('zh-TW',{maximumFractionDigits:2})??'—'} · 最小 {result.histogram.min} · 最大 {result.histogram.max}</p>
    <p className="muted">區間左含右不含，最後一箱包含最大值。{result.histogram.query_limit!==null&&`目前依查詢限制最多 ${result.histogram.query_limit} 筆計算。`}</p>
    <label>篩選直方圖區間<select value="" disabled={interactionDisabled} onChange={e=>{
      if(e.target.value==='')return;
      const value=result.histogram!.filter_ranges[Number(e.target.value)],field=result.histogram!.field;
      if(value)onFilter({source_visual_id:visual.component_id,block_id:field.block_id,column_name:field.column_name,operator:'between',value});
    }}><option value="">選擇區間</option>{rows.map((row,index)=><option key={index} value={index}>[{row.lower}, {row.upper}{row.right_inclusive?']':')'} · {row.count} 筆</option>)}</select></label>
  </div>}{map?.chart&&<div className="map-caption">
    <p>已定位 {map.chart.mapped} 個地點 · 未定位 {map.chart.unmapped} 個</p>
    <p className="muted">離線概略底圖 · 氣泡依第一指標絕對值調整；負值為紅色，零值與無數值保留最小標記。座標來自核心地名對照。</p>
  </div>}{facets&&<div className="facet-controls">
    <p className="muted">分面：{dimensionName} · 指標：{metricName} · {visual.visualization.extra.facet_shared_y===true?'共用縱軸':'各分面獨立縱軸'}</p>
    {visual.query.metrics.length>1&&<p className="muted">圖中顯示第一個指標，其餘指標保留於「查看數據」。</p>}
    <nav aria-label="分面選取">{facets.visible.map(f=><button key={f.key} disabled={interactionDisabled||!!dim?.truncate_date_to}
      aria-label={`${interactionLabel}分面 ${dim.column_name}：${f.label}`} onClick={()=>onFilter({source_visual_id:visual.component_id,
        block_id:dim.block_id,column_name:dim.column_name,operator:f.value===null?'is_null':'eq',value:f.value})}>{f.label}</button>)}</nav>
    {facets.pages>1&&<nav aria-label="分面分頁" className="table-pagination"><button disabled={facets.page===0} onClick={()=>setFacetPosition({result,page:facets.page-1})}>上一組分面</button>
      <span role="status">第 {facets.page+1}／{facets.pages} 頁 · 共 {facets.facets.length} 個分面</span>
      <button disabled={facets.page+1>=facets.pages} onClick={()=>setFacetPosition({result,page:facets.page+1})}>下一組分面</button></nav>}
    {result.truncated&&<p role="status">目前只顯示已載入的查詢資料，請縮小篩選範圍。</p>}
  </div>}<div className={facets?'facet-plot':undefined} style={facets?{maxHeight:Math.max(180,visual.visualization.height_px-65)}:undefined}><div ref={bindElement}/></div><details className="accessible-data"><summary>查看數據</summary><DataTable result={result} visual={kind==='histogram'?undefined:visual} onFilter={onFilter} interactionDisabled={interactionDisabled} interactionLabel={interactionLabel}/></details></>;
}
export class ChartBoundary extends Component<{children:ReactNode}, {error:boolean}> {
  state = {error:false};
  static getDerivedStateFromError() { return {error:true}; }
  render() { return this.state.error ? <p role="alert">此圖表無法顯示，其他分析仍可使用。</p> : this.props.children; }
}
