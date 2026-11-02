import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';

// Compile the maintained TSX in memory; do not maintain a duplicate renderer.
const require=createRequire(new URL('../../apps/web/package.json',import.meta.url));
const ts=require('typescript');
const {createElement}=require('react');
const {renderToStaticMarkup}=require('react-dom/server');
const source=readFileSync(new URL('../../apps/web/src/components/KpiSparkline.tsx',import.meta.url),'utf8');
const compiled=ts.transpileModule(source,{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText
  .replaceAll('"react/jsx-runtime"',JSON.stringify(pathToFileURL(require.resolve('react/jsx-runtime')).href));
const {KpiSparkline}=await import('data:text/javascript;base64,'+Buffer.from(compiled).toString('base64'));
const render=points=>renderToStaticMarkup(createElement(KpiSparkline,{series:{version:1,status:'ready',reason:null,caption:'UTC daily',truncated:false,limit:365,points}}));

test('sparkline does not connect across absent days or unavailable values',()=>{
  const html=render([{date:'2024-01-01',value:1},{date:'2024-01-02',value:2},
    {date:'2024-01-04',value:3},{date:'2024-01-05',value:null},{date:'2024-01-06',value:4}]);
  assert.equal((html.match(/<path /g)||[]).length,3);
  assert.equal((html.match(/<circle /g)||[]).length,4);
  assert.equal((html.match(/ L/g)||[]).length,1);
  assert.match(html,/<table>/);
  assert.match(html,/2024-01-05/);
});

test('single and constant series remain visible at finite centered coordinates',()=>{
  const single=render([{date:'2024-01-01',value:5}]);
  assert.match(single,/cx="150" cy="30"/);
  const constant=render([{date:'2024-01-01',value:0},{date:'2024-01-02',value:0}]);
  assert.equal((constant.match(/cy="30"/g)||[]).length,2);
  assert.doesNotMatch(single+constant,/NaN|Infinity/);
});

test('extreme finite numbers stay in the view box and exact strings remain table data',()=>{
  const points=[{date:'2024-01-01',value:-1e308},{date:'2024-01-02',value:1e308},
    {date:'2024-01-03',value:'9007199254740993'},{date:'2024-01-04',value:'<script>bad()</script>'}];
  const before=structuredClone(points),html=render(points);
  assert.doesNotMatch(html,/NaN|Infinity|<script>/);
  assert.equal((html.match(/<circle /g)||[]).length,2);
  assert.match(html,/cy="55"/);assert.match(html,/cy="5"/);
  assert.match(html,/9007199254740993/);assert.match(html,/&lt;script&gt;/);
  assert.deepEqual(points,before);
});

test('an unavailable series retains readable values without an empty SVG',()=>{
  const html=render([{date:'2024-01-01',value:'0.1234567890123456789'}]);
  assert.doesNotMatch(html,/<svg/);
  assert.match(html,/0.1234567890123456789/);
});
