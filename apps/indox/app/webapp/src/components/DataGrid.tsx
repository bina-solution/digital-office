// ─────────────────────────────────────────────────────────────────────────────
// <DataGrid> — the operable table for the INDOX console.
//
// Headless core (TanStack Table v8) + row virtualization (TanStack Virtual), so
// we own EVERY DOM node. That ownership is the whole point of this component
// and the reason the documents table was moved back onto it:
//
//  • ROW OPEN IS A REAL LINK. The row-header cell renders an actual <a href>,
//    and the row itself is a focusable `role="row"` that opens on Enter. It does
//    not depend on a grid engine emitting a focus event, so it cannot be
//    swallowed by cell focus/selection handling (which is exactly how the
//    documents table lost navigation: row-open was inferred from a
//    `afterfocus` event that does not re-fire on the already-focused cell, on a
//    "link" that was a <span>, restricted to ONE column because every other
//    column was live-editable).
//  • CELL EDITING IS BEHIND AN EXPLICIT AFFORDANCE. `editMode` is off by
//    default; the toolbar toggle turns it on. While it is off nothing in a cell
//    competes with the click that opens the row.
//  • ROWS ARE IN THE ACCESSIBILITY TREE. role=table/row/columnheader/rowheader/
//    gridcell + aria-rowcount/aria-rowindex/aria-sort/aria-selected, on real
//    text nodes.
//  • LOADING SHOWS STRUCTURE, NOT BLANK WHITE. Skeleton rows fill the body on
//    first load instead of a hidden body under a populated toolbar/footer.
//
// Features: click-header sort, per-column header filters (text / enum / month)
// in a portal so the scroll container cannot clip them, resizable columns
// (RTL-aware), sticky header, virtualization, row selection + a caller-supplied
// selection action bar, a search toolbar with active-filter chips, a column
// picker, opt-in inline cell edit (double-click → type-appropriate editor; Esc
// cancels, Enter/blur commits with optimistic UI + error rollback + toast), and
// a pagination footer.
//
// Two modes:
//   • client — the grid sorts/filters/paginates the `rows` you pass.
//   • server — you own the data: pass the current page's `rows` + `rowCount`
//     (total) and react to `onStateChange({sorting,pageIndex,pageSize,search,
//     filters})` by refetching. Search is debounced before it fires.
// ─────────────────────────────────────────────────────────────────────────────
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from 'react';
import { createPortal } from 'react-dom';
import { IC } from '../icons';
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  type ColumnDef,
  type SortingState,
  type VisibilityState,
  type RowSelectionState,
  type ColumnSizingState,
  type PaginationState,
  type Row,
} from '@tanstack/react-table';
import { useVirtualizer } from '@tanstack/react-virtual';

export type GridCellType =
  | 'text'
  | 'number'
  | 'boolean'
  | 'select'
  | 'json'
  | 'date'
  | 'datetime';

/** The per-column filter a header popover writes; filters across columns AND together.
 *  Deliberately the same shape the previous grid emitted, so a page's translation of
 *  these into backend clauses did not have to be rewritten (and re-verified) to move. */
export type GridFilterValue =
  | { kind: 'text'; op: 'contains' | 'equals' | 'empty' | 'notEmpty'; value?: string }
  | { kind: 'enum'; values: string[] }
  | { kind: 'range'; min?: string; max?: string }
  // one month ('YYYY-MM'), or GRID_MONTH_NONE for the rows that have no date at all
  | { kind: 'month'; key: string };

/** The "rows with no date" bucket. One token shared by this component and the page's
 *  server-side translation, instead of each spelling it out. */
export const GRID_MONTH_NONE = '__no_date__';

/** 'YYYY-MM' → 'מרץ 2026'. Built from the key, never from the bucket list, so a chip can
 *  still name its month after the index behind it has been refetched or dropped. */
export function gridMonthLabel(key: string): string {
  if (key === GRID_MONTH_NONE) return 'ללא תאריך';
  const [y, m] = key.split('-').map(Number);
  if (!y || !m) return key;
  return new Date(y, m - 1, 1).toLocaleDateString('he-IL', { year: 'numeric', month: 'long' });
}

export interface GridColumn {
  /** field key on the row object */
  key: string;
  /** display header (Hebrew label) */
  header: string;
  /** the header's tooltip. A header narrow enough to clip must still be ONE HOVER from
   *  its full name — including the raw column name, which is what an operator needs when
   *  they are about to talk to the database about it. Defaults to `header`. */
  headerTitle?: string;
  type?: GridCellType;
  editable?: boolean;
  /** false = this column's header does not sort. For action/verb columns, whose cells are
   *  buttons rather than data — ordering rows by "פתח" is a click that cannot mean anything. */
  sortable?: boolean;
  width?: number;
  minWidth?: number;
  /** default-hidden (still toggleable in the column picker) */
  hidden?: boolean;
  /** options for `type: 'select'` editors AND for the enum header filter */
  options?: { value: string; label: string }[];
  align?: 'start' | 'end' | 'center';
  /** custom read-mode renderer (overrides the default by-type render) */
  render?: (value: unknown, row: GridRow) => ReactNode;
  /** plain-text form of the cell, for the title tooltip and CSV export when `render`
   *  produces markup. Defaults to the raw value. */
  text?: (value: unknown, row: GridRow) => string;
  /** return an error string to REJECT an inline edit (toast shown), null to accept */
  validate?: (value: unknown) => string | null | undefined;
  /** header filter affordance. Inferred: 'enum' when `options` is set, 'month' when
   *  `months` is set, else 'text'. `false` removes the affordance. */
  filter?: false | 'text' | 'enum' | 'month';
  /** MONTH BUCKETS for a date column's header filter, supplied by the page (it owns the
   *  aggregate). A month is a single exact clause the backend implements outright, which
   *  is why it is a first-class filter kind and not two range bounds. */
  months?: { key: string; label: string; count: number }[];
  /** the month index for this column is in flight (renders a note in the popover) */
  monthsLoading?: boolean;
  /** rows with NO usable value in this date column → the "ללא תאריך" bucket */
  monthsNoneCount?: number;
  /** rows whose date is present but UNREADABLE. Stated, never linked: there is no filter
   *  that selects them, and a clickable bucket that under-delivers is worse than a number. */
  monthsBadCount?: number;
  /** the index behind `months` was capped rather than read in full — said out loud */
  monthsSampled?: boolean;
}

export type GridRow = Record<string, unknown>;

/** THE ONE SELECTOR. A selection is either explicit ids or "everything matching the
 *  current query, minus except" — the SAME object the bulk endpoints receive, so what
 *  the operator sees selected and what the server acts on can never diverge. */
export type GridSelection =
  | { kind: 'ids'; ids: string[] }
  | { kind: 'filter'; except: string[] };

export interface GridState {
  sorting: { key: string; dir: 'asc' | 'desc' }[];
  pageIndex: number;
  pageSize: number;
  search: string;
  filters: Record<string, GridFilterValue>;
}

