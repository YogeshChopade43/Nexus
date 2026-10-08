import { expect, test, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { TimezoneSelect } from './TimezoneSelect';

test('lists timezones, keeps an unlisted saved value, and offers an empty default', () => {
  const onChange = vi.fn();
  render(<TimezoneSelect aria-label="Timezone" value="Asia/Kolkata" onChange={onChange} emptyLabel="Your timezone (from Settings)" />);
  const select = screen.getByLabelText('Timezone') as HTMLSelectElement;
  expect(select.value).toBe('Asia/Kolkata');
  expect(screen.getByRole('option', { name: 'UTC' })).toBeInTheDocument();
  expect(screen.getByRole('option', { name: 'Your timezone (from Settings)' })).toBeInTheDocument();
  fireEvent.change(select, { target: { value: 'UTC' } });
  expect(onChange).toHaveBeenCalledWith('UTC');
});
