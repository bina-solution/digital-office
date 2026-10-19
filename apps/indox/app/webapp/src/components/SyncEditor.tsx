import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { api, SyncRegistryEntry } from '../api';
import { Ic } from './DataGrid';
import { IC } from '../icons';
import {
  Conn, ConnKind, Folder, IN_CONSOLE, SIBLINGS_NOTE, connections, driveCreateFolder, driveFolders,
  folderPath, folderParts, mailCreateLabel, mailLabels, organizerLabelMap,
} from '../siblings';

/**
 * THE SYNC EDITOR (RELEASE-DECISIONS N5) — additive and honest.
 *
 * What went wrong before, and what this file does about each:
 *   - a stored id absent from the sibling's list rendered as the PLACEHOLDER ("ללא — הקובץ נשאר
 *     במקומו" while a destination was configured)  → every picker PINS its stored value, in
 *     words: "— לא נמצא ברשימה", with the id beside it;
 *   - a failed sibling call degraded to a raw-id text box with no explanation → loading and error
 *     states, always the stored id and the connection it belongs to, and manual entry as an
 *     EXPLICIT choice behind a disclosure;
 *   - save rebuilt `pairs[0]` from the three fields it knew and destroyed `failed / failed_to /
 *     in_progress`, hardcoded `projection:'on'`, `engine`, `drive_profile_id:'admin'` → the payload
 *     is a DIFF: the existing pair / labels / batch are spread and only the keys the operator
 *     changed travel; engine/projection/processor/authority are never invented here;
 *   - "צור" overwrote an untouched field → it writes into the field that has FOCUS and says so;
 *   - `Select` was defined inside the component (remounted on every render, losing focus) and the
 *     page's 5 s poll remounted the drawer → `PinnedSelect` / `LocationPicker` are module-level,
 *     and the page freezes its poll while this drawer is open;
 *   - the failed folder / failed label and `schedule_min` were invisible → editable;
 *   - a NEW pipe was written on the first click → a review step lists every field that will be
 *     written, the derived ones included, before the create.
 */

export const DOC_TYPES = ['INVOICE', 'RECEIPT', 'ORDER', 'SHIPMENT', 'BANK_REPORT', 'BALANCE_SHEET'];
export const AUTHORITY_HE: Record<string, string> = { fallback: 'רק בכשל זיהוי', hint: 'רמז', decisive: 'החלטי' };
export const SRC_LABEL: Record<string, string> = { gmail: 'Gmail', drive: 'Drive' };
/** the scheduler's own cadence — a pipe's `schedule_min` cannot make it run more often */
export const SCHEDULER_MIN = 15;
/** D13: gmail take 25 / chunk 5 (one IMAP connection per mailbox); drive is wider */
const BATCH_DEFAULT: Record<ConnKind, { take: number; chunk: number }> = {
  drive: { take: 50, chunk: 25 },
  gmail: { take: 25, chunk: 5 },
};

type Pair = Record<string, unknown> & {
  from?: string; to_sync?: string; to?: string; synced?: string; failed_to?: string; failed?: string;
};

/* ── a sibling list, with its loading and error state ─────────────────────────────────────────── */
interface Listing<T> { items: T[]; loading: boolean; error: string | null }
const EMPTY_LISTING = { items: [], loading: false, error: null };

function useSiblingList<T>(key: string, load: (key: string, refresh: boolean) => Promise<T[]>) {
  const [state, setState] = useState<Listing<T>>(EMPTY_LISTING as Listing<T>);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!key) {
      setState(EMPTY_LISTING as Listing<T>);
      return;
    }
    let dead = false;
    setState((s) => ({ ...s, loading: true, error: null }));
    load(key, tick > 0)
      .then((items) => { if (!dead) setState({ items, loading: false, error: null }); })
      .catch((e: unknown) => {
        if (!dead) setState({ items: [], loading: false, error: e instanceof Error ? e.message : String(e) });
      });
    return () => { dead = true; };
  }, [key, tick, load]);
  const refresh = useCallback(() => setTick((t) => t + 1), []);
  return { ...state, refresh };
}

const loadFolders = (id: string, refresh: boolean) => driveFolders(id, refresh);
const loadLabels = (id: string, refresh: boolean) => mailLabels(id, refresh);

/* ── PinnedSelect: a <select> that never loses the stored value ────────────────────────────────── */
export function PinnedSelect({
  value, onChange, options, placeholder, loading, error, disabled, ariaLabel,
}: {
  value: string;
  onChange: (v: string) => void;
  options: { v: string; l: string; sub?: string }[];
  placeholder: string;
  loading?: boolean;
  error?: string | null;
  disabled?: boolean;
  ariaLabel?: string;
}) {
  const known = options.some((o) => o.v === value);
  const [manual, setManual] = useState(false);
  return (
    <div>
      <select value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled} aria-label={ariaLabel}>
        <option value="">{loading ? 'טוען רשימה…' : placeholder}</option>
        {value && !known && <option value={value}>{value} — לא נמצא ברשימה</option>}
        {options.map((o) => (
          <option key={o.v} value={o.v}>{o.l}{o.sub ? ` — ${o.sub}` : ''}</option>
        ))}
      </select>
      {error && (
        <div className="small" style={{ color: 'var(--red)', marginTop: 4 }}>
          הרשימה לא נקראה: {error}
        </div>
      )}
      {value && !known && !loading && (
        <div className="small" style={{ color: 'var(--amber)', marginTop: 4 }}>
          הערך השמור <span className="mono num">{value}</span> אינו ברשימה שנקראה — הוא יישאר כפי שהוא עד
          שתבחרו אחר.
        </div>
      )}
      {(error || !options.length) && !loading && (
        <details style={{ marginTop: 4 }} open={manual} onToggle={(e) => setManual((e.target as HTMLDetailsElement).open)}>
          <summary className="link small" style={{ cursor: 'pointer' }}>הזנת מזהה ידנית</summary>
          <input
            className="mono"
            value={value}
            onChange={(e) => onChange(e.target.value.trim())}
            placeholder={placeholder}
            aria-label={`${ariaLabel || placeholder} — הזנה ידנית`}
            style={{ marginTop: 4 }}
          />
        </details>
      )}
    </div>
  );
}

