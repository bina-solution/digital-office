// ─────────────────────────────────────────────────────────────────────────────
// <NewRowDrawer> — THE add-a-record surface for any table on <DataGrid>.
//
// WHY THIS EXISTS AND NOT A BLANK ROW
//
// `onAddRow` used to POST `{}` and prepend whatever came back. On a five-row
// lookup table that reads as "a row appeared, type into it". On `companies` —
// 1,180 rows, sorted by name, paged 50 at a time, with two quick-filters that
// both mean "this record is incomplete" — it is the opposite of an affordance:
// the new row carries no name, so under the active sort it is not where the eye
// went; it trips both quick-filters the instant it exists; and every column it
// needs must be found and double-clicked one at a time. A record with an
// identity has to be BORN with that identity, not acquire one by inline repair.
//
// WHY IT IS GENERIC AND NOT AN "ADD COMPANY" FORM
//
// It takes the SAME `GridColumn[]` the grid is already rendering, so the fields,
// their Hebrew labels, which of them are editable, their `validate` functions
// and their order all come from one declaration that already existed. There is
// no second schema to keep in step — rename a column for the grid and this
// drawer renames it too. A page adds only what is genuinely its own: which keys
// are REQUIRED, and (optionally) a duplicate check against the rows it holds.
//
// THE MINIMAL PART. Columns the grid hides (`hidden`), plus any the page names
// in `advancedKeys`, sit behind one disclosure — so the default form is the four
// fields a person actually types, not every column the table has. Nothing is
// invented: emptiness is emptiness (a blank field is simply not sent), so a
// record created here is byte-identical to one created by typing into cells.
//
// ACCESSIBILITY, matching <ConfirmModal> exactly: Escape cancels · backdrop
// click cancels · focus moves to the first field on open and is RESTORED to the
// opener on close · Tab cycles inside the panel · `role="dialog"` with the title
// as its accessible name · each invalid field is `aria-invalid` and wired to its
// message by `aria-describedby`. RTL needs no special casing (document is rtl).
// ─────────────────────────────────────────────────────────────────────────────
import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { Ic, type GridColumn } from './DataGrid';
import { IC } from '../icons';

export interface NewRowDrawerProps {
  /** the grid's own columns — labels, order, `editable`, `validate` and `hidden`
   *  are all read from here, so there is no second field list to maintain */
  columns: GridColumn[];
  title: string;
  /** keys that must be non-empty before the record can be saved */
  requiredKeys?: string[];
  /** keys demoted to the disclosure even though the grid shows them. The default
   *  form should be what a person TYPES, and on `companies` that is four fields —
   *  the second id, the second mail and the aging-report prompt are real columns
   *  that are simply not part of creating a company. Nothing is lost: they are one
   *  click away here, and editable in the cell afterwards like everything else. */
  advancedKeys?: string[];
  /** short sentence under the title: what this record IS, in the operator's words */
  hint?: string;
  /** soft duplicate check against rows the page already holds. Returns a warning
   *  to SHOW, never a block — "this id already exists" is information, and the
   *  operator is the one who knows whether it is a mistake or a second branch. */
  duplicateWarning?: (seed: Record<string, string>) => string | null;
  /** save. Throws with a readable message on failure; the drawer stays open with
   *  everything typed still in it, because retyping a form is not error recovery. */
  onSubmit: (seed: Record<string, unknown>) => Promise<void>;
  onClose: () => void;
}

