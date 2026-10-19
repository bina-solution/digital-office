import { ReactNode, useCallback, useEffect, useId, useRef, useState } from 'react';

/**
 * THE ONE CONFIRMATION SURFACE — replaces every `window.confirm()` in this app.
 *
 * WHY A COMPONENT AND NOT THE BROWSER'S OWN DIALOG
 *
 * A native `confirm()` can carry exactly one thing: a string the caller wrote before it knew
 * anything. That is why "שחרר הכל" and "עצור הכל" read identically at 13:40 (when releasing every
 * lock would have killed a working batch) and at 15:44 (when it was the correct repair) — the
 * dialog could not say how many locks were held or whether anything was in flight, so the operator
 * was asked to authorise an action whose consequence the product knew and did not show. Same for
 * "מחק טווח": `confirm()` said "irreversible" without saying irreversible to WHAT.
 *
 * So the consequence sentence is a REQUIRED prop, not an optional nicety, and `facts` exists to
 * carry the measured numbers beside it. A caller that cannot measure something passes `unknown`
 * — a stated "not measured" — rather than a zero. A number nobody took is not a number, and
 * rendering it as one is the single failure mode this whole component exists to prevent.
 *
 * IT STANDS ALONE ON PURPOSE. No context, no provider, no App.tsx wiring, no CSS of its own (it
 * reuses `.modal-ov` / `.modal` / `.modal-h`, which index.css has always carried). Drop it into any
 * page, or take the `useConfirm()` hook when the call site is imperative — which is every site that
 * used to read `if (!confirm(...)) return;`.
 *
 * ACCESSIBILITY, because a modal that traps nothing is a modal in appearance only:
 * Escape cancels · backdrop click cancels · focus moves into the dialog on open and is RESTORED to
 * the element that opened it on close · Tab cycles inside the dialog · `role="alertdialog"` with the
 * title and the consequence wired as its accessible name and description. RTL needs no special
 * casing (the document is `dir="rtl"`); the confirm button is first in DOM order so it is the first
 * stop after the dialog itself.
 */

export interface ConfirmFact {
  /** what this number IS, in words — never a bare figure */
  label: string;
  value: ReactNode;
  /** colours the value the same way the rest of the app colours a state */
  kind?: 'ok' | 'warn' | 'bad' | 'muted';
  /** the fact behind the fact (how it was measured, when) */
  title?: string;
}

export interface ConfirmSpec {
  /** what is about to happen, in a few words */
  title: string;
  /**
   * REQUIRED. What this click will DO, with the real numbers in it — "יימחקו 34,567 שורות
   * מטבלת הלוג" beats "בלתי הפיך". If the caller has no numbers it must say so via `unknown`.
   */
  consequence: ReactNode;
  /** measured facts that decide the answer (locks held, executions in flight, rows matched…) */
  facts?: ConfirmFact[];
  /** what could NOT be measured, and therefore is NOT being claimed. Rendered as a visible
   *  caveat — this is the honest half of a degraded read (an endpoint that 404s, a count the
   *  server could not take). Never substitute a zero for this. */
  unknown?: ReactNode;
  /** destructive: red confirm button, and the title gets the warning treatment */
  danger?: boolean;
  confirmLabel?: string;
  cancelLabel?: string;
}

const FOCUSABLE =
  'a[href],button:not([disabled]),textarea,input,select,[tabindex]:not([tabindex="-1"])';

