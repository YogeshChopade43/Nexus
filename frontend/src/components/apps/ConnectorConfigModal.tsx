import { useState, type FormEvent } from 'react';
import { KeyRound, Loader2, ShieldCheck } from 'lucide-react';
import { Modal } from '../ui/Modal';
import { Input } from '../ui/Input';
import { Button } from '../ui/Button';
import type { App, ConnectorConfig } from '../../types/app';

interface ConnectorField {
  key: string;
  label: string;
  type: 'password' | 'email' | 'url';
  placeholder: string;
  autoComplete?: string;
}

const connectorFields: Record<string, ConnectorField[]> = {
  github: [
    { key: 'token', label: 'Personal access token', type: 'password', placeholder: 'ghp_...', autoComplete: 'off' },
  ],
  slack: [
    { key: 'token', label: 'Bot token', type: 'password', placeholder: 'xoxb-...', autoComplete: 'off' },
  ],
  grafana: [
    { key: 'baseUrl', label: 'Grafana URL', type: 'url', placeholder: 'https://grafana.example.com' },
    { key: 'token', label: 'Service account token', type: 'password', placeholder: 'glsa_...', autoComplete: 'off' },
  ],
  jira: [
    { key: 'baseUrl', label: 'Jira URL', type: 'url', placeholder: 'https://your-domain.atlassian.net' },
    { key: 'email', label: 'Atlassian email', type: 'email', placeholder: 'you@example.com', autoComplete: 'email' },
    { key: 'token', label: 'Atlassian API token', type: 'password', placeholder: 'API token', autoComplete: 'off' },
  ],
  linear: [
    { key: 'token', label: 'API key', type: 'password', placeholder: 'Linear API key', autoComplete: 'off' },
  ],
  notion: [
    { key: 'token', label: 'Integration token', type: 'password', placeholder: 'secret_...', autoComplete: 'off' },
  ],
};

interface ConnectorConfigModalProps {
  app: App | null;
  open: boolean;
  onClose: () => void;
  onSubmit: (app: App, config: ConnectorConfig) => Promise<void>;
  submitting: boolean;
}

export function ConnectorConfigModal({ app, open, onClose, onSubmit, submitting }: ConnectorConfigModalProps) {
  if (!app) return null;

  const fields = connectorFields[app.app_id ?? app.id] ?? [];
  const [values, setValues] = useState<ConnectorConfig>({});
  const [error, setError] = useState('');

  const setValue = (key: string, value: string) => {
    setValues(prev => ({ ...prev, [key]: value }));
    setError('');
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const missing = fields.find(field => !values[field.key]?.trim());
    if (missing) {
      setError(`${missing.label} is required`);
      return;
    }

    const config = Object.fromEntries(
      fields.map(field => [field.key, values[field.key]?.trim() ?? ''])
    ) as ConnectorConfig;
    await onSubmit(app, config);
  };

  return (
    <Modal
      open={open}
      onClose={submitting ? () => {} : onClose}
      title={`Connect ${app.name}`}
      description="Provide the credentials Nexus needs to access this integration."
      size="md"
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="flex items-start gap-3 p-3 rounded-lg bg-nexus-accent-dim/50 border-nexus-border border">
          <ShieldCheck className="w-5 h-5 text-nexus-accent flex-shrink-0 mt-0.5" />
          <p className="text-sm text-nexus-text-secondary">
            Credentials are sent directly to the Nexus backend for this connection and are not stored in your browser.
          </p>
        </div>

        <div className="space-y-4">
          {fields.map(field => (
            <Input
              key={field.key}
              label={field.label}
              type={field.type}
              value={values[field.key] ?? ''}
              onChange={(event) => setValue(field.key, event.target.value)}
              placeholder={field.placeholder}
              autoComplete={field.autoComplete}
              required
              disabled={submitting}
              aria-label={`${app.name} ${field.label}`}
            />
          ))}
        </div>

        {error && (
          <p className="text-sm text-nexus-danger" role="alert">
            {error}
          </p>
        )}

        <div className="flex items-center gap-2 text-xs text-nexus-text-muted">
          <KeyRound className="w-4 h-4" />
          <span>Use a token with only the permissions this integration requires.</span>
        </div>

        <div className="flex justify-end gap-2 pt-1">
          <Button type="button" variant="secondary" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" loading={submitting} disabled={submitting} className="gap-1.5">
            {submitting && <Loader2 className="w-4 h-4 animate-spin" />}
            {submitting ? 'Connecting...' : 'Connect app'}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