export function NewRowDrawer({
  columns,
  title,
  requiredKeys = [],
  advancedKeys = [],
  hint,
  duplicateWarning,
  onSubmit,
  onClose,
}: NewRowDrawerProps) {
  const uid = useId();
  const panelRef = useRef<HTMLDivElement | null>(null);
  const firstRef = useRef<HTMLInputElement | null>(null);
  const openerRef = useRef<Element | null>(null);

  const [values, setValues] = useState<Record<string, string>>({});
  const [touched, setTouched] = useState<Record<string, boolean>>({});
  const [more, setMore] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  /* the fields, straight off the grid's columns: real data columns only (the ✕
     action column has no `editable`), primary/generated ones excluded because
     the DB assigns them. Grid order is deliberate — it is the RTL reading order
     the operator already learned from the table. */
  const fields = useMemo(
    () => columns.filter((c) => c.editable && c.key !== '_del'),
    [columns],
  );
  const isAdvanced = useCallback(
    (c: GridColumn) => Boolean(c.hidden) || advancedKeys.includes(c.key),
    [advancedKeys],
  );
  const primary = useMemo(() => fields.filter((c) => !isAdvanced(c)), [fields, isAdvanced]);
  const advanced = useMemo(() => fields.filter(isAdvanced), [fields, isAdvanced]);

  const errorFor = useCallback(
    (c: GridColumn): string | null => {
      const raw = (values[c.key] ?? '').trim();
      if (raw === '') return requiredKeys.includes(c.key) ? 'שדה חובה' : null;
      return (c.validate ? c.validate(raw) : null) ?? null;
    },
    [values, requiredKeys],
  );

  const problems = useMemo(
    () => fields.map((c) => [c, errorFor(c)] as const).filter(([, e]) => e),
    [fields, errorFor],
  );
  const canSave = problems.length === 0 && !busy;

  const dupe = useMemo(
    () => (duplicateWarning ? duplicateWarning(values) : null),
    [duplicateWarning, values],
  );

  const submit = useCallback(async () => {
    // mark everything touched so a click on a disabled-looking form still SAYS why
    setTouched(Object.fromEntries(fields.map((c) => [c.key, true])));
    if (problems.length > 0) {
      panelRef.current
        ?.querySelector<HTMLInputElement>(`[data-key="${CSS.escape(problems[0][0].key)}"]`)
        ?.focus();
      return;
    }
    const seed: Record<string, unknown> = {};
    for (const c of fields) {
      const v = (values[c.key] ?? '').trim();
      if (v !== '') seed[c.key] = v; // empty is empty — never written as ''
    }
    setBusy(true);
    setErr(null);
    try {
      await onSubmit(seed);
      onClose();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [fields, problems, values, onSubmit, onClose]);

  // focus in on open, focus back to the opener on close
  useEffect(() => {
    openerRef.current = document.activeElement;
    firstRef.current?.focus();
    return () => {
      const opener = openerRef.current;
      if (opener instanceof HTMLElement && document.contains(opener)) opener.focus();
    };
  }, []);

  // Escape cancels · Tab cycles inside the panel
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onClose();
        return;
      }
      if (e.key !== 'Tab') return;
      const nodes = panelRef.current?.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input, textarea, select, [href], [tabindex]:not([tabindex="-1"])',
      );
      if (!nodes || nodes.length === 0) return;
      const first = nodes[0];
      const last = nodes[nodes.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', onKey, true);
    return () => document.removeEventListener('keydown', onKey, true);
  }, [onClose]);

  const renderField = (c: GridColumn, i: number) => {
    const bad = touched[c.key] ? errorFor(c) : null;
    const req = requiredKeys.includes(c.key);
    return (
      <div key={c.key} className="field">
        <label htmlFor={`${uid}-${c.key}`}>
          {c.header}
          {req && (
            <span aria-hidden style={{ marginInlineStart: 4, color: 'var(--red)' }}>*</span>
          )}
        </label>
        <input
          id={`${uid}-${c.key}`}
          data-key={c.key}
          ref={i === 0 && !isAdvanced(c) ? firstRef : undefined}
          type="text"
          dir="auto"
          value={values[c.key] ?? ''}
          required={req}
          aria-required={req || undefined}
          aria-invalid={bad ? true : undefined}
          aria-describedby={bad ? `${uid}-${c.key}-err` : undefined}
          onChange={(e) => setValues((s) => ({ ...s, [c.key]: e.target.value }))}
          onBlur={() => setTouched((s) => ({ ...s, [c.key]: true }))}
          /* Enter saves from anywhere in the form — this is a four-field record,
             and reaching for the mouse to commit it is the slow path. */
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              void submit();
            }
          }}
        />
        {bad && (
          <div id={`${uid}-${c.key}-err`} className="small" style={{ color: 'var(--red)' }}>
            {bad}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="drawer-ov">
      <div className="scrim" onClick={onClose} />
      <div
        className="drawer"
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${uid}-title`}
      >
        <div className="drawer-h">
          <h3 id={`${uid}-title`}>{title}</h3>
          <button
            type="button"
            onClick={onClose}
            className="icbtn"
            aria-label="סגור"
            title="סגירה בלי לשמור (Esc)"
          >
            <Ic p={IC.x} />
          </button>
        </div>
        <div className="drawer-body">
          {hint && (
            <p className="small muted" style={{ marginTop: 0 }}>
              {hint}
            </p>
          )}
          <div className="space-y-3">{primary.map(renderField)}</div>
          {advanced.length > 0 && (
            <>
              <button
                type="button"
                className="link small"
                aria-expanded={more}
                onClick={() => setMore((m) => !m)}
                style={{ marginTop: 12 }}
              >
                <Ic p={more ? IC.minus : IC.plus} /> {more ? 'פחות שדות' : `עוד שדות (${advanced.length})`}
              </button>
              {more && (
                <div className="space-y-3" style={{ marginTop: 10 }}>
                  {advanced.map(renderField)}
                </div>
              )}
            </>
          )}
        </div>
        <div className="drawer-foot">
          {dupe && <div className="callout warn">{dupe}</div>}
          {err && <div className="callout bad">{err}</div>}
          <button
            type="button"
            onClick={() => void submit()}
            disabled={!canSave}
            className="btn"
            style={{ width: '100%', justifyContent: 'center' }}
          >
            {busy ? 'שומר…' : 'הוסף'}
          </button>
        </div>
      </div>
    </div>
  );
}

export default NewRowDrawer;
