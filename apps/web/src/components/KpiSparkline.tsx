import type {Result} from '../types';

/** Coordinates are presentation only; daily aggregates come from the API. */
export function KpiSparkline({series}:{series:NonNullable<NonNullable<Result['kpi']>['sparkline']>}) {
  const points=series.points.map(p=>({...p,day:Date.parse(p.date+'T00:00:00Z')/86400000}));
  const finite=points.filter(p=>typeof p.value==='number'&&Number.isFinite(p.value));
  const magnitude=Math.max(1,...finite.map(p=>Math.abs(p.value as number)));
  const values=finite.map(p=>(p.value as number)/magnitude);
  const low=Math.min(...values),high=Math.max(...values);
  const first=points[0]?.day??0,last=points.at(-1)?.day??first;
  const x=(day:number)=>first===last?150:5+(day-first)/(last-first)*290;
  const y=(value:number)=>low===high?30:5+(1-(value/magnitude-low)/(high-low))*50;
  let previous:number|null=null;
  const paths:string[]=[];
  for(const p of points){
    if(typeof p.value!=='number'||!Number.isFinite(p.value)){previous=null;continue;}
    const point=`${x(p.day)},${y(p.value)}`;
    if(previous!==null&&p.day-previous===1)paths[paths.length-1]+=` L${point}`;
    else paths.push(`M${point}`);
    previous=p.day;
  }
  return <section aria-label="KPI 趨勢小圖" className="kpi-sparkline">
    <p>{series.caption}</p>{series.reason&&<p role="status">{series.reason}</p>}
    {!!finite.length&&<svg viewBox="0 0 300 60" role="img" aria-label={`逐日趨勢，${finite.length} 個有效日期；詳細數值見趨勢資料`} style={{width:'100%',height:70}}>
      {paths.map((d,i)=><path key={i} d={d} fill="none" stroke="currentColor" strokeWidth="2"/>)}
      {finite.map(p=><circle key={p.date} cx={x(p.day)} cy={y(p.value as number)} r="2" fill="currentColor"/>)}
    </svg>}
    <details><summary>趨勢資料（{points.length} 個日期）</summary><div style={{maxHeight:220,overflow:'auto'}} tabIndex={0} aria-label="逐日指標資料">
      <table><thead><tr><th scope="col">日期（UTC）</th><th scope="col">指標原值</th></tr></thead><tbody>{points.map(p=><tr key={p.date}><th scope="row">{p.date}</th><td>{p.value??'—'}</td></tr>)}</tbody></table>
    </div></details>
  </section>;
}
