/** The file name a workflow is exported as. */
export const exportFileName = (name: string) =>
  `${name.replace(/[^a-z0-9]+/gi, '-').replace(/^-+|-+$/g, '').toLowerCase() || 'workflow'}.nexus.json`;

/** What to tell you after exporting: how the other person opens it, and the secrets the export left out. */
export function shareNote(fileName: string, cleared: string[]): string {
  const note = `Saved ${fileName}. Send it to anyone: they open it with Import on their Nexus.`;
  return cleared.length ? `${note} Left out so it’s safe to share (they’ll add their own): ${cleared.join('; ')}.` : note;
}
