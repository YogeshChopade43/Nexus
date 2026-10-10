import { useState } from 'react';
import { Button } from '../ui/Button';
import { getErrorMessage } from '../../lib/utils';
import { marketplaceService } from '../../services/marketplace';
import type { MarketField, MarketItem } from '../../types/marketplace';
import type { McpServer } from '../../types/mcp';
import { inputClass } from './ServerFormModal';

/** The settings a registry listing asks for (generated from its install recipe), and Install. */
export function InstallForm({ item, onInstalled }: { item: MarketItem; onInstalled: (server: McpServer) => void }) {
  const [values, setValues] = useState<Record<string, string>>(
    () => Object.fromEntries(item.fields.map(f => [f.key, f.default])),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const required = item.fields.filter(f => f.required);
  const optional = item.fields.filter(f => !f.required);  // folded away: some listings declare dozens
  const renderField = (field: MarketField) => (
    <label key={field.key} className="block">
      <span className="block text-xs font-medium text-nexus-text-secondary mb-1">
        {field.label}{field.required && <span className="text-nexus-danger"> *</span>}
      </span>
      <input
        type={field.secret ? 'password' : 'text'}
        value={values[field.key] ?? ''}
        onChange={(e) => setValues(v => ({ ...v, [field.key]: e.target.value }))}
        aria-required={field.required}
        autoComplete="off"
        className={inputClass}
      />
      {field.description && <span className="block text-xs text-nexus-text-muted mt-1">{field.description}</span>}
    </label>
  );

  const install = async () => {
    setBusy(true);
    setError(null);
    try {
      onInstalled(await marketplaceService.install(item.name!, values));
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); void install(); }}>
      {item.fields.length === 0 && (
        <p className="text-sm text-nexus-text-secondary">
          No settings needed. If the server uses sign-in, Nexus asks you to sign in after installing.
        </p>
      )}
      {required.map(renderField)}
      {optional.length > 0 && (
        <details className="rounded-lg border border-nexus-border p-3">
          <summary className="text-sm text-nexus-text-secondary cursor-pointer">Optional settings ({optional.length})</summary>
          <div className="space-y-3 mt-3">{optional.map(renderField)}</div>
        </details>
      )}
      {item.fields.some(f => f.secret) && <p className="text-xs text-nexus-text-muted">Secret values are stored encrypted and never shown again.</p>}
      <div>
        <p className="text-xs text-nexus-text-muted mb-1">
          Installing connects to (as published by {item.publisher}):
        </p>
        <pre aria-label="Where Nexus will connect" className="text-xs text-nexus-text-secondary bg-nexus-bg-tertiary/50 rounded p-2 max-h-40 overflow-auto whitespace-pre-wrap break-all">
          {[
            item.launch.url,
            ...Object.entries(item.launch.headers).map(([k, v]) => `${k}: ${v}`),
          ].join('\n')}
        </pre>
      </div>
      {error && <p role="alert" className="text-sm text-nexus-danger">{error}</p>}
      <div className="flex justify-end">
        <Button type="submit" variant="primary" loading={busy} disabled={busy} aria-label="Install">
          {busy ? 'Installing…' : 'Install'}
        </Button>
      </div>
    </form>
  );
}
