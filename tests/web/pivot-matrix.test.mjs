import test from 'node:test';
import assert from 'node:assert/strict';
import {pivotMatrix,pivotKey} from '../../apps/web/src/components/pivotMatrix.ts';

const frame=rows=>({status:'ready',rows});
const source=()=>({...frame([{row:'A',column:'X',avg:3},{row:'A',column:'Y',avg:12},{row:'B',column:'X',avg:30}]),
  pivot:{version:1,row_field:{block_id:'b',column_name:'row',key:'row'},column_field:{block_id:'b',column_name:'column',key:'column'},
    metrics:[{block_id:'b',metric_name:'average',key:'avg'}],totals_scope:'filtered_population',having_scope:'each_aggregation_grain',
    row_totals:frame([{row:'A',avg:6},{row:'B',avg:30}]),column_totals:frame([{column:'X',avg:12},{column:'Y',avg:12}]),
    grand_total:frame([{avg:12}]),truncated:false}});

test('pivot indexes core totals without recomputing nonadditive measures',()=>{
  const input=source(),before=structuredClone(input),m=pivotMatrix(input);
  assert.equal(m.cells.get(pivotKey('A')).get(pivotKey('X')).avg,3);
  assert.equal(m.rowTotals.get(pivotKey('A')).avg,6);
  assert.equal(m.columnTotals.get(pivotKey('X')).avg,12);
  assert.equal(m.grand.avg,12);
  assert.equal(m.cells.get(pivotKey('B')).get(pivotKey('Y')),undefined);
  assert.deepEqual(input,before);
});

test('typed keys, null measures and colliding display labels remain distinct',()=>{
  const input=source(),values=[null,'（空值）',1,'1',true,'true'];
  input.rows=values.map(row=>({row,column:'X',avg:null}));
  input.pivot.row_totals=frame(values.map(row=>({row,avg:null})));
  const m=pivotMatrix(input);
  assert.equal(m.rows.length,6);assert.equal(new Set(m.rows.map(r=>r.label)).size,6);
  for(const value of values)assert.equal(m.cells.get(pivotKey(value)).get(pivotKey('X')).avg,null);
});

test('limited cells preserve independent total axes without materializing missing cells',()=>{
  const input=source();input.rows=[input.rows[0]];
  const m=pivotMatrix(input);
  assert.equal(m.rows.length,2);assert.equal(m.columns.length,2);
  assert.equal(m.cells.size,1);assert.equal(m.cells.get(pivotKey('B')),undefined);
  assert.equal(m.grand.avg,12);
});

test('one dimension and empty grain totals have explicit representations',()=>{
  const input=source();input.pivot.column_field=null;input.pivot.column_totals=null;
  input.rows=[{row:'A',avg:6}];input.pivot.grand_total=frame([]);
  const m=pivotMatrix(input);
  assert.equal(m.columns.length,1);assert.equal(m.grand,undefined);
  assert.equal(m.cells.get(pivotKey('A')).get(pivotKey(null)).avg,6);
});

test('duplicate combinations, missing metrics and incompatible contracts fail explicitly',()=>{
  for(const mutate of [
    r=>r.rows.push(r.rows[0]),r=>delete r.rows[0].avg,
    r=>r.pivot.row_totals.rows.push(r.pivot.row_totals.rows[0]),
    r=>r.pivot.grand_total.rows.push({avg:4}),r=>r.pivot.version=2,
    r=>r.pivot.metrics[0].key='row',r=>r.rows[0].row={},
  ]){const input=source();mutate(input);assert.throws(()=>pivotMatrix(input));}
});

test('high cardinality input remains sparse',()=>{
  const input=source();input.rows=Array.from({length:5000},(_,i)=>({row:`r${i}`,column:`c${i}`,avg:i}));
  input.pivot.row_totals=frame([]);input.pivot.column_totals=frame([]);
  const m=pivotMatrix(input);
  assert.equal(m.rows.length,5000);assert.equal(m.columns.length,5000);
  assert.equal([...m.cells.values()].reduce((n,row)=>n+row.size,0),5000);
});
