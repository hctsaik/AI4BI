import test from 'node:test';
import assert from 'node:assert/strict';
import {scatterChart} from '../../apps/web/src/components/scatterChart.ts';
const visual={visualization:{extra:{},show_legend:true}};
const result=()=>({rows:[{},{},{}],scatter:{version:1,x_key:'amount',y_key:'rate',group_key:'group',size_key:'size',excluded_count:1,points:[
  {row_index:0,x:100,y:2,group:1,size:100},{row_index:1,x:50,y:-4,group:'1',size:25},{row_index:2,x:75,y:9,group:'<b>group</b>',size:null}]}});
test('scatter uses governed metric coordinates and distinct group identities',()=>{
  const input=result(),before=structuredClone(input),chart=scatterChart(visual,input);
  assert.deepEqual(chart.traces.map(t=>t.x),[[100],[50],[75]]);
  assert.deepEqual(chart.traces.map(t=>t.y),[[2],[-4],[9]]);
  assert.deepEqual(chart.traces.map(t=>t.customdata),[[1],['1'],['<b>group</b>']]);
  assert.deepEqual(chart.traces.map(t=>t.marker.size),[[40],[20],[7]]);
  assert.equal(new Set(chart.traces.map(t=>t.marker.symbol)).size,3);
  assert.equal(chart.traces[2].name,'&lt;b&gt;group&lt;/b&gt;');
  assert.equal(chart.layout.xaxis.title.text,'amount');assert.equal(chart.layout.yaxis.title.text,'rate');
  assert.equal(chart.excluded,1);assert.deepEqual(input,before);
});
test('scatter accepts empty coordinates and rejects invalid bindings',()=>{
  const empty=result();empty.scatter.points=[];assert.equal(scatterChart(visual,empty).count,0);
  for(const mutate of [r=>delete r.scatter,r=>r.scatter.points[0].x=Infinity,r=>r.scatter.points[0].row_index=9,
    r=>r.scatter.points.push(r.scatter.points[0]),r=>r.scatter.points[0].size=-1]){
    const input=result();mutate(input);assert.throws(()=>scatterChart(visual,input));
  }
});
test('server trendlines preserve fitted values and do not expose filter customdata',()=>{
  const input=result();input.scatter.trendline='ols';input.scatter.trendlines=[{group:1,method:'ols',status:'ready',x:[2,3],y:[5,7]}];
  const fit=scatterChart(visual,input).traces.at(-1);
  assert.equal(fit.mode,'lines');assert.deepEqual(fit.x,[2,3]);assert.deepEqual(fit.y,[5,7]);
  assert.equal(fit.customdata,undefined);assert.equal(fit.line.dash,'dash');
  assert.equal(fit.showlegend,false);assert.equal(fit.legendgroup,scatterChart(visual,input).traces[0].legendgroup);
  input.scatter.trendlines[0].y=[5,NaN];assert.throws(()=>scatterChart(visual,input));
});