export interface DataGridProps {
  columns: GridColumn[];
  rows: GridRow[];
  getRowId: (row: GridRow) => string;
  mode?: 'client' | 'server';
  /** server mode: total rows matching the filter/search (for "page N of M") */
  rowCount?: number;
  loading?: boolean;
  error?: string | null;
  /** server mode: fires (debounced for search) when sort/page/search/filters change */
  onStateChange?: (state: GridState) => void;
  /** commit an inline edit; resolve to accept (optimistic) or reject to roll back.
   *  Only ever called while the operator has switched edit mode ON. */
  onCellEdit?: (rowId: string, key: string, value: unknown) => Promise<void>;
  onAddRow?: () => void;
  /** open the row — navigation. Wired to the row-header link, a click anywhere on the
   *  row, and Enter on the focused row. */
  onRowOpen?: (row: GridRow) => void;
  /** the href the row-header link carries, so middle-click / ctrl-click / "copy link"
   *  / a screen reader's link list all behave like the real navigation they are. */
  getRowHref?: (row: GridRow) => string;
  /** which column is the row header (carries the link). Defaults to the first column. */
  rowHeaderKey?: string;
  selectable?: boolean;
  onSelectionChange?: (ids: string[]) => void;
  /** the action bar shown above the grid while ≥1 row is selected. The grid owns the
   *  count and "נקה בחירה"; the page owns what its selection MEANS. */
  selectionActions?: (ids: string[], clear: () => void) => ReactNode;
  /** bump this number to drop the selection — e.g. after a bulk write landed. Declarative
   *  so the page never needs an imperative handle on the grid. */
  clearSelectionSignal?: number;
  /** ONE-SELECTOR mode (server pages). When both props are set, the grid's checkboxes
   *  read and write THIS state instead of the internal page-scoped selection: the header
   *  checkbox always selects ALL rows matching the current query (kind 'filter'), and a
   *  row checkbox picks ids or carves exceptions out of the matching set. Page changes
   *  keep the selection — the filter IS the selection — while changing the search or a
   *  column filter clears it (a selection made under a different query is a different
   *  set). The honest count comes from `rowCount`, and the server resolves the same
   *  {filter, except} object at execution time. */
  selection?: GridSelection;
  onSelectionModelChange?: (sel: GridSelection) => void;
  /** rendered at the START of the grid toolbar, before the search — the page's identity
   *  controls (e.g. a repo selector) live IN the table rather than in a strip above it. */
  toolbarStart?: ReactNode;
  /** rendered at the END of the grid toolbar (after the add button) — view toggles etc. */
  toolbarEnd?: ReactNode;
  /** page-level filter chips (e.g. URL drill-downs) shown in the grid's own chip row,
   *  each with its own remove — ONE chip language for every active narrowing. */
  extraChips?: { label: string; title?: string; onClear: () => void }[];
  /** fired with a column key when its header filter popover OPENS, so a page can load
   *  per-column filter data lazily (a month index costs a server-side aggregate). */
  onFilterOpen?: (colKey: string) => void;
  /** the words on the add button (an icon is drawn before them) */
  addRowLabel?: ReactNode;
  searchPlaceholder?: string;
  emptyMessage?: string;
  initialPageSize?: number;
  pageSizeOptions?: number[];
  /** keys hidden on first render (column picker can re-show them) */
  initialHiddenKeys?: string[];
  /* [url-view-state 2026-08-24] READ-ONCE initial values, so a shared link restores the
     view it was copied from. Same one-way contract as initialPageSize: the grid seeds its
     state from these on mount and never re-reads them — the URL is where you arrived,
     the grid's own state is where you are. */
  initialSearch?: string;
  initialSorting?: { id: string; desc: boolean }[];
  initialPageIndex?: number;
  /** read-once seed for the column filters — the URL half of "the URL is the selector".
   *  The popovers own them afterwards; the page re-serializes changes via onStateChange. */
  initialFilters?: Record<string, GridFilterValue>;
  /** viewport height for the virtualized body (px) — the pre-measurement fallback only */
  height?: number;
  /** aria-label for the table element */
  label?: string;
  /* LAYOUT PERSISTENCE — opt-in, and inert without it.
     A stable id turns this grid's column widths and show/hide into a per-browser memory:
     an operator who narrows a column or hides four of them finds it that way tomorrow.
     WHY OPT-IN: the documents table's view is carried by the URL instead (see
     `initialHiddenKeys` / `initialFilters` above), and two memories of the same thing
     would fight — a restored link would be overwritten by whatever the last visit left
     behind. A page passes `tableId` only if the URL does NOT own its view. */
  tableId?: string;
  /** offer a one-step undo after an accepted cell edit (toast action + Ctrl/⌘+Z).
   *  OFF by default: it adds an affordance, and a screen that has not asked for one
   *  must not grow it just because it shares a component. */
  undoEdits?: boolean;
}

/* ── layout memory (localStorage) ──────────────────────────────────────────────
   Deliberately small: widths + hidden keys, nothing else. Sorting, paging, search
   and filters are the QUESTION being asked and belong to the URL or to the visit;
   column layout is how this operator likes to READ the answer, which is why it is
   the only part that outlives the tab.

   Every path is guarded: a private window, cleared site data or a browser that
   throws on access must degrade to "no memory", never to a broken grid. */
const LAYOUT_V = 1;
/* `visibility` is TanStack's own VisibilityState — the DEVIATIONS from the schema default,
   not a list of hidden columns. That distinction is the whole correctness of the merge: a
   bare hidden-list cannot tell "this column was added after the memory was written" from
   "the operator re-showed a column that defaults hidden", and would get one of them wrong. */
type StoredLayout = { v: number; visibility?: Record<string, boolean>; sizing?: Record<string, number> };

function readLayout(tableId: string | undefined): StoredLayout | null {
  if (!tableId) return null;
  try {
    const raw = window.localStorage.getItem(`dg:layout:${tableId}`);
    if (!raw) return null;
    const p = JSON.parse(raw) as StoredLayout;
    return p && p.v === LAYOUT_V ? p : null; // a bumped shape is ignored, not migrated
  } catch {
    return null;
  }
}

function writeLayout(tableId: string | undefined, layout: StoredLayout): void {
  if (!tableId) return;
  try {
    window.localStorage.setItem(`dg:layout:${tableId}`, JSON.stringify(layout));
  } catch {
    /* quota, private mode, blocked site data — the grid works without the memory */
  }
}

const ROW_H = 38;
const DEFAULT_COL_W = 170;
const SELECT_W = 40;
const SEARCH_DEBOUNCE_MS = 350;
const SKELETON_ROWS = 14;

/** Feather-style stroke icon — the console's own icon convention (24×24, stroke=currentColor,
 *  width 2, round caps), so the grid's controls read as part of the same product.
 *  Exported: every icon-bearing control in the app draws from this one primitive. */
export function Ic({ p, title }: { p: string; title?: string }) {
  return (
    <svg
      className="dg-ic"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {title ? <title>{title}</title> : null}
      <path d={p} />
    </svg>
  );
}
/* RTL pager: "first/prev" travel toward inline-start (visually right), "next/last" toward
   inline-end (left). Feather chevron / chevrons path data. */
const IC_FIRST = 'M13 17l5-5-5-5M6 17l5-5-5-5';
const IC_PREV = 'M9 18l6-6-6-6';
const IC_NEXT = 'M15 18l-6-6 6-6';
const IC_LAST = 'M11 17l-5-5 5-5M18 17l-5-5 5-5';

/* Local styles for the parts of this grid that index.css does not already dress.
   Everything here is `.dg-*` like the rest of the grid and uses the app's own
   tokens — no second design system, and no shared stylesheet to conflict over. */
const DG_LOCAL_CSS = `
/* the page-fill shell hands its single child the leftover height; index.css already
   says this for the other grid's fill class, and this is the same statement for ours */
.page-fill > .dg-root{flex:1 1 auto;min-height:0}
.dg-selbar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:8px 12px;
  border-bottom:1px solid var(--line);background:var(--accent-soft)}
.dg-selcount{font-size:12.5px;font-weight:800;color:var(--accent-d);white-space:nowrap}
.dg-selbar.edit{background:var(--warn-soft)} .dg-selbar.edit .dg-selcount{color:var(--amber)}
.dg-idlink{color:var(--accent-d);font-weight:700;text-decoration:underline;text-underline-offset:2px}
.dg-idlink:hover{color:var(--accent)}
.dg-row-open{cursor:pointer}
.dg-row:focus{outline:none}
.dg-row:focus-visible{outline:2px solid var(--accent);outline-offset:-2px;z-index:1}
.dg-skelbar{height:9px;border-radius:5px;background:var(--line);animation:dgpulse 1.2s ease-in-out infinite}
@keyframes dgpulse{0%,100%{opacity:.4}50%{opacity:.9}}
.dg-pop{position:fixed;z-index:60;background:var(--surface);border:1px solid var(--line);
  border-radius:10px;box-shadow:var(--shadow-lg);padding:9px;min-width:236px;max-width:330px;
  max-height:360px;overflow:auto;font-size:12.5px}
.dg-pop h4{margin:0 0 7px;font-size:12px;font-weight:800;color:var(--muted)}
.dg-pop-item{display:flex;align-items:center;gap:7px;padding:4px 5px;border-radius:6px;cursor:pointer}
.dg-pop-item:hover{background:var(--surface-2)}
.dg-pop-item input{width:auto;flex:none}
.dg-pop-item .lbl{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.dg-pop-foot{display:flex;gap:8px;justify-content:flex-end;align-items:center;
  padding-top:8px;margin-top:7px;border-top:1px solid var(--line)}
.dg-fbtn{background:none;border:none;cursor:pointer;color:var(--muted);font-size:11px;
  padding:0 4px;line-height:0;flex:none;display:inline-flex;align-items:center}
.dg-fbtn .dg-ic{width:12px;height:12px}
.dg-fbtn:hover{color:var(--ink)}
.dg-fbtn.on{color:var(--accent-d);font-weight:800}
.dg-errdot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--red);flex:none}
.dg-hint{font-size:11.5px;color:var(--muted)}
/* .dg-pgbtn / .dg-ic live in index.css — PipelineBar uses them on DataGrid-less screens */
/* THIN SCROLLBARS. The default desktop scrollbar is a 17px gutter fighting the table for
   attention; this is the quiet overlay-style one a data product should have. */
.dg-scroll{scrollbar-width:thin;scrollbar-color:color-mix(in srgb, var(--muted) 38%, transparent) transparent}
.dg-scroll::-webkit-scrollbar{width:9px;height:9px}
.dg-scroll::-webkit-scrollbar-track{background:transparent}
.dg-scroll::-webkit-scrollbar-corner{background:transparent}
.dg-scroll::-webkit-scrollbar-thumb{background:color-mix(in srgb, var(--muted) 32%, transparent);
  border-radius:8px;border:2px solid transparent;background-clip:padding-box}
.dg-scroll::-webkit-scrollbar-thumb:hover{background:color-mix(in srgb, var(--muted) 55%, transparent);
  border:2px solid transparent;background-clip:padding-box}
`;

