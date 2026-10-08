import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../ui/Card';
import { api } from '../../services/api';
import { settingsService } from '../../services/settings';
import { getErrorMessage } from '../../lib/utils';
import type { UserSettings } from '../../types/settings';

interface Dashboard {
  days: number;
  runs_per_day: { date: string; completed: number; failed: number; other: number }[];
  total_runs: number;
  failed_runs: number;
  failure_rate: number;
  top_failing: { workflow_id: number; name: string; failures: number }[];
  slowest_steps: { workflow_id: number; workflow: string; step: string; average_ms: number; max_ms: number; runs: number }[];
  tokens_per_day: { date: string; input: number; output: number }[];
  tokens_by_model: { model: string; input: number; output: number; estimated: boolean; cost: number | null }[];
  tokens_today: number;
  daily_token_limit: number;
}

type Prices = UserSettings['llmPrices'];

const RANGES = [7, 14, 30];
const number = new Intl.NumberFormat();

function duration(ms: number): string {
  return ms < 1000 ? `${ms} ms` : ms < 60_000 ? `${(ms / 1000).toFixed(1)} s` : `${(ms / 60_000).toFixed(1)} min`;
}

/** Stacked bars from plain divs: one column per day. */
function Bars({ rows, series, label }: {
  rows: { date: string; [key: string]: number | string }[];
  series: { key: string; color: string; name: string }[];
  label: string;
}) {
  const max = Math.max(1, ...rows.map(r => series.reduce((sum, s) => sum + Number(r[s.key]), 0)));
  return (
    <div>
      <div className="flex items-end gap-1 h-32" role="img" aria-label={label}>
        {rows.map(row => {
          const title = `${row.date}: ${series.map(s => `${number.format(Number(row[s.key]))} ${s.name}`).join(', ')}`;
          return (
            <div key={row.date} className="flex-1 h-full flex flex-col justify-end min-w-0" title={title}>
              {series.map(s => (
                <div key={s.key} className={s.color} style={{ height: `${(Number(row[s.key]) / max) * 100}%` }} />
              ))}
            </div>
          );
        })}
      </div>
      <div className="flex justify-between text-[10px] text-nexus-text-muted mt-1">
        <span>{rows[0]?.date.slice(5)}</span>
        <span>{rows[rows.length - 1]?.date.slice(5)}</span>
      </div>
      <div className="flex gap-3 text-xs text-nexus-text-secondary mt-2">
        {series.map(s => <span key={s.key} className="flex items-center gap-1"><span className={`w-2.5 h-2.5 rounded-sm ${s.color}`} />{s.name}</span>)}
      </div>
    </div>
  );
}