/* ── the location chooser: the folder's NAME first, its path second ───────────────────────────── */
/**
 * What this replaces, and why (measured on the live drawer at its 440px width):
 *
 *   1. every option was ONE span holding the joined path ("א/ב/ג") with `text-overflow:ellipsis`.
 *      CSS truncates the END, so the leaf — the only part that differs between two folders under
 *      the same parent — was the FIRST thing cut, and 580 rows all read "חשבוניות הכנסים/…".
 *      A row is now `.leaf` + `.crumb`, and the crumb carries `flex-shrink:100000`, so every
 *      missing pixel comes out of the ancestors and the folder's own name is the last to go.
 *   2. `.opt .id` was `max-width:40%` with `opacity:0` — invisible, yet still eating 140px of the
 *      342px a row had. The id is now absolutely positioned (`.idhov`), so it costs no width and
 *      still appears on hover, where an identifier belongs.
 *   3. the list was flat and alphabetical. Drive hands us `parent` already, so when the caller
 *      passes it the list is a COLLAPSIBLE TREE opened to the stored value. Typing switches to a
 *      flat search that separates "the NAME matches" from "it merely LIVES INSIDE a match" —
 *      without that split, "ספקים" answers with 433 rows that all read "2024".
 *
 * Mail labels carry no `parent` (Gmail nests them inside the name with "/"), so they render as a
 * flat list of the same leaf+crumb rows; `rank` still puts the organizer's labels first.
 */
export interface PickItem {
  id: string;
  /** the full path — still what the review rows show and what the pipe's name is slugged from */
  name: string;
  rank?: number;
  /** drive only: the real tree. Passing it turns the list into a tree. */
  parent?: string | null;
  /** the item's own name. Derived from `name` when absent (labels), which is why a drive caller
   *  passes it explicitly: a folder name may itself contain "/". */
  leaf?: string;
}

interface PickNode {
  id: string; leaf: string; crumb: string; path: string;
  parent: string | null; depth: number; kids: number; rank: number;
}

/** one model for both shapes: real parent links when the caller has them, the "/" inside the name
 *  when it does not. A label list simply comes out as a tree of depth 0 — i.e. a flat list. */
function buildNodes(items: PickItem[]) {
  const hasTree = items.some((i) => i.parent !== undefined);
  const ids = new Set(items.map((i) => i.id));
  const byId = new Map<string, PickNode>();
  for (const i of items) {
    const parts = i.name.split('/').filter(Boolean);
    const parent = hasTree && i.parent && ids.has(i.parent) ? i.parent : null;
    byId.set(i.id, {
      id: i.id,
      leaf: i.leaf ?? (parts.length ? parts[parts.length - 1] : i.name),
      /* nearest ancestor FIRST, so the ellipsis drops the far root and keeps the parent */
      crumb: hasTree ? '' : parts.slice(0, -1).reverse().join(' ‹ '),
      path: i.name,
      parent, depth: 0, kids: 0, rank: i.rank ?? 1,
    });
  }
  for (const n of byId.values()) {
    if (n.parent) { const p = byId.get(n.parent); if (p) p.kids++; }
    if (!hasTree) continue;
    const names: string[] = [];
    let p = n.parent ? byId.get(n.parent) : undefined;
    let guard = 0;
    while (p && guard++ < 12) { names.push(p.leaf); p = p.parent ? byId.get(p.parent) : undefined; }
    n.depth = names.length;
    n.crumb = names.join(' ‹ ');
  }
  const kids = new Map<string, PickNode[]>();
  for (const n of byId.values()) {
    const k = n.parent || '';
    if (!kids.has(k)) kids.set(k, []);
    (kids.get(k) as PickNode[]).push(n);
  }
  for (const arr of kids.values()) arr.sort((a, b) => a.rank - b.rank || a.leaf.localeCompare(b.leaf, 'he'));
  return { byId, kids };
}

const EMPTY_ITEMS: PickItem[] = [];

/** The item arrays are `useMemo`d by the editor, so keying the built tree off the array itself
 *  means 580 folders are walked once per list — not once per field per render. */
const nodeCache = new WeakMap<PickItem[], ReturnType<typeof buildNodes>>();
function nodesFor(items: PickItem[]) {
  let built = nodeCache.get(items);
  if (!built) { built = buildNodes(items); nodeCache.set(items, built); }
  return built;
}

/** the matched run, marked — so a search hit says WHY it is a hit */
function hi(text: string, q: string): ReactNode {
  if (!q) return text;
  const i = text.toLowerCase().indexOf(q);
  if (i < 0) return text;
  return <>{text.slice(0, i)}<mark>{text.slice(i, i + q.length)}</mark>{text.slice(i + q.length)}</>;
}

/** one destination the editor writes: a line in the group, and the picker when it is the armed one */
export interface LocField {
  k: Field;
  label: string;
  /** what this destination MEANS, in words — beside the picker's title, not in the row */
  sub: string;
  items: PickItem[];
  value: string;
  onChange: (v: string) => void;
  loading: boolean;
  error: string | null;
  /** the connection this list was read from — named above the group, always */
  connLabel: string | null;
  allowNone?: boolean;
  noneLabel?: string;
  hint?: ReactNode;
}

/**
 * The destinations were one <LocationPicker> each, every one rendering its own copy of the same
 * 580-row list in a 180px scrollbox — three nested scroll regions stacked inside a 440px drawer.
 * They are one-line fields now, and ONE picker serves whichever line is armed. `active` is the
 * editor's existing focus state, so "צור" still writes into the field last touched.
 */
