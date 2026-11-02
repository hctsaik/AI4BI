import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import type { Result } from '../types';
import { DataTable } from './VisualChart';

export function DatasetPreview({workspaceId,datasetId}:{workspaceId:string;datasetId:string}) {
  const [offset,setOffset]=useState(0);
  const [result,setResult]=useState<Result|null>(null);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState('');
  const [attempt,setAttempt]=useState(0);
  useEffect(()=>{
    const controller=new AbortController();
    setLoading(true);setError('');
    void api<Result>(`/workspaces/${workspaceId}/datasets/${datasetId}/preview?offset=${offset}&limit=100`,undefined,undefined,controller.signal)
      .then(value=>{if(!controller.signal.aborted)setResult(value);})
      .catch(reason=>{if(!controller.signal.aborted)setError(reason instanceof Error?reason.message:String(reason));})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return ()=>controller.abort();
  },[workspaceId,datasetId,offset,attempt]);
  function go(next:number){if(loading)return;setLoading(true);setOffset(next);}
  return <section className="preview-panel" aria-busy={loading}>
    <h3>資料預覽 {result&&<small>{result.row_count} 列</small>}</h3>
    {loading&&<p role="status">載入資料中…</p>}
    {error&&<div role="alert">{error} <button onClick={()=>setAttempt(value=>value+1)}>重試預覽</button></div>}
    {result&&<>{!loading&&!error&&<DataTable result={{...result,row_count:result.rows?.length??0}}/>}
      <nav className="table-pagination" aria-label="資料預覽分頁">
        <button aria-disabled={loading||offset===0} onClick={()=>{if(offset>0)go(Math.max(0,offset-100));}}>上一頁</button>
        <span role="status">{loading?'載入中…':error?'預覽未完成':`第 ${result.rows?.length?offset+1:0}–${offset+(result.rows?.length??0)}／共 ${result.row_count} 列`}</span>
        <button aria-disabled={loading||offset+100>=(result.row_count??0)} onClick={()=>{if(offset+100<(result.row_count??0))go(offset+100);}}>下一頁</button>
      </nav></>}
  </section>;
}
