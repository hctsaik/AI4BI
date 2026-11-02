import type { components } from '../generated/api';
export type CommandKind = components['schemas']['Command']['command_type'];
let bearer: string | null = null;
export class ApiError extends Error {
  constructor(public code: string, message: string, public status: number) { super(message); }
}
export async function api<T>(path: string, body?: unknown, method?: string, signal?: AbortSignal): Promise<T> {
  const headers: Record<string, string> = { 'x-ai4bi-request': '1' };
  if (bearer) headers.authorization = `Bearer ${bearer}`;
  if (body !== undefined && !(body instanceof FormData)) headers['content-type'] = 'application/json';
  const response = await fetch(`/api/v1${path}`, {method: method ?? (body === undefined ? 'GET' : 'POST'),
    credentials: 'same-origin', headers, body: body instanceof FormData ? body : body === undefined ? undefined : JSON.stringify(body), signal});
  const data = await response.json();
  if (!response.ok) throw new ApiError(data.error?.code ?? 'REQUEST_FAILED', data.error?.message ?? '操作失敗，請稍後再試。', response.status);
  return data;
}
export async function pair(code: string) {
  const result = await api<{token: string}>('/session', {code});
  bearer = result.token;
}
export async function downloadArtifact(artifactId:string, filename:string, signal?:AbortSignal):Promise<void> {
  const headers:Record<string,string> = {'x-ai4bi-request':'1'};
  if(bearer)headers.authorization=`Bearer ${bearer}`;
  const response=await fetch(`/api/v1/artifacts/${encodeURIComponent(artifactId)}`,{
    credentials:'same-origin',headers,signal,redirect:'error'});
  if(!response.ok){
    const body=await response.json().catch(()=>null);
    throw new ApiError(body?.error?.code??'DOWNLOAD_FAILED',body?.error?.message??'下載失敗，請稍後再試。',response.status);
  }
  const blob=await response.blob();
  if(signal?.aborted)throw new DOMException('Aborted','AbortError');
  const url=URL.createObjectURL(blob);
  const link=document.createElement('a');
  try{
    link.href=url;link.download=filename;document.body.appendChild(link);link.click();
  }catch(error){URL.revokeObjectURL(url);throw error;}
  finally{link.remove();}
  // Keep the blob available while the browser hands the click to its download
  // manager. Revocation releases it even when the user dismisses Save As.
  setTimeout(()=>URL.revokeObjectURL(url),60000);
}
export function key() { return crypto.randomUUID(); }
export async function pollJob<T>(jobId: string, signal?: AbortSignal): Promise<T> {
  for (;;) {
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    const job = await api<{status: string; result: T; error?: {message:string}}>('/jobs/' + jobId, undefined, undefined, signal);
    if (job.status === 'succeeded') return job.result;
    if (job.status === 'failed' || job.status === 'cancelled') throw new Error(job.error?.message ?? '工作已取消。');
    await new Promise(resolve => setTimeout(resolve, 200));
  }
}
