import { useEffect, useMemo, useRef, useState } from 'react';
import { api, key, pollJob } from '../lib/api';
import type { components } from '../generated/api';

export type AlertCandidate = {
  block_id: string;
  metric_name: string;
  label: string;
  unit: string;
  columns: string[];
};

export type SummaryAlertRule = components['schemas']['SummaryAlertRule'];

type AlertRule = {
  rule_id: string;
  block_id: string;
  metric_name: string;
  label: string;
  unit: string;
  operator: 'lt' | 'gt';
  threshold: number;
  filter_column?: string;
  filter_value?: string;
};

type AlertEvaluation = {
  alerts: { rule_id: string; value: number | null; fired: boolean; message: string }[];
};

type Props = {
  base: string;
  revision: number;
  storageKey: string;
  candidates: AlertCandidate[];
  querying: boolean;
};

function loadRules(storageKey: string): AlertRule[] {
  try {
    const value: unknown = JSON.parse(sessionStorage.getItem(storageKey) ?? '[]');
    if (!Array.isArray(value)) return [];
    return value.flatMap((entry): AlertRule[] => {
      if (!entry || typeof entry !== 'object') return [];
      const rule = entry as Partial<AlertRule>;
      // Existing rules stored the metric reference beside a visual_id. Keep them
      // valid across the move from KPI-only choices to the complete metric list.
      if (typeof rule.rule_id !== 'string' || typeof rule.block_id !== 'string' ||
          typeof rule.metric_name !== 'string' || typeof rule.label !== 'string' ||
          typeof rule.unit !== 'string' || (rule.operator !== 'lt' && rule.operator !== 'gt') ||
          typeof rule.threshold !== 'number' || !Number.isFinite(rule.threshold) ||
          (rule.filter_column !== undefined && typeof rule.filter_column !== 'string') ||
          (rule.filter_value !== undefined && typeof rule.filter_value !== 'string')) return [];
      if ((rule.filter_column === undefined) !== (rule.filter_value === undefined)) return [];
      return [{
        rule_id: rule.rule_id, block_id: rule.block_id, metric_name: rule.metric_name,
        label: rule.label, unit: rule.unit, operator: rule.operator, threshold: rule.threshold,
        ...(rule.filter_column !== undefined ? { filter_column: rule.filter_column, filter_value: rule.filter_value } : {}),
      }];
    });
  } catch {
    return [];
  }
}

function candidateKey(candidate: Pick<AlertCandidate, 'block_id' | 'metric_name'>): string {
  return `${candidate.block_id}\u0000${candidate.metric_name}`;
}

export function readSummaryAlertRules(storageKey: string, candidates: AlertCandidate[]): SummaryAlertRule[] {
  const available = new Set(candidates.map(candidateKey));
  return loadRules(storageKey).flatMap(rule => {
    if (!available.has(candidateKey(rule))) return [];
    return [{
      block_id: rule.block_id, metric_name: rule.metric_name,
      operator: rule.operator, threshold: rule.threshold,
      ...(rule.filter_column !== undefined ? { filter_column: rule.filter_column, filter_value: rule.filter_value } : {}),
    }];
  });
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value);
}

