import type {Result, Row} from '../types';

export const pivotKey = (value:Row[string]) => JSON.stringify([typeof value,value]);
export const pivotLabel = (value:Row[string]) => value===null?'（空值）':String(value);

/** Index only supplied core values. Neither missing cells nor totals are calculated here. */
export function pivotMatrix(result:Result) {
  const spec=result.pivot;
  if(!spec||spec.version!==1||spec.totals_scope!=='filtered_population')throw new Error('缺少相容的樞紐總計，請重新查詢。');
  const rowField=spec.row_field.key,columnField=spec.column_field?.key;
  const fields=[rowField,...(columnField?[columnField]:[]),...spec.metrics.map(m=>m.key)];
  if(!spec.metrics.length||new Set(fields).size!==fields.length)throw new Error('樞紐欄位名稱缺失或重複。');
  const rows=new Map<string,Row[string]>(),columns=new Map<string,Row[string]>();
  const cells=new Map<string,Map<string,Row>>();
  function value(row:Row,key:string) {
    if(!Object.hasOwn(row,key))throw new Error('樞紐資料缺少必要欄位。');
    const v=row[key];
    if(v!==null&&!['string','number','boolean'].includes(typeof v)||typeof v==='number'&&!Number.isFinite(v))throw new Error('樞紐資料型別不相容。');
    return v;
  }
  function measures(row:Row) {for(const metric of spec!.metrics)value(row,metric.key);}
  function axis(map:Map<string,Row[string]>,v:Row[string]){const key=pivotKey(v);map.set(key,v);return key;}
  for(const row of result.rows??[]) {
    measures(row);
    const r=axis(rows,value(row,rowField)),c=axis(columns,columnField?value(row,columnField):null);
    const values=cells.get(r)??new Map<string,Row>();
    if(values.has(c))throw new Error('樞紐儲存格重複，無法自行合併。');
    values.set(c,row);cells.set(r,values);
  }
  function totals(source:Result|null,key:string|undefined,axes:Map<string,Row[string]>) {
    const indexed=new Map<string,Row>();
    for(const row of source?.rows??[]) {
      measures(row);const id=axis(axes,key?value(row,key):null);
      if(indexed.has(id))throw new Error('樞紐總計重複，無法自行合併。');
      indexed.set(id,row);
    }
    return indexed;
  }
  const rowTotals=totals(spec.row_totals,rowField,rows);
  const columnTotals=totals(spec.column_totals,columnField,columns);
  if(!columnField&&!columns.size)columns.set(pivotKey(null),null);
  const grand=spec.grand_total.rows??[];
  if(grand.length>1)throw new Error('樞紐總計不唯一。');
  if(grand[0])measures(grand[0]);
  function labels(axes:Map<string,Row[string]>) {
    const counts=new Map<string,number>();
    for(const v of axes.values())counts.set(pivotLabel(v),(counts.get(pivotLabel(v))??0)+1);
    return [...axes].map(([key,v])=>({key,value:v,label:pivotLabel(v)+(counts.get(pivotLabel(v))!>1?` [${v===null?'null':typeof v}]`:'')}));
  }
  return {spec,rows:labels(rows),columns:labels(columns),cells,rowTotals,columnTotals,grand:grand[0]};
}
