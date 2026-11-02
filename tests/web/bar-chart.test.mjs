import test from 'node:test';
import assert from 'node:assert/strict';
import {barChart} from '../../apps/web/src/components/barChart.ts';
const visual={visualization:{extra:{}}};
const result=()=>({chart_format:{version:1,x_title:'Category',y_title:'Value',y_scale:'log',y_min:1,y_max:100,
  legend_position:'top',show_legend:true,data_labels:true,labels:{m:['2.00','3.00']}},
  bar:{version:1,orientation:'horizontal',mode:'stack',grouped:true,categories:[{label:'<A>',filter_value:1},{label:'B',filter_value:null}],
   series:[{name:'<Group>',metric_key:'m',points:[{row_index:0,category_index:0,value:2},{row_index:1,category_index:1,value:3}]}]}});
test('horizontal bars swap value axes but preserve typed category filters and row labels',()=>{
 const input=result(),before=structuredClone(input),chart=barChart(visual,input),trace=chart.traces[0];
 assert.deepEqual(trace.x,[2,3]);assert.deepEqual(trace.y,[0,1]);assert.deepEqual(trace.customdata,[1,null]);
 assert.deepEqual(trace.text,['2.00','3.00']);assert.equal(trace.name,'&lt;Group&gt;');
 assert.deepEqual(chart.layout.xaxis.range,[0,2]);assert.equal(chart.layout.xaxis.title.text,'Value');
 assert.deepEqual(chart.layout.yaxis.ticktext,['&lt;A&gt;','B']);assert.equal(chart.layout.barmode,'stack');assert.deepEqual(input,before);
});
test('vertical and overlay bars preserve individual values and category positions',()=>{
 const input=result();input.bar.orientation='vertical';input.bar.mode='overlay';
 const chart=barChart(visual,input);assert.deepEqual(chart.traces[0].x,[0,1]);assert.deepEqual(chart.traces[0].y,[2,3]);
 assert.equal(chart.layout.yaxis.type,'log');assert.equal(chart.traces[0].opacity,.65);
 assert.throws(()=>barChart(visual,{}));
});
