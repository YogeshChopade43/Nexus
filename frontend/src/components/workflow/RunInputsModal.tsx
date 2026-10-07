import { useEffect, useState } from 'react';
import { Play } from 'lucide-react';
import { Modal } from '../ui/Modal';
import { Button } from '../ui/Button';
import { fieldClass } from './StepConfig';
import type { ManualInput } from '../../types/workflow';

interface RunInputsModalProps {
  open: boolean;
  title: string;
  inputs: ManualInput[];
  /** Resolves to an error message, or null when the run started. */
  onSubmit: (values: Record<string, unknown>) => Promise<string | null>;
  onClose: () => void;
}

function initialValues(inputs: ManualInput[]): Record<string, unknown> {
  return Object.fromEntries(inputs.map(i => [i.name, i.type === 'boolean' ? Boolean(i.default && String(i.default) !== 'false') : i.default ?? '']));
}

export function RunInputsModal({ open, title, inputs, onSubmit, onClose }: RunInputsModalProps) {
  const [values, setValues] = useState<Record<string, unknown>>(() => initialValues(inputs));
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    if (open) {
      setValues(initialValues(inputs));
      setError(null);
    }
  }, [open, inputs]);

  const submit = async () => {
    setRunning(true);
    setError(null);
    try {
      const failure = await onSubmit(values);
      if (failure) setError(failure);
    } finally {
      setRunning(false);
    }
  };

  return (
    <Modal open={open} onClose={() => !running && onClose()} title={title} size="md">
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); void submit(); }}>
        {inputs.map(input => (
          <label key={input.name} className="block">
            <span className="block text-xs font-medium text-nexus-text-secondary mb-1">
              {input.name}{input.required && <span className="text-nexus-danger"> *</span>}
            </span>
            {input.type === 'boolean' ? (
              <input type="checkbox" checked={Boolean(values[input.name])} onChange={(e) => setValues({ ...values, [input.name]: e.target.checked })} />
            ) : (
              <input type={input.type === 'number' ? 'number' : 'text'} value={String(values[input.name] ?? '')}
                onChange={(e) => setValues({ ...values, [input.name]: e.target.value })} className={fieldClass} />
            )}
          </label>
        ))}
        {error && <p className="text-sm text-nexus-danger" role="alert">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" size="sm" onClick={onClose} disabled={running}>Cancel</Button>
          <Button type="submit" variant="primary" size="sm" loading={running} disabled={running} className="gap-1.5">
            <Play className="w-4 h-4" /> Run
          </Button>
        </div>
      </form>
    </Modal>
  );
}
