import type {Layout} from 'plotly.js';
import type {Result} from '../types';

export function cartesianFormat(data:NonNullable<Result['chart_format']>,horizontal=false):Partial<Layout>{
  const log=data.y_scale==='log',lower=data.y_min,upper=data.y_max;
  const axis:Partial<Layout['yaxis']>={type:data.y_scale,title:{text:data.y_title}};
  if(lower!==null&&upper!==null){axis.range=log?[Math.log10(lower),Math.log10(upper)]:[lower,upper];axis.autorange=false;}
  else if(lower!==null||upper!==null){
    axis.autorange=true;
    axis.autorangeoptions={...(lower!==null?{minallowed:log?Math.log10(lower):lower}:{}),...(upper!==null?{maxallowed:log?Math.log10(upper):upper}:{})};
  }else axis.autorange=true;
  const anchors:Record<string,Partial<Layout['legend']>>={top:{orientation:'h',x:1,xanchor:'right',y:1.02,yanchor:'bottom'},
    bottom:{orientation:'h',x:.5,xanchor:'center',yref:'container',y:0,yanchor:'bottom'},
    left:{orientation:'v',x:-.1,xanchor:'right',y:1},right:{orientation:'v',x:1.02,y:1}};
  return {xaxis:{title:{text:data.x_title},automargin:true},yaxis:{...axis,automargin:true},showlegend:data.show_legend,legend:anchors[data.legend_position],
    ...(data.baseline?.status==='ready'?{shapes:[{type:'line',
      ...(horizontal?{xref:'x',yref:'paper',x0:data.baseline.value!,x1:data.baseline.value!,y0:0,y1:1}:{xref:'paper',yref:'y',x0:0,x1:1,y0:data.baseline.value!,y1:data.baseline.value!}),
      line:{color:'#e45756',width:2,dash:'dot'}}]}:{}),
    ...(data.show_legend&&data.legend_position==='bottom'?{margin:{l:65,r:25,t:15,b:110}}:{})};
}
