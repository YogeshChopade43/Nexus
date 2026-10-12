import { useEffect, useState } from 'react';
import { mentionTargets, splitMentions } from './mentions';

/** Text with "@App" / "@document" mentions shown as highlighted chips. Only colour and a box-shadow mark them
 *  (no padding or weight), so the text keeps the exact width it has in the message box above it. */
export function MentionText({ text, labels }: { text: string; labels: string[] }) {
  return (
    <>
      {splitMentions(text, labels).map((part, i) => (part.mention
        ? <mark key={i} data-mention className="rounded-[4px] bg-nexus-accent/15 text-nexus-accent-text shadow-[0_0_0_2px_rgb(var(--nexus-accent)/0.15)]">{part.text}</mark>
        : <span key={i}>{part.text}</span>))}
    </>
  );
}

/** Names that can be mentioned (connected apps, ready documents), loaded only for text that has an "@". */
export function useMentionLabels(text: string): string[] {
  const [labels, setLabels] = useState<string[]>([]);
  const wanted = text.includes('@');
  useEffect(() => {
    if (!wanted) return;
    let alive = true;
    void mentionTargets().then(targets => { if (alive) setLabels(targets.map(t => t.label)); });
    return () => { alive = false; };
  }, [wanted]);
  return labels;
}