export function ConfirmModal({
  spec,
  onConfirm,
  onCancel,
  busy = false,
}: {
  spec: ConfirmSpec;
  onConfirm: () => void;
  onCancel: () => void;
  /** the caller's work is in flight — the dialog stays up, disabled, instead of vanishing
   *  into an unexplained pause */
  busy?: boolean;
}) {
  const panelRef = useRef<HTMLDivElement | null>(null);
  const confirmRef = useRef<HTMLButtonElement | null>(null);
  const openerRef = useRef<Element | null>(null);
  // a page can host more than one of these (settings has three); fixed ids would collide
  const uid = useId();

  useEffect(() => {
    openerRef.current = document.activeElement;
    confirmRef.current?.focus();
    const opener = openerRef.current;
    return () => {
      // give focus back where it came from; a modal that drops focus on the body
      // leaves a keyboard user at the top of the page with no idea what happened
      if (opener instanceof HTMLElement && document.contains(opener)) opener.focus();
    };
  }, []);

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        if (!busy) onCancel();
        return;
      }
      if (e.key !== 'Tab') return;
      const nodes = panelRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE);
      if (!nodes || nodes.length === 0) return;
      const first = nodes[0];
      const last = nodes[nodes.length - 1];
      const act = document.activeElement;
      if (e.shiftKey && (act === first || act === panelRef.current)) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && act === last) {
        e.preventDefault();
        first.focus();
      }
    },
    [busy, onCancel],
  );

  return (
    <div
      className="modal-ov"
      onMouseDown={(e) => {
        // backdrop only — a mousedown that STARTED inside the dialog (a drag across a
        // number, say) must not read as "cancel"
        if (e.target === e.currentTarget && !busy) onCancel();
      }}
    >
      <div
        className="modal"
        /* the pipeline dialogs carry seven measured facts; `.modal` is centred and unscrolled,
           so a tall one would push its own buttons off the viewport */
        style={{ maxHeight: '85vh', overflowY: 'auto' }}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={`${uid}-title`}
        aria-describedby={`${uid}-consequence`}
        ref={panelRef}
        tabIndex={-1}
        onKeyDown={onKeyDown}
      >
        <div className="modal-h">
          <h3 id={`${uid}-title`} style={spec.danger ? { color: 'var(--red)' } : undefined}>
            {spec.title}
          </h3>
        </div>

        <div id={`${uid}-consequence`} style={{ fontSize: 13, lineHeight: 1.6 }}>
          {spec.consequence}
        </div>

        {!!spec.facts?.length && (
          <div style={{ marginTop: 12 }}>
            {spec.facts.map((f, i) => (
              <div className="kv" key={`${f.label}:${i}`}>
                <dt title={f.title}>{f.label}</dt>
                <dd className="num">
                  {f.kind ? <span className={`pill ${f.kind}`}>{f.value}</span> : f.value}
                </dd>
              </div>
            ))}
          </div>
        )}

        {spec.unknown && (
          <div className="callout warn" style={{ marginTop: 12 }}>
            <b>לא נמדד.</b> {spec.unknown}
          </div>
        )}

        <div
          className="flex items-center gap-2"
          style={{ marginTop: 18, justifyContent: 'flex-start' }}
        >
          <button
            ref={confirmRef}
            className={`btn${spec.danger ? ' danger' : ''}`}
            disabled={busy}
            onClick={onConfirm}
          >
            {busy ? <span className="spinner" /> : spec.confirmLabel || 'אישור'}
          </button>
          <button className="btn ghost" disabled={busy} onClick={onCancel}>
            {spec.cancelLabel || 'ביטול'}
          </button>
          <span className="muted small" style={{ marginInlineStart: 'auto' }}>
            Esc לביטול
          </span>
        </div>
      </div>
    </div>
  );
}

export default ConfirmModal;

/**
 * The imperative form, for the call sites that used to read `if (!confirm(...)) return;`.
 *
 *   const { ask, confirmUI } = useConfirm();
 *   ...
 *   if (!(await ask({ title: '…', consequence: <>…</>, danger: true }))) return;
 *   ...
 *   return (<div>{confirmUI}{…}</div>);
 *
 * `ask` resolves `false` on Escape, on a backdrop click and on ביטול — the same three ways the
 * native dialog said no, so a call site converts by changing the condition and nothing else.
 * The awaited work stays with the CALLER: this hook decides consent, never side effects.
 */
export function useConfirm(): {
  ask: (spec: ConfirmSpec) => Promise<boolean>;
  confirmUI: ReactNode;
} {
  const [pending, setPending] = useState<ConfirmSpec | null>(null);
  const resolveRef = useRef<((ok: boolean) => void) | null>(null);

  const settle = useCallback((ok: boolean) => {
    setPending(null);
    const r = resolveRef.current;
    resolveRef.current = null;
    r?.(ok);
  }, []);

  const ask = useCallback((spec: ConfirmSpec) => {
    // a second ask while one is open cancels the first rather than losing its promise
    resolveRef.current?.(false);
    setPending(spec);
    return new Promise<boolean>((resolve) => {
      resolveRef.current = resolve;
    });
  }, []);

  // a page unmounting mid-question must not leave an awaited promise dangling forever
  useEffect(() => () => resolveRef.current?.(false), []);

  return {
    ask,
    confirmUI: pending ? (
      <ConfirmModal spec={pending} onConfirm={() => settle(true)} onCancel={() => settle(false)} />
    ) : null,
  };
}
