import { useEffect, useRef, useState } from 'react';
import { api, key, pollJob } from '../lib/api';
import type { components } from '../generated/api';
import type { AlertCandidate } from './AlertPanel';
import { readSummaryAlertRules } from './AlertPanel';

type SummaryPreferences = { enabled: boolean; frequency: 'daily' | 'weekly'; period: 'week' | 'month' };
type SummaryResult = {
  summary_contract: 'business-summary-v1'; title: string; generated_at: string; period: 'week' | 'month';
  markdown: string; sections: { heading: string; lines: string[] }[];
  snapshot_id: string; revision: number; page_id: string; data_versions: Record<string, string>;
};

const DEFAULT_PREFERENCES: SummaryPreferences = { enabled: false, frequency: 'daily', period: 'week' };

function loadPreferences(storageKey: string): SummaryPreferences {
  try {
    const value: unknown = JSON.parse(sessionStorage.getItem(storageKey) ?? 'null');
    if (!value || typeof value !== 'object') return DEFAULT_PREFERENCES;
    const candidate = value as Partial<SummaryPreferences>;
    return {
      enabled: candidate.enabled === true,
      frequency: candidate.frequency === 'weekly' ? 'weekly' : 'daily',
      period: candidate.period === 'month' ? 'month' : 'week',
    };
  } catch {
    return DEFAULT_PREFERENCES;
  }
}

export function SummaryPanel({ base, revision, pageId, storageKey, alertStorageKey, alertCandidates, disabled }:
  { base: string; revision: number; pageId: string; storageKey: string; alertStorageKey: string;
    alertCandidates: AlertCandidate[]; disabled: boolean }) {
  const [preferences, setPreferences] = useState(() => loadPreferences(storageKey));
  const [result, setResult] = useState<SummaryResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const active = useRef<{ controller: AbortController; jobId: string } | null>(null);

  useEffect(() => {
    try { sessionStorage.setItem(storageKey, JSON.stringify(preferences)); }
    catch { /* Keep the preference for this mounted report when storage is unavailable. */ }
  }, [preferences, storageKey]);

  useEffect(() => () => {
    const task = active.current;
    if (!task) return;
    task.controller.abort();
    if (task.jobId) void api(`/jobs/${task.jobId}/cancel`, {}).catch(() => {});
  }, []);

  async function generate() {
    if (active.current || busy || disabled) return;
    setBusy(true); setError('');
    const task = { controller: new AbortController(), jobId: '' };
    active.current = task;
    try {
      const request: components['schemas']['SummaryRequest'] = {
        idempotency_key: key(), base_revision: revision, period: preferences.period,
        page_id: pageId, alert_rules: readSummaryAlertRules(alertStorageKey, alertCandidates),
      };
      const job = await api<{ job_id: string }>(base + '/summaries', request, undefined, task.controller.signal);
      task.jobId = job.job_id;
      if (task.controller.signal.aborted) {
        void api(`/jobs/${task.jobId}/cancel`, {}).catch(() => {});
        return;
      }
      setResult(await pollJob<SummaryResult>(job.job_id, task.controller.signal));
    } catch (cause) {
      if (!task.controller.signal.aborted) setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      if (active.current === task) active.current = null;
      if (!task.controller.signal.aborted) setBusy(false);
    }
  }

  function download() {
    if (!result) return;
    const blob = new Blob([result.markdown], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url; link.download = `business-summary-${result.period}.md`;
    document.body.appendChild(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  }

  return <details className="summary-panel">
    <summary>📋 業務摘要</summary>
    <p>依目前報表頁面使用的資料來源，產生期間重點、前三名與已觸發的提醒。</p>
    <div className="summary-controls">
      <label>摘要週期
        <select aria-label="摘要週期" value={preferences.period}
          onChange={event => setPreferences(current => ({ ...current, period: event.target.value as SummaryPreferences['period'] }))}>
          <option value="week">週報（對比上週）</option><option value="month">月報（對比上月）</option>
        </select>
      </label>
      <button className="primary" disabled={disabled || busy} onClick={() => void generate()}>
        {busy ? '正在產生摘要…' : '✨ 產生摘要'}
      </button>
    </div>
    {error && <p role="alert">{error}</p>}
    {result && <section className="summary-result" aria-label="業務摘要結果">
      <h3>{result.title}</h3><p>產生時間：{new Date(result.generated_at).toLocaleString()}</p>
      {result.sections.map((section, index) => <section key={`${section.heading}-${index}`}>
        <h4>{section.heading}</h4>
        {section.lines.length ? <ul>{section.lines.map((line, lineIndex) => <li key={lineIndex}>{line}</li>)}</ul> : <p>（無）</p>}
      </section>)}
      <button onClick={download}>⬇️ 下載摘要 (.md)</button>
    </section>}
    <hr />
    <label className="summary-schedule-toggle"><input type="checkbox" aria-label="排程定期摘要"
      checked={preferences.enabled} onChange={event => setPreferences(current => ({ ...current, enabled: event.target.checked }))}/>
      排程定期摘要</label>
    <label>頻率
      <select aria-label="摘要排程頻率" value={preferences.frequency} disabled={!preferences.enabled}
        onChange={event => setPreferences(current => ({ ...current, frequency: event.target.value as SummaryPreferences['frequency'] }))}>
        <option value="daily">每天</option><option value="weekly">每週</option>
      </select>
    </label>
    {preferences.enabled && <p role="status">已記錄排程偏好。目前請手動產生並下載；自動執行與寄送尚未啟用。</p>}
  </details>;
}