export function AlertPanel({ base, revision, storageKey, candidates, querying }: Props) {
  const [rules, setRules] = useState<AlertRule[]>(() => loadRules(storageKey));
  const [metricKey, setMetricKey] = useState('');
  const [operator, setOperator] = useState<'lt' | 'gt'>('lt');
  const [threshold, setThreshold] = useState('');
  const [scopeColumn, setScopeColumn] = useState('');
  const [scopeValue, setScopeValue] = useState('');
  const [evaluation, setEvaluation] = useState<AlertEvaluation | null>(null);
  const [evaluating, setEvaluating] = useState(false);
  const [evaluationError, setEvaluationError] = useState('');
  const active = useRef<{ controller: AbortController; jobId: string } | null>(null);
  const byMetric = useMemo(() => new Map(candidates.map(candidate => [candidateKey(candidate), candidate])), [candidates]);
  const activeRules = useMemo(() => rules.filter(rule => byMetric.has(candidateKey(rule))), [rules, byMetric]);
  const results = useMemo(() => new Map((evaluation?.alerts ?? []).map(result => [result.rule_id, result])), [evaluation]);

  useEffect(() => {
    try {
      sessionStorage.setItem(storageKey, JSON.stringify(rules));
    } catch {
      // Keep the rules available for this mounted report if browser storage is unavailable.
    }
  }, [rules, storageKey]);

  useEffect(() => {
    if (querying || activeRules.length === 0) {
      setEvaluation(null);
      setEvaluationError('');
      setEvaluating(false);
      return;
    }
    const task = { controller: new AbortController(), jobId: '' };
    active.current = task;
    setEvaluation(null);
    setEvaluationError('');
    setEvaluating(true);
    const request = {
      idempotency_key: key(), base_revision: revision,
      alert_rules: activeRules.map(rule => ({
        rule_id: rule.rule_id, block_id: rule.block_id, metric_name: rule.metric_name,
        operator: rule.operator, threshold: rule.threshold,
        ...(rule.filter_column !== undefined ? { filter_column: rule.filter_column, filter_value: rule.filter_value } : {}),
      })),
    };
    void api<{ job_id: string }>(base + '/alerts', request, undefined, task.controller.signal)
      .then(job => {
        task.jobId = job.job_id;
        if (task.controller.signal.aborted) {
          void api(`/jobs/${task.jobId}/cancel`, {}).catch(() => {});
          return Promise.reject(new DOMException('Aborted', 'AbortError'));
        }
        return pollJob<AlertEvaluation>(job.job_id, task.controller.signal);
      })
      .then(result => { if (active.current === task) setEvaluation(result); })
      .catch(cause => {
        if (!task.controller.signal.aborted && active.current === task)
          setEvaluationError(cause instanceof Error ? cause.message : String(cause));
      })
      .finally(() => {
        if (active.current === task) {
          active.current = null;
          setEvaluating(false);
        }
      });
    return () => {
      task.controller.abort();
      if (task.jobId) void api(`/jobs/${task.jobId}/cancel`, {}).catch(() => {});
    };
  }, [activeRules, base, querying, revision]);

  function addRule(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const candidate = byMetric.get(metricKey);
    const limit = Number(threshold);
    if (!candidate || threshold.trim() === '' || !Number.isFinite(limit) ||
        (scopeColumn !== '' && scopeValue.trim() === '')) return;
    setRules(current => [...current, {
      rule_id: crypto.randomUUID(), block_id: candidate.block_id, metric_name: candidate.metric_name,
      label: candidate.label, unit: candidate.unit, operator, threshold: limit,
      ...(scopeColumn ? { filter_column: scopeColumn, filter_value: scopeValue.trim() } : {}),
    }]);
    setThreshold('');
    setScopeValue('');
  }

  const fired = activeRules.flatMap(rule => {
    const result = results.get(rule.rule_id);
    return result?.fired && result.message ? [{ rule, message: result.message }] : [];
  });

  return <>
    {fired.map(({ rule, message }) => <div key={rule.rule_id} role="alert" className="alert-fired">{message}</div>)}
    <details className="alert-panel">
      <summary>🔔 提醒設定（{rules.length}）</summary>
      <p>可選擇任一事實指標及欄位範圍；資料或提醒規則變更時會用本機查詢引擎重新評估。此功能不會背景執行或寄送通知。</p>
      {candidates.length ? <form onSubmit={addRule}>
        <label>指標
          <select aria-label="提醒指標" value={metricKey} onChange={event => { setMetricKey(event.target.value); setScopeColumn(''); setScopeValue(''); }}>
            <option value="">選擇指標</option>
            {candidates.map(candidate => <option key={candidateKey(candidate)} value={candidateKey(candidate)}>
              {candidate.label} · {candidate.block_id}{candidate.unit ? ` (${candidate.unit})` : ''}
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
        <label>範圍欄位
          <select aria-label="提醒範圍欄位" value={scopeColumn} disabled={!metricKey}
            onChange={event => { setScopeColumn(event.target.value); setScopeValue(''); }}>
            <option value="">全部資料</option>
            {(byMetric.get(metricKey)?.columns ?? []).map(column => <option key={column} value={column}>{column}</option>)}
          </select>
        </label>
        <label>範圍值
          <input aria-label="提醒範圍值" value={scopeValue} disabled={!scopeColumn}
            onChange={event => setScopeValue(event.target.value)} placeholder="例如 Etch"/>
        </label>
        <button className="primary" disabled={!metricKey || threshold.trim() === '' || !Number.isFinite(Number(threshold)) ||
          (scopeColumn !== '' && scopeValue.trim() === '')}>新增提醒</button>
      </form> : <p role="status">目前沒有可設定提醒的事實指標。</p>}
      {querying && rules.length > 0 && <p role="status">資料正在更新，提醒結果暫停檢查。</p>}
      {evaluating && <p role="status">正在用本機資料重新評估提醒…</p>}
      {evaluationError && <p role="alert">提醒評估失敗：{evaluationError}</p>}
      {rules.length > 0 && <ul aria-label="目前的提醒">{rules.map(rule => {
        const candidate = byMetric.get(candidateKey(rule));
        const result = results.get(rule.rule_id);
        const state = !candidate ? '來源或指標已不可用' : querying || evaluating ? '評估中' : result?.value === null ? '無法計算' :
          result ? `${result.fired ? '已觸發' : '未觸發'} · 目前 ${formatNumber(result.value)}` : '等待評估';
        return <li key={rule.rule_id}>
          {rule.label}{rule.filter_column ? `（${rule.filter_column}：${rule.filter_value}）` : ''} {rule.operator === 'lt' ? '低於' : '高於'} {formatNumber(rule.threshold)}{rule.unit ? ` ${rule.unit}` : ''} · {state}
          <button aria-label={`刪除提醒 ${rule.label}`} onClick={() => setRules(current => current.filter(item => item.rule_id !== rule.rule_id))}>刪除</button>
        </li>;
      })}</ul>}
    </details>
  </>;
}
