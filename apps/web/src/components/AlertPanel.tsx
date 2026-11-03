import { useEffect, useMemo, useState } from 'react';
import type { components } from '../generated/api';

export type AlertCandidate = {
  visual_id: string;
  block_id: string;
  metric_name: string;
  label: string;
  value: number;
  unit: string;
};

export type SummaryAlertRule = components['schemas']['SummaryAlertRule'];

type AlertRule = {
  rule_id: string;
  visual_id: string;
  block_id?: string;
  metric_name?: string;
  label: string;
  unit: string;
  operator: 'lt' | 'gt';
  threshold: number;
};

type Props = {
  storageKey: string;
  candidates: AlertCandidate[];
  querying: boolean;
};

function loadRules(storageKey: string): AlertRule[] {
  try {
    const value: unknown = JSON.parse(sessionStorage.getItem(storageKey) ?? '[]');
    if (!Array.isArray(value)) return [];
    return value.filter((rule): rule is AlertRule => Boolean(rule &&
      typeof rule.rule_id === 'string' && typeof rule.visual_id === 'string' &&
      typeof rule.label === 'string' && typeof rule.unit === 'string' &&
      (rule.operator === 'lt' || rule.operator === 'gt') &&
      typeof rule.threshold === 'number' && Number.isFinite(rule.threshold)));
  } catch {
    return [];
  }
}

export function readSummaryAlertRules(storageKey: string, candidates: AlertCandidate[]): SummaryAlertRule[] {
  const byVisual = new Map(candidates.map(candidate => [candidate.visual_id, candidate]));
  return loadRules(storageKey).flatMap(rule => {
    const candidate = byVisual.get(rule.visual_id);
    const blockId = rule.block_id || candidate?.block_id;
    const metricName = rule.metric_name || candidate?.metric_name;
    if (!blockId || !metricName || !Number.isFinite(rule.threshold)) return [];
    return [{ block_id: blockId, metric_name: metricName, operator: rule.operator, threshold: rule.threshold }];
  });
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value);
}

export function AlertPanel({ storageKey, candidates, querying }: Props) {
  const [rules, setRules] = useState<AlertRule[]>(() => loadRules(storageKey));
  const [visualId, setVisualId] = useState('');
  const [operator, setOperator] = useState<'lt' | 'gt'>('lt');
  const [threshold, setThreshold] = useState('');
  const byVisual = useMemo(() => new Map(candidates.map(candidate => [candidate.visual_id, candidate])), [candidates]);

  useEffect(() => {
    try {
      sessionStorage.setItem(storageKey, JSON.stringify(rules));
    } catch {
      // The rules remain available for this mounted report if browser storage is unavailable.
    }
  }, [rules, storageKey]);

  const fired = querying ? [] : rules.flatMap(rule => {
    const candidate = byVisual.get(rule.visual_id);
    if (!candidate) return [];
    const matches = rule.operator === 'lt' ? candidate.value < rule.threshold : candidate.value > rule.threshold;
    return matches ? [{ rule, candidate }] : [];
  });

  function addRule(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const candidate = byVisual.get(visualId);
    const limit = Number(threshold);
    if (!candidate || threshold.trim() === '' || !Number.isFinite(limit)) return;
    setRules(current => [...current, {
      rule_id: crypto.randomUUID(), visual_id: candidate.visual_id, label: candidate.label,
      block_id: candidate.block_id, metric_name: candidate.metric_name,
      unit: candidate.unit, operator, threshold: limit,
    }]);
    setThreshold('');
  }

  return <>
    {fired.map(({ rule, candidate }) => <div key={rule.rule_id} role="alert" className="alert-fired">
      🔔 {rule.label} 目前為 {formatNumber(candidate.value)}{rule.unit ? ` ${rule.unit}` : ''}，已
      {rule.operator === 'lt' ? '低於' : '高於'}你設定的 {formatNumber(rule.threshold)}{rule.unit ? ` ${rule.unit}` : ''}
    </div>)}
    <details className="alert-panel">
      <summary>🔔 提醒設定（{rules.length}）</summary>
      <p>依本頁 KPI 的目前查詢值與篩選條件檢查。提醒只在此瀏覽器工作階段顯示，不會背景寄送。</p>
      {candidates.length ? <form onSubmit={addRule}>
        <label>指標
          <select aria-label="提醒圖表" value={visualId} onChange={event => setVisualId(event.target.value)}>
            <option value="">選擇 KPI</option>
            {candidates.map(candidate => <option key={candidate.visual_id} value={candidate.visual_id}>
              {candidate.label}{candidate.unit ? ` (${candidate.unit})` : ''}
            </option>)}
          </select>
        </label>
        <label>條件
          <select aria-label="提醒條件" value={operator} onChange={event => setOperator(event.target.value as 'lt' | 'gt')}>
            <option value="lt">低於</option><option value="gt">高於</option>
          </select>
        </label>
        <label>門檻值
          <input aria-label="提醒門檻" type="number" step="any" value={threshold} onChange={event => setThreshold(event.target.value)}/>
        </label>
        <button className="primary" disabled={!visualId || threshold.trim() === '' || !Number.isFinite(Number(threshold))}>新增提醒</button>
      </form> : <p role="status">{querying ? 'KPI 載入後即可設定提醒。' : '本頁目前沒有可設定提醒的 KPI。'}</p>}
      {querying && rules.length > 0 && <p role="status">KPI 正在更新，提醒結果暫停檢查。</p>}
      {rules.length > 0 && <ul aria-label="目前的提醒">{rules.map(rule => {
        const candidate = byVisual.get(rule.visual_id);
        const state = querying ? '更新中' : candidate ? `目前 ${formatNumber(candidate.value)}${rule.unit ? ` ${rule.unit}` : ''}` : '等待本頁 KPI 結果';
        return <li key={rule.rule_id}>
          {rule.label} {rule.operator === 'lt' ? '低於' : '高於'} {formatNumber(rule.threshold)}{rule.unit ? ` ${rule.unit}` : ''} · {state}
          <button aria-label={`刪除提醒 ${rule.label}`} onClick={() => setRules(current => current.filter(item => item.rule_id !== rule.rule_id))}>刪除</button>
        </li>;
      })}</ul>}
    </details>
  </>;
}
