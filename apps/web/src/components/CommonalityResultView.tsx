import type {CommonalityResult} from '../types';

export function CommonalityResultView({result,title}:{result:CommonalityResult;title?:string}){
  const label=title?`共同性分析結果：${title}`:'共同性分析結果';
    return <section role="region" aria-label={label}>
      {title&&<h3>{title}</h3>}
      <p role="status">{{ready:'共同性分析完成',empty:'沒有可對齊的群體',no_qualifying_groups:'沒有符合門檻的群體',no_comparison_groups:'全部群體符合門檻，沒有對照群體'}[result.status]}</p>
      <p>母體 {result.population_count}；符合門檻 {result.qualifying_count}；對照 {result.comparison_count}</p>
      <p>缺少量測 {result.unmeasured_group_count} 群；缺少曝光 {result.unexposed_group_count} 群；排除缺值曝光 {result.excluded_detail_rows} 列、結果 {result.excluded_outcome_rows} 列。</p>
      <p>{result.notice} p 值顯示至小數四位；0.0000 是捨入結果。</p>
      <table><thead><tr><th>實體</th><th>符合門檻群數</th><th>涵蓋率 %</th><th>Lift</th><th>p 值</th></tr></thead>
        <tbody>{result.rows.map((row,i)=><tr key={i}><td>{String(row.entity)}</td><td>{row.qualifying_count}</td><td>{row.coverage_percent}</td><td>{row.lift}</td><td>{row.p_value===null?'無法檢定':row.p_value.toFixed(4)}</td></tr>)}</tbody></table>
    </section>;
}