// ── toast — THE ONE NOTICE CHANNEL of the app (N13) ─────────────────────────────────────────
// A module-level store, not component state: every screen's action feedback (a save, a run, a
// delete, a failure) lands in the same corner in the same shape, and `ToastHost` — mounted once
// by App.tsx — is the only thing that draws it. Six notice idioms used to coexist (green callouts
// that also carried failures, pills, inline spans, a `note` state per page); this is the one that
// is left. A failure is `bad` and red, always; `warn` is for "did not run, and here is why";
// `ok` is reserved for something that actually happened.
export type ToastAction = { label: string; run: () => void };
export type ToastKind = 'ok' | 'bad' | 'warn';
export interface Toast { id: number; kind: ToastKind; text: string; action?: ToastAction }

let TOASTS: Toast[] = [];
const toastListeners = new Set<() => void>();
const toastEmit = () => { for (const l of toastListeners) l(); };
const toastSubscribe = (l: () => void) => { toastListeners.add(l); return () => { toastListeners.delete(l); }; };
const toastSnapshot = () => TOASTS;

export function dropToast(id: number): void {
  if (!TOASTS.some((t) => t.id === id)) return;
  TOASTS = TOASTS.filter((t) => t.id !== id);
  toastEmit();
}
/** Push one notice. Returns its id (a caller can drop it early, e.g. when its work finished). */
export function pushToast(kind: ToastKind, text: string, action?: ToastAction): number {
  const id = Date.now() + Math.random();
  TOASTS = [...TOASTS, { id, kind, text, action }];
  toastEmit();
  /* A toast you only READ and one you must ACT ON are not the same deadline. 4.2s is plenty to
     register "נשמר"; it is not enough to notice an undo, move the mouse across the screen and
     click it — measured by failing to do exactly that during QA. An offered action gets the time
     an action needs, and a failure gets long enough to be read twice. */
  window.setTimeout(() => dropToast(id), action ? 9000 : kind === 'bad' ? 8000 : 4200);
  return id;
}
/** the hook every screen uses: `const { push } = useToasts(); push('bad', 'השמירה נכשלה: …')` */
export function useToasts(): { toasts: Toast[]; push: typeof pushToast; drop: typeof dropToast } {
  const toasts = useSyncExternalStore(toastSubscribe, toastSnapshot, toastSnapshot);
  return { toasts, push: pushToast, drop: dropToast };
}
/** the one renderer of the stack — mounted once, in App.tsx, above every route */
export function ToastHost() {
  const { toasts, drop } = useToasts();
  return (
    <div className="dg-toast-wrap">
      {toasts.map((t) => (
        <div key={t.id} className={`dg-toast ${t.kind}`} role={t.kind === 'bad' ? 'alert' : 'status'}>
          <span style={{ whiteSpace: 'pre-line' }}>{t.text}</span>
          {t.action && (
            <button
              type="button"
              className="dg-toast-act"
              onClick={() => {
                drop(t.id);
                t.action?.run();
              }}
            >
              {t.action.label}
            </button>
          )}
        </div>
      ))}
    </div>
  );
}

function fmtCell(value: unknown, type: GridCellType | undefined): string {
  if (value == null || value === '') return '';
  if (type === 'boolean') return value === true || value === 'true' ? 'כן' : 'לא';
  if (type === 'json' || typeof value === 'object') {
    try {
      return JSON.stringify(value);
    } catch {
      return String(value);
    }
  }
  return String(value);
}

/** plain text for a cell — the title tooltip, and what a caller exports to CSV */
export function gridCellText(col: GridColumn, row: GridRow): string {
  if (col.text) return col.text(row[col.key], row);
  return fmtCell(row[col.key], col.type);
}

function filterKind(c: GridColumn): false | 'text' | 'enum' | 'month' {
  if (c.filter !== undefined) return c.filter;
  if (c.options && c.options.length) return 'enum';
  if (c.months || c.type === 'date' || c.type === 'datetime') return 'month';
  return 'text';
}

function isFilterActive(f: GridFilterValue | undefined): boolean {
  if (!f) return false;
  if (f.kind === 'month') return !!f.key;
  if (f.kind === 'enum') return f.values.length > 0;
  if (f.kind === 'range') return !!(f.min || f.max);
  return f.op === 'empty' || f.op === 'notEmpty' || !!f.value;
}

function filterSummary(f: GridFilterValue): string {
  if (f.kind === 'month') return gridMonthLabel(f.key);
  if (f.kind === 'enum') return f.values.join(', ');
  if (f.kind === 'range') {
    if (f.min && f.max) return `${f.min} – ${f.max}`;
    if (f.min) return `≥ ${f.min}`;
    if (f.max) return `≤ ${f.max}`;
    return '';
  }
  if (f.op === 'empty') return 'ריק';
  if (f.op === 'notEmpty') return 'לא ריק';
  return `${f.op === 'equals' ? '=' : '⊃'} ${f.value ?? ''}`;
}

/** client-mode only — the server owns this in server mode. Handles the two date shapes
 *  the corpus actually holds (ISO and D/M/YYYY) rather than assuming an ISO prefix. */
function monthKeyOf(raw: unknown): string | null {
  const s = String(raw ?? '').trim();
  if (!s) return null;
  const iso = /^(\d{4})-(\d{2})/.exec(s);
  if (iso) return `${iso[1]}-${iso[2]}`;
  const dmy = /^(\d{1,2})[/.](\d{1,2})[/.](\d{2,4})$/.exec(s);
  if (dmy) {
    const y = Number(dmy[3]);
    const year = y < 100 ? 2000 + y : y;
    return `${year}-${String(Number(dmy[2])).padStart(2, '0')}`;
  }
  const d = new Date(s);
  if (!Number.isNaN(d.getTime())) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
  }
  return null;
}

function passesFilter(row: GridRow, key: string, f: GridFilterValue | undefined): boolean {
  if (!f) return true;
  const raw = row[key];
  if (f.kind === 'enum') return !f.values.length || f.values.includes(String(raw ?? ''));
  if (f.kind === 'month') {
    const mk = monthKeyOf(raw);
    return f.key === GRID_MONTH_NONE ? mk == null : mk === f.key;
  }
  if (f.kind === 'range') {
    const n = Number(raw);
    if (f.min !== undefined && f.min !== '' && !(Number.isFinite(n) && n >= Number(f.min))) return false;
    if (f.max !== undefined && f.max !== '' && !(Number.isFinite(n) && n <= Number(f.max))) return false;
    return true;
  }
  const s = String(raw ?? '').toLowerCase();
  const v = (f.value ?? '').toLowerCase();
  if (f.op === 'equals') return s === v;
  if (f.op === 'empty') return s === '';
  if (f.op === 'notEmpty') return s !== '';
  return v === '' ? true : s.includes(v);
}

