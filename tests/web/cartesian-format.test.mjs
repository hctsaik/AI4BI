import test from 'node:test';
import assert from 'node:assert/strict';
import {cartesianFormat} from '../../apps/web/src/components/cartesianFormat.ts';
const settings={version:1,y_scale:'linear',y_min:null,y_max:null,x_title:'City',y_title:'Revenue',legend_position:'bottom',show_legend:true,data_labels:false,labels:{}};
test('baseline uses raw data coordinates in both orientations and omits unavailable results',()=>{
 const ready={...settings,y_scale:'log',baseline:{status:'ready',value:100}};
 const vertical=cartesianFormat(ready).shapes[0],horizontal=cartesianFormat(ready,true).shapes[0];
 assert.equal(vertical.y0,100);assert.equal(vertical.yref,'y');assert.equal(vertical.xref,'paper');
 assert.equal(horizontal.x0,100);assert.equal(horizontal.xref,'x');assert.equal(horizontal.yref,'paper');
 assert.equal(cartesianFormat({...settings,baseline:{status:'unavailable'}}).shapes,undefined);
});
test('cartesian axes preserve linear bounds and convert log ranges exactly once',()=>{
 const linear=cartesianFormat({...settings,y_min:-2,y_max:100});assert.deepEqual(linear.yaxis.range,[-2,100]);
 const log=cartesianFormat({...settings,y_scale:'log',y_min:1,y_max:1000});assert.deepEqual(log.yaxis.range,[0,3]);
 assert.equal(log.yaxis.autorange,false);assert.equal(log.xaxis.title.text,'City');
});
test('one-sided log bounds use exponents and legend is explicit',()=>{
 const chart=cartesianFormat({...settings,y_scale:'log',y_min:10,show_legend:false});
 assert.deepEqual(chart.yaxis.autorangeoptions,{minallowed:1});assert.equal(chart.yaxis.range,undefined);assert.equal(chart.yaxis.autorange,true);
 assert.equal(chart.showlegend,false);assert.equal(chart.legend.orientation,'h');
 assert.equal(cartesianFormat({...settings,legend_position:'left'}).legend.xanchor,'right');
});
