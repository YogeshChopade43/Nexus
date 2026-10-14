import { expect, test } from 'vitest';
import { exportFileName, shareNote } from './sharing';

test('after exporting, say how to share it and what was left out', () => {
  expect(exportFileName('Daily Briefing!')).toBe('daily-briefing.nexus.json');
  expect(shareNote('daily-briefing.nexus.json', [])).toBe(
    'Saved daily-briefing.nexus.json. Send it to anyone: they open it with Import on their Nexus.');
  expect(shareNote('x.nexus.json', ['Call API: Authorization', 'Call API: api_key in the address'])).toBe(
    'Saved x.nexus.json. Send it to anyone: they open it with Import on their Nexus. '
    + 'Left out so it’s safe to share (they’ll add their own): Call API: Authorization; Call API: api_key in the address.');
});
