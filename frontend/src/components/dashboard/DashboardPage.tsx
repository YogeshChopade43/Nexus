import { Activity, AlertTriangle, BarChart3, Coins, Cpu, Gauge, Timer } from 'lucide-react';
import { EmptyState, PageHeader, SegmentedControl } from '../ui/PageHeader';
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
  const totals = rows.map(r => series.reduce((sum, s) => sum + Number(r[s.key]), 0));
  const max = Math.max(1, ...totals);
  if (totals.every(total => total === 0)) {
    return <EmptyState icon={BarChart3} title="Nothing in this period" description="Bars appear here once there is activity." className="h-[11.5rem] py-0" />;
  }
  return (
    <div>
      <div className="relative flex h-36 items-end gap-1 border-b border-nexus-border" role="img" aria-label={label}>
        <div className="pointer-events-none absolute inset-x-0 top-0 border-t border-dashed border-nexus-border/70" aria-hidden />
        <div className="pointer-events-none absolute inset-x-0 top-1/2 border-t border-dashed border-nexus-border/70" aria-hidden />
        {rows.map(row => {
          const title = `${row.date}: ${series.map(s => `${number.format(Number(row[s.key]))} ${s.name}`).join(', ')}`;
          return (
            <div key={row.date} className="group relative z-[1] flex h-full min-w-0 flex-1 flex-col justify-end" title={title}>
              <div className="flex flex-col overflow-hidden rounded-t-[3px] transition-opacity group-hover:opacity-80">
                {series.map(s => (
                  <div key={s.key} className={s.color} style={{ height: `${(Number(row[s.key]) / max) * 9}rem` }} />
                ))}
              </div>
            </div>
          );
        })}
      </div>
      <div className="mt-1.5 flex justify-between text-[11px] tabular-nums text-nexus-text-muted">
        <span>{rows[0]?.date.slice(5)}</span>
        <span>{rows[rows.length - 1]?.date.slice(5)}</span>
      </div>
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-nexus-text-secondary">
        {series.map(s => <span key={s.key} className="flex items-center gap-1.5"><span className={`h-2 w-2 rounded-full ${s.color}`} />{s.name}</span>)}
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
  if (!data || prices === null) {
    return (
      <div className="space-y-6" aria-busy="true" aria-label="Loading dashboard">
        <div className="h-12 w-72 animate-pulse rounded-md bg-nexus-bg-tertiary" />
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {[0, 1, 2, 3].map(i => <div key={i} className="h-[6.5rem] animate-pulse rounded-xl bg-nexus-bg-secondary" />)}
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          {[0, 1].map(i => <div key={i} className="h-64 animate-pulse rounded-xl bg-nexus-bg-secondary" />)}
        </div>
      </div>
    );
  }

  const totalTokens = data.tokens_by_model.reduce((sum, m) => sum + m.input + m.output, 0);
  const totalCost = data.tokens_by_model.reduce((sum, m) => sum + (m.cost ?? 0), 0);

  return (
    <div className="space-y-6">
      <PageHeader title="Dashboard" description="How your workflows are running and what the AI costs."
        actions={<SegmentedControl label="Time range" value={days} onChange={setDays}
          options={RANGES.map(r => ({ value: r, label: `${r} days` }))} />} />

      <div className="grid gap-4 grid-cols-2 lg:grid-cols-4">
        {([
          ['Runs', number.format(data.total_runs), `in the last ${days} days`, Activity],
          ['Failure rate', `${(data.failure_rate * 100).toFixed(1)}%`, `${number.format(data.failed_runs)} failed`, Gauge],
          ['AI tokens', number.format(totalTokens), totalCost ? `≈ $${totalCost.toFixed(2)}` : 'input + output', Cpu],
          ['Tokens today', number.format(data.tokens_today), data.daily_token_limit ? `of ${number.format(data.daily_token_limit)} daily limit` : 'no daily limit', Coins],
        ] as const).map(([label, value, detail, Icon]) => (
          <Card key={label}>
            <div className="flex items-center justify-between">
              <p className="text-[13px] font-medium text-nexus-text-secondary">{label}</p>
              <Icon className="h-4 w-4 text-nexus-text-muted" aria-hidden />
            </div>
            <p className="mt-2 text-2xl font-semibold tabular-nums tracking-tight text-nexus-text">{value}</p>
            <p className="mt-0.5 text-xs text-nexus-text-muted">{detail}</p>
          </Card>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Runs per day</CardTitle></CardHeader>
          <CardContent>
            <Bars rows={data.runs_per_day} label="Runs per day" series={[
              { key: 'failed', color: 'bg-nexus-danger', name: 'failed' },
              { key: 'other', color: 'bg-nexus-warning', name: 'cancelled or running' },
              { key: 'completed', color: 'bg-nexus-success', name: 'completed' },
            ]} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>AI tokens per day</CardTitle></CardHeader>
          <CardContent>
            <Bars rows={data.tokens_per_day} label="AI tokens per day" series={[
              { key: 'output', color: 'bg-nexus-accent', name: 'output' },
              { key: 'input', color: 'bg-nexus-accent/35', name: 'input' },
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
            {data.slowest_steps.length === 0 ? <EmptyState icon={Timer} title="No runs yet" description="Step timings show up after your workflows run." className="py-6" /> : (
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
            {data.top_failing.length === 0 ? <EmptyState icon={AlertTriangle} title="No failed runs" description="Workflows that fail most often will be listed here." className="py-6" /> : (
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
          {data.tokens_by_model.length === 0 ? <EmptyState icon={Cpu} title="No AI calls in this period" description="Chats and AI steps in workflows are counted here, per model." className="py-6" /> : (
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-nexus-text-muted">
                <tr><th className="py-1.5 font-medium">Model</th><th className="font-medium">Input</th><th className="font-medium">Output</th><th className="font-medium">$ / M in</th><th className="font-medium">$ / M out</th><th className="font-medium">Cost</th></tr>
              </thead>
              <tbody className="divide-y divide-nexus-border text-nexus-text-secondary tabular-nums">
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
                          className="h-7 w-20 rounded-md border px-2 text-xs tabular-nums"
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
