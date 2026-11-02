import test from 'node:test';
import assert from 'node:assert/strict';
import {smallMultiples} from '../../apps/web/src/components/smallMultiples.ts';

const visual = () => ({component_id:'facets',col_span:12,query:{spec_id:'facets',block_refs:[{block_id:'source'}],
  dimensions:[{block_id:'source',column_name:'category'},{block_id:'source',column_name:'x'}],
  metrics:[{block_id:'source',metric_name:'amount'}],filters:[],sort:[]},
  visualization:{visual_type:'small_multiples',height_px:400,show_legend:false,extra:{facet_wrap:2,facet_shared_y:true}}});
const result = () => ({status:'ready',columns:['category','x','amount'],rows:
  [null,'null',false,'false',1,'1',...Array.from({length:8},(_,i)=>`group-${i}`)].flatMap((category,i)=>[
    {category,x:2,amount:i===0?null:20+i},{category,x:1,amount:10+i}])});

test('typed facets and missing measures retain core values through page layout', () => {
  const source=result(), original=structuredClone(source);
  const first=smallMultiples(visual(),source,0,'#2874a6'),second=smallMultiples(visual(),source,1,'#2874a6');
  assert.equal(first.error,null);assert.equal(first.facets.length,14);
  assert.equal(first.visible.length,12);assert.equal(second.visible.length,2);assert.equal(first.pages,2);
  const traces=[...first.traces,...second.traces];
  assert.ok(traces.every(item=>item.type==='scatter'&&JSON.stringify(item.x)==='[1,2]'));
  assert.deepEqual(traces.find(item=>item.customdata[0]===null).y,[10,null]);
  for(const value of [null,'null',false,'false',1,'1'])assert.equal(traces.filter(item=>item.customdata[0]===value).length,1);
  assert.equal(new Set(first.facets.map(item=>item.label)).size,14);
  assert.deepEqual(source,original);
});

test('shared scale covers all pages while independent axes preserve autoscaling', () => {
  const chart=visual(),source=result();
  const first=smallMultiples(chart,source,0,'blue'),second=smallMultiples(chart,source,1,'blue');
  assert.deepEqual(first.layout.yaxis.range,second.layout.yaxis.range);
  assert.ok(first.layout.yaxis.range[0]<10&&first.layout.yaxis.range[1]>33);
  assert.equal(first.layout.yaxis2.matches,'y');assert.equal(first.layout.grid.columns,2);
  chart.visualization.extra={facet_wrap:999};
  const independent=smallMultiples(chart,source,999,'blue');
  assert.equal(independent.page,1);assert.equal(independent.layout.yaxis.range,undefined);
  const fallback=smallMultiples(chart,source,0,'blue');assert.equal(fallback.layout.grid.columns,3);
});

test('single dimension uses bars and includes zero in shared scale', () => {
  const chart=visual();chart.query.dimensions.splice(1);
  const source={status:'ready',columns:['category','amount'],rows:[{category:'A',amount:100},{category:'B',amount:200}]};
  const output=smallMultiples(chart,source,0,'blue');
  assert.equal(output.error,null);assert.ok(output.traces.every(item=>item.type==='bar'));
  assert.ok(output.layout.yaxis.range[0]<=0);assert.deepEqual(output.traces.map(item=>item.y),[[100],[200]]);
});

test('numeric facet and horizontal ordering are numeric without merging text values', () => {
  const source={status:'ready',columns:['category','x','amount'],rows:[
    {category:10,x:10,amount:1},{category:2,x:10,amount:2},{category:2,x:2,amount:3},{category:'2',x:1,amount:4}]};
  const output=smallMultiples(visual(),source,0,'blue');
  assert.deepEqual(output.facets.map(item=>item.value),[2,10,'2']);
  assert.deepEqual(output.traces[0].x,[2,10]);assert.deepEqual(output.traces[0].y,[3,2]);
});

test('ambiguous cells, missing columns, nonnumeric measures and extra dimensions are explicit errors', () => {
  const chart=visual(),source=result();
  assert.match(smallMultiples(chart,{...source,rows:[source.rows[0],source.rows[0]]},0,'blue').error,/不唯一/);
  assert.match(smallMultiples(chart,{...source,columns:['category','x']},0,'blue').error,/欄位/);
  for(const amount of ['12',Infinity,NaN])assert.match(smallMultiples(chart,{...source,rows:[{category:'a',x:1,amount}]},0,'blue').error,/有限數值/);
  chart.query.dimensions.push({block_id:'source',column_name:'extra'});
  assert.match(smallMultiples(chart,source,0,'blue').error,/至多一個橫軸/);
});

test('aliases resolve result columns and category markup remains literal text', () => {
  const chart=visual();chart.query.dimensions[0].alias='group';chart.query.metrics[0].alias='measure';
  const source={status:'ready',columns:['group','x','measure'],rows:[{group:'<b>A & B</b>',x:1,measure:7}]};
  const output=smallMultiples(chart,source,0,'blue');
  assert.equal(output.error,null);assert.equal(output.traces[0].y[0],7);
  assert.equal(output.layout.annotations[0].text,'&lt;b&gt;A &amp; B&lt;/b&gt;');
  assert.equal(output.traces[0].customdata[0],'<b>A & B</b>');
});
