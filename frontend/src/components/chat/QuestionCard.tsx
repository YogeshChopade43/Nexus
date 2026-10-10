import { useState } from 'react';
import { MessageCircleQuestion } from 'lucide-react';
import { Button } from '../ui/Button';
import { cn } from '../../lib/utils';
import type { AgentQuestion, QuestionAnswers } from '../../types/chat';

const OTHER = '__other__';

/** The agent's multiple-choice questions: click an option (or several), or type your own under "Other". */
export function QuestionCard({ questions, onSubmit, disabled }: {
  questions: AgentQuestion[];
  onSubmit: (answers: QuestionAnswers) => void;
  disabled?: boolean;
}) {
  const [picked, setPicked] = useState<Record<string, string[]>>({});
  const [other, setOther] = useState<Record<string, string>>({});

  const toggle = (q: AgentQuestion, label: string) => setPicked(prev => {
    const current = prev[q.question] ?? [];
    if (!q.multi_select) return { ...prev, [q.question]: [label] };
    return { ...prev, [q.question]: current.includes(label) ? current.filter(l => l !== label) : [...current, label] };
  });

  // An answer: the chosen labels, with "Other" replaced by what they typed.
  const answerFor = (q: AgentQuestion): string[] => (picked[q.question] ?? [])
    .map(label => (label === OTHER ? (other[q.question] ?? '').trim() : label))
    .filter(Boolean);
  const complete = questions.every(q => answerFor(q).length > 0);

  const submit = () => onSubmit(Object.fromEntries(questions.map(q => {
    const answer = answerFor(q);
    return [q.question, q.multi_select ? answer : answer[0]];
  })));

  return (
    <div role="group" aria-label="Questions from Nexus" className="space-y-4 text-sm">
      {questions.map(q => {
        const chosen = picked[q.question] ?? [];
        const type = q.multi_select ? 'checkbox' : 'radio';
        return (
          <fieldset key={q.question} className="space-y-2">
            <legend className="flex items-start gap-2 font-medium text-nexus-text">
              <MessageCircleQuestion className="w-4 h-4 mt-0.5 text-nexus-accent flex-shrink-0" aria-hidden />
              <span>
                {q.header && <span className="mr-2 px-1.5 py-0.5 rounded bg-nexus-accent/15 text-nexus-accent text-xs font-semibold">{q.header}</span>}
                {q.question}
                {q.multi_select && <span className="ml-1 text-xs font-normal text-nexus-text-muted">(pick any)</span>}
              </span>
            </legend>
            <div className="grid gap-2 sm:grid-cols-2">
              {[...q.options, { label: 'Other', description: 'Type your own answer', value: OTHER }].map(option => {
                const value = 'value' in option ? option.value : option.label;
                const on = chosen.includes(value);
                return (
                  <label key={value} className={cn('flex items-start gap-2 p-2.5 rounded-lg border cursor-pointer transition-colors',
                    on ? 'border-nexus-accent bg-nexus-accent/10' : 'border-nexus-border hover:border-nexus-accent/60')}>
                    <input type={type} name={q.question} checked={on} disabled={disabled}
                      onChange={() => toggle(q, value)} className="mt-0.5" aria-label={option.label} />
                    <span className="min-w-0">
                      <span className="block font-medium text-nexus-text">{option.label}</span>
                      {option.description && <span className="block text-xs text-nexus-text-secondary">{option.description}</span>}
                    </span>
                  </label>
                );
              })}
            </div>
            {chosen.includes(OTHER) && (
              <input autoFocus value={other[q.question] ?? ''} disabled={disabled} aria-label={`Your answer to: ${q.question}`}
                onChange={(e) => setOther(prev => ({ ...prev, [q.question]: e.target.value }))}
                onKeyDown={(e) => { if (e.key === 'Enter' && complete) { e.preventDefault(); submit(); } }}
                placeholder="Type your answer"
                className="w-full px-3 py-2 rounded-lg bg-nexus-bg-tertiary border border-nexus-border text-nexus-text focus:outline-none focus:ring-2 focus:ring-nexus-accent" />
            )}
          </fieldset>
        );
      })}
      <div className="flex justify-end">
        <Button size="sm" onClick={submit} disabled={disabled || !complete}>Send answers</Button>
      </div>
    </div>
  );
}

/** What the user answered, shown under a reply once the card is done. */
export function AnsweredQuestions({ answers }: { answers: QuestionAnswers }) {
  return (
    <ul className="mb-2 space-y-0.5 text-xs text-nexus-text-secondary" aria-label="Your answers">
      {Object.entries(answers).map(([question, answer]) => (
        <li key={question} className="flex gap-1.5">
          <MessageCircleQuestion className="w-3.5 h-3.5 mt-0.5 text-nexus-accent flex-shrink-0" aria-hidden />
          <span>{question} <span className="text-nexus-text">→ {Array.isArray(answer) ? answer.join(', ') : answer}</span></span>
        </li>
      ))}
    </ul>
  );
}
