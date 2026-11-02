import {useState} from 'react';
import type {Dataset,Visual} from '../types';

/** One atomic report edit keeps the target and warning thresholds consistent. */
export function KpiSettings({visual,datasets,onSave}:{visual:Visual;datasets:Dataset[];onSave:(extra:Record<string,unknown>,sparkline:boolean)=>void}) {
  const extra=visual.visualization.extra,rag=extra.rag as {target?:number;warn?:number;good_if?:string}|undefined;
  const [unit,setUnit]=useState(String(extra.unit??'')),[decimals,setDecimals]=useState(String(extra.decimals??''));
  const [compact,setCompact]=useState(extra.compact===true),[target,setTarget]=useState(String(extra.target??''));
  const [direction,setDirection]=useState(String(extra.target_good_if??'gte'));
  const [ragEnabled,setRagEnabled]=useState(!!rag),[ragTarget,setRagTarget]=useState(String(rag?.target??''));
  const [warn,setWarn]=useState(String(rag?.warn??'')),[ragDirection,setRagDirection]=useState(rag?.good_if??'gte');
  const [error,setError]=useState('');
  const [sparkline,setSparkline]=useState(visual.visualization.show_sparkline===true);
  const [sparkDate,setSparkDate]=useState(extra.sparkline_date_column?JSON.stringify([extra.sparkline_date_block??visual.query.block_refs[0].block_id,extra.sparkline_date_column]):'');
  const [period,setPeriod]=useState(String(extra.compare_period??'')),[mode,setMode]=useState(String(extra.compare_mode??'trailing'));
  const [policy,setPolicy]=useState(String(extra.compare_filter_policy??'replace'));
  const [dateField,setDateField]=useState(extra.compare_date_column?JSON.stringify([extra.compare_date_block??visual.query.block_refs[0].block_id,extra.compare_date_column]):'');
  const dateFields=datasets.filter(d=>visual.query.block_refs.some(b=>b.block_id===d.contract.block_id)).flatMap(d=>d.contract.columns.filter(c=>['date','timestamp','datetime'].includes(c.data_type.toLowerCase())).map(c=>({value:JSON.stringify([d.contract.block_id,c.name]),label:`${d.contract.block_id} · ${c.name}`})));
  function save(){
    if(sparkline&&(visual.query.dimensions.length||visual.query.metrics.length!==1||(!period&&!dateFields.some(f=>f.value===sparkDate)))){setError('趨勢小圖需要日期欄位及單一未分組指標。');return;}
    if(period&&(!dateFields.some(f=>f.value===dateField)||visual.query.dimensions.length||visual.query.metrics.length!==1)){setError('期間比較需要日期欄位及單一未分組指標。');return;}
    const numeric=[target,...(ragEnabled?[ragTarget,warn]:[])].filter(v=>v!=='');
    if(numeric.some(v=>!Number.isFinite(Number(v)))||(ragEnabled&&ragTarget==='')){setError('請填入有限數字，狀態目標不可空白。');return;}
    if(decimals!==''&&(!Number.isInteger(Number(decimals))||Number(decimals)<0||Number(decimals)>6)){setError('小數位須為 0 到 6 的整數。');return;}
    if(ragEnabled&&warn!==''&&(ragDirection==='gte'?Number(warn)>Number(ragTarget):Number(warn)<Number(ragTarget))){setError('注意門檻須位於未達標側。');return;}
    const next:Record<string,unknown>={...extra,unit,compact,target_good_if:direction};
    if(decimals==='')delete next.decimals;else next.decimals=Number(decimals);
    if(target==='')delete next.target;else next.target=Number(target);
    if(ragEnabled)next.rag={target:Number(ragTarget),good_if:ragDirection,...(warn===''?{}:{warn:Number(warn)})};else delete next.rag;
    if(period){const [block,column]=JSON.parse(dateField) as string[];Object.assign(next,{compare_period:period,compare_mode:mode,compare_filter_policy:policy,compare_date_block:block,compare_date_column:column});}
    else{for(const field of ['compare_period','compare_mode','compare_filter_policy','compare_date_block','compare_date_column'])delete next[field];}
    if(sparkline&&!period){const [block,column]=JSON.parse(sparkDate) as string[];Object.assign(next,{sparkline_date_block:block,sparkline_date_column:column});}
    setError('');onSave(next,sparkline);
  }
  const directions=<><option value="gte">越高越好（≥）</option><option value="lte">越低越好（≤）</option></>;
  return <fieldset className="kpi-settings"><legend>指標格式與目標</legend>
    <label>KPI 單位<input maxLength={64} value={unit} onChange={e=>setUnit(e.target.value)}/></label>
    <label><input type="checkbox" checked={sparkline} onChange={e=>setSparkline(e.target.checked)}/>顯示逐日趨勢小圖</label>
    {sparkline&&!period&&<label>趨勢日期欄位<select aria-label="趨勢日期欄位" value={sparkDate} onChange={e=>setSparkDate(e.target.value)}><option value="">選取日期欄位</option>{dateFields.map(f=><option key={f.value} value={f.value}>{f.label}</option>)}</select></label>}
    {sparkline&&<p>逐日趨勢保留原篩選；期間比較啟用時使用相同比較日期與本期範圍。最多最近 365 個有結果日期，缺日不補零。</p>}
    <label>KPI 小數位<input type="number" min={0} max={6} step={1} placeholder="自動（最多兩位）" value={decimals} onChange={e=>setDecimals(e.target.value)}/></label>
    <label>期間比較<select aria-label="期間比較" value={period} onChange={e=>setPeriod(e.target.value)}><option value="">不比較</option>{mode==='trailing'&&<option value="week">最近 7 天與前 7 天</option>}<option value="month">{mode==='trailing'?'最近 30 天與前 30 天':'本月至今與去年同月同期'}</option><option value="quarter">{mode==='trailing'?'最近 90 天與前 90 天':'本季至今與去年同季同期'}</option><option value="year">{mode==='trailing'?'最近 365 天與前 365 天':'今年至今與去年同期'}</option></select></label>
    <label>比較模式<select aria-label="比較模式" value={mode} onChange={e=>{setMode(e.target.value);if(e.target.value==='calendar'&&period==='week')setPeriod('month');}}><option value="trailing">固定天數視窗</option><option value="calendar">日曆期間對去年</option></select></label>
    {period&&<><label>比較日期欄位<select aria-label="比較日期欄位" value={dateField} onChange={e=>setDateField(e.target.value)}><option value="">選取日期欄位</option>{dateFields.map(f=><option key={f.value} value={f.value}>{f.label}</option>)}</select></label>
      <label>比較日期篩選<select aria-label="比較日期篩選" value={policy} onChange={e=>setPolicy(e.target.value)}><option value="replace">以比較視窗取代日期條件</option><option value="keep">保留全部篩選</option></select></label>
      <p className="muted">錨定篩選內最新日期，以 UTC 日界比較。取代日期條件時仍保留其他篩選與權限；混合其他欄位的 OR 日期群組須先調整。期間與差異會列在卡片及匯出中。</p></>}
    <label><input type="checkbox" checked={compact} onChange={e=>setCompact(e.target.checked)}/>縮寫大數字（K／M／B）</label>
    <label>進度目標<input type="number" step="any" placeholder="不設定" value={target} onChange={e=>setTarget(e.target.value)}/></label>
    <label>進度方向<select aria-label="進度方向" value={direction} onChange={e=>setDirection(e.target.value)}>{directions}</select></label>
    <label><input type="checkbox" checked={ragEnabled} onChange={e=>setRagEnabled(e.target.checked)}/>顯示達標／注意狀態</label>
    {ragEnabled&&<><label>狀態目標<input type="number" step="any" value={ragTarget} onChange={e=>setRagTarget(e.target.value)}/></label>
      <label>注意門檻<input type="number" step="any" placeholder="不設定" value={warn} onChange={e=>setWarn(e.target.value)}/></label>
      <label>狀態方向<select aria-label="狀態方向" value={ragDirection} onChange={e=>setRagDirection(e.target.value)}>{directions}</select></label></>}
    <p className="muted">目標以指標原始單位輸入。進度比較目前數值與固定目標，沒有依日期預估。分組與多指標保留資料表。</p>
    {error&&<p role="alert">{error}</p>}
    <button type="button" onClick={save}>套用指標設定</button>
  </fieldset>;
}
