import type { SelectHTMLAttributes } from 'react';

// The browser's own list of IANA timezones (ES2022 Intl; typed loosely for the ES2020 lib).
const intl = Intl as unknown as { supportedValuesOf?: (key: string) => string[] };
const browserZone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
const ZONES = ['UTC', ...new Set([...(intl.supportedValuesOf?.('timeZone') ?? [browserZone])].filter(z => z !== 'UTC'))];

interface TimezoneSelectProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, 'value' | 'onChange'> {
  value: string;
  onChange: (timezone: string) => void;
  /** Adds a first option with value "" (e.g. "use the default"). */
  emptyLabel?: string;
}

/** Pick a timezone from a list instead of typing its name. */
export function TimezoneSelect({ value, onChange, emptyLabel, ...props }: TimezoneSelectProps) {
  const zones = value && !ZONES.includes(value) ? [value, ...ZONES] : ZONES;
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} {...props}>
      {emptyLabel !== undefined && <option value="">{emptyLabel}</option>}
      {zones.map(zone => <option key={zone} value={zone}>{zone.replace(/_/g, ' ')}</option>)}
    </select>
  );
}
