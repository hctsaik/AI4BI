import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(new URL('../../apps/web/package.json',import.meta.url));
const ts=require('typescript');
const source=readFileSync(new URL('../../apps/web/src/lib/api.ts',import.meta.url),'utf8');
const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
let sequence=0;
const load=()=>import('data:text/javascript;base64,'+Buffer.from(compiled).toString('base64')+'#'+sequence++);

function browser(t){
  const events=[];
  const oldDocument=globalThis.document;
  const link={href:'',download:'',click(){events.push('click');},remove(){events.push('remove');}};
  globalThis.document={createElement:()=>link,body:{appendChild(){events.push('append');}}};
  t.after(()=>{if(oldDocument===undefined)delete globalThis.document;else globalThis.document=oldDocument;});
  t.mock.method(URL,'createObjectURL',blob=>{events.push(blob);return 'blob:local-artifact';});
  t.mock.method(URL,'revokeObjectURL',url=>events.push(['revoke',url]));
  let cleanup;
  t.mock.method(globalThis,'setTimeout',(callback,delay)=>{assert.equal(delay,60000);cleanup=callback;return 0;});
  return {events,link,cleanup:()=>cleanup?.()};
}

test('download uses authenticated fetch then the actual blob and releases its URL',async t=>{
  const ui=browser(t), api=await load(), calls=[];
  const bytes=new Blob(['export-data'],{type:'application/octet-stream'});
  t.mock.method(globalThis,'fetch',async(url,options)=>{
    calls.push({url,options});
    return url.endsWith('/session')?{ok:true,json:async()=>({token:'test-only-token'})}:{ok:true,blob:async()=>bytes};
  });
  await api.pair('test-pair-code');
  await api.downloadArtifact('a/b','report.xlsx');
  assert.equal(calls[1].url,'/api/v1/artifacts/a%2Fb');
  assert.equal(calls[1].options.headers.authorization,'Bearer test-only-token');
  assert.equal(calls[1].options.credentials,'same-origin');
  assert.equal(calls[1].options.redirect,'error');
  assert.equal(ui.link.href,'blob:local-artifact');
  assert.equal(ui.link.download,'report.xlsx');
  assert.deepEqual(ui.events,[bytes,'append','click','remove']);
  ui.cleanup();
  assert.deepEqual(ui.events.at(-1),['revoke','blob:local-artifact']);
});

test('an expired cookie cannot become a downloaded error document',async t=>{
  const ui=browser(t), api=await load();
  t.mock.method(globalThis,'fetch',async()=>({ok:false,status:401,json:async()=>({error:{code:'SESSION_REQUIRED',message:'Pair again'}})}));
  await assert.rejects(api.downloadArtifact('artifact','report.xlsx'),error=>error.code==='SESSION_REQUIRED'&&error.status===401);
  assert.deepEqual(ui.events,[]);
});

test('closing a publication while bytes arrive suppresses its download',async t=>{
  const ui=browser(t), api=await load(), abort=new AbortController();
  t.mock.method(globalThis,'fetch',async(_url,options)=>{
    assert.equal(options.signal,abort.signal);
    assert.equal(options.headers.authorization,undefined);
    return {ok:true,blob:async()=>{abort.abort();return new Blob(['data']);}};
  });
  await assert.rejects(api.downloadArtifact('artifact','report.xlsx',abort.signal),{name:'AbortError'});
  assert.deepEqual(ui.events,[]);
});
