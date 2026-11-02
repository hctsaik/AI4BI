import type {Data, Layout} from 'plotly.js';
import type {Result, Row, Visual} from '../types';

export const FACETS_PER_PAGE = 12;
type Value = Row[string];
type Facet = {key:string;value:Value;label:string;rows:Row[]};
const identity = (value:Value) => JSON.stringify([typeof value,value]);
const label = (value:Value) => value===null?'（空值）':String(value);
const escapeText = (value:string) => value.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
const compare = (a:Value,b:Value) => a===b?0:a===null?-1:b===null?1:
  typeof a!==typeof b?typeof a< typeof b?-1:1:
  typeof a==='number'&&typeof b==='number'?a-b:String(a).localeCompare(String(b));

export function smallMultiples(visual:Visual, result:Result, requestedPage:number, color:string) {
  const columns=result.columns??[];
  const dims=visual.query.dimensions;
  const metric=visual.query.metrics[0];
  const resolve=(alias:string|undefined,raw:string|undefined) => [alias,raw].find((name):name is string=>!!name&&columns.includes(name));
  const facetColumn=resolve(dims[0]?.alias,dims[0]?.column_name);
  const xColumn=resolve(dims[1]?.alias,dims[1]?.column_name);
  const yColumn=resolve(metric?.alias,metric?.metric_name);
  const empty={facets:[] as Facet[],visible:[] as Facet[],page:0,pages:1,traces:[] as Data[],layout:{} as Partial<Layout>};
  if(!facetColumn||!yColumn||dims.length>2||(dims.length===2&&!xColumn))
    return {...empty,error:'小倍數圖需要一個分面維度、至多一個橫軸維度，以及查詢結果中的指標欄位。'};
  const groups=new Map<string,Facet>();
  const cells=new Set<string>();
  for(const row of result.rows??[]) {
    const value=row[facetColumn];
    if(value===undefined||(xColumn&&row[xColumn]===undefined)||row[yColumn]===undefined)
      return {...empty,error:'查詢結果缺少小倍數圖需要的欄位，請重新查詢。'};
    if(row[yColumn]!==null&&(typeof row[yColumn]!=='number'||!Number.isFinite(row[yColumn])))
      return {...empty,error:'小倍數圖的指標必須是有限數值或空值。'};
    const key=identity(value);
    const cell=JSON.stringify([key,xColumn?identity(row[xColumn]):null]);
    if(cells.has(cell))return {...empty,error:'分面與橫軸組合不唯一，請調整查詢維度；圖表不會自行加總。'};
    cells.add(cell);
    if(!groups.has(key))groups.set(key,{key,value,label:label(value),rows:[]});
    groups.get(key)!.rows.push(row);
  }
  const facets=[...groups.values()].sort((a,b)=>compare(a.value,b.value));
  const labels=new Map<string,number>();
  for(const facet of facets)labels.set(facet.label,(labels.get(facet.label)??0)+1);
  for(const facet of facets)if((labels.get(facet.label)??0)>1)
    facet.label+=facet.value===null?'（空值型別）':typeof facet.value==='string'?'（文字）':typeof facet.value==='number'?'（數值）':'（布林）';
  const pages=Math.max(1,Math.ceil(facets.length/FACETS_PER_PAGE));
  const page=Math.max(0,Math.min(pages-1,Math.trunc(requestedPage)||0));
  const visible=facets.slice(page*FACETS_PER_PAGE,(page+1)*FACETS_PER_PAGE);
  const setting=Number(visual.visualization.extra.facet_wrap??3);
  const wrap=Number.isInteger(setting)&&setting>=1&&setting<=6?setting:3;
  const cols=Math.max(1,Math.min(wrap,visible.length)), rows=Math.ceil(visible.length/cols);
  const layout:Partial<Layout>={grid:{rows,columns:cols,pattern:'independent',xgap:0.22,ygap:0.35},
    height:Math.max(180,rows*190),margin:{l:55,r:20,t:35,b:55},showlegend:false,annotations:[]};
  let low=Infinity,high=-Infinity;
  for(const row of result.rows??[])if(typeof row[yColumn]==='number') {
    low=Math.min(low,row[yColumn] as number);high=Math.max(high,row[yColumn] as number);
  }
  if(!xColumn){low=Math.min(0,low);high=Math.max(0,high);}
  const span=high-low;
  const padding=(Number.isFinite(span)&&span>0?span:Math.max(Math.abs(low),Math.abs(high),1))*0.05;
  const sharedRange=Number.isFinite(low)&&Number.isFinite(high)?[
    Number.isFinite(low-padding)?low-padding:low,Number.isFinite(high+padding)?high+padding:high]:undefined;
  const traces:Data[]=visible.map((facet,index)=>{
    const suffix=index?String(index+1):'';
    const xaxis=`x${suffix}`,yaxis=`y${suffix}`;
    const points=[...facet.rows];
    if(xColumn)points.sort((a,b)=>compare(a[xColumn],b[xColumn]));
    layout[`xaxis${suffix}` as 'xaxis']={type:xColumn?undefined:'category',gridcolor:'#edf1f4',zeroline:false,automargin:true};
    layout[`yaxis${suffix}` as 'yaxis']={gridcolor:'#edf1f4',zeroline:false,automargin:true,
      range:visual.visualization.extra.facet_shared_y===true?sharedRange:undefined,
      matches:visual.visualization.extra.facet_shared_y===true&&index?'y':undefined};
    layout.annotations!.push({text:escapeText(facet.label),xref:`${xaxis} domain` as 'x domain',
      yref:`${yaxis} domain` as 'y domain',x:0.5,y:1.05,xanchor:'center',yanchor:'bottom',showarrow:false});
    return {type:xColumn?'scatter':'bar',mode:'lines+markers',name:facet.label,
      x:points.map(row=>xColumn?(typeof row[xColumn]==='boolean'?String(row[xColumn]):row[xColumn]):facet.label),
      y:points.map(row=>row[yColumn]),customdata:points.map(()=>facet.value),
      xaxis,yaxis,connectgaps:false,marker:{color,size:7},line:{color,width:2.5},
      hovertemplate:'%{x}<br>%{y:,.3f}<extra></extra>'} as Data;
  });
  return {facets,visible,page,pages,traces,layout,error:null};
}