export function LocationFields({ title, fields, active, onActive }: {
  title: string;
  fields: LocField[];
  active: Field;
  onActive: (k: Field) => void;
}) {
  const cur = fields.find((f) => f.k === active) || null;
  const [q, setQ] = useState('');
  const [deep, setDeep] = useState(false);
  const [cursor, setCursor] = useState(-1);
  const [manual, setManual] = useState(false);
  const [open, setOpen] = useState<Set<string>>(new Set());

  const items = cur ? cur.items : EMPTY_ITEMS;
  const { byId, kids } = nodesFor(items);
  const curValue = cur ? cur.value : '';

  /* land where you already are: the stored value's branch is the one that is open */
  useEffect(() => {
    setQ(''); setDeep(false); setCursor(-1);
    if (!curValue) { setOpen(new Set()); return; }
    const seed = new Set<string>();
    let n = byId.get(curValue);
    let guard = 0;
    while (n && n.parent && guard++ < 12) { seed.add(n.parent); n = byId.get(n.parent); }
    setOpen(seed);
  }, [active, curValue, byId]);

  const needle = q.trim().toLowerCase();
  const found = useMemo(() => {
    if (!needle) return null;
    const name: PickNode[] = [], inside: PickNode[] = [];
    for (const n of byId.values()) {
      if (n.leaf.toLowerCase().includes(needle) || n.id.toLowerCase() === needle) name.push(n);
      else if (n.path.toLowerCase().includes(needle) || n.crumb.toLowerCase().includes(needle)) inside.push(n);
    }
    const by = (a: PickNode, b: PickNode) => a.rank - b.rank || a.leaf.localeCompare(b.leaf, 'he');
    name.sort(by); inside.sort(by);
    return { name, inside };
  }, [byId, needle]);

  /* the rows actually on screen, in order — what ↑/↓ walks and what Enter picks */
  const shown = useMemo<PickNode[]>(() => {
    if (found) return deep ? [...found.name, ...found.inside] : found.name;
    const out: PickNode[] = [];
    const walk = (parent: string) => {
      for (const n of (kids.get(parent) || [])) {
        out.push(n);
        if (n.kids && open.has(n.id)) walk(n.id);
      }
    };
    walk('');
    return out;
  }, [found, deep, kids, open]);

  if (!fields.length) return null;
  const connLabel = cur ? cur.connLabel : fields[0].connLabel;
  const total = items.length;
  const node = curValue ? byId.get(curValue) : undefined;
  const pinned = Boolean(curValue) && !node && Boolean(cur && !cur.loading);

  const pick = (v: string) => { if (cur) { cur.onChange(v); setCursor(-1); } };
  const toggle = (id: string) => setOpen((s) => {
    const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n;
  });

  /* the row is a DIV holding two real buttons: the chevron opens the branch, the rest picks it.
     (A clickable span inside a <button> is invalid markup and unreachable from the keyboard.) */
  const row = (n: PickNode, i: number) => {
    const on = n.id === curValue;
    return (
      <div key={n.id} className={`optrow${on ? ' on' : ''}${i === cursor ? ' cursor' : ''}`}>
        {!found && n.depth > 0 && (
          <span className="tw" aria-hidden="true">
            {Array.from({ length: n.depth }, (_, d) => <i key={d} />)}
          </span>
        )}
        {!found && (n.kids ? (
          <button
            type="button"
            className={`chev${open.has(n.id) ? '' : ' closed'}`}
            title={open.has(n.id) ? 'סגירת הענף' : `פתיחת הענף (${n.kids})`}
            aria-expanded={open.has(n.id)}
            aria-label={`${open.has(n.id) ? 'סגירת' : 'פתיחת'} ${n.leaf}`}
            onClick={() => toggle(n.id)}
          >
            <Ic p={IC.chevronDown} />
          </button>
        ) : (
          <span className="chev leafnode" aria-hidden="true"><Ic p={IC.chevronDown} /></span>
        ))}
        <button
          type="button"
          className="opt"
          role="option"
          aria-selected={on}
          title={n.path && n.path !== n.leaf ? `${n.leaf} · ${n.path}` : n.leaf}
          onClick={() => pick(n.id)}
          onFocus={() => cur && onActive(cur.k)}
        >
          <Ic p={IC.folder} />
          <span className="leaf">{hi(n.leaf, needle)}</span>
          {n.crumb && <span className="crumb">{n.crumb}</span>}
          {!found && n.kids > 0 && <span className="cnt">{n.kids}</span>}
          {on && <Ic p={IC.check} />}
          <span className="idhov">{n.id}</span>
        </button>
      </div>
    );
  };

  return (
    <div>
      <div className="pickhead">
        <span style={{ color: 'var(--ink)', fontWeight: 600 }}>{title}</span>
        <span title="הרשימה נקראת מהחיבור הזה, בדפדפן">
          {connLabel ? <>מתוך <b>{connLabel}</b>{total ? ` · ${total} פריטים` : ''}</> : 'בחרו חיבור תחילה'}
        </span>
      </div>

      <div className="fieldrows">
        {fields.map((f) => {
          const fn = f.value ? nodesFor(f.items).byId.get(f.value) : undefined;
          return (
            <button
              key={f.k}
              type="button"
              className={`fieldrow${active === f.k ? ' on' : ''}`}
              onClick={() => onActive(f.k)}
              title={`${f.label} — ${f.sub}. לחיצה מכוונת את הבורר לשדה הזה.`}
            >
              <span className="fk">{f.label}</span>
              <span className="fv">
                {f.value ? (
                  <>
                    <span className="leaf">{fn ? fn.leaf : f.value}</span>
                    {fn && fn.crumb && <span className="crumb">{fn.crumb}</span>}
                    {!fn && !f.loading && <span className="pin">— לא נמצא ברשימה</span>}
                  </>
                ) : (
                  <span className="none">{f.noneLabel || 'לא נבחר'}</span>
                )}
              </span>
              <Ic p={IC.chevronDown} />
            </button>
          );
        })}
      </div>

      {cur && (
        <div className="picker">
          <div className="ptop">
            <Ic p={IC.folder} />
            <span>בחירת {cur.label}</span>
            <span className="sp" />
            <span style={{ fontWeight: 400 }}>{cur.sub}</span>
          </div>

          <div className="cur" title={node ? node.path : curValue || undefined}>
            {curValue ? (
              <>
                <div className="l1">
                  <Ic p={IC.folder} />
                  <span className="nm">{node ? node.leaf : curValue}</span>
                  {pinned && <span className="pin">— לא נמצא ברשימה</span>}
                  {cur.loading && !node && <span className="muted small">בודק…</span>}
                </div>
                {/* only when there IS a path: a drive folder at the root and a flat mail label
                    both have no ancestors, and "בשורש" is meaningless for the label */}
                {node && node.crumb && <div className="l2">{node.crumb}</div>}
                <span className="idhov">{curValue}</span>
              </>
            ) : (
              <div className="l1"><span className="muted">{cur.allowNone ? cur.noneLabel || 'ללא' : 'לא נבחר'}</span></div>
            )}
          </div>

          <div className="srch">
            <Ic p={IC.search} />
            <input
              className="q"
              value={q}
              onChange={(e) => { setQ(e.target.value); setDeep(false); setCursor(e.target.value.trim() ? 0 : -1); }}
              onFocus={() => onActive(cur.k)}
              onKeyDown={(e) => {
                if (e.key === 'ArrowDown') { e.preventDefault(); setCursor((c) => Math.min(shown.length - 1, c + 1)); }
                else if (e.key === 'ArrowUp') { e.preventDefault(); setCursor((c) => Math.max(0, c - 1)); }
                else if (e.key === 'Enter') { e.preventDefault(); if (shown[cursor]) pick(shown[cursor].id); }
                else if (e.key === 'Escape' && q) { e.preventDefault(); e.stopPropagation(); setQ(''); setCursor(-1); }
              }}
              placeholder={cur.loading ? 'טוען רשימה…' : total ? 'חיפוש לפי שם או נתיב…' : 'אין פריטים ברשימה'}
              aria-label={`חיפוש · ${cur.label}`}
              disabled={!connLabel}
            />
            {q && (
              <button type="button" className="icbtn" title="ניקוי החיפוש" aria-label="ניקוי החיפוש"
                      style={{ width: 22, height: 22 }} onClick={() => { setQ(''); setCursor(-1); }}>
                <Ic p={IC.x} />
              </button>
            )}
          </div>

          {cur.error ? (
            <div className="state bad">הרשימה לא נקראה: {cur.error}</div>
          ) : !IN_CONSOLE ? (
            <div className="state">{SIBLINGS_NOTE}</div>
          ) : cur.loading && !total ? (
            <div className="state">טוען רשימה…</div>
          ) : !connLabel ? (
            <div className="state">בחרו חיבור כדי לראות את הרשימה.</div>
          ) : (
            <div className="list" role="listbox" aria-label={cur.label}>
              {cur.allowNone && !found && (
                <div className={`optrow${!curValue ? ' on' : ''}`}>
                  <button type="button" className="opt" role="option" aria-selected={!curValue}
                          onClick={() => pick('')} onFocus={() => onActive(cur.k)}>
                    <Ic p={IC.x} />
                    <span className="leaf muted">{cur.noneLabel || 'ללא'}</span>
                  </button>
                </div>
              )}
              {found ? (
                <>
                  {found.name.length > 0 && <div className="grp">השם מכיל «{q.trim()}» · {found.name.length}</div>}
                  {found.name.map((n, i) => row(n, i))}
                  {deep && found.inside.length > 0 && (
                    <div className="grp">נמצאות בתוך פריט מתאים · {found.inside.length}</div>
                  )}
                  {deep && found.inside.map((n, i) => row(n, found.name.length + i))}
                  {!found.name.length && !deep && (
                    <div className="state">
                      אין פריט ששמו מכיל «{q.trim()}».{' '}
                      {found.inside.length > 0
                        ? <button className="link" onClick={() => setDeep(true)}>
                            יש {found.inside.length} בתוך פריט כזה — להציג?
                          </button>
                        : 'אפשר ליצור אחד למטה.'}
                    </div>
                  )}
                </>
              ) : shown.length ? (
                shown.map((n, i) => row(n, i))
              ) : (
                <div className="state">הרשימה ריקה — אפשר ליצור למטה.</div>
              )}
            </div>
          )}

          <div className="pfoot">
            {found ? (
              <span>
                {found.name.length} לפי שם
                {found.inside.length > 0 && (
                  <>
                    {' · '}
                    <button className="link" onClick={() => setDeep((d) => !d)}
                            title={deep ? 'הסתרת פריטים שרק יושבים בתוך התאמה' : 'הצגת פריטים שרק יושבים בתוך התאמה'}>
                      {deep ? `הסתרת ${found.inside.length} שבתוכן` : `+${found.inside.length} שבתוכן`}
                    </button>
                  </>
                )}
              </span>
            ) : (
              <span>{total} פריטים</span>
            )}
            <span className="sp" />
            <span className="kbd">↑</span><span className="kbd">↓</span><span className="kbd">Enter</span>
            <span>מזהה — בריחוף</span>
          </div>
        </div>
      )}

      {cur && cur.hint && <div className="muted small" style={{ marginTop: 4 }}>{cur.hint}</div>}

      {cur && (cur.error || !IN_CONSOLE) && (
        <details style={{ marginTop: 4 }} open={manual} onToggle={(e) => setManual((e.target as HTMLDetailsElement).open)}>
          <summary className="link small" style={{ cursor: 'pointer' }}>הזנת מזהה ידנית</summary>
          <input
            className="mono"
            value={cur.value}
            onChange={(e) => cur.onChange(e.target.value.trim())}
            onFocus={() => onActive(cur.k)}
            placeholder="מזהה"
            aria-label={`${cur.label} — הזנה ידנית`}
            style={{ marginTop: 4 }}
          />
        </details>
      )}
    </div>
  );
}

