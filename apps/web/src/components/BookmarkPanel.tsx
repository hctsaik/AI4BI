import { useState } from 'react';
import type { CommandKind } from '../lib/api';
import type { Bookmark, Dataset, ExplorationView, Report } from '../types';

type BookmarkCommand = Extract<CommandKind,'save_bookmark'|'update_bookmark'|'rename_bookmark'|'delete_bookmark'>;

function incompatibility(item:Bookmark,report:Report,datasets?:Dataset[]) {
  const page=Object.hasOwn(report.pages,item.view.page_id)?report.pages[item.view.page_id]:undefined;
  if(!page)return '頁面已不存在';
  if(item.view.selected_visual_id&&!Object.hasOwn(page.visuals,item.view.selected_visual_id))return '選取圖表已不存在';
  for(const field of datasets?item.fields:[]){
    const column=datasets?.find(d=>d.contract.block_id===field.block_id)?.contract.columns.find(c=>c.name===field.column_name);
    if(!column||column.data_type!==field.data_type)return '資料欄位或型別已變更';
  }
  for(const filter of item.view.filters){
    if(!Object.values(page.visuals).some(v=>v.query.block_refs.some(b=>b.block_id===filter.block_id)))return '此頁已沒有相容資料來源';
    if(filter.source_visual_id){
      const source=Object.hasOwn(page.visuals,filter.source_visual_id)?page.visuals[filter.source_visual_id]:undefined;
      if(!source?.query.dimensions.some(d=>d.block_id===filter.block_id&&d.column_name===filter.column_name&&!d.truncate_date_to))return '來源圖表或維度已變更';
    }
  }
  return '';
}

export function BookmarkPanel({report,datasets,view,busy,onCommand,onApply}:{
  report:Report;datasets?:Dataset[];view:ExplorationView;busy:boolean;
  onCommand:(kind:BookmarkCommand,payload:Record<string,unknown>)=>void;onApply:(id:string)=>void;
}) {
  const [name,setName]=useState('');
  const items=report.web_extensions?.bookmarks??[];
  return <details className="bookmark-panel"><summary>探索書籤（{items.length}）</summary>
    <p>{report.read_only?'套用書籤會還原探索與已捕捉的三層篩選，以此唯讀版本的參數與資料重新計算。':'保存目前頁面、選取圖表、探索與三層篩選。套用只改檢視，不改報表；使用目前參數與資料重新計算。'}</p>
    <fieldset disabled={busy||report.read_only}><form onSubmit={e=>{e.preventDefault();onCommand('save_bookmark',{name,view});}}>
      <label>新書籤名稱<input required maxLength={80} value={name} onChange={e=>setName(e.target.value)}/></label>
      <button disabled={!name.trim()||items.length>=30}>保存目前探索為書籤</button>
    </form></fieldset>
    {items.map(item=>{
      const issue=incompatibility(item,report,datasets);
      return <section key={item.bookmark_id} aria-label={`探索書籤 ${item.name}`}>
        <fieldset disabled={busy||report.read_only}><label>書籤名稱 {item.name}<input key={item.name+String(busy)} maxLength={80} defaultValue={item.name} onBlur={e=>{
          const name=e.target.value.trim();if(name&&name!==item.name)onCommand('rename_bookmark',{bookmark_id:item.bookmark_id,name});else e.target.value=item.name;
        }}/></label></fieldset>
        <p>{report.pages[item.view.page_id]?.display_name||report.pages[item.view.page_id]?.title||item.view.page_id} · {item.view.filters.length} 個探索篩選 · {item.persistent_filters==null?'沿用報表條件':`${item.persistent_filters.length} 個已捕捉持久篩選`} · {Object.keys(item.view.drill_state??{}).length} 個鑽取路徑</p>
        {issue&&<p className="error">無法套用：{issue}。請以目前探索更新書籤。</p>}
        <button disabled={busy||!!issue} onClick={()=>onApply(item.bookmark_id)}>套用書籤 {item.name}</button>
        <button disabled={busy||report.read_only} onClick={()=>onCommand('update_bookmark',{bookmark_id:item.bookmark_id,view})}>以目前探索更新 {item.name}</button>
        <button disabled={busy||report.read_only} onClick={()=>onCommand('delete_bookmark',{bookmark_id:item.bookmark_id})}>刪除書籤 {item.name}</button>
      </section>;
    })}
  </details>;
}