// ── one inline-edit editor, focused on mount ─────────────────────────────────
function CellEditor({
  col,
  initial,
  onCommit,
  onCancel,
}: {
  col: GridColumn;
  initial: unknown;
  onCommit: (value: unknown) => void;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState<string>(
    initial == null ? '' : typeof initial === 'object' ? JSON.stringify(initial) : String(initial),
  );

  const commit = () => {
    if (col.type === 'number') {
      if (draft.trim() === '') return onCommit(null);
      const n = Number(draft);
      return onCommit(Number.isNaN(n) ? draft : n);
    }
    if (col.type === 'boolean') return onCommit(draft === 'true');
    onCommit(draft);
  };

  const common = {
    autoFocus: true,
    className: 'dg-editor mono',
    'aria-label': `עריכת ${col.header}`,
    onKeyDown: (e: React.KeyboardEvent) => {
      // The editor lives inside a row that opens on Enter — stop the key here so
      // committing an edit can never also navigate away from the row being edited.
      e.stopPropagation();
      if (e.key === 'Enter' && col.type !== 'json') {
        e.preventDefault();
        commit();
      } else if (e.key === 'Escape') {
        e.preventDefault();
        onCancel();
      }
    },
  };

  if (col.type === 'boolean') {
    return (
      <select {...common} value={draft} onChange={(e) => setDraft(e.target.value)} onBlur={commit}>
        <option value="true">נכון</option>
        <option value="false">— לא נכון</option>
      </select>
    );
  }
  if (col.type === 'select' && col.options) {
    /* A value the pipeline produced but the column does not list must still be SELECTED and
       must survive an unrelated edit. Without this row the editor opens showing the empty
       option — i.e. it claims the row has no value — and blurring writes that emptiness. */
    const opts = col.options.some((o) => o.value === draft) || draft === ''
      ? col.options
      : [...col.options, { value: draft, label: draft }];
    return (
      <select {...common} value={draft} onChange={(e) => setDraft(e.target.value)} onBlur={commit}>
        <option value="">—</option>
        {opts.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    );
  }
  if (col.type === 'json') {
    return (
      <textarea
        {...common}
        className="dg-editor dg-editor-area mono"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        spellCheck={false}
      />
    );
  }
  return (
    <input
      {...common}
      type="text"
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
    />
  );
}

// ── header filter popover ────────────────────────────────────────────────────
/* Rendered through a portal, positioned from the button's rect. The header lives
   inside `.dg-scroll` (overflow:auto), which would otherwise clip an absolutely
   positioned menu — the popover would open invisible or half-cut. */
function FilterPopover({
  col,
  kind,
  value,
  anchor,
  onApply,
  onClear,
  onClose,
}: {
  col: GridColumn;
  kind: 'text' | 'enum' | 'month';
  value: GridFilterValue | undefined;
  anchor: DOMRect;
  onApply: (v: GridFilterValue) => void;
  onClear: () => void;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [enumSel, setEnumSel] = useState<string[]>(
    value?.kind === 'enum' ? value.values : [],
  );
  const [enumQ, setEnumQ] = useState('');
  const [textOp, setTextOp] = useState<'contains' | 'equals' | 'empty' | 'notEmpty'>(
    value?.kind === 'text' ? value.op : 'contains',
  );
  const [textVal, setTextVal] = useState(value?.kind === 'text' ? (value.value ?? '') : '');
  const [monthQ, setMonthQ] = useState('');

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      const t = e.target as HTMLElement | null;
      // Leave the ▾ buttons to their own handler. Closing here first would make a second
      // click on the SAME button close and immediately reopen the popover instead of
      // dismissing it, and a click on ANOTHER column's button is a switch, not a dismiss.
      if (t?.closest('.dg-fbtn')) return;
      if (ref.current && !ref.current.contains(t)) onClose();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDoc);
      document.removeEventListener('keydown', onKey);
    };
  }, [onClose]);

  const width = 264;
  const left = Math.max(8, Math.min(anchor.left - width + anchor.width, window.innerWidth - width - 8));
  const top = Math.min(anchor.bottom + 4, window.innerHeight - 60);

  const body = (() => {
    if (kind === 'enum') {
      const opts = (col.options ?? []).filter(
        (o) => !enumQ || o.label.includes(enumQ) || o.value.toUpperCase().includes(enumQ.toUpperCase()),
      );
      return (
        <>
          <h4>{col.header}</h4>
          {(col.options?.length ?? 0) > 12 && (
            <input
              className="dg-search"
              style={{ width: '100%', paddingInline: 8, marginBottom: 6 }}
              placeholder="סינון הרשימה…"
              value={enumQ}
              onChange={(e) => setEnumQ(e.target.value)}
              aria-label="סינון רשימת הערכים"
            />
          )}
          {opts.map((o) => (
            <label key={o.value} className="dg-pop-item">
              <input
                type="checkbox"
                checked={enumSel.includes(o.value)}
                onChange={() =>
                  setEnumSel((cur) =>
                    cur.includes(o.value) ? cur.filter((v) => v !== o.value) : [...cur, o.value],
                  )
                }
              />
              <span className="lbl" title={o.value}>
                {o.label}
              </span>
            </label>
          ))}
          <div className="dg-pop-foot">
            <button type="button" className="link" onClick={onClear}>
              נקה
            </button>
            <button
              type="button"
              className="btn sm"
              onClick={() => onApply({ kind: 'enum', values: enumSel })}
            >
              החל
            </button>
          </div>
        </>
      );
    }
    if (kind === 'month') {
      const buckets = (col.months ?? []).filter((b) => !monthQ || b.label.includes(monthQ) || b.key.includes(monthQ));
      return (
        <>
          <h4>{col.header} — לפי חודש</h4>
          {col.monthsLoading && <div className="dg-hint">טוען את חלוקת החודשים…</div>}
          {!col.monthsLoading && (col.months?.length ?? 0) > 12 && (
            <input
              className="dg-search"
              style={{ width: '100%', paddingInline: 8, marginBottom: 6 }}
              placeholder="חיפוש חודש…"
              value={monthQ}
              onChange={(e) => setMonthQ(e.target.value)}
              aria-label="חיפוש חודש"
            />
          )}
          {!col.monthsLoading &&
            buckets.map((b) => (
              <button
                key={b.key}
                type="button"
                className="dg-pop-item"
                style={{ width: '100%', background: 'none', border: 'none', textAlign: 'start' }}
                onClick={() => onApply({ kind: 'month', key: b.key })}
              >
                <span className="lbl">{b.label}</span>
                <span className="num muted">{b.count.toLocaleString('he-IL')}</span>
              </button>
            ))}
          {!col.monthsLoading && (col.monthsNoneCount ?? 0) > 0 && (
            <button
              type="button"
              className="dg-pop-item"
              style={{ width: '100%', background: 'none', border: 'none', textAlign: 'start' }}
              onClick={() => onApply({ kind: 'month', key: GRID_MONTH_NONE })}
            >
              <span className="lbl">ללא תאריך</span>
              <span className="num muted">{(col.monthsNoneCount ?? 0).toLocaleString('he-IL')}</span>
            </button>
          )}
          {!col.monthsLoading && !buckets.length && !(col.monthsNoneCount ?? 0) && (
            <div className="dg-hint">אין חודשים להצגה.</div>
          )}
          {(col.monthsBadCount ?? 0) > 0 && (
            <div className="dg-hint" style={{ marginTop: 6 }}>
              {(col.monthsBadCount ?? 0).toLocaleString('he-IL')} מסמכים עם תאריך שלא ניתן לפענוח — הם
              אינם שייכים לאף חודש ואין אפשרות לסנן אליהם.
            </div>
          )}
          {col.monthsSampled && (
            <div className="dg-hint" style={{ marginTop: 6 }}>
              הספירה חלקית (המדד נקטע) — המספרים הם רצפה, לא סכום מדויק.
            </div>
          )}
          <div className="dg-pop-foot">
            <button type="button" className="link" onClick={onClear}>
              כל החודשים
            </button>
          </div>
        </>
      );
    }
    return (
      <>
        <h4>{col.header}</h4>
        <select
          value={textOp}
          onChange={(e) => setTextOp(e.target.value as typeof textOp)}
          style={{ width: '100%', marginBottom: 6 }}
          aria-label="סוג התנאי"
        >
          <option value="contains">מכיל</option>
          <option value="equals">שווה ל…</option>
          <option value="empty">ריק</option>
          <option value="notEmpty">לא ריק</option>
        </select>
        {(textOp === 'contains' || textOp === 'equals') && (
          <input
            className="dg-search"
            style={{ width: '100%', paddingInline: 8 }}
            value={textVal}
            placeholder="ערך…"
            onChange={(e) => setTextVal(e.target.value)}
            aria-label="ערך לסינון"
            onKeyDown={(e) => {
              if (e.key === 'Enter') onApply({ kind: 'text', op: textOp, value: textVal });
            }}
          />
        )}
        <div className="dg-pop-foot">
          <button type="button" className="link" onClick={onClear}>
            נקה
          </button>
          <button
            type="button"
            className="btn sm"
            onClick={() => onApply({ kind: 'text', op: textOp, value: textVal })}
          >
            החל
          </button>
        </div>
      </>
    );
  })();

  return createPortal(
    <div
      ref={ref}
      className="dg-pop"
      role="dialog"
      aria-label={`סינון ${col.header}`}
      style={{ left, top, width }}
    >
      {body}
    </div>,
    document.body,
  );
}