/* ── the review rows: every field that will be written, derived ones marked ──────────────────── */
export interface ReviewRow { k: string; v: ReactNode; derived?: boolean }

const slug = (v: string) =>
  String(v || '').trim().replace(/[/]+/g, '-').replace(/[^\p{L}\p{N}]+/gu, '-').replace(/^-+|-+$/g, '').toLowerCase();

type Field = 'src' | 'dst' | 'failed';
const FIELD_HE: Record<Field, string> = { src: 'המקור', dst: 'היעד', failed: 'הכשלים' };

export default function SyncEditor({ existing, takenNames, onClose, onSaved }: {
  existing: SyncRegistryEntry | null;
  takenNames: string[];
  onClose: () => void;
  /** called with a one-line summary of what was written */
  onSaved: (summary: string) => void;
}) {
  const isNew = !existing;
  const kind0 = (existing?.source as ConnKind) || 'drive';
  const [kind, setKind] = useState<ConnKind>(kind0);
  const pairs = useMemo(() => ((existing?.pairs || []) as Pair[]).filter((p) => p && typeof p === 'object'), [existing]);
  const p0: Pair = pairs[0] || {};
  const labels0 = existing?.labels || {};

  /* the ORIGINAL values — the diff below is taken against these, never against what the
     sibling lists happen to contain */
  const orig = useMemo(() => ({
    connId: String(existing?.connection || ''),
    driveConnId: String(existing?.drive_connection_id || ''),
    src: kind0 === 'gmail' ? String(labels0.to_sync || '') : String(p0.to_sync || p0.from || ''),
    dst: kind0 === 'gmail' ? String(existing?.dest_folder || '') : String(p0.synced || p0.to || ''),
    failed: kind0 === 'gmail' ? String(labels0.failed || '') : String(p0.failed || p0.failed_to || ''),
    name: existing?.name || '',
    typeHint: String(existing?.type_hint || ''),
    typeAuthority: String(existing?.type_authority || 'hint'),
    take: existing?.batch?.take ?? BATCH_DEFAULT[kind0].take,
    chunk: existing?.batch?.chunk ?? BATCH_DEFAULT[kind0].chunk,
    scheduleMin: existing?.batch?.schedule_min ?? SCHEDULER_MIN,
  }), [existing, kind0, p0, labels0]);

  const [connId, setConnId] = useState(orig.connId);
  const [driveConnId, setDriveConnId] = useState(orig.driveConnId);
  const [src, setSrc] = useState(orig.src);
  const [dst, setDst] = useState(orig.dst);
  const [failed, setFailed] = useState(orig.failed);
  const [name, setName] = useState(orig.name);
  const [typeHint, setTypeHint] = useState(orig.typeHint);
  const [typeAuthority, setTypeAuthority] = useState(orig.typeAuthority);
  const [take, setTake] = useState<number>(orig.take);
  const [chunk, setChunk] = useState<number>(orig.chunk);
  const [scheduleMin, setScheduleMin] = useState<number>(orig.scheduleMin);
  const [focus, setFocus] = useState<Field>('src');
  const [newLoc, setNewLoc] = useState('');
  const [creating, setCreating] = useState(false);
  const [review, setReview] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  /* connections of both siblings — one read, cached per session */
  const [conns, setConns] = useState<Conn[]>([]);
  const [connsLoading, setConnsLoading] = useState(true);
  const [connsErr, setConnsErr] = useState<string | null>(null);
  useEffect(() => {
    let dead = false;
    if (!IN_CONSOLE) { setConnsLoading(false); setConnsErr(SIBLINGS_NOTE); return; }
    connections()
      .then((r) => { if (!dead) { setConns(r.conns); setConnsErr(r.errors.length ? r.errors.join(' · ') : null); } })
      .catch((e: unknown) => { if (!dead) setConnsErr(e instanceof Error ? e.message : String(e)); })
      .finally(() => { if (!dead) setConnsLoading(false); });
    return () => { dead = true; };
  }, []);
  const connById = useMemo(() => new Map(conns.map((c) => [c.id, c])), [conns]);
  const sourceConns = useMemo(() => conns.filter((c) => c.kind === kind), [conns, kind]);
  const driveConns = useMemo(() => conns.filter((c) => c.kind === 'drive'), [conns]);
  const connLabel = (id: string) => (id ? connById.get(id)?.label || id : null);

  /* the lists behind the pickers */
  const folders = useSiblingList<Folder>(kind === 'drive' ? connId : '', loadFolders);
  const labels = useSiblingList<string>(kind === 'gmail' ? connId : '', loadLabels);
  const destFolders = useSiblingList<Folder>(kind === 'gmail' ? driveConnId : '', loadFolders);

  const folderById = useMemo(() => new Map(folders.items.map((f) => [f.id, f])), [folders.items]);
  const destById = useMemo(() => new Map(destFolders.items.map((f) => [f.id, f])), [destFolders.items]);
  /* `parent` + `leaf` are what turn the list into a TREE: the picker walks the real Drive links
     rather than splitting the joined path, so a folder whose own name contains "/" still sits in
     the right place. `name` stays the full path — the review rows and the pipe's name read it. */
  const folderItems = useMemo<PickItem[]>(
    () => folders.items.map((f) => ({
      id: f.id, name: folderPath(folderById, f.id) || f.name, leaf: f.name, parent: f.parent ?? null,
    })),
    [folders.items, folderById],
  );
  const destItems = useMemo<PickItem[]>(
    () => destFolders.items.map((f) => ({
      id: f.id, name: folderPath(destById, f.id) || f.name, leaf: f.name, parent: f.parent ?? null,
    })),
    [destFolders.items, destById],
  );
  /* The registry stores organizer KEYS (DOC_TO_SYNC…) and the engine resolves them to the NAMES
     the mailbox carries. The picker therefore offers every organizer key by its NAME (the key as
     the stored value), then every mailbox label the store does not name (stored literally —
     the engine uses an unknown key literally too). Read once per editor. */
  const [labelMap, setLabelMap] = useState<Map<string, string>>(new Map());
  useEffect(() => {
    let dead = false;
    organizerLabelMap().then((m) => { if (!dead) setLabelMap(m); }).catch(() => { if (!dead) setLabelMap(new Map()); });
    return () => { dead = true; };
  }, []);
  const labelItems = useMemo<PickItem[]>(() => {
    const named = new Set(labelMap.values());
    const fromStore: PickItem[] = [...labelMap.entries()].map(([key, name]) => ({ id: key, name, rank: 0 }));
    /* a mailbox's SYSTEM folders ([Gmail]/…, INBOX) are not labels a pipe syncs from or files to */
    const system = (l: string) => /^\[Gmail\]/i.test(l) || /^-?INBOX$/i.test(l);
    const literal: PickItem[] = labels.items.filter((l) => !named.has(l) && !system(l)).map((l) => ({ id: l, name: l, rank: 1 }));
    return [...fromStore, ...literal];
  }, [labels.items, labelMap]);

  /* the name the pipe will carry */
  const uniqueName = (base: string) => {
    const taken = new Set(takenNames.filter((n) => n !== existing?.name));
    if (!taken.has(base)) return base;
    for (let i = 2; i < 100; i++) if (!taken.has(`${base}-${i}`)) return `${base}-${i}`;
    return base;
  };
  const srcName = kind === 'drive' ? folderPath(folderById, src) || src : src;
  const finalName = (name.trim() || uniqueName(`${kind}-${slug(srcName) || 'sync'}`)).trim();
  const nameTaken = takenNames.some((n) => n === finalName && n !== existing?.name);

  /* "צור" — into the FOCUSED field, and it says which */
  async function createLocation() {
    const v = newLoc.trim();
    if (!v) return;
    setErr(null);
    setCreating(true);
    try {
      if (kind === 'gmail' && focus !== 'dst') {
        if (!connId) throw new Error('בחרו חיבור מייל תחילה');
        await mailCreateLabel(connId, v);
        labels.refresh();
        if (focus === 'src') setSrc(v); else setFailed(v);
      } else if (kind === 'gmail') {
        if (!driveConnId) throw new Error('בחרו דרייב לשמירת הקבצים תחילה');
        const f = await driveCreateFolder(driveConnId, v);
        destFolders.refresh();
        setDst(f.id);
      } else {
        if (!connId) throw new Error('בחרו חיבור דרייב תחילה');
        const f = await driveCreateFolder(connId, v);
        folders.refresh();
        if (focus === 'src') setSrc(f.id); else if (focus === 'dst') setDst(f.id); else setFailed(f.id);
      }
      setNewLoc('');
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setCreating(false);
    }
  }

  /* the gmail destination that will be CREATED when none is chosen: INDOX/<name> on the drive */
  const destWillBeCreated = kind === 'gmail' && !dst && Boolean(driveConnId) && IN_CONSOLE;
  async function ensureDest(): Promise<string> {
    if (dst) return dst;
    if (!destWillBeCreated) return '';
    const all = await driveFolders(driveConnId, true);
    const root = all.find((f) => !f.parent && f.name === 'INDOX') || (await driveCreateFolder(driveConnId, 'INDOX'));
    const refreshed = await driveFolders(driveConnId, true);
    const leaf = refreshed.find((f) => f.parent === root.id && f.name === finalName)
      || (await driveCreateFolder(driveConnId, finalName, root.id));
    return leaf.id;
  }

  /* ── THE DIFF: what will be written, and only that ─────────────────────────────────────────── */
  const changes = useMemo(() => {
    const rows: ReviewRow[] = [];
    const payload: Record<string, unknown> = {};
    /* the folder's own name first, its ancestors after — the review row truncated the joined path
       at its END too, which cut exactly the name the operator is checking */
    const nm = (id: string, map: Map<string, Folder>): ReactNode => {
      /* same split, same owner as the sync cards — never the joined path in one clamped line */
      const { leaf, crumb } = folderParts(map, id);
      if (!leaf) return <span className="leaf mono">{id}</span>;
      return <><span className="leaf">{leaf}</span>{crumb && <span className="crumb">{crumb}</span>}</>;
    };

    if (isNew) {
      payload.name = finalName;
      payload.source = kind;
      rows.push({ k: 'שם המקור', v: <span className="mono">{finalName}</span>, derived: !name.trim() });
      rows.push({ k: 'סוג מקור', v: SRC_LABEL[kind] });
    } else if (finalName !== orig.name) {
      payload.name = finalName;
      rows.push({ k: 'שם המקור', v: <><span className="mono">{orig.name}</span> <Ic p={IC.arrowLeft} /> <span className="mono">{finalName}</span></> });
    }
    if (isNew || connId !== orig.connId) {
      payload.connection = connId;
      rows.push({ k: 'חיבור', v: connLabel(connId) || '—' });
    }
    if (kind === 'drive') {
      const pair: Pair = { ...p0 };
      let touched = false;
      if (isNew || src !== orig.src) { pair.from = src; pair.to_sync = src; touched = true; rows.push({ k: 'תיקיית מקור', v: nm(src, folderById) }); }
      if (isNew ? Boolean(dst) : dst !== orig.dst) {
        touched = true;
        if (dst) { pair.to = dst; pair.synced = dst; } else { delete pair.to; delete pair.synced; }
        rows.push({ k: 'תיקיית יעד אחרי סנכרון', v: dst ? nm(dst, folderById) : 'ללא — הקובץ נשאר במקומו' });
      }
      if (isNew ? Boolean(failed) : failed !== orig.failed) {
        touched = true;
        if (failed) { pair.failed = failed; pair.failed_to = failed; } else { delete pair.failed; delete pair.failed_to; }
        rows.push({ k: 'תיקיית כשלים', v: failed ? nm(failed, folderById) : 'ללא' });
      }
      if (touched) payload.pairs = [pair, ...pairs.slice(1)];
    } else {
      const lab: Record<string, string> = { ...labels0 };
      let touched = false;
      if (isNew || src !== orig.src) { lab.to_sync = src; touched = true; rows.push({ k: 'תווית מקור', v: src }); }
      if (isNew ? Boolean(failed) : failed !== orig.failed) {
        touched = true;
        if (failed) lab.failed = failed; else delete lab.failed;
        rows.push({ k: 'תווית כשל', v: failed || 'ללא' });
      }
      if (touched) payload.labels = lab;
      if (isNew || driveConnId !== orig.driveConnId) {
        payload.drive_connection_id = driveConnId || null;
        rows.push({ k: 'דרייב לקבצים המצורפים', v: connLabel(driveConnId) || '—' });
      }
      if (isNew ? true : dst !== orig.dst) {
        if (dst) { payload.dest_folder = dst; rows.push({ k: 'תיקיית יעד', v: nm(dst, destById) }); }
        else if (destWillBeCreated) rows.push({ k: 'תיקיית יעד', v: <>תיווצר <span className="mono">INDOX/{finalName}</span> על הדרייב שנבחר</>, derived: true });
        else if (!isNew) { payload.dest_folder = null; rows.push({ k: 'תיקיית יעד', v: 'ללא' }); }
      }
    }
    if (isNew ? Boolean(typeHint) : typeHint !== orig.typeHint) {
      payload.type_hint = typeHint || null;
      payload.fallback_type = typeHint || null;
      rows.push({ k: 'סוג מסמך צפוי', v: typeHint || 'לא ידוע' });
      if (!typeHint) { payload.type_authority = null; }
    }
    if (typeHint && (isNew || typeAuthority !== orig.typeAuthority || typeHint !== orig.typeHint)) {
      payload.type_authority = typeAuthority;
      rows.push({ k: 'משקל הסוג בזיהוי', v: AUTHORITY_HE[typeAuthority] || typeAuthority });
    }
    const batch: Record<string, number> = {};
    if (isNew || take !== orig.take) batch.take = take;
    if (isNew || chunk !== orig.chunk) batch.chunk = chunk;
    if (isNew || scheduleMin !== orig.scheduleMin) batch.schedule_min = scheduleMin;
    if (Object.keys(batch).length) {
      payload.batch = batch;
      if ('take' in batch) rows.push({ k: 'פריטים לסבב', v: String(take) });
      if ('chunk' in batch) rows.push({ k: 'גודל נגלה', v: String(chunk) });
      if ('schedule_min' in batch) rows.push({ k: 'תדירות (דק׳)', v: String(scheduleMin) });
    }
    if (isNew) {
      rows.push({ k: 'מנוע · הקרנה · פעיל', v: 'v3 · on · פעיל — ברירות המחדל של השרת', derived: true });
    }
    return { payload, rows };
  }, [isNew, finalName, orig, kind, connId, src, dst, failed, typeHint, typeAuthority, take, chunk, scheduleMin,
      p0, pairs, labels0, driveConnId, destWillBeCreated, folderById, destById, name, connById]);

  const validate = (): string | null => {
    if (!connId) return 'בחרו חיבור';
    if (!src) return kind === 'gmail' ? 'בחרו תווית מקור' : 'בחרו תיקיית מקור';
    if (nameTaken) return `כבר קיים מקור בשם '${finalName}'`;
    if (!Number.isInteger(take) || take < 1 || take > 500) return 'פריטים לסבב: מספר שלם בין 1 ל-500';
    if (!Number.isInteger(chunk) || chunk < 1 || chunk > 500) return 'גודל נגלה: מספר שלם בין 1 ל-500';
    if (!Number.isInteger(scheduleMin) || scheduleMin < SCHEDULER_MIN || scheduleMin > 1440)
      return `תדירות: מספר שלם בין ${SCHEDULER_MIN} ל-1440 דקות`;
    return null;
  };

  async function save() {
    setErr(null);
    const bad = validate();
    if (bad) { setErr(bad); setReview(false); return; }
    if (isNew && !review) { setReview(true); return; }
    if (!isNew && !changes.rows.length) { setErr('לא שונה דבר — אין מה לשמור.'); return; }
    setBusy(true);
    try {
      const payload = { ...changes.payload };
      if (kind === 'gmail' && (isNew || dst !== orig.dst) && !dst && destWillBeCreated) {
        const created = await ensureDest();
        if (created) payload.dest_folder = created;
      }
      const r = isNew
        ? await api.createSyncEntry(payload)
        : await api.patchSyncEntry(existing!.name, payload);
      if (r && r.success === false) {
        setErr('השמירה לא הושלמה — מסד הנתונים אינו זמין כרגע.');
        return;
      }
      const what = changes.rows.map((x) => x.k).join(' · ');
      onSaved(isNew ? `המקור '${finalName}' נוצר (${what})` : `'${finalName}' נשמר: ${what}`);
      onClose();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
      setReview(false);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape' && !busy) onClose(); };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [onClose, busy]);

  const connOpts = sourceConns.map((c) => ({ v: c.id, l: c.label, sub: c.identity }));
  const driveOpts = driveConns.map((c) => ({ v: c.id, l: c.label, sub: c.identity }));
  const createTarget = kind === 'gmail' && focus === 'dst' ? 'תיקייה' : kind === 'gmail' ? 'תווית' : 'תיקייה';

  return (
    <div className="drawer-ov">
      <div className="scrim" onClick={() => { if (!busy) onClose(); }} />
      <div className="drawer sync-drawer" role="dialog" aria-modal="true" aria-label={isNew ? 'מקור סנכרון חדש' : `עריכת מקור ${existing?.name}`}>
        <div className="drawer-h">
          <h3>{isNew ? 'מקור סנכרון חדש' : <>עריכת מקור · <span className="mono">{existing?.name}</span></>}</h3>
          <button onClick={onClose} className="icbtn" aria-label="סגירה" title="סגירה בלי לשמור (Esc)" disabled={busy}>
            <Ic p={IC.x} />
          </button>
        </div>

        {review ? (
          <div className="drawer-body space-y-3">
            <div className="callout" style={{ marginTop: 0 }}>
              <b>סקירה לפני היצירה.</b> אלה השדות שייכתבו לרשם הסנכרון. שורות בכחול נגזרות
              ממה שבחרתם (או מברירות המחדל של השרת) ולא הוקלדו ישירות.
            </div>
            <div className="review">
              {changes.rows.map((r, i) => (
                <div key={i} className={`row${r.derived ? ' derived' : ''}`}>
                  <span className="k">{r.k}</span>
                  <span className="v">{r.v}</span>
                </div>
              ))}
            </div>
            <div className="muted small">
              הסבב האוטומטי רץ כל {SCHEDULER_MIN} דק׳; המקור החדש ייכנס לסבב הבא. אפשר להריץ אותו
              מיד מהכרטיס אחרי היצירה.
            </div>
            {err && <div className="callout bad">{err}</div>}
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button className="btn ghost" onClick={() => setReview(false)} disabled={busy}>חזרה לעריכה</button>
              <button className="btn" onClick={save} disabled={busy} title="כותב את השדות שלמעלה לרשם הסנכרון">
                {busy ? <><span className="spinner" /> יוצר…</> : 'צור את המקור'}
              </button>
            </div>
          </div>
        ) : (
          <div className="drawer-body space-y-3">
            {!IN_CONSOLE && <div className="callout warn" style={{ marginTop: 0 }}>{SIBLINGS_NOTE} השדות מקבלים מזהים ידנית.</div>}
            {connsErr && IN_CONSOLE && <div className="callout warn" style={{ marginTop: 0 }}>חלק מרשימת החיבורים לא נקרא: {connsErr}</div>}

            {isNew && (
              <label>סוג מקור
                <select value={kind} onChange={(e) => {
                  const k = e.target.value as ConnKind;
                  setKind(k); setConnId(''); setSrc(''); setDst(''); setFailed('');
                  setTake(BATCH_DEFAULT[k].take); setChunk(BATCH_DEFAULT[k].chunk);
                }}>
                  <option value="drive">Drive — תיקייה</option>
                  <option value="gmail">Gmail — תווית</option>
                </select>
              </label>
            )}

            <label>חיבור ({SRC_LABEL[kind]})
              <PinnedSelect
                value={connId}
                onChange={(v) => { setConnId(v); setSrc(''); setFailed(''); if (kind === 'drive') setDst(''); }}
                options={connOpts}
                placeholder={connsLoading ? 'טוען חיבורים…' : `בחרו חיבור ${SRC_LABEL[kind]}`}
                loading={connsLoading}
                error={IN_CONSOLE ? null : SIBLINGS_NOTE}
                ariaLabel="חיבור"
              />
            </label>

            {kind === 'drive' ? (
              <LocationFields
                title="תיקיות הסנכרון" active={focus} onActive={setFocus}
                fields={[
                  {
                    k: 'src', label: 'תיקיית מקור', sub: 'מה לסנכרן',
                    items: folderItems, value: src, onChange: setSrc,
                    loading: folders.loading, error: folders.error, connLabel: connLabel(connId),
                  },
                  {
                    k: 'dst', label: 'יעד אחרי סנכרון', sub: 'לאן הקובץ עובר אחרי שנמסר',
                    items: folderItems, value: dst, onChange: setDst,
                    loading: folders.loading, error: folders.error, connLabel: connLabel(connId),
                    allowNone: true, noneLabel: 'ללא — הקובץ נשאר במקומו',
                  },
                  {
                    k: 'failed', label: 'תיקיית כשלים', sub: 'לאן נופל מה שלא נמסר',
                    items: folderItems, value: failed, onChange: setFailed,
                    loading: folders.loading, error: folders.error, connLabel: connLabel(connId),
                    allowNone: true, noneLabel: 'ללא — קובץ שנכשל נשאר במקומו',
                    hint: 'לכאן המנוע מעביר קובץ שלא הצליח למסור — התיקייה שפותחים כשמשהו לא בסדר.',
                  },
                ]}
              />
            ) : (
              <>
                <LocationFields
                  title="תוויות התיבה" active={focus} onActive={setFocus}
                  fields={[
                    {
                      k: 'src', label: 'תווית מקור', sub: 'מה לסנכרן',
                      items: labelItems, value: src, onChange: setSrc,
                      loading: labels.loading, error: labels.error, connLabel: connLabel(connId),
                    },
                    {
                      k: 'failed', label: 'תווית כשל', sub: 'מה מסומן כשלא נמסר',
                      items: labelItems, value: failed, onChange: setFailed,
                      loading: labels.loading, error: labels.error, connLabel: connLabel(connId),
                      allowNone: true, noneLabel: 'ללא — הודעה שנכשלה לא מסומנת',
                      hint: 'התווית שהמנוע מצמיד להודעה שלא הצליח למסור.',
                    },
                  ]}
                />
                <label>דרייב לשמירת הקבצים המצורפים
                  <PinnedSelect
                    value={driveConnId} onChange={(v) => { setDriveConnId(v); setDst(''); }} options={driveOpts}
                    placeholder={connsLoading ? 'טוען חיבורים…' : 'בחרו חיבור דרייב'} loading={connsLoading}
                    error={IN_CONSOLE ? null : SIBLINGS_NOTE} ariaLabel="דרייב לקבצים המצורפים"
                  />
                </label>
                {/* its own group: this list comes off a DIFFERENT connection than the labels above,
                    so it cannot share their picker. Two panels for mail, one for drive — down from
                    three lists each rendering the same rows. */}
                <LocationFields
                  title="תיקיית הקבצים המצורפים" active={focus} onActive={setFocus}
                  fields={[
                    {
                      k: 'dst', label: 'תיקיית יעד', sub: 'לאן נשמרים הקבצים',
                      items: destItems, value: dst, onChange: setDst,
                      loading: destFolders.loading, error: destFolders.error, connLabel: connLabel(driveConnId),
                      allowNone: true,
                      noneLabel: destWillBeCreated ? `אוטומטי — תיווצר INDOX/${finalName}` : 'לא נבחרה',
                    },
                  ]}
                />
              </>
            )}

            {IN_CONSOLE && (
              <div>
                <div className="muted small" style={{ marginBottom: 4 }}>
                  יצירת {createTarget} חדש/ה — תיכתב לשדה <b>{FIELD_HE[focus]}</b> (השדה שבחרתם אחרון).
                </div>
                <div style={{ display: 'flex', gap: 6 }}>
                  <input value={newLoc} onChange={(e) => setNewLoc(e.target.value)}
                         placeholder={createTarget === 'תווית' ? 'שם תווית חדשה…' : 'שם תיקייה חדשה…'}
                         aria-label={`שם ${createTarget} חדש/ה`} style={{ flex: 1 }}
                         onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); void createLocation(); } }} />
                  <button className="btn" onClick={createLocation} disabled={!newLoc.trim() || creating}
                          title={`יוצר ${createTarget} בחיבור ומציב אותה בשדה ${FIELD_HE[focus]}`}>
                    {creating ? <span className="spinner" /> : <Ic p={IC.plus} />} צור
                  </button>
                </div>
              </div>
            )}

            <label>סוג מסמך צפוי (לא חובה)
              <select value={typeHint} onChange={(e) => setTypeHint(e.target.value)}>
                <option value="">— לא ידוע —</option>
                {DOC_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </label>
            {typeHint && (
              <label>משקל הסוג בזיהוי
                <select value={typeAuthority} onChange={(e) => setTypeAuthority(e.target.value)}>
                  {Object.entries(AUTHORITY_HE).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                </select>
              </label>
            )}
            <div style={{ display: 'flex', gap: 10 }}>
              <label style={{ flex: 1 }}>פריטים לסבב
                <input type="number" min={1} max={500} value={take} onChange={(e) => setTake(Number(e.target.value))} />
              </label>
              <label style={{ flex: 1 }}>גודל נגלה
                <input type="number" min={1} max={500} value={chunk} onChange={(e) => setChunk(Number(e.target.value))} />
              </label>
              <label style={{ flex: 1 }}>תדירות (דק׳)
                <input type="number" min={SCHEDULER_MIN} max={1440} step={SCHEDULER_MIN} value={scheduleMin}
                       onChange={(e) => setScheduleMin(Number(e.target.value))} />
              </label>
            </div>
            <div className="muted small">
              הסבב האוטומטי רץ כל {SCHEDULER_MIN} דק׳ ולוקח מקור רק כשעברה עליו התדירות שלו — לכן {SCHEDULER_MIN} הוא
              המינימום. «נגלה» = כמה מסירות יוצאות במקביל בסבב (למייל: חיבור IMAP אחד לתיבה, לכן קטן).
            </div>
            <label>שם המקור<input value={name} onChange={(e) => setName(e.target.value)} placeholder={finalName} /></label>
            <div className="muted small">
              ייכתב בשם <span className="mono">{finalName}</span>.{nameTaken ? ' השם תפוס.' : ''}
            </div>

            {!isNew && (
              <div>
                <div className="muted small" style={{ marginBottom: 4 }}>
                  {changes.rows.length ? `מה ייכתב בשמירה (${changes.rows.length}):` : 'לא שונה דבר עדיין — השמירה תכתוב רק שדות ששיניתם.'}
                </div>
                {changes.rows.length > 0 && (
                  <div className="review">
                    {changes.rows.map((r, i) => (
                      <div key={i} className={`row${r.derived ? ' derived' : ''}`}>
                        <span className="k">{r.k}</span><span className="v">{r.v}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {err && <div className="callout bad">{err}</div>}
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button className="btn ghost" onClick={onClose} disabled={busy}>ביטול</button>
              <button className="btn" onClick={save} disabled={busy || (!isNew && !changes.rows.length)}
                      title={isNew ? 'מציג סקירה של כל השדות שייכתבו לפני היצירה' : 'כותב רק את השדות ששיניתם'}>
                {busy ? <><span className="spinner" /> שומר…</> : isNew ? 'המשך לסקירה' : 'שמירה'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
