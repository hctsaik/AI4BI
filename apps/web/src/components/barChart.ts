import type {Data,Layout} from 'plotly.js';
import type {Result,Visual} from '../types';
import {cartesianFormat} from './cartesianFormat.ts';
const colors=['#2874a6','#20a397','#e7a645','#735da8','#c56574','#5d8290'];
const escape=(value:string)=>value.replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]!));
export function barChart(visual:Visual,result:Result){
  const bar=result.bar,format=result.chart_format;
  if(!bar||bar.version!==1||!format)throw new Error('缺少相容的長條資料，請重新查詢。');
  const horizontal=bar.orientation==='horizontal';
  const categoryAxis={type:'linear' as const,tickmode:'array' as const,tickvals:bar.categories.map((_,i)=>i),ticktext:bar.categories.map(c=>escape(c.label)),automargin:true};
  const layout=cartesianFormat(format,horizontal);
  const traces=bar.series.map((series,i)=>{
    const categories=series.points.map(p=>p.category_index),values=series.points.map(p=>p.value);
    const color=String(!bar.grouped?(visual.visualization.extra.color??visual.visualization.extra.bar_color??colors[i%colors.length]):colors[i%colors.length]);
    return {type:'bar',orientation:horizontal?'h':'v',name:escape(series.name),
      x:horizontal?values:categories,y:horizontal?categories:values,
      customdata:series.points.map(p=>bar.categories[p.category_index].filter_value),
      hovertext:series.points.map(p=>`${escape(bar.categories[p.category_index].label)}<br>${escape(series.name)}：${p.value??'—'}`),hoverinfo:'text',
      ...(format.data_labels?{text:series.points.map(p=>format.labels[series.metric_key][p.row_index]),textposition:'outside',cliponaxis:false}:{}),
      marker:{color,line:{color:'white',width:.6}},...(bar.mode==='overlay'?{opacity:.65}:{})} as Data;
  });
  return {traces,layout:{...layout,barmode:bar.mode,
    xaxis:horizontal?layout.yaxis:{...layout.xaxis,...categoryAxis},
    yaxis:horizontal?{...layout.xaxis,...categoryAxis}:layout.yaxis} as Partial<Layout>};
}
