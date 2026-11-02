import type {Data,Layout} from 'plotly.js';
import type {Result} from '../types';

const colors=['#2874a6','#20a397','#e7a645','#735da8','#c56574','#5d8290'];
const escape=(value:unknown)=>String(value??'（空值）').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]!));

export function pieFilterValue(result:Result,point:{pointNumber?:unknown;pointNumbers?:unknown}){
  const indices=point.pointNumbers;
  if(Array.isArray(indices)&&indices.length!==1)return null;
  const index=Array.isArray(indices)?indices[0]:point.pointNumber;
  if(typeof index!=='number'||!Number.isInteger(index)||index<0)return null;
  const slice=result.pie?.slices[index];
  return slice?{value:slice.filter_value}:null;
}

export function pieChart(result:Result){
  const pie=result.pie;
  if(!pie||pie.version!==1)throw new Error('缺少相容的圓餅資料，請重新查詢。');
  if(pie.status!=='ready')return {traces:[],layout:{},reason:pie.reason};
  const {slices,settings}=pie,labels=new Set<string>();
  for(const slice of slices){
    if(labels.has(slice.label)||!Number.isInteger(slice.row_index)||slice.row_index<0||!result.rows?.[slice.row_index]||
      !Number.isFinite(slice.value)||slice.value<0||!Number.isFinite(slice.percent))throw new Error('圓餅資料或標籤無效。');
    labels.add(slice.label);
  }
  const anchors:Record<string,Partial<Layout['legend']>>={top:{orientation:'h',x:0,y:1.12},bottom:{orientation:'h',x:0,y:-.15},
    left:{orientation:'v',x:-.05,xanchor:'right',y:1},right:{orientation:'v',x:1.02,y:1}};
  const text=slices.map(s=>[escape(s.label),...(settings.show_percent?[`${s.percent.toFixed(2)}%`]:[]),...(settings.data_labels?[String(s.value)]:[])].join('<br>'));
  return {reason:null,traces:[{type:'pie',values:slices.map(s=>s.value),labels:slices.map(s=>escape(s.label)),
    ids:slices.map(s=>String(s.row_index)),customdata:slices.map(s=>s.filter_value),hole:settings.hole,sort:false,
    text,textinfo:'text',hovertemplate:slices.map(s=>`${escape(s.label)}<br>${s.value}<br>${s.percent.toFixed(2)}%<extra></extra>`),
    marker:{colors:slices.map((_,i)=>colors[i%colors.length])},showlegend:settings.show_legend} as Data],
    layout:{showlegend:settings.show_legend,legend:anchors[settings.legend_position]??{},margin:{l:25,r:25,t:35,b:50}} as Partial<Layout>};
}
