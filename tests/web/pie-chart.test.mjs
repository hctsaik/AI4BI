import test from 'node:test';
import assert from 'node:assert/strict';
import {pieChart,pieFilterValue} from '../../apps/web/src/components/pieChart.ts';
const result=()=>({rows:[{},{}],pie:{version:1,status:'ready',reason:null,metric_key:'value',weight_total:5,excluded_count:0,
 settings:{hole:.4,show_percent:true,data_labels:false,show_legend:true,legend_position:'right'},
 slices:[{row_index:0,label:'<b>A</b>',value:2,percent:40,filter_value:1},{row_index:1,label:'B',value:3,percent:60,filter_value:'1'}]}});
test('pie displays one weight series with server percentages and typed slice filters',()=>{
 const input=result(),before=structuredClone(input),chart=pieChart(input),trace=chart.traces[0];
 assert.equal(chart.traces.length,1);assert.deepEqual(trace.values,[2,3]);assert.deepEqual(trace.customdata,[1,'1']);
 assert.deepEqual(trace.labels,['&lt;b&gt;A&lt;/b&gt;','B']);assert.ok(trace.text[0].includes('40.00%'));
 assert.equal(trace.hole,.4);assert.equal(chart.layout.showlegend,true);assert.deepEqual(input,before);
});
test('pie respects hole labels and legend positions without recalculating percentages',()=>{
 for(const position of ['top','bottom','left','right','hide']){
  const input=result();Object.assign(input.pie.settings,{hole:0,show_percent:false,data_labels:true,legend_position:position,show_legend:position!=='hide'});
  const chart=pieChart(input);assert.equal(chart.layout.showlegend,position!=='hide');assert.equal(chart.traces[0].hole,0);
  assert.equal(chart.traces[0].text[1],'B<br>3');assert.ok(chart.traces[0].hovertemplate[1].includes('60.00%'));
 }
});
test('pie retains unavailable reasons and rejects duplicate labels or invalid weights',()=>{
 const input=result();input.pie.status='unavailable';input.pie.reason='negative';assert.equal(pieChart(input).reason,'negative');
 for(const mutate of [r=>r.pie.slices[0].value=-1,r=>r.pie.slices[0].row_index=9,r=>r.pie.slices[0].label='B']){
  const invalid=result();mutate(invalid);assert.throws(()=>pieChart(invalid));
 }
});
test('pie event indices resolve a single original value instead of trace customdata arrays',()=>{
 const input=result();assert.deepEqual(pieFilterValue(input,{pointNumbers:[0]}),{value:1});
 assert.deepEqual(pieFilterValue(input,{pointNumber:1}),{value:'1'});
 input.pie.slices[0].filter_value=null;assert.deepEqual(pieFilterValue(input,{pointNumbers:[0]}),{value:null});
 for(const point of [{pointNumbers:[0,1]},{pointNumber:-1},{pointNumber:9},{pointNumbers:['0']},{}])assert.equal(pieFilterValue(input,point),null);
});
