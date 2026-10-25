// Renders docs/generated/reference.json, which docs/scripts/gen_reference.py writes from the Python code.
import { Fragment, type ReactNode } from 'react';
import reference from '@/generated/reference.json';

type Setting = (typeof reference.settings)[number];

// One tone panel, rows told apart by space and a hover step, never by rules (app/global.css: .docs-panel, .docs-row).
const PANEL = 'docs-panel not-prose my-6 flex flex-col rounded-xl bg-fd-card p-1.5';
const ROW = 'docs-row rounded-lg px-4 py-4 transition-colors hover:bg-fd-accent/40';
const VALUE = 'font-mono text-[13px] text-fd-foreground';

function shown(v: unknown) {
  if (v === '') return '""';
  return typeof v === 'string' ? v : JSON.stringify(v);
}

function values(items: string[]) {
  return items.map((v, i) => (
    <Fragment key={v}>
      {i > 0 && <span className="text-fd-muted-foreground"> · </span>}
      <code className={VALUE}>{v}</code>
    </Fragment>
  ));
}

function accepts(s: Setting): ReactNode {
  if (s.choices.length) return values(s.choices);
  if (s.range)
    return (
      <>
        <code className={VALUE}>{s.range[0]}</code> to <code className={VALUE}>{s.range[1]}</code>
      </>
    );
  if (s.type === 'boolean') return values(['true', 'false']);
  if (s.type === 'text') return s.may_be_empty ? 'text, may be empty' : 'text';
  return s.type;
}

export function Settings({ only, secrets = false }: { only?: string[]; secrets?: boolean }) {
  const rows = reference.settings.filter((s) => (only ? only.includes(s.key) : s.secret === secrets));
  return (
    <div className={PANEL}>
      {rows.map((s) => (
        <div
          key={s.key}
          id={`setting-${s.key}`}
          className={`${ROW} grid scroll-mt-24 gap-x-8 gap-y-2 sm:grid-cols-[12rem_1fr]`}
        >
          <div className="flex flex-col gap-1">
            <code className="font-mono text-[14px] font-semibold break-all text-fd-foreground">{s.key}</code>
            <span className="text-[13px] text-fd-muted-foreground">{s.type}</span>
          </div>
          <div className="flex min-w-0 flex-col gap-2.5">
            <p className="text-base leading-relaxed text-fd-foreground">{s.help}</p>
            <dl className="grid grid-cols-[4.25rem_1fr] gap-x-3 gap-y-1 text-[13px] leading-relaxed">
              {!s.secret && (
                <>
                  <dt className="text-fd-muted-foreground">default</dt>
                  <dd className="break-all">
                    <code className={VALUE}>{shown(s.default)}</code>
                  </dd>
                </>
              )}
              <dt className="text-fd-muted-foreground">accepts</dt>
              <dd className="break-words text-fd-foreground">{accepts(s)}</dd>
              <dt className="text-fd-muted-foreground">env</dt>
              <dd className="break-all">
                <code className={VALUE}>{s.env}</code>
              </dd>
            </dl>
          </div>
        </div>
      ))}
    </div>
  );
}

export function Commands() {
  return (
    <div className={PANEL}>
      {reference.commands.map((c) => (
        <div key={c.usage} className={`${ROW} grid gap-x-8 gap-y-1 sm:grid-cols-[15rem_1fr]`}>
          <code className="font-mono text-[14px] font-semibold text-fd-foreground">{c.usage}</code>
          <span className="text-base text-fd-foreground">{c.help}</span>
        </div>
      ))}
    </div>
  );
}

export function Voices() {
  return (
    <div className={`${PANEL} sm:grid sm:grid-cols-2`}>
      {reference.voices.map((v) => (
        <div key={v.id} className={`${ROW} flex flex-col gap-1`}>
          <code className="font-mono text-[14px] font-semibold text-fd-foreground">{v.id}</code>
          <span className="text-[14px] text-fd-foreground">{v.description}</span>
        </div>
      ))}
    </div>
  );
}

export function Hooks() {
  return (
    <ul>
      {reference.hooks.map((h) => (
        <li key={h.event}>
          <code>{h.event}</code>
          {h.matcher && (
            <>
              {' '}
              with matcher <code>{h.matcher}</code>
            </>
          )}
        </li>
      ))}
    </ul>
  );
}
