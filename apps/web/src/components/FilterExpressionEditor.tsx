import type { Dataset, FilterExpression, FilterPredicate } from '../types';

export const filterOperators={eq:'等於',neq:'不等於',gt:'大於',gte:'大於或等於',lt:'小於',lte:'小於或等於',in:'符合其中一值',not_in:'不符合任一值',between:'介於（含端點）',like:'文字樣式（% 為任意文字）',is_null:'為空值',is_not_null:'不是空值'};
type LeafDraft={column:string;operator:keyof typeof filterOperators;value:string};
export type GroupDraft={operator:'and'|'or';children:(LeafDraft|GroupDraft)[]};
const leaf=():LeafDraft=>({column:'',operator:'eq',value:''});
export const emptyGroup=():GroupDraft=>({operator:'or',children:[leaf(),leaf()]});

export function parseFilterValue(raw:string,dtype:string,operator:string):unknown {
  if(['is_null','is_not_null'].includes(operator))return null;
  function scalar(value:string){
    if(['integer','int','int64','int32','number','float','numeric','double','decimal'].includes(dtype.toLowerCase())){
      const n=Number(value);if(!value.trim()||!Number.isFinite(n))throw new Error('請輸入有效數字。');return n;
    }
    if(['boolean','bool'].includes(dtype.toLowerCase())){if(value==='true')return true;if(value==='false')return false;throw new Error('布林值請輸入 true 或 false。');}
    return value;
  }
  const result=['in','not_in','between'].includes(operator)?raw.split(/\r?\n/).map(scalar):scalar(raw);
  if(operator==='between'&&(!Array.isArray(result)||result.length!==2))throw new Error('區間需兩個值，每行一個。');
  return result;
}

export function groupFromSaved(expression:FilterExpression):GroupDraft {
  return {operator:expression.operator,children:expression.children.map(child=>'children' in child?groupFromSaved(child):{
    column:child.column_name,operator:child.operator as LeafDraft['operator'],
    value:Array.isArray(child.value)?child.value.map(String).join('\n'):child.value==null?'':String(child.value),
  })};
}

export function serializeGroup(draft:GroupDraft,contract:Dataset['contract']):unknown {
  return {operator:draft.operator,children:draft.children.map(child=>{
    if('children' in child)return serializeGroup(child,contract);
    const column=contract.columns.find(c=>c.name===child.column);
    if(!column)throw new Error('請選擇每個群組條件的欄位。');
    return {block_id:contract.block_id,column_name:child.column,operator:child.operator,value:parseFilterValue(child.value,column.data_type,child.operator)};
  })};
}

export function expressionLabel(expression:FilterExpression|FilterPredicate):string {
  return 'children' in expression?'（'+expression.children.map(expressionLabel).join(expression.operator==='and'?' 且 ':' 或 ')+'）':
    `${expression.column_name} ${filterOperators[expression.operator as LeafDraft['operator']]} ${Array.isArray(expression.value)?expression.value.join('、'):expression.value==null?'':String(expression.value)}`;
}

export function FilterExpressionEditor({value,columns,onChange,path='1',depth=1}:{value:GroupDraft;columns:Dataset['contract']['columns'];onChange:(value:GroupDraft)=>void;path?:string;depth?:number}){
  function replace(index:number,child:LeafDraft|GroupDraft){onChange({...value,children:value.children.map((old,i)=>i===index?child:old)});}
  return <fieldset className="filter-expression" aria-label={`條件群組 ${path}`}>
    <legend>群組 {path}</legend>
    <label>群組關係<select aria-label={`群組 ${path} 關係`} value={value.operator} onChange={e=>onChange({...value,operator:e.target.value as GroupDraft['operator']})}>
      <option value="and">全部符合（AND）</option><option value="or">任一符合（OR）</option>
    </select></label>
    {value.children.map((child,index)=>{const id=`${path}.${index+1}`;return <div className="filter-expression-child" key={index}>
      {'children' in child?<FilterExpressionEditor value={child} columns={columns} path={id} depth={depth+1} onChange={next=>replace(index,next)}/>:<>
        <label>條件 {id} 欄位<select aria-label={`條件 ${id} 欄位`} required value={child.column} onChange={e=>replace(index,{...child,column:e.target.value,value:''})}>
          <option value="">選擇欄位</option>{columns.map(c=><option key={c.name} value={c.name}>{c.name}（{c.data_type}）</option>)}
        </select></label>
        <label>條件 {id} 運算子<select aria-label={`條件 ${id} 運算子`} value={child.operator} onChange={e=>replace(index,{...child,operator:e.target.value as LeafDraft['operator']})}>
          {Object.entries(filterOperators).map(([key,label])=><option key={key} value={key}>{label}</option>)}
        </select></label>
        {!['is_null','is_not_null'].includes(child.operator)&&<label>條件 {id} 值<textarea aria-label={`條件 ${id} 值`} value={child.value} onChange={e=>replace(index,{...child,value:e.target.value})} placeholder="多值或區間每行一值；布林值 true／false"/></label>}
      </>}
      <button type="button" disabled={value.children.length<=2} onClick={()=>onChange({...value,children:value.children.filter((_,i)=>i!==index)})}>移除條件 {id}</button>
    </div>;})}
    <button type="button" disabled={value.children.length>=100} onClick={()=>onChange({...value,children:[...value.children,leaf()]})}>加入條件至群組 {path}</button>
    <button type="button" disabled={depth>=4||value.children.length>=100} onClick={()=>onChange({...value,children:[...value.children,emptyGroup()]})}>加入子群組至 {path}</button>
  </fieldset>;
}
