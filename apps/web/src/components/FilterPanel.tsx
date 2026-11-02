import { useEffect, useState } from 'react';
import type { CommandKind } from '../lib/api';
import type { Dataset, PersistentFilter, Report } from '../types';
import { FilterExpressionEditor, emptyGroup, groupFromSaved, serializeGroup, expressionLabel, filterOperators as operators, parseFilterValue } from './FilterExpressionEditor';

const scopes={report:'整份報表',page:'指定頁面',visual:'指定圖表'};
type FilterCommand=Extract<CommandKind,'add_filter'|'update_filter'|'delete_filter'>;

export function FilterPanel({report,datasets,pageId,selectedId,busy,onCommand}:{
  report:Report;datasets:Dataset[];pageId:string;selectedId:string;busy:boolean;
  onCommand:(kind:FilterCommand,payload:Record<string,unknown>)=>void;
}) {
  const [editing,setEditing]=useState<string|null>(null),[scope,setScope]=useState<PersistentFilter['scope']>('report');
  const [targetPage,setTargetPage]=useState(pageId),[targetVisual,setTargetVisual]=useState(selectedId);
  const [block,setBlock]=useState(datasets[0]?.contract.block_id??''),[column,setColumn]=useState('');
  const [operator,setOperator]=useState<keyof typeof operators>('eq'),[value,setValue]=useState(''),[error,setError]=useState('');
  const [mode,setMode]=useState<'single'|'group'>('single'),[group,setGroup]=useState(emptyGroup);
  const items=report.web_extensions?.persistent_filters??[];
  useEffect(()=>{if(!editing){setTargetPage(pageId);setTargetVisual(selectedId);}},[pageId,selectedId,editing]);
  useEffect(()=>{if(editing&&!items.some(f=>f.filter_id===editing))setEditing(null);},[items,editing]);
  const contract=datasets.find(d=>d.contract.block_id===block)?.contract;
  const dtype=contract?.columns.find(c=>c.name===column)?.data_type.toLowerCase()??'string';
  const numeric=['integer','int','int64','int32','number','float','numeric','double','decimal'].includes(dtype);
  const boolean=['boolean','bool'].includes(dtype),multiple=['in','not_in','between'].includes(operator),empty=['is_null','is_not_null'].includes(operator);
  function edit(item:PersistentFilter){
    setEditing(item.filter_id);setScope(item.scope);setTargetPage(item.page_id??pageId);setTargetVisual(item.visual_id??selectedId);
    setBlock(item.block_id);setError('');
    if('expression' in item){setMode('group');setGroup(groupFromSaved(item.expression));}
    else {setMode('single');setColumn(item.column_name);setOperator(item.operator as keyof typeof operators);
      setValue(Array.isArray(item.value)?item.value.map(String).join('\n'):item.value==null?'':String(item.value));}
  }
  return <details className="filter-panel"><summary>已保存的篩選（{items.length}）</summary>
    <p>各筆篩選須同時符合（AND）；群組內可選全部符合或任一符合，最多四層。群組使用同一資料來源，全報表合計最多 100 個條件。清除探索選取不會移除這些條件。</p>
    <fieldset disabled={busy||report.read_only}><form onSubmit={e=>{e.preventDefault();setError('');
      try{
        if(!contract)throw new Error('請選擇資料來源。');
        const predicate=mode==='group'?{expression:serializeGroup(group,contract)}:{column_name:column,operator,value:parseFilterValue(value,dtype,operator)};
        const filter={scope,page_id:scope==='report'?null:targetPage,visual_id:scope==='visual'?targetVisual:null,block_id:block,...predicate};
        onCommand(editing?'update_filter':'add_filter',{filter,...(editing?{filter_id:editing}:{})});
      }catch(e){setError(e instanceof Error?e.message:String(e));}
    }}>
      <label>篩選組合<select aria-label="篩選組合" value={mode} onChange={e=>setMode(e.target.value as 'single'|'group')}><option value="single">單一條件</option><option value="group">AND／OR 群組</option></select></label>
      <label>篩選作用範圍<select aria-label="篩選作用範圍" value={scope} onChange={e=>setScope(e.target.value as PersistentFilter['scope'])}>{Object.entries(scopes).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label>
      {scope!=='report'&&<label>篩選頁面<select aria-label="篩選頁面" value={targetPage} onChange={e=>{setTargetPage(e.target.value);setTargetVisual('');}}>{Object.entries(report.pages).map(([id,p])=><option key={id} value={id}>{p.display_name||p.title}</option>)}</select></label>}
      {scope==='visual'&&<label>篩選圖表<select aria-label="篩選圖表" required value={targetVisual} onChange={e=>setTargetVisual(e.target.value)}><option value="">選擇圖表</option>{Object.entries(report.pages[targetPage]?.visuals??{}).map(([id,v])=><option key={id} value={id}>{v.visualization.title||id}</option>)}</select></label>}
      <label>篩選資料來源<select aria-label="篩選資料來源" required value={block} onChange={e=>{setBlock(e.target.value);setColumn('');setValue('');setGroup(emptyGroup());}}><option value="">選擇資料來源</option>{datasets.map(d=><option key={d.dataset_id} value={d.contract.block_id}>{d.contract.description||d.contract.block_id}</option>)}</select></label>
      {mode==='group'?<FilterExpressionEditor value={group} columns={contract?.columns??[]} onChange={setGroup}/>:<>
      <label>篩選欄位<select aria-label="篩選欄位" required value={column} onChange={e=>{setColumn(e.target.value);setValue('');}}><option value="">選擇欄位</option>{contract?.columns.map(c=><option key={c.name} value={c.name}>{c.name}（{c.data_type}）</option>)}</select></label>
      <label>篩選條件<select aria-label="篩選條件" value={operator} onChange={e=>setOperator(e.target.value as keyof typeof operators)}>{Object.entries(operators).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label>
      {!empty&&<label>篩選值{multiple?<textarea aria-label="篩選值" value={value} onChange={e=>setValue(e.target.value)} placeholder="每行一個值；區間需兩行，文字保留空白"/>:boolean?<select aria-label="篩選值" required value={value} onChange={e=>setValue(e.target.value)}><option value="">選擇布林值</option><option value="true">true</option><option value="false">false</option></select>:<input aria-label="篩選值" type={numeric?'number':dtype==='date'?'date':dtype==='timestamp'||dtype==='datetime'?'datetime-local':'text'} step="any" required={numeric||dtype==='date'} value={value} onChange={e=>setValue(e.target.value)}/>}</label>}
      </>}
      <button disabled={!block||mode==='single'&&!column||!editing&&items.length>=100}>{editing?'更新篩選':'新增篩選'}</button>
      {editing&&<button type="button" onClick={()=>{setEditing(null);setError('');}}>取消編輯篩選</button>}
      {error&&<p role="alert">{error}</p>}
    </form></fieldset>
    {items.map((item,index)=><section key={item.filter_id} aria-label={`已保存篩選 ${index+1}`}>
      <p>{scopes[item.scope]}{item.page_id?` · ${report.pages[item.page_id]?.display_name||report.pages[item.page_id]?.title||item.page_id}`:''}{item.visual_id?` · ${report.pages[item.page_id!]?.visuals[item.visual_id]?.visualization.title||item.visual_id}`:''}：{item.block_id} · {expressionLabel('expression' in item?item.expression:item)}</p>
      <button disabled={busy||report.read_only} onClick={()=>edit(item)}>編輯篩選 {index+1}</button>
      <button disabled={busy||report.read_only} onClick={()=>onCommand('delete_filter',{filter_id:item.filter_id})}>刪除篩選 {index+1}</button>
    </section>)}
  </details>;
}
