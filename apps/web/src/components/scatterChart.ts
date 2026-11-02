import type {Data,Layout} from 'plotly.js';
import type {Result,Visual} from '../types';

const colors=['#2874a6','#20a397','#e7a645','#735da8','#c56574','#5d8290'];
const symbols=['circle','square','diamond','cross','triangle-up','triangle-down'];
const escape=(value:unknown)=>String(value??'（空值）').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]!));

export function scatterChart(visual:Visual,result:Result){
  const data=result.scatter;
  if(!data||data.version!==1)throw new Error('缺少相容的散點座標，請重新查詢。');
  const groups=new Map<string,typeof data.points>();
  const seen=new Set<number>();
  for(const point of data.points){
    if(!Number.isInteger(point.row_index)||point.row_index<0||!result.rows?.[point.row_index]||seen.has(point.row_index)||
      !Number.isFinite(point.x)||!Number.isFinite(point.y)||point.size!==null&&(!Number.isFinite(point.size)||point.size<0))throw new Error('散點座標或列索引無效。');
    seen.add(point.row_index);
    const key=JSON.stringify([typeof point.group,point.group]);
    const group=groups.get(key)??[];group.push(point);groups.set(key,group);
  }
  const maximum=Math.max(0,...data.points.map(p=>p.size??0));
  const traces:Data[]=[...groups.values()].map((points,i)=>({type:'scatter',mode:'markers',
    legendgroup:JSON.stringify([typeof points[0].group,points[0].group]),
    x:points.map(p=>p.x),y:points.map(p=>p.y),customdata:points.map(p=>p.group),
    name:data.group_key?escape(points[0].group):'全部',
    text:points.map(p=>`${data.group_key?`${escape(data.group_key)}：${escape(p.group)}<br>`:''}${escape(data.x_key)}：${p.x}<br>${escape(data.y_key??'列序號')}：${p.y}${data.size_key?`<br>${escape(data.size_key)}：${p.size??'（空值）'}`:''}`),
    hoverinfo:'text',marker:{color:data.group_key?colors[i%colors.length]:String(visual.visualization.extra.color??colors[0]),
      symbol:symbols[i%symbols.length],size:points.map(p=>data.size_key&&maximum?Math.max(7,40*Math.sqrt((p.size??0)/maximum)):9),opacity:.8}
  } as Data));
  for(const fit of data.trendlines??[]){
    if(fit.status!=='ready')continue;
    if(fit.x.length!==fit.y.length||fit.x.some(v=>!Number.isFinite(v))||fit.y.some(v=>!Number.isFinite(v)))throw new Error('趨勢線座標無效。');
    const index=[...groups.keys()].indexOf(JSON.stringify([typeof fit.group,fit.group]));
    const label=`${fit.method.toUpperCase()}${data.group_key?` · ${escape(fit.group)}`:''}`;
    traces.push({type:'scatter',mode:'lines',x:fit.x,y:fit.y,name:label,showlegend:false,
      legendgroup:JSON.stringify([typeof fit.group,fit.group]),
      line:{color:data.group_key?colors[Math.max(0,index)%colors.length]:String(visual.visualization.extra.color??colors[0]),dash:'dash',width:2},
      hovertemplate:`${label}<br>%{x}<br>%{y}<extra></extra>`} as Data);
  }
  const layout:Partial<Layout>={xaxis:{title:{text:String(visual.visualization.x_axis_label??data.x_key)}},
    yaxis:{title:{text:String(visual.visualization.y_axis_label??data.y_key??'列序號（從 0 起）')}}};
  return {traces,layout,excluded:data.excluded_count,count:data.points.length};
}
