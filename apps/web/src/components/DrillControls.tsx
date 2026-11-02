import {useEffect,useMemo,useState} from 'react';
import type {Dataset,DrillState,Filter,Result,Visual} from '../types';
import {VisualChart} from './VisualChart';

export function DrillChart({visual,result,state,busy,onChange,onFilter}:{visual:Visual;result?:Result;state?:DrillState;busy:boolean;
  onChange:(state:DrillState|undefined)=>void;onFilter:(filter:Filter)=>void}) {
  const drill=result?.drill??state;
  const configured=visual.visualization.extra.drill_hierarchy;
  const pendingHierarchy=!drill&&result?.status!=='error'&&Array.isArray(configured)&&configured.length>=2&&configured.every(value=>typeof value==='string')?configured as string[]:null;
  const effective=useMemo(()=>result?.query?{...visual,query:result.query}:visual,[visual,result?.query]);
  const select=(filter:Filter)=>{
    if(pendingHierarchy)return;
    if(!drill){onFilter(filter);return;}
    if(busy)return;
    if(drill.path.length<drill.hierarchy.length-1&&filter.column_name===drill.hierarchy[drill.path.length])
      onChange({...drill,path:[...drill.path,{column:filter.column_name,value:filter.value as DrillState['path'][number]['value']}]});
  };
  return <>{pendingHierarchy&&<nav className="drill-controls" aria-label="圖表鑽取" aria-busy="true">
    <span>全部 · {pendingHierarchy[0]}</span><small role="status">正在準備鑽取…</small>
  </nav>}{drill&&<nav className="drill-controls" aria-label="圖表鑽取">
    <span>全部{drill.path.map(step=>` › ${step.value==null?'（空值）':String(step.value)}`).join('')} · {drill.hierarchy[drill.path.length]}</span>
    <button disabled={busy||!drill.path.length} onClick={()=>onChange({...drill,path:drill.path.slice(0,-1)})}>返回上一層</button>
    <button disabled={busy||!drill.path.length} onClick={()=>onChange(undefined)}>重設鑽取</button>
    <small>{drill.path.length<drill.hierarchy.length-1?`點選分類或數據值，鑽取至 ${drill.hierarchy[drill.path.length+1]}`:'已到最末層'}</small>
  </nav>}<VisualChart visual={effective} result={result} onFilter={select} interactionDisabled={!!pendingHierarchy||!!drill&&(busy||drill.path.length===drill.hierarchy.length-1)} interactionLabel={drill||pendingHierarchy?'鑽取':'篩選'}/></>;
}

export function DrillEditor({visual,datasets,busy,onChange}:{visual:Visual;datasets:Dataset[];busy:boolean;onChange:(hierarchy:string[])=>void}) {
  const stored=JSON.stringify(visual.visualization.extra.drill_hierarchy??[]);
  const [text,setText]=useState<string[]>(JSON.parse(stored));
  useEffect(()=>setText(JSON.parse(stored)),[visual.component_id,stored]);
  const columns=datasets.find(d=>d.contract.block_id===visual.query.block_refs[0]?.block_id)?.contract.columns??[];
  return <details><summary>鑽取層級設定</summary><p>同一資料來源，依序點選分類深入下一欄位。設定會保存；鑽取路徑只改目前檢視。</p>
    <ol>{text.map((column,index)=><li key={index}>{column} <button type="button" disabled={busy} aria-label={`移除鑽取層級 ${index+1}`} onClick={()=>setText(text.filter((_,i)=>i!==index))}>移除</button></li>)}</ol>
    <select aria-label="新增鑽取層級" value="" disabled={busy||text.length>=10} onChange={e=>setText([...text,e.target.value])}>
      <option value="">選擇下一層欄位</option>{columns.filter(c=>!text.includes(c.name)).map(c=><option key={c.name} value={c.name}>{c.name}</option>)}</select>
    <button type="button" disabled={busy||text.length===1||JSON.stringify(text)===stored} onClick={()=>onChange(text)}>保存鑽取層級</button>
    <button type="button" disabled={busy||stored==='[]'} onClick={()=>onChange([])}>停用鑽取</button>
  </details>;
}
