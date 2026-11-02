import test from 'node:test';
import assert from 'node:assert/strict';
import {geographicMap} from '../../apps/web/src/components/geographicMap.ts';
const visual=()=>({query:{dimensions:[{column_name:'city'}],metrics:[{metric_name:'amount',alias:'value'}]},visualization:{extra:{}}});
const source=()=>({rows:[{city:'台北',value:100},{city:'台南',value:-25},{city:'London',value:0},{city:'<b>name</b>',value:null},{city:'unknown',value:7}],
  geo:{version:1,location_field:{key:'city'},mapped_count:4,unmapped_count:1,points:[
    {row_index:0,latitude:25,longitude:121},{row_index:1,latitude:23,longitude:120},
    {row_index:2,latitude:51,longitude:0},{row_index:3,latitude:20,longitude:100}]}});

test('geographic bubbles retain metric signs, nulls, zero and raw filter identities',()=>{
  const input=source(),before=structuredClone(input),map=geographicMap(visual(),input),trace=map.traces[0];
  assert.equal(trace.type,'scattergeo');assert.equal(map.mapped,4);assert.equal(map.unmapped,1);
  assert.deepEqual(trace.marker.size,[40,20,7,7]);
  assert.equal(trace.marker.color[1],'#b34a57');assert.equal(trace.marker.color[3],'#8395a1');
  assert.deepEqual(trace.customdata,['台北','台南','London','<b>name</b>']);
  assert.ok(trace.text[3].includes('&lt;b&gt;'));assert.deepEqual(input,before);
});

test('map range controls use offline geographic projection with fixed resolution',()=>{
  for(const [view,fit,projection] of [['auto','locations','mercator'],['taiwan',false,'mercator'],['world',false,'natural earth']]){
    const chart=visual();chart.visualization.extra.map_view=view;
    const map=geographicMap(chart,source());
    assert.equal(map.layout.geo.fitbounds,fit);assert.equal(map.layout.geo.resolution,50);
    assert.equal(map.layout.geo.projection.type,projection);
  }
});

test('invalid coordinates and row bindings are rejected before plotting',()=>{
  for(const mutate of [r=>r.geo.version=2,r=>r.geo.points[0].latitude=91,r=>r.geo.points[0].longitude=Infinity,
    r=>r.geo.points[0].row_index=99,r=>r.geo.points.push(r.geo.points[0]),r=>delete r.rows[0].value]){
    const input=source();mutate(input);assert.throws(()=>geographicMap(visual(),input));
  }
  const input=source();input.geo.points=[];input.geo.unmapped_count=5;
  assert.equal(geographicMap(visual(),input).mapped,0);
});