export function DashboardPage() {
  const [days, setDays] = useState(14);
  const [data, setData] = useState<Dashboard | null>(null);
  const [prices, setPrices] = useState<Prices | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api.get<Dashboard>('/api/dashboard', { days: String(days) }).then(setData).catch(err => setError(getErrorMessage(err)));
  }, [days]);
  useEffect(load, [load]);
  useEffect(() => {
    settingsService.getSettings().then(s => setPrices(s.user.llmPrices ?? {})).catch(() => setPrices({}));
  }, []);

  const savePrice = (model: string, field: 'input' | 'output', value: string) => {
    const next = { ...prices, [model]: { input: 0, output: 0, ...prices?.[model], [field]: Number(value) || 0 } };
    setPrices(next);
    settingsService.updateUserSettings({ llmPrices: next }).then(load).catch(err => setError(getErrorMessage(err)));
  };

  if (error) return <p className="text-sm text-nexus-danger" role="alert">{error}</p>;
  if (!data || prices === null) return <p className="text-sm text-nexus-text-muted">Loading…</p>;

  const totalTokens = data.tokens_by_model.reduce((sum, m) => sum + m.input + m.output, 0);
  const totalCost = data.tokens_by_model.reduce((sum, m) => sum + (m.cost ?? 0), 0);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-nexus-text">Dashboard</h1>
          <p className="text-nexus-text-secondary mt-1">How your workflows are running and what the AI costs.</p>
        </div>
        <div className="flex gap-1" role="radiogroup" aria-label="Time range">
          {RANGES.map(r => (
            <button key={r} role="radio" aria-checked={days === r} onClick={() => setDays(r)}
              className={`px-3 py-1.5 rounded-lg text-sm ${days === r ? 'bg-nexus-accent text-nexus-bg' : 'bg-nexus-bg-tertiary text-nexus-text-secondary'}`}>
              {r} days
            </button>
          ))}
        </div>
      </div>

      <div className="grid gap-4 grid-cols-2 lg:grid-cols-4">
        {[
          ['Runs', number.format(data.total_runs)],
          ['Failure rate', `${(data.failure_rate * 100).toFixed(1)}%`],
          ['AI tokens', number.format(totalTokens)],
          ['Today', data.daily_token_limit ? `${number.format(data.tokens_today)} / ${number.format(data.daily_token_limit)}` : number.format(data.tokens_today)],
        ].map(([label, value]) => (
          <Card key={label}><CardContent className="p-4">
            <p className="text-xs text-nexus-text-muted">{label}</p>
            <p className="text-xl font-semibold text-nexus-text mt-1">{value}</p>
          </CardContent></Card>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Runs per day</CardTitle></CardHeader>
          <CardContent>
            <Bars rows={data.runs_per_day} label="Runs per day" series={[
              { key: 'failed', color: 'bg-red-400', name: 'failed' },
              { key: 'other', color: 'bg-amber-400', name: 'cancelled or running' },
              { key: 'completed', color: 'bg-green-500', name: 'completed' },
            ]} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>AI tokens per day</CardTitle></CardHeader>
          <CardContent>
            <Bars rows={data.tokens_per_day} label="AI tokens per day" series={[
              { key: 'output', color: 'bg-nexus-accent', name: 'output' },
              { key: 'input', color: 'bg-nexus-accent/40', name: 'input' },
            ]} />
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Slowest steps</CardTitle>
            <CardDescription>Average time per step in the selected period.</CardDescription>
          </CardHeader>
          <CardContent>
            {data.slowest_steps.length === 0 ? <p className="text-sm text-nexus-text-muted">No runs yet.</p> : (
              <ul className="space-y-2 text-sm">
                {data.slowest_steps.map(s => (
                  <li key={`${s.workflow_id}-${s.step}`} className="flex justify-between gap-3">
                    <span className="min-w-0 truncate"><span className="text-nexus-text">{s.step}</span> <span className="text-nexus-text-muted">in {s.workflow}</span></span>
                    <span className="text-nexus-text-secondary whitespace-nowrap" title={`slowest ${duration(s.max_ms)} over ${s.runs} run(s)`}>{duration(s.average_ms)}</span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Most failures</CardTitle>
          </CardHeader>
          <CardContent>
            {data.top_failing.length === 0 ? <p className="text-sm text-nexus-text-muted">No failed runs. 🎉</p> : (
              <ul className="space-y-2 text-sm">
                {data.top_failing.map(f => (
                  <li key={f.workflow_id} className="flex justify-between gap-3">
                    <Link to={`/workflows?open=${f.workflow_id}`} className="text-nexus-text hover:underline truncate">{f.name}</Link>
                    <span className="text-nexus-danger">{f.failures}</span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>AI usage by model</CardTitle>
          <CardDescription>
            Enter your provider's prices (US$ per million tokens) to see estimated cost.
            {data.tokens_by_model.some(m => m.estimated) && ' Streamed chat replies are estimated at ~4 characters per token.'}
          </CardDescription>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          {data.tokens_by_model.length === 0 ? <p className="text-sm text-nexus-text-muted">No AI calls in this period.</p> : (
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-nexus-text-muted">
                <tr><th className="py-1.5 font-medium">Model</th><th className="font-medium">Input</th><th className="font-medium">Output</th><th className="font-medium">$ / M in</th><th className="font-medium">$ / M out</th><th className="font-medium">Cost</th></tr>
              </thead>
              <tbody className="divide-y divide-nexus-border text-nexus-text-secondary">
                {data.tokens_by_model.map(m => (
                  <tr key={m.model}>
                    <td className="py-1.5 pr-3 text-nexus-text font-mono text-xs">{m.model || 'unknown'}</td>
                    <td className="pr-3">{number.format(m.input)}</td>
                    <td className="pr-3">{number.format(m.output)}</td>
                    {(['input', 'output'] as const).map(field => (
                      <td key={field} className="pr-3">
                        <input
                          type="number" min={0} step="0.01"
                          aria-label={`${field} price for ${m.model}`}
                          defaultValue={prices[m.model]?.[field] ?? ''}
                          onBlur={(e) => savePrice(m.model, field, e.target.value)}
                          className="w-20 px-2 py-1 rounded bg-nexus-bg-tertiary border border-nexus-border text-xs"
                        />
                      </td>
                    ))}
                    <td>{m.cost === null ? '—' : `$${m.cost.toFixed(2)}`}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot><tr><td colSpan={5} className="pt-2 text-right text-xs text-nexus-text-muted">Total</td><td className="pt-2">${totalCost.toFixed(2)}</td></tr></tfoot>
            </table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
