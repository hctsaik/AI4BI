import type {Data,Layout} from 'plotly.js';
import type {Result,Visual} from '../types';

const escape=(value:unknown)=>String(value??'（空值）').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]!));

export function geographicMap(visual:Visual,result:Result) {
  const geo=result.geo;
  if(!geo||geo.version!==1)throw new Error('缺少相容的地點座標，請重新查詢。');
  const metric=visual.query.metrics[0],metricKey=metric?.alias??metric?.metric_name;
  const seen=new Set<number>();
  const points=geo.points.map(point=>{
    if(!Number.isInteger(point.row_index)||point.row_index<0||seen.has(point.row_index))throw new Error('地圖列索引無效或重複。');
    seen.add(point.row_index);
    const row=result.rows?.[point.row_index];
    if(!row||!Object.hasOwn(row,geo.location_field.key)||!Number.isFinite(point.latitude)||Math.abs(point.latitude)>90||
      !Number.isFinite(point.longitude)||Math.abs(point.longitude)>180)throw new Error('地圖座標或資料列無效。');
    const value=metricKey?row[metricKey]:null;
    if(metricKey&&!Object.hasOwn(row,metricKey))throw new Error('地圖指標欄位缺失。');
    const amount=typeof value==='number'&&Number.isFinite(value)?value:null;
    return {...point,location:row[geo.location_field.key],value,amount};
  });
  const max=Math.max(0,...points.map(p=>Math.abs(p.amount??0)));
  const color=String(visual.visualization.extra.color??'#2874a6');
  const trace={type:'scattergeo',mode:'markers',lat:points.map(p=>p.latitude),lon:points.map(p=>p.longitude),
    customdata:points.map(p=>p.location),text:points.map(p=>`${escape(p.location)}<br>${escape(metricKey??'地點')}：${escape(p.value)}`),
    hoverinfo:'text',showlegend:false,marker:{size:points.map(p=>p.amount===null||p.amount===0?7:Math.max(7,40*Math.sqrt(Math.abs(p.amount)/max))),
      color:points.map(p=>p.amount===null?'#8395a1':p.amount<0?'#b34a57':color),opacity:.8,line:{width:1,color:'#fff'}}} as Data;
  const view=visual.visualization.extra.map_view??'auto';
  const geoLayout={resolution:50,showland:true,landcolor:'#e5ede3',showocean:true,
    oceancolor:'#e7f2f8',showcoastlines:true,coastlinecolor:'#77958c',showcountries:false,showframe:false,
    bgcolor:'transparent',...(view==='taiwan'?{fitbounds:false,center:{lat:23.8,lon:120.5},projection:{type:'mercator',scale:45}}:
      view==='world'?{fitbounds:false,projection:{type:'natural earth',scale:1}}:{fitbounds:'locations',projection:{type:'mercator'}})};
  return {traces:[trace],layout:{geo:geoLayout,margin:{l:0,r:0,t:5,b:0}} as Partial<Layout>,
    mapped:points.length,unmapped:geo.unmapped_count,nonNumeric:points.filter(p=>p.amount===null).length};
}