export default function DataGrid({
  columns,
  rows,
  getRowId,
  mode = 'client',
  rowCount,
  loading = false,
  error = null,
  onStateChange,
  onCellEdit,
  onAddRow,
  onRowOpen,
  getRowHref,
  rowHeaderKey,
  selectable = false,
  onSelectionChange,
  selectionActions,
  clearSelectionSignal = 0,
  selection,
  onSelectionModelChange,
  toolbarStart,
  toolbarEnd,
  extraChips,
  onFilterOpen,
  addRowLabel = 'שורה',
  searchPlaceholder = 'חיפוש…',
  emptyMessage = 'אין רשומות להצגה.',
  initialPageSize = 50,
  pageSizeOptions = [25, 50, 100, 200],
  initialHiddenKeys = [],
  initialSearch = '',
  initialSorting = [],
  initialPageIndex = 0,
  initialFilters,
  height = 560,
  label = 'טבלה',
  tableId,
  undoEdits = false,
}: DataGridProps) {
  const server = mode === 'server';
  const { push } = useToasts();
  // read ONCE, on mount — a lazy initializer, so this is not a localStorage hit per render
  const [storedLayout] = useState<StoredLayout | null>(() => readLayout(tableId));

  const colByKey = useMemo(() => {
    const m = new Map<string, GridColumn>();
    for (const c of columns) m.set(c.key, c);
    return m;
  }, [columns]);

  const headerCol = rowHeaderKey ?? columns[0]?.key;

  // ── table state ────────────────────────────────────────────────────────────
  const [sorting, setSorting] = useState<SortingState>(initialSorting);
  const [globalFilter, setGlobalFilter] = useState(initialSearch);
  const [searchInput, setSearchInput] = useState(initialSearch);
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>(() => {
    const base = Object.fromEntries(
      [...initialHiddenKeys, ...columns.filter((c) => c.hidden).map((c) => c.key)].map((k) => [k, false]),
    );
    /* A REMEMBERED LAYOUT NEVER OUTRANKS THE SCHEMA — it only records where the operator
       DEVIATED from it. Defaults first, then the stored deviations for columns that still
       exist. So a column dropped from the table cannot linger in the memory, and a column
       ADDED since the memory was written has no stored entry and simply keeps its schema
       default — the case that matters most as the column catalog grows. */
    if (!storedLayout?.visibility) return base;
    const known = new Set(columns.map((c) => c.key));
    for (const [k, v] of Object.entries(storedLayout.visibility)) if (known.has(k)) base[k] = v;
    return base;
  });
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [columnSizing, setColumnSizing] = useState<ColumnSizingState>(() => {
    if (!storedLayout?.sizing) return {};
    const known = new Set(columns.map((c) => c.key));
    return Object.fromEntries(Object.entries(storedLayout.sizing).filter(([k]) => known.has(k)));
  });
  const [pagination, setPagination] = useState<PaginationState>({
    pageIndex: Math.max(0, initialPageIndex),
    pageSize: initialPageSize,
  });
  const [filters, setFilters] = useState<Record<string, GridFilterValue>>(initialFilters ?? {});
  const [openFilter, setOpenFilter] = useState<{ key: string; rect: DOMRect } | null>(null);

  /* Mirror the layout into the memory. No debounce needed: both states settle on a
     discrete gesture (a picker toggle, a drag that ended), not on every mouse move —
     TanStack commits column sizing once, at the end of the resize. Inert without
     `tableId`, so a page that does not opt in never touches localStorage. */
  useEffect(() => {
    if (!tableId) return;
    writeLayout(tableId, { v: LAYOUT_V, visibility: columnVisibility, sizing: columnSizing });
  }, [tableId, columnVisibility, columnSizing]);

  /* EDIT MODE — the explicit affordance. Off by default, and while it is off no cell
     carries a dblclick handler, a `cursor:cell`, or an editor. Live cell editing is
     what made row navigation unreliable on this table in the first place: with every
     column editable, opening a row had to be narrowed to one column and inferred from
     focus. Editing is now something the operator turns ON, deliberately, for as long
     as they need it. */
  const [editMode, setEditMode] = useState(false);
  const anyEditable = useMemo(() => !!onCellEdit && columns.some((c) => c.editable), [onCellEdit, columns]);
  useEffect(() => {
    if (!anyEditable && editMode) setEditMode(false);
  }, [anyEditable, editMode]);

  // optimistic edit overlay: `${rowId}::${key}` → { value, saving }
  const [pending, setPending] = useState<
    Record<string, { value: unknown; saving: boolean }>
  >({});
  const [editing, setEditing] = useState<{ rowId: string; key: string } | null>(null);

  /* Every query-shaping change resets to page 1 IN THE SAME BATCH as the change itself.
     Doing it in a follow-up effect instead means the state emitted to a server-mode parent
     briefly pairs the NEW filter with the OLD page index — a wasted round trip whose
     response is an empty page 4 of a result set that now has one page. */
  const toFirstPage = useCallback(() => {
    setPagination((p) => (p.pageIndex === 0 ? p : { ...p, pageIndex: 0 }));
  }, []);

  // the controlled-selection emitter, ref'd so query-shaping callbacks stay stable
  const onSelectionModelChangeRef = useRef(onSelectionModelChange);
  onSelectionModelChangeRef.current = onSelectionModelChange;
  const globalFilterRef = useRef(globalFilter);
  globalFilterRef.current = globalFilter;

  // ── debounce the search box → globalFilter (client) / onStateChange (server)
  useEffect(() => {
    const t = window.setTimeout(() => {
      if (globalFilterRef.current !== searchInput) {
        // different query, different set — see the selection-lifetime comment below
        onSelectionModelChangeRef.current?.({ kind: 'ids', ids: [] });
      }
      setGlobalFilter(searchInput);
      setPagination((p) => (p.pageIndex === 0 ? p : { ...p, pageIndex: 0 }));
    }, SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(t);
  }, [searchInput]);

  // ── notify parent in server mode when the query-shaping state changes ───────
  const onStateChangeRef = useRef(onStateChange);
  onStateChangeRef.current = onStateChange;
  useEffect(() => {
    if (!server) return;
    onStateChangeRef.current?.({
      sorting: sorting.map((s) => ({ key: s.id, dir: s.desc ? 'desc' : 'asc' })),
      pageIndex: pagination.pageIndex,
      pageSize: pagination.pageSize,
      search: globalFilter,
      filters,
    });
  }, [server, sorting, pagination.pageIndex, pagination.pageSize, globalFilter, filters]);

  const setFilter = useCallback(
    (key: string, v: GridFilterValue | null) => {
      setFilters((cur) => {
        const next = { ...cur };
        if (v == null || !isFilterActive(v)) delete next[key];
        else next[key] = v;
        return next;
      });
      toFirstPage();
      // a selection made under a different query is not the same set
      setRowSelection({});
      onSelectionModelChangeRef.current?.({ kind: 'ids', ids: [] });
    },
    [toFirstPage],
  );

  const changeSorting = useCallback<typeof setSorting>(
    (updater) => {
      setSorting(updater);
      toFirstPage();
    },
    [toFirstPage],
  );

  // ── client-mode column filtering (the server owns it in server mode) ───────
  const filteredRows = useMemo(() => {
    if (server) return rows;
    const active = Object.entries(filters);
    if (!active.length) return rows;
    return rows.filter((r) => active.every(([k, f]) => passesFilter(r, k, f)));
  }, [server, rows, filters]);

  // ── build TanStack columns (select + data) ─────────────────────────────────
  const tableColumns = useMemo<ColumnDef<GridRow>[]>(() => {
    const defs: ColumnDef<GridRow>[] = [];
    if (selectable) {
      defs.push({
        id: '__select',
        size: SELECT_W,
        enableSorting: false,
        enableResizing: false,
        enableHiding: false,
      });
    }
    for (const c of columns) {
      defs.push({
        id: c.key,
        accessorFn: (r) => r[c.key],
        header: c.header,
        size: c.width ?? DEFAULT_COL_W,
        minSize: c.minWidth ?? 54,
        enableSorting: c.sortable !== false,
        enableResizing: true,
      });
    }
    return defs;
  }, [columns, selectable]);

  const table = useReactTable<GridRow>({
    data: filteredRows,
    columns: tableColumns,
    state: {
      sorting,
      columnVisibility,
      rowSelection,
      columnSizing,
      pagination,
      globalFilter: server ? '' : globalFilter,
    },
    getRowId,
    enableRowSelection: selectable,
    onSortingChange: changeSorting,
    onColumnVisibilityChange: setColumnVisibility,
    onRowSelectionChange: setRowSelection,
    onColumnSizingChange: setColumnSizing,
    onPaginationChange: setPagination,
    onGlobalFilterChange: setGlobalFilter,
    columnResizeMode: 'onChange',
    columnResizeDirection: 'rtl',
    manualSorting: server,
    manualFiltering: server,
    manualPagination: server,
    rowCount: server ? (rowCount ?? filteredRows.length) : undefined,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: server ? undefined : getSortedRowModel(),
    getFilteredRowModel: server ? undefined : getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
  });

  // propagate selection ids upward
  const selectedIds = useMemo(
    () => Object.keys(rowSelection).filter((k) => rowSelection[k]),
    [rowSelection],
  );
  const onSelectionChangeRef = useRef(onSelectionChange);
  onSelectionChangeRef.current = onSelectionChange;
  useEffect(() => {
    if (!selectable) return;
    onSelectionChangeRef.current?.(selectedIds);
  }, [selectedIds, selectable]);
  /* ONE-SELECTOR (controlled) mode: both props supplied → the grid's checkboxes drive
     the page's GridSelection and the internal page-scoped rowSelection is unused. */
  const controlled = selection !== undefined && !!onSelectionModelChange;
  const emitSel = onSelectionModelChange;
  const selTotal = server ? (rowCount ?? filteredRows.length) : filteredRows.length;
  const rowIsSelected = useCallback(
    (id: string): boolean => {
      if (!selection) return false;
      return selection.kind === 'filter' ? !selection.except.includes(id) : selection.ids.includes(id);
    },
    [selection],
  );
  const toggleRowSel = useCallback(
    (id: string, on: boolean) => {
      if (!selection || !emitSel) return;
      if (selection.kind === 'filter') {
        const except = on
          ? selection.except.filter((x) => x !== id)
          : [...new Set([...selection.except, id])];
        emitSel({ kind: 'filter', except });
      } else {
        const ids = on ? [...new Set([...selection.ids, id])] : selection.ids.filter((x) => x !== id);
        emitSel({ kind: 'ids', ids });
      }
    },
    [selection, emitSel],
  );
  const clearSelection = useCallback(() => {
    if (controlled) emitSel?.({ kind: 'ids', ids: [] });
    else setRowSelection({});
  }, [controlled, emitSel]);

  /* THE SELECTION NEVER OUTLIVES ITS QUERY. Internal mode: paging (and the parent bumping
     `clearSelectionSignal` after a bulk write) drops it, so "נבחרו 1,847" always means
     1,847 rows the operator can still see and count. Controlled mode: paging KEEPS the
     selection — the filter is the selection, and the count stays honest because it is
     derived from `rowCount` and the server resolves the same query — but changing the
     search or a column filter clears it (different query, different set; see setFilter
     and the search debounce). */
  useEffect(() => {
    setRowSelection({});
  }, [pagination.pageIndex, pagination.pageSize, clearSelectionSignal]);

  // ── virtualization over the current page's rows ─────────────────────────────
  const bodyRows = table.getRowModel().rows;
  const scrollRef = useRef<HTMLDivElement>(null);

  // Responsive height: fill from the grid's top down to the bottom of the
  // viewport (minus the footer + a little breathing room) so the table ALWAYS
  // fits any screen size and scrolls INTERNALLY instead of overflowing the page.
  const [autoH, setAutoH] = useState<number | null>(null);
  useEffect(() => {
    const measure = () => {
      const el = scrollRef.current;
      if (!el) return;
      const top = el.getBoundingClientRect().top;
      const vh = window.innerHeight || document.documentElement.clientHeight || 640;
      setAutoH(Math.max(220, Math.floor(vh - top - 84)));
    };
    measure();
    const t = window.setTimeout(measure, 120); // after fonts/layout settle
    window.addEventListener('resize', measure);
    let ro: ResizeObserver | undefined;
    if (typeof ResizeObserver !== 'undefined') {
      ro = new ResizeObserver(measure);
      if (document.body) ro.observe(document.body);
    }
    return () => {
      window.clearTimeout(t);
      window.removeEventListener('resize', measure);
      ro?.disconnect();
    };
  }, []);

  const rowVirtualizer = useVirtualizer({
    count: bodyRows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_H,
    overscan: 12,
  });
  const virtualRows = rowVirtualizer.getVirtualItems();
  const totalSize = rowVirtualizer.getTotalSize();

  // shared grid template so header + every row align, incl. horizontal scroll
  const visibleLeaf = table.getVisibleLeafColumns();
  const template = visibleLeaf.map((c) => `${c.getSize()}px`).join(' ');
  const minWidth = visibleLeaf.reduce((s, c) => s + c.getSize(), 0);

  /* UNDO — ONE level, and deliberately only one.
     It holds the last edit that the SERVER accepted, and undoing replays it through the
     same commit path (validation, optimistic overlay, rollback on failure), so undo is
     not a second way to write a cell — it is the same way, with the old value.

     Why not a stack: this grid is `mode:'server'` over a table another pipeline is
     writing to. A deep history would let you "undo" onto a row that has since moved on,
     silently overwriting someone else's newer value with a stale one. One step, offered
     at the moment of the edit and forgotten after, cannot outlive its own context. */
  const lastEdit = useRef<{ rowId: string; key: string; prev: unknown; now: unknown } | null>(null);
  /** self-reference, so the undo action can re-enter the same commit without the callback
   *  having to depend on itself */
  const commitEditRef = useRef<
    ((rowId: string, key: string, value: unknown, previous: unknown, undoable?: boolean) => Promise<void>) | null
  >(null);

  // ── inline edit commit with optimistic UI + rollback ────────────────────────
  const commitEdit = useCallback(
    async (rowId: string, key: string, value: unknown, previous: unknown, undoable = true) => {
      setEditing(null);
      if (value === previous || (value == null && previous == null)) return;
      if (!onCellEdit) return;
      const col = colByKey.get(key);
      const bad = col?.validate?.(value);
      if (bad) {
        push('bad', `${col?.header ?? key}: ${bad}`);
        return;
      }
      const pk = `${rowId}::${key}`;
      setPending((p) => ({ ...p, [pk]: { value, saving: true } }));
      try {
        await onCellEdit(rowId, key, value);
        // keep the optimistic value shown; drop the "saving" flag. When the
        // parent refreshes `rows`, its value takes over and we clear the overlay.
        setPending((p) => ({ ...p, [pk]: { value, saving: false } }));
        if (!undoable) {
          lastEdit.current = null; // an undo consumes the memory it acted on
          push('ok', `בוטל: ${col?.header ?? key}`);
        } else if (undoEdits) {
          lastEdit.current = { rowId, key, prev: previous, now: value };
          push('ok', `נשמר: ${col?.header ?? key}`, {
            label: 'בטל',
            // `undoable:false` — the undo itself is not undoable, so there is no redo loop
            run: () => void commitEditRef.current?.(rowId, key, previous, value, false),
          });
        } else {
          push('ok', `נשמר: ${col?.header ?? key}`);
        }
      } catch (e) {
        // rollback — remove overlay so the original row value shows again
        setPending((p) => {
          const n = { ...p };
          delete n[pk];
          return n;
        });
        const msg = e instanceof Error ? e.message : String(e);
        push('bad', `שמירה נכשלה: ${col?.header ?? key} — ${msg}`);
      }
    },
    [onCellEdit, push, colByKey, undoEdits],
  );
  commitEditRef.current = commitEdit;

  /* Ctrl/⌘+Z, the shortcut everyone already has in their fingers. Gated three ways: edit
     mode must be on, no editor may be open (an open <input> owns its own undo), and there
     must be an edit to take back. Clearing on exit from edit mode is what keeps the offer
     honest — you cannot return an hour later and undo something you have forgotten. */
  useEffect(() => {
    if (!editMode || !undoEdits) {
      lastEdit.current = null;
      return;
    }
    const onKey = (e: KeyboardEvent) => {
      if (!(e.key === 'z' || e.key === 'Z') || !(e.ctrlKey || e.metaKey) || e.shiftKey) return;
      if (editing || !lastEdit.current) return;
      const t = e.target as HTMLElement | null;
      if (t && /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)) return;
      e.preventDefault();
      const { rowId, key, prev, now } = lastEdit.current;
      void commitEditRef.current?.(rowId, key, prev, now, false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [editMode, editing, undoEdits]);

  // once the parent's rows reflect a saved value, drop that overlay entry
  useEffect(() => {
    setPending((p) => {
      if (Object.keys(p).length === 0) return p;
      let changed = false;
      const next = { ...p };
      for (const rowObj of rows) {
        const id = getRowId(rowObj);
        for (const key of Object.keys(rowObj)) {
          const pk = `${id}::${key}`;
          const ov = next[pk];
          if (ov && !ov.saving && String(rowObj[key] ?? '') === String(ov.value ?? '')) {
            delete next[pk];
            changed = true;
          }
        }
      }
      return changed ? next : p;
    });
  }, [rows, getRowId]);

  const totalForFooter = server
    ? (rowCount ?? bodyRows.length)
    : table.getFilteredRowModel().rows.length;
  const pageCount = Math.max(1, Math.ceil(totalForFooter / pagination.pageSize) || 1);
  const selectedCount =
    controlled && selection
      ? selection.kind === 'filter'
        ? Math.max(0, selTotal - selection.except.length)
        : selection.ids.length
      : selectedIds.length;
  /** what selectionActions receives as `ids` — explicit ids only; a filter-kind selection
   *  has no id list by design (the page acts through its own selection payload). */
  const actionIds = controlled && selection
    ? selection.kind === 'ids'
      ? selection.ids
      : []
    : selectedIds;
  const showSkeleton = loading && bodyRows.length === 0 && !error;

  // ── row open ────────────────────────────────────────────────────────────────
  const openRow = useCallback(
    (row: GridRow) => {
      onRowOpen?.(row);
    },
    [onRowOpen],
  );

  /** A click anywhere on the row opens it — EXCEPT on a control (checkbox, editor,
   *  button) or on the row-header link, which runs its own handler. */
  const rowClick = useCallback(
    (e: React.MouseEvent, row: GridRow) => {
      if (!onRowOpen || e.defaultPrevented || e.button !== 0) return;
      const t = e.target as HTMLElement | null;
      if (t?.closest('a,input,select,textarea,button,label,[data-dg-noopen]')) return;
      if (window.getSelection()?.toString()) return; // the operator was selecting text
      openRow(row);
    },
    [onRowOpen, openRow],
  );

  /* ROVING TABINDEX. Exactly ONE row is in the tab order at a time and the arrow keys move
     between rows — the pattern a data grid is supposed to use. Making all 50 rows tabbable
     would technically satisfy "Enter opens the row" while burying every control after the
     table under fifty tab presses. */
  const [focusIdx, setFocusIdx] = useState(0);
  useEffect(() => {
    setFocusIdx(0);
  }, [pagination.pageIndex, pagination.pageSize]);

  const rowKeyDown = useCallback(
    (e: React.KeyboardEvent, row: Row<GridRow>) => {
      const t = e.target as HTMLElement | null;
      if (t?.closest('input,select,textarea')) return;
      if (e.key === 'Enter') {
        if (!onRowOpen) return;
        e.preventDefault();
        openRow(row.original);
      } else if (e.key === ' ' && selectable) {
        e.preventDefault();
        if (controlled) toggleRowSel(row.id, !rowIsSelected(row.id));
        else row.toggleSelected();
      } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        const cur = e.currentTarget as HTMLElement;
        const next = (e.key === 'ArrowDown' ? cur.nextElementSibling : cur.previousElementSibling) as
          | HTMLElement
          | null;
        if (next?.classList.contains('dg-row')) {
          e.preventDefault();
          next.focus();
        }
      }
    },
    [onRowOpen, openRow, selectable, controlled, toggleRowSel, rowIsSelected],
  );

  // ── render one cell (read or edit) ──────────────────────────────────────────
  function renderDataCell(row: Row<GridRow>, colId: string) {
    const col = colByKey.get(colId);
    if (!col) return null;
    const rowId = row.id;
    const pk = `${rowId}::${colId}`;
    const ov = pending[pk];
    const raw = ov ? ov.value : row.original[colId];
    const isEditing = editing?.rowId === rowId && editing?.key === colId;
    const canEdit = editMode && !!col.editable && !!onCellEdit;
    const align = col.align ?? (col.type === 'number' ? 'end' : 'start');

    if (isEditing) {
      return (
        <div className="dg-cell dg-cell-editing" style={{ textAlign: align }}>
          <CellEditor
            col={col}
            initial={raw}
            onCommit={(v) => commitEdit(rowId, colId, v, row.original[colId])}
            onCancel={() => setEditing(null)}
          />
        </div>
      );
    }

    const isHeaderCell = colId === headerCol;
    const plain = col.text ? col.text(raw, row.original) : fmtCell(raw, col.type);
    let display: ReactNode = col.render ? col.render(raw, row.original) : plain;

    if (isHeaderCell && onRowOpen) {
      const href = getRowHref?.(row.original);
      display = (
        <a
          className="dg-idlink"
          href={href ?? '#'}
          // ONE tab stop per row: the row itself. The anchor stays a real link for the
          // a11y tree, middle-click, ctrl-click and "copy link address" — it just isn't
          // a second stop the keyboard has to walk past 50 times a page.
          tabIndex={-1}
          onClick={(e) => {
            // let the browser own the modified clicks (new tab / new window / download)
            if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
            e.preventDefault();
            openRow(row.original);
          }}
        >
          {display === '' ? plain || rowId : display}
        </a>
      );
    }

    const numClass = col.type === 'number' ? ' num' : '';
    return (
      <div
        className={`dg-cell${canEdit ? ' dg-cell-editable' : ''}${ov?.saving ? ' dg-cell-saving' : ''}`}
        style={{ textAlign: align }}
        title={plain || undefined}
        onDoubleClick={canEdit ? () => setEditing({ rowId, key: colId }) : undefined}
      >
        <span className={`dg-cell-val${numClass}`}>
          {display === '' || display == null ? <span className="dg-null">—</span> : display}
        </span>
        {ov?.saving && <span className="dg-spin" aria-label="שומר" />}
      </div>
    );
  }

  // ── active-filter chips ─────────────────────────────────────────────────────
  const activeChips: { label: string; title?: string; onClear: () => void }[] = [];
  if (globalFilter)
    activeChips.push({
      label: `חיפוש: "${globalFilter}"`,
      onClear: () => {
        setSearchInput('');
        setGlobalFilter('');
      },
    });
  for (const [key, f] of Object.entries(filters)) {
    const c = colByKey.get(key);
    activeChips.push({
      label: `${c?.header ?? key}: ${filterSummary(f)}`,
      title: key,
      onClear: () => setFilter(key, null),
    });
  }
  for (const s of sorting) {
    const c = colByKey.get(s.id);
    activeChips.push({
      label: `מיון: ${c?.header ?? s.id} ${s.desc ? '↓' : '↑'}`,
      onClear: () => setSorting((prev) => prev.filter((x) => x.id !== s.id)),
    });
  }

  const openFilterCol = openFilter ? colByKey.get(openFilter.key) : undefined;
  const openFilterKind = openFilterCol ? filterKind(openFilterCol) : false;

  // the roving tab stop, clamped into the rendered window: scrolling the focused row out
  // of the virtualized range must not leave the table with no tabbable row at all
  const firstRendered = virtualRows[0]?.index ?? 0;
  const lastRendered = virtualRows[virtualRows.length - 1]?.index ?? 0;
  const tabRowIdx =
    focusIdx >= firstRendered && focusIdx <= lastRendered ? focusIdx : firstRendered;

  return (
    <div className="dg-root">
      <style>{DG_LOCAL_CSS}</style>

      {/* ── toolbar ── */}
      <div className="dg-toolbar">
        {toolbarStart}
        <div className="dg-search-wrap">
          <span className="dg-search-icon" aria-hidden="true"><Ic p={IC.search} /></span>
          <input
            className="dg-search"
            value={searchInput}
            placeholder={searchPlaceholder}
            aria-label={searchPlaceholder}
            onChange={(e) => setSearchInput(e.target.value)}
          />
          {searchInput && (
            <button className="dg-search-clear" onClick={() => setSearchInput('')} aria-label="נקה חיפוש" title="ניקוי החיפוש">
              <Ic p={IC.x} />
            </button>
          )}
        </div>
        <div className="dg-chips">
          {[...(extraChips ?? []), ...activeChips].map((c, i) => (
            <span key={i} className="dg-chip" title={c.title}>
              {c.label}
              <button className="dg-chip-x" onClick={c.onClear} aria-label={`הסר ${c.label}`} title={`הסרת הסינון: ${c.label}`}>
                <Ic p={IC.x} />
              </button>
            </span>
          ))}
        </div>
        <span className="dg-count num" aria-live="polite">
          {loading
            ? 'טוען…'
            : totalForFooter === 1
              ? 'שורה אחת'
              : `${totalForFooter.toLocaleString('he-IL')} שורות`}
          {selectedCount > 0 && ` · ${selectedCount.toLocaleString('he-IL')} נבחרו`}
        </span>
        {anyEditable && (
          <button
            className={`btn ghost sm${editMode ? ' active' : ''}`}
            aria-pressed={editMode}
            onClick={() => {
              setEditing(null);
              setEditMode((v) => !v);
            }}
            title={
              editMode
                ? 'כיבוי עריכה בטבלה — לחיצה על שורה תפתח את המסמך'
                : 'הפעלת עריכה בטבלה — לחיצה כפולה על תא תפתח עורך'
            }
          >
            <Ic p={IC.edit} /> {editMode ? 'עריכה פעילה' : 'עריכה'}
          </button>
        )}
        <ColumnPicker columns={columns} table={table} />
        {onAddRow && (
          <button className="btn sm" onClick={onAddRow} title={typeof addRowLabel === 'string' ? addRowLabel : undefined}>
            <Ic p={IC.plus} /> {addRowLabel}
          </button>
        )}
        {toolbarEnd}
      </div>

      {editMode && (
        <div className="dg-selbar edit">
          <span className="dg-selcount">
            עריכה בטבלה פעילה
          </span>
          <span className="dg-hint">
            לחיצה כפולה על תא פותחת עורך. פתיחת מסמך נשארת דרך המזהה המקושר או Enter על השורה.
          </span>
        </div>
      )}

      {/* ── selection action bar ── */}
      {selectable && selectedCount > 0 && (
        <div className="dg-selbar" role="region" aria-label="פעולות על השורות שנבחרו">
          <span className="dg-selcount">
            נבחרו {selectedCount.toLocaleString('he-IL')}
            {controlled && selection?.kind === 'filter' && (
              <>
                {' · כל התואמים לסינון'}
                {selection.except.length > 0 &&
                  ` (למעט ${selection.except.length.toLocaleString('he-IL')})`}
              </>
            )}
          </span>
          {selectionActions?.(actionIds, clearSelection)}
          <span style={{ flex: '1 1 auto' }} />
          <button className="btn ghost sm" onClick={clearSelection}>
            נקה בחירה
          </button>
        </div>
      )}

      {/* ── scroll viewport (sticky header + virtualized body) ── */}
      <div className="dg-scroll" ref={scrollRef} style={{ height: autoH ?? height }}>
        <div
          className="dg-table"
          style={{ minWidth }}
          role="table"
          aria-label={label}
          aria-busy={loading || undefined}
          aria-rowcount={totalForFooter}
          aria-colcount={visibleLeaf.length}
        >
          {/* header */}
          <div className="dg-head" style={{ gridTemplateColumns: template }} role="row" aria-rowindex={1}>
            {table.getHeaderGroups().map((hg) =>
              hg.headers.map((h) => {
                const colId = h.column.id;
                if (colId === '__select') {
                  /* Controlled mode: the header checkbox ALWAYS means the whole matching
                     set — one click selects all `rowCount` rows behind the filter, one
                     click clears. No page-then-offer two-step. */
                  const all = controlled
                    ? selection?.kind === 'filter' && selection.except.length === 0 && selTotal > 0
                    : table.getIsAllPageRowsSelected();
                  const some = controlled
                    ? !all && selectedCount > 0
                    : table.getIsSomePageRowsSelected();
                  return (
                    <div key={h.id} className="dg-hcell dg-hcell-fixed" role="columnheader">
                      <input
                        type="checkbox"
                        className="dg-check"
                        checked={all}
                        ref={(el) => {
                          if (el) el.indeterminate = !all && some;
                        }}
                        onChange={(e) => {
                          if (controlled) {
                            emitSel?.(
                              e.target.checked
                                ? { kind: 'filter', except: [] }
                                : { kind: 'ids', ids: [] },
                            );
                          } else {
                            table.toggleAllPageRowsSelected(e.target.checked);
                          }
                        }}
                        title={
                          controlled
                            ? `בחירת כל ${selTotal.toLocaleString('he-IL')} השורות התואמות לסינון`
                            : undefined
                        }
                        aria-label={
                          controlled ? 'בחר את כל השורות התואמות לסינון' : 'בחר את כל השורות בעמוד'
                        }
                      />
                    </div>
                  );
                }
                const meta = colByKey.get(colId);
                const sortDir = h.column.getIsSorted();
                const fk = meta ? filterKind(meta) : false;
                const hasFilter = isFilterActive(filters[colId]);
                return (
                  <div
                    key={h.id}
                    className="dg-hcell"
                    role="columnheader"
                    aria-sort={sortDir === 'asc' ? 'ascending' : sortDir === 'desc' ? 'descending' : 'none'}
                  >
                    <button
                      className="dg-hbtn"
                      onClick={h.column.getToggleSortingHandler()}
                      title={`${meta?.headerTitle ?? meta?.header ?? colId} — לחצו למיון`}
                    >
                      <span className="dg-hlabel">{meta?.header ?? colId}</span>
                      <span className="dg-sort">
                        {sortDir === 'asc' ? '↑' : sortDir === 'desc' ? '↓' : ''}
                      </span>
                    </button>
                    {meta && fk && (
                      <button
                        className={`dg-fbtn${hasFilter ? ' on' : ''}`}
                        aria-label={`סינון לפי ${meta.header}`}
                        title={`סינון לפי ${meta.header}`}
                        aria-expanded={openFilter?.key === colId}
                        onClick={(e) => {
                          const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
                          setOpenFilter((cur) => {
                            if (cur?.key === colId) return null;
                            onFilterOpen?.(colId);
                            return { key: colId, rect };
                          });
                        }}
                      >
                        <Ic p={IC.chevronDown} />
                      </button>
                    )}
                    {h.column.getCanResize() && (
                      <div
                        className={`dg-resizer${h.column.getIsResizing() ? ' active' : ''}`}
                        onMouseDown={h.getResizeHandler()}
                        onTouchStart={h.getResizeHandler()}
                      />
                    )}
                  </div>
                );
              }),
            )}
          </div>

          {/* body */}
          {error ? (
            <div className="dg-state dg-state-error" role="alert">
              {error}
            </div>
          ) : showSkeleton ? (
            /* STRUCTURE, NOT BLANK WHITE. The previous grid hid its body until an
               internal readiness dance finished — a toolbar and a footer claiming
               39,222 records above and below several seconds of empty page. */
            <div className="dg-body" style={{ height: SKELETON_ROWS * ROW_H }} aria-hidden="true">
              {Array.from({ length: SKELETON_ROWS }).map((_, i) => (
                <div
                  key={i}
                  className="dg-row"
                  style={{
                    gridTemplateColumns: template,
                    transform: `translateY(${i * ROW_H}px)`,
                    height: ROW_H,
                  }}
                >
                  {visibleLeaf.map((c) => (
                    <div key={c.id} className="dg-cell-wrap">
                      <div className="dg-cell">
                        <span
                          className="dg-skelbar"
                          style={{
                            width: c.id === '__select' ? 14 : `${45 + ((i * 13 + c.id.length * 7) % 45)}%`,
                            animationDelay: `${(i % 6) * 90}ms`,
                          }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          ) : bodyRows.length === 0 ? (
            <div className="dg-state">{loading ? 'טוען…' : emptyMessage}</div>
          ) : (
            <div className="dg-body" style={{ height: totalSize }}>
              {virtualRows.map((vr) => {
                const row = bodyRows[vr.index];
                return (
                  <div
                    key={row.id}
                    role="row"
                    aria-rowindex={vr.index + 2}
                    aria-selected={
                      selectable ? (controlled ? rowIsSelected(row.id) : row.getIsSelected()) : undefined
                    }
                    tabIndex={onRowOpen && vr.index === tabRowIdx ? 0 : -1}
                    onFocus={() => setFocusIdx(vr.index)}
                    data-dg-rowindex={vr.index}
                    className={`dg-row${
                      (controlled ? rowIsSelected(row.id) : row.getIsSelected()) ? ' dg-row-sel' : ''
                    }${onRowOpen && !editMode ? ' dg-row-open' : ''}`}
                    style={{
                      gridTemplateColumns: template,
                      transform: `translateY(${vr.start}px)`,
                      height: ROW_H,
                    }}
                    onClick={editMode ? undefined : (e) => rowClick(e, row.original)}
                    onKeyDown={(e) => rowKeyDown(e, row)}
                  >
                    {row.getVisibleCells().map((cell) => {
                      const colId = cell.column.id;
                      if (colId === '__select') {
                        const checked = controlled ? rowIsSelected(row.id) : row.getIsSelected();
                        return (
                          <div key={cell.id} className="dg-cell dg-cell-fixed" role="gridcell">
                            <input
                              type="checkbox"
                              className="dg-check"
                              checked={checked}
                              onChange={
                                controlled
                                  ? (e) => toggleRowSel(row.id, e.target.checked)
                                  : row.getToggleSelectedHandler()
                              }
                              aria-label={`בחר שורה ${row.id}`}
                            />
                          </div>
                        );
                      }
                      return (
                        <div
                          key={cell.id}
                          className="dg-cell-wrap"
                          role={colId === headerCol ? 'rowheader' : 'gridcell'}
                        >
                          {renderDataCell(row, colId)}
                        </div>
                      );
                    })}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* ── pagination footer ── */}
      <div className="dg-foot">
        <div className="dg-pagesize">
          <span className="muted small">שורות בעמוד</span>
          <select
            value={pagination.pageSize}
            aria-label="שורות בעמוד"
            onChange={(e) =>
              setPagination((p) => ({ ...p, pageIndex: 0, pageSize: Number(e.target.value) }))
            }
          >
            {pageSizeOptions.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </div>
        {/* icon-only pager, names on hover — the console's own stroke-icon language */}
        <div className="dg-pager">
          <button
            className="btn ghost sm dg-pgbtn"
            aria-label="העמוד הראשון"
            title="העמוד הראשון"
            disabled={pagination.pageIndex === 0}
            onClick={() => setPagination((p) => ({ ...p, pageIndex: 0 }))}
          >
            <Ic p={IC_FIRST} />
          </button>
          <button
            className="btn ghost sm dg-pgbtn"
            aria-label="העמוד הקודם"
            title="העמוד הקודם"
            disabled={pagination.pageIndex === 0}
            onClick={() => setPagination((p) => ({ ...p, pageIndex: Math.max(0, p.pageIndex - 1) }))}
          >
            <Ic p={IC_PREV} />
          </button>
          <span className="dg-pageinfo num">
            עמוד {pagination.pageIndex + 1} מתוך {pageCount}
          </span>
          <button
            className="btn ghost sm dg-pgbtn"
            aria-label="העמוד הבא"
            title="העמוד הבא"
            disabled={pagination.pageIndex >= pageCount - 1}
            onClick={() =>
              setPagination((p) => ({ ...p, pageIndex: Math.min(pageCount - 1, p.pageIndex + 1) }))
            }
          >
            <Ic p={IC_NEXT} />
          </button>
          <button
            className="btn ghost sm dg-pgbtn"
            aria-label="העמוד האחרון"
            title="העמוד האחרון"
            disabled={pagination.pageIndex >= pageCount - 1}
            onClick={() => setPagination((p) => ({ ...p, pageIndex: pageCount - 1 }))}
          >
            <Ic p={IC_LAST} />
          </button>
        </div>
      </div>

      {/* ── header filter popover ── */}
      {openFilter && openFilterCol && openFilterKind && (
        <FilterPopover
          col={openFilterCol}
          kind={openFilterKind}
          value={filters[openFilter.key]}
          anchor={openFilter.rect}
          onApply={(v) => {
            setFilter(openFilter.key, v);
            setOpenFilter(null);
          }}
          onClear={() => {
            setFilter(openFilter.key, null);
            setOpenFilter(null);
          }}
          onClose={() => setOpenFilter(null)}
        />
      )}

      {/* toasts are drawn by <ToastHost/> in App.tsx — one stack for the whole app */}
    </div>
  );
}

// ── column show/hide picker ──────────────────────────────────────────────────
function ColumnPicker({
  columns,
  table,
}: {
  columns: GridColumn[];
  table: ReturnType<typeof useReactTable<GridRow>>;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open]);

  const hiddenCount = columns.filter((c) => !table.getColumn(c.key)?.getIsVisible()).length;

  return (
    <div className="dg-colpick" ref={ref}>
      <button
        className="btn ghost sm"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        עמודות{hiddenCount > 0 ? ` (${columns.length - hiddenCount}/${columns.length})` : ''}
      </button>
      {open && (
        <div className="dg-colpick-menu">
          <div className="dg-colpick-actions">
            <button className="link" onClick={() => table.toggleAllColumnsVisible(true)}>
              הצג הכל
            </button>
            <button
              className="link"
              onClick={() => {
                for (const c of columns) table.getColumn(c.key)?.toggleVisibility(false);
              }}
            >
              הסתר הכל
            </button>
          </div>
          {columns.map((c) => {
            const col = table.getColumn(c.key);
            if (!col) return null;
            return (
              <label key={c.key} className="dg-colpick-item" title={c.headerTitle ?? c.header}>
                <input
                  type="checkbox"
                  checked={col.getIsVisible()}
                  onChange={col.getToggleVisibilityHandler()}
                />
                <span>{c.header}</span>
              </label>
            );
          })}
        </div>
      )}
    </div>
  );
}
