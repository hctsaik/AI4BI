import { useEffect, useRef, useState } from 'react';
import type { Dataset, ParameterRange, ReportExtensions } from '../types';
import type { CommandKind } from '../lib/api';

type ScenarioCommand = Extract<CommandKind,'save_scenario'|'update_scenario'|'rename_scenario'|'apply_scenario'|'delete_scenario'>;

function ParameterEditor({name,value,range,disabled,onValue,onRange,onDelete}:{
  name:string;value:number;range?:ParameterRange;disabled:boolean;
  onValue:(value:number)=>void;onRange:(range?:ParameterRange)=>void;onDelete:()=>void;
}) {
  const [draft,setDraft]=useState(String(value));
  const [minimum,setMinimum]=useState(String(range?.minimum??0));
  const [maximum,setMaximum]=useState(String(range?.maximum??1));
  const [step,setStep]=useState(String(range?.step??0.01));
  const [rangeError,setRangeError]=useState('');
  const dirty=useRef(false);
  useEffect(()=>{setDraft(String(value));dirty.current=false;},[value,disabled]);
  const reset=()=>{dirty.current=false;setDraft(String(value));};
  const commit=(next:number)=>{if(dirty.current){dirty.current=false;if(Number.isFinite(next)&&next!==value)onValue(next);}};
  return <div className="parameter-editor">
    <label>參數 {name}<input type="number" step="any" min={range?.minimum} max={range?.maximum}
      value={draft} onChange={e=>{dirty.current=true;setDraft(e.target.value);}}
      onKeyDown={e=>{if(e.key==='Escape')reset();}}
      onBlur={e=>{if(e.target.value.trim()&&e.target.validity.valid)commit(Number(e.target.value));else reset();}}/></label>
    {range&&<label>滑桿 {name}<input type="range" min={range.minimum} max={range.maximum} step={range.step} value={draft}
      onPointerDown={e=>e.currentTarget.setPointerCapture(e.pointerId)}
      onChange={e=>{dirty.current=true;setDraft(e.target.value);}}
      onPointerUp={e=>commit(Number(e.currentTarget.value))} onPointerCancel={reset}
      onKeyDown={e=>{if(e.key==='Escape'){e.preventDefault();reset();}}}
      onKeyUp={e=>{if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End','PageUp','PageDown'].includes(e.key))commit(Number(e.currentTarget.value));}}
      onBlur={e=>commit(Number(e.currentTarget.value))}/><output>{draft}</output></label>}
    <details><summary>範圍設定 {name}</summary><form onSubmit={e=>{e.preventDefault();
      const low=Number(minimum),high=Number(maximum),increment=Number(step),span=high-low;
      if(![low,high,increment,span,span/increment].every(Number.isFinite)||span<=0||increment<=0||increment>span||value<low||value>high){
        setRangeError('最小值須小於最大值，步長須大於零且不超過範圍，目前參數值也須在範圍內。');return;
      }
      setRangeError('');onRange({minimum:low,maximum:high,step:increment});}}>
      <label>最小值 {name}<input required type="number" step="any" value={minimum} onChange={e=>setMinimum(e.target.value)}/></label>
      <label>最大值 {name}<input required type="number" step="any" value={maximum} onChange={e=>setMaximum(e.target.value)}/></label>
      <label>步長 {name}<input required type="number" step="any" value={step} onChange={e=>setStep(e.target.value)}/></label>
      <button>套用範圍 {name}</button>
      {range&&<button type="button" onClick={()=>onRange()}>移除範圍 {name}</button>}
      {rangeError&&<p role="alert">{rangeError}</p>}
    </form></details>
    <button type="button" onClick={onDelete}>刪除參數 {name}</button>
  </div>;
}

export function ScenarioEditor({value, datasets, disabled, onChange, onScenario}: {
  value?:ReportExtensions; datasets:Dataset[]; disabled:boolean; onChange:(value:ReportExtensions)=>void;
  onScenario:(kind:ScenarioCommand,payload:Record<string,unknown>)=>void;
}) {
  const current=value??{version:1 as const,parameters:{},calculated_metrics:[]};
  const [name,setName]=useState('');
  const [amount,setAmount]=useState('0.1');
  const [block,setBlock]=useState(datasets[0]?.contract.block_id??'');
  const [metric,setMetric]=useState('');
  const [formula,setFormula]=useState('');
  const [scenarioName,setScenarioName]=useState('');
  return <details className="scenario-editor"><summary>參數與計算指標</summary>
    <p>參數以 @名稱 用於計算公式；調整後由分析引擎重新計算，並隨報表保存與復原。</p>
    <fieldset disabled={disabled}>
      {Object.entries(current.parameters).map(([key,number])=>{
        const range=Object.hasOwn(current.parameter_ranges??{},key)?current.parameter_ranges?.[key]:undefined;
        return <ParameterEditor key={key+JSON.stringify(range)}
        name={key} value={number} range={range} disabled={disabled}
        onValue={next=>onChange({...current,parameters:{...current.parameters,[key]:next}})}
        onRange={range=>{const ranges={...current.parameter_ranges};delete ranges[key];onChange({...current,parameter_ranges:range?{...ranges,[key]:range}:ranges});}}
        onDelete={()=>{const parameters={...current.parameters},ranges={...current.parameter_ranges};delete parameters[key];delete ranges[key];onChange({...current,parameters,parameter_ranges:ranges});}}/>;})}
      <form onSubmit={event=>{event.preventDefault();onChange({...current,parameters:{...current.parameters,[name]:Number(amount)}});}}>
        <label>參數名稱<input required pattern="[A-Za-z_][A-Za-z0-9_]*" value={name} onChange={e=>setName(e.target.value)} placeholder="discount"/></label>
        <label>初始值<input required type="number" step="any" value={amount} onChange={e=>setAmount(e.target.value)}/></label>
        <button disabled={!name||Object.hasOwn(current.parameters,name)}>新增參數</button>
      </form>
      <details className="saved-scenarios"><summary>已保存的參數情境（{current.scenarios?.length??0}）</summary>
        <p>保存目前整組參數；套用後以目前公式與資料重新計算。後來新增的參數保留目前值。</p>
        <form onSubmit={e=>{e.preventDefault();onScenario('save_scenario',{name:scenarioName});}}>
          <label>新情境名稱<input required maxLength={80} value={scenarioName} onChange={e=>setScenarioName(e.target.value)}/></label>
          <button disabled={!scenarioName.trim()||!Object.keys(current.parameters).length||(current.scenarios?.length??0)>=30}>保存目前參數為情境</button>
        </form>
        {(current.scenarios??[]).map(item=>{
          const incompatible=Object.entries(item.parameters).some(([key,value])=>{
            const range=Object.hasOwn(current.parameter_ranges??{},key)?current.parameter_ranges?.[key]:undefined;
            return !Object.hasOwn(current.parameters,key)||(range&&(value<range.minimum||value>range.maximum));
          });
          const matches=Object.entries(item.parameters).every(([key,value])=>current.parameters[key]===value);
          return <section key={item.scenario_id} aria-label={`參數情境 ${item.name}`}>
            <label>情境名稱 {item.name}<input key={item.name+String(disabled)} maxLength={80} defaultValue={item.name} onBlur={e=>{
              const name=e.target.value.trim();if(name&&name!==item.name)onScenario('rename_scenario',{scenario_id:item.scenario_id,name});else e.target.value=item.name;
            }}/></label>
            <p>{Object.entries(item.parameters).map(([key,value])=>`${key} = ${value}`).join('，')}</p>
            <p>{incompatible?'無法套用：參數已刪除或數值超出目前範圍，請以目前值更新。':matches?'目前參數符合此情境。':'可套用已保存數值。'}</p>
            <button type="button" disabled={incompatible} onClick={()=>onScenario('apply_scenario',{scenario_id:item.scenario_id})}>套用情境 {item.name}</button>
            <button type="button" disabled={!Object.keys(current.parameters).length} onClick={()=>onScenario('update_scenario',{scenario_id:item.scenario_id})}>以目前值更新 {item.name}</button>
            <button type="button" onClick={()=>onScenario('delete_scenario',{scenario_id:item.scenario_id})}>刪除情境 {item.name}</button>
          </section>;
        })}
      </details>
      <p>刪除前須先移除公式或圖表中的引用；未通過驗證時保留原報表。</p>
      <ul>{current.calculated_metrics.map(item=><li key={item.block_id+item.name}><b>{item.name}</b> = <code>{item.formula}</code>
        <button type="button" onClick={()=>onChange({...current,calculated_metrics:current.calculated_metrics.filter(other=>other!==item)})}>刪除指標 {item.name}</button></li>)}</ul>
      <form onSubmit={event=>{event.preventDefault();onChange({...current,calculated_metrics:[...current.calculated_metrics,{block_id:block,name:metric,formula}]});}}>
        <label>計算來源<select value={block} onChange={e=>setBlock(e.target.value)}>{datasets.map(ds=><option key={ds.dataset_id} value={ds.contract.block_id}>{ds.contract.description||ds.contract.block_id}</option>)}</select></label>
        <label>計算指標名稱<input required pattern="[A-Za-z_][A-Za-z0-9_]*" value={metric} onChange={e=>setMetric(e.target.value)}/></label>
        <label>計算公式<input required value={formula} onChange={e=>setFormula(e.target.value)} placeholder="SUM(move_count) * (1 - @discount)"/></label>
        <button disabled={!block||!metric||!formula}>新增計算指標</button>
      </form>
    </fieldset>
  </details>;
}
