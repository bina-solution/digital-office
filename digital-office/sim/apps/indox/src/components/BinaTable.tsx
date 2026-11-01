import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { RevoGrid } from '@revolist/react-datagrid';
import { ask, tell } from '../ask';
import { IC, Ic } from '../icons';

/**
 * bina-table (React) — the platform-standard table on RevoGrid (a framework-
 * agnostic web component). ONE config shape → a full-featured, Hebrew-first,
 * ERP-grade grid. Everything below is wired ONCE here and inherited by every
 * table: sort (+aria-sort), Hebrew filter panel, global search, column
 * reorder/resize (+persistence), pinning, density toggle (+persistence), row
 * numbers, virtualization, inline edit with VALIDATION + ROLLBACK + UNDO,
 * VISUAL RTL arrow keys, RTL scroll origin, empty/loading states, aria-live
 * announcements, and add/delete-row hooks.
 */
export interface BinaColumn {
  key: string;
  label: string;
  width?: number;
  editable?: boolean;
  sortable?: boolean;
  filter?: boolean;
  /** 'end' for numeric/amount columns (ERP convention), default 'start' */
  align?: 'start' | 'end' | 'center';
  /** pin the column to the RTL start (right) or end (left).
   *  ⚠ RevoGrid clips pinned headers in RTL — avoid until fixed upstream. */
  pin?: 'start' | 'end';
  /** display formatter (e.g. currency ₪, dates) — read-mode only, editing sees the raw value */
  format?: (value: unknown, row: Record<string, unknown>) => string;
  /** rich cell markup (pills/chips/bars) — returns an HTML STRING; use the
   *  exported `pillHtml`/`escapeHtml` helpers, never raw user input. Wins over format. */
  html?: (value: unknown, row: Record<string, unknown>) => string;
  /** start hidden (user can re-show via the column picker) */
  hidden?: boolean;
  /** return an error string to REJECT the edit (toast shown), null to accept */
  validate?: (value: unknown) => string | null | undefined;
  /** custom sort order (dd/mm/yyyy dates, status ranks…) — compares ROW objects */
  compare?: (a: Record<string, unknown>, b: Record<string, unknown>) => number;
}

// numeric-aware, Hebrew-locale-aware value comparator (default sort)
function defaultCompare(a: unknown, b: unknown): number {
  const ae = a == null || a === '', be = b == null || b === '';
  if (ae && be) return 0;
  if (ae) return -1;
  if (be) return 1;
  const na = Number(a), nb = Number(b);
  if (!isNaN(na) && !isNaN(nb)) return na - nb;
  return String(a).localeCompare(String(b), 'he', { numeric: true, sensitivity: 'base' });
}

export const escapeHtml = (v: unknown): string =>
  String(v ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] as string,
  );
/** status pill markup for `html:` columns — kind: ok|warn|bad|muted */
export const pillHtml = (text: unknown, kind: 'ok' | 'warn' | 'bad' | 'muted' = 'muted'): string =>
  text == null || text === '' ? '' : `<span class="pill ${kind}">${escapeHtml(text)}</span>`;

// he-IL display helpers for common ERP columns (use as `format:`)
export const fmtCurrency = (v: unknown): string =>
  v == null || v === ''
    ? ''
    : Number(v).toLocaleString('he-IL', { style: 'currency', currency: 'ILS' });
export const fmtDate = (v: unknown): string => {
  if (!v) return '';
  const d = new Date(String(v));
  return Number.isNaN(d.getTime()) ? String(v) : d.toLocaleDateString('he-IL');
};

export interface BinaTableProps {
  columns: BinaColumn[];
  data: Record<string, unknown>[];
  rowKey?: string;
  /** persistence key — column widths + density survive reloads per table */
  tableId?: string;
  loading?: boolean;
  onEdit?: (id: unknown, key: string, value: unknown) => void | Promise<void>;
  onAddRow?: () => void | Promise<void>;
  onDeleteRow?: (id: unknown) => void | Promise<void>;
  /** bulk-import hook: rows parsed from a CSV/XLSX file, keyed by column key */
  onImportRows?: (rows: Record<string, unknown>[]) => Promise<{ ok: number; fail: number }>;
  /** bulk-delete hook (ids by rowKey); enables the selection checkboxes */
  onDeleteRows?: (ids: unknown[]) => Promise<{ ok: number; fail: number }>;
  /** row-selection checkboxes (default: on when onDeleteRows is provided) */
  selectable?: boolean;
  addLabel?: string;
  searchable?: boolean;
  searchPlaceholder?: string;
  /** show the CSV export button (default true) */
  exportable?: boolean;
  /** client-side pagination page size (e.g. 25). Omit = free virtual scroll. */
  pageSize?: number;
  /** open a row (navigation/drawer) on click; colKey = the clicked column,
   *  so pages can restrict opening to e.g. the ID column on editable grids */
  onRowClick?: (row: Record<string, unknown>, colKey?: string) => void;
  /** quick-filter chips above the toolbar (single-select; 'הכל' is added) */
  quickFilters?: { key: string; label: string; fn: (row: Record<string, unknown>) => boolean }[];
  /** show the column picker (default: true when any column is hideable/hidden) */
  columnPicker?: boolean;
  /** 'server': data/rowCount come from the parent; sort/search/page changes
   *  emit onState instead of filtering locally (DataGrid.tsx contract) */
  mode?: 'client' | 'server';
  rowCount?: number;
  onState?: (s: BinaTableState) => void;
  height?: number;
  /** Fill the parent instead of standing at a fixed pixel height. A grid that hardcodes its own
   *  height forces the page around it to be taller than the viewport, which is how you end up with
   *  two scrollbars: the grid's, and the document's behind it. */
  fill?: boolean;
  theme?: string;
}

export interface BinaTableState {
  page: number;
  pageSize: number | null;
  search: string;
  sort: { key: string; dir: 'asc' | 'desc' } | null;
}

// Hebrew localization for RevoGrid's filter panel (its default UI is English/LTR)
const FILTER_CONFIG = {
  localization: {
    captions: {
      title: 'סינון לפי',
      save: 'החל',
      reset: 'איפוס',
      ok: 'אישור',
      cancel: 'ביטול',
      add: 'הוסף תנאי',
      placeholder: 'ערך…',
      and: 'וגם',
      or: 'או',
      filterCondition: 'תנאי סינון',
      removeFilter: 'הסר סינון',
      reorderFilter: 'סדר מחדש',
    },
    filterNames: {
      none: 'ללא',
      empty: 'ריק',
      notEmpty: 'לא ריק',
      eq: 'שווה ל',
      notEq: 'שונה מ',
      begins: 'מתחיל ב',
      contains: 'מכיל',
      notContains: 'לא מכיל',
      eqN: '= (מספר)',
      neqN: '≠ (מספר)',
      gt: 'גדול מ',
      gte: 'גדול/שווה',
      lt: 'קטן מ',
      lte: 'קטן/שווה',
    },
  },
};

// DataGrid-feel rows (the tag_rules table the user prefers) / dense analyst mode
const ROW_COMFORT = 44;
const ROW_COMPACT = 34;
const stop = (e: Event) => e.stopPropagation();
// what a notice says was done — one as one, the number after its word as the toolbar's count has it: «נמחקה 1»,
// «נמחקו 5»; and of what failed: «, אחת נכשלה», «, 3 נכשלו»
const countDone = (n: number, alone: string, many: string) => `${n === 1 ? alone : many} ${n}`;
const countFailed = (n: number) => (n ? (n === 1 ? ', אחת נכשלה' : `, ${n} נכשלו`) : '');

// per-table UI prefs (column widths + density) — localStorage, never critical
function loadPrefs(tableId?: string): {
  sizes: Record<string, number>;
  compact?: boolean;
  manual?: boolean;
  pageSize?: number;
} {
  if (!tableId) return { sizes: {} };
  try {
    return { sizes: {}, ...JSON.parse(localStorage.getItem(`bt:${tableId}`) || '{}') };
  } catch {
    return { sizes: {} };
  }
}
function savePrefs(tableId: string | undefined, patch: Record<string, unknown>) {
  if (!tableId) return;
  try {
    const cur = loadPrefs(tableId);
    localStorage.setItem(`bt:${tableId}`, JSON.stringify({ ...cur, ...patch }));
  } catch {
    /* storage unavailable — prefs just don't persist */
  }
}

export default function BinaTable({
  columns,
  data,
  rowKey = 'id',
  tableId,
  loading = false,
  onEdit,
  onAddRow,
  onDeleteRow,
  onImportRows,
  onDeleteRows,
  selectable,
  addLabel = 'שורה',
  searchable = true,
  searchPlaceholder = 'חיפוש בטבלה…',
  exportable = true,
  pageSize: pageSizeProp,
  onRowClick,
  quickFilters,
  columnPicker,
  mode = 'client',
  rowCount,
  onState,
  height = 520,
  fill = false,
  theme = 'compact',
}: BinaTableProps) {
  const withSelection = selectable ?? !!onDeleteRows;
  const server = mode === 'server';
  // column visibility (picker) — persisted per table; falls back to column.hidden
  const [hiddenKeys, setHiddenKeys] = useState<string[]>(() => {
    const saved = loadPrefs(tableId) as { hidden?: string[] };
    return saved.hidden ?? columns.filter((c) => c.hidden).map((c) => c.key);
  });
  const [pickerOpen, setPickerOpen] = useState(false);
  // the table's own tools (density, columns, export, import, the focused row) behind «עוד» where the card is narrow
  const [toolsOpen, setToolsOpen] = useState(false);
  // quick-filter chips (single-select; null = הכל)
  const [activeQF, setActiveQF] = useState<string | null>(null);
  // THE WRAPPER OWNS SORTING in both modes (engine sort is always cancelled):
  // engine sort state dies with every source replacement (verified live — a
  // refresh/edit repaint silently unsorted the grid) and, under client
  // pagination, would only order the current page slice. Client mode sorts the
  // whole view below; server mode emits onState for the parent to refetch.
  const [sortState, setSortState] = useState<{ key: string; dir: 'asc' | 'desc' } | null>(null);
  // the grid element as STATE (callback ref): the grid mounts only after the
  // container is measured, so effects must re-run when the element appears —
  // a plain ref silently leaves listeners unbound on the first (null) pass
  const [gridEl, setGridEl] = useState<HTMLElement | null>(null);
  const ref = useRef<HTMLElement | null>(null);
  const bindGrid = useCallback((node: unknown) => {
    ref.current = (node as HTMLElement) ?? null;
    setGridEl((node as HTMLElement) ?? null);
  }, []);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const [availW, setAvailW] = useState<number | null>(null);
  const [q, setQ] = useState('');
  const [rowSize, setRowSize] = useState(() =>
    loadPrefs(tableId).compact ? ROW_COMPACT : ROW_COMFORT,
  );
  const focusRow = useRef<number | null>(null);

  // row selection (ids by rowKey). Kept in a ref so virtualized cellTemplates
  // always read fresh state; selCount mirrors it for React (toolbar).
  const selRef = useRef<Set<string>>(new Set());
  const [selCount, setSelCount] = useState(0);
  const toggleSel = useCallback((id: string) => {
    const s = selRef.current;
    if (s.has(id)) s.delete(id);
    else s.add(id);
    setSelCount(s.size);
  }, []);
  const clearSel = useCallback(() => {
    selRef.current = new Set();
    setSelCount(0);
  }, []);

  const colByKey = useMemo(() => {
    const m = new Map<string, BinaColumn>();
    for (const c of columns) m.set(c.key, c);
    return m;
  }, [columns]);

  // Fill the viewport: RevoGrid's own `stretch` is a no-op in RTL, and when the
  // columns underfill the container it LEFT-anchors them, leaving a dead gap at
  // the RTL start (looks broken/clipped). So we own the fill: measure the
  // container and scale column widths proportionally to span it exactly.
  useEffect(() => {
    const w = wrapRef.current;
    if (!w || typeof ResizeObserver === 'undefined') return;
    const measure = () => setAvailW(Math.max(0, Math.floor(w.getBoundingClientRect().width) - 54));
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(w);
    return () => ro.disconnect();
  }, []);

  // THE RTL STRATEGY: RevoGrid's `rtl` mode has hard layout bugs (content
  // translated off the RTL start with no scroll range, pinned-header clipping,
  // scroll drift on sort, inverted arrows, stretch no-op). So we run the ENGINE
  // in its bug-free LTR mode and flip the PRESENTATION: columns reversed (the
  // first configured column renders physically rightmost), cell/header text is
  // styled RTL via CSS, and load/sort snap the viewport to the far right.
  const revoColumns = useMemo(() => {
    const saved = loadPrefs(tableId).sizes;
    const visible = columns.filter((c) => !hiddenKeys.includes(c.key));
    const base = visible.map((c) => saved[c.key] || c.width || 160);
    const selW = withSelection ? 44 : 0;
    const total = base.reduce((a, b) => a + b, 0);
    // NATURAL WIDTHS. Stretch UP only when columns underfill the container
    // (full-width table, no dead gap); when they overflow, keep natural widths
    // and scroll horizontally like every real grid. Once the user resizes a
    // column (prefs.manual) their exact pixels win — no auto-stretch at all.
    const manual = !!loadPrefs(tableId).manual;
    const fill = availW ? availW - selW : 0;
    const factor = !manual && fill > 0 && total > 0 && total < fill ? fill / total : 1;
    const mapped = visible.map((c, i) => ({
      prop: c.key,
      name: c.label,
      size: Math.floor(base[i] * factor),
      sortable: c.sortable !== false,
      readonly: !c.editable,
      filter: c.filter !== false,
      ...(c.pin ? { pin: c.pin === 'start' ? 'colPinStart' : 'colPinEnd' } : {}),
      cellProperties: () => ({
        class: {
          ...(c.align && c.align !== 'start' ? { [`bt-align-${c.align}`]: true } : {}),
          ...(c.editable ? { 'bt-editable': true } : {}),
        },
      }),
      ...(!c.format && !c.html
        ? {
            // read-mode default: em-dash placeholder for empty cells
            cellTemplate: (
              h: (tag: string, p: Record<string, unknown>, children?: unknown) => unknown,
              props: { model?: Record<string, unknown>; prop?: string },
            ) => {
              const v = props.model?.[String(props.prop)];
              if (v == null || v === '') return h('span', { class: 'bt-null' }, '—');
              return typeof v === 'object' ? JSON.stringify(v) : String(v);
            },
          }
        : {}),
      ...(c.format && !c.html
        ? {
            cellTemplate: (
              h: (tag: string, p: Record<string, unknown>, children?: unknown) => unknown,
              props: { model?: Record<string, unknown>; prop?: string },
            ) => {
              const out = c.format!(props.model?.[String(props.prop)], props.model ?? {});
              return out === '' ? h('span', { class: 'bt-null' }, '—') : out;
            },
          }
        : {}),
      ...(c.html
        ? {
            cellTemplate: (
              h: (tag: string, p: Record<string, unknown>) => unknown,
              props: { model?: Record<string, unknown>; prop?: string },
            ) =>
              h('span', {
                class: 'bt-htmlcell',
                innerHTML: c.html!(props.model?.[String(props.prop)], props.model ?? {}),
              }),
          }
        : {}),
    }));
    mapped.reverse(); // LTR engine: last column renders rightmost = RTL first
    if (withSelection) {
      // selection checkboxes — appended after the reverse so they render at the
      // far RIGHT of the data columns, beside the row numbers (RTL leading edge)
      mapped.push({
        prop: '__sel',
        name: '',
        size: 44,
        sortable: false,
        readonly: true,
        filter: false,
        // center the checkbox; kill the default cell padding + text-overflow
        // (a 15px input inside a padded 40px cell overflowed → stray "…")
        cellProperties: () => ({ class: { 'bt-selcell': true } }),
        cellTemplate: (
          h: (tag: string, props: Record<string, unknown>, ...kids: unknown[]) => unknown,
          props: { model?: Record<string, unknown> },
        ) => {
          const id = String(props.model?.[rowKey] ?? '');
          // The box is 15px; what a finger hits is its LABEL, which fills the 44px cell. The label keeps the whole
          // press, as the box alone did: passed on, it moved the grid's focus to this cell, and on a phone the
          // grid draws its drag handle (30px) over the box before the press ends — the first tap ticked nothing,
          // and a ticked box under the handle could not be unticked.
          return h('label', { class: 'bt-sellbl', onMouseDown: stop, onTouchStart: stop, onClick: stop },
            h('input', {
              type: 'checkbox',
              class: 'bt-selbox',
              checked: selRef.current.has(id),
              onClick: (e: Event) => {
                e.stopPropagation();
                toggleSel(id);
              },
            }));
        },
      } as unknown as (typeof mapped)[number]);
    }
    return mapped;
  }, [columns, hiddenKeys, tableId, availW, withSelection, rowKey, toggleSel]);


  const view = useMemo(() => {
    if (server) return data; // server owns filtering/sorting/paging
    const qf = quickFilters?.find((f) => f.key === activeQF);
    let rows = qf ? data.filter((r) => qf.fn(r)) : data;
    const s = q.trim().toLowerCase();
    if (s) {
      rows = rows.filter((r) =>
        columns.some((c) => String(r[c.key] ?? '').toLowerCase().includes(s)),
      );
    }
    if (sortState) {
      const c = colByKey.get(sortState.key);
      const dir = sortState.dir === 'desc' ? -1 : 1;
      const key = sortState.key;
      rows = [...rows].sort(
        (a, b) => (c?.compare ? c.compare(a, b) : defaultCompare(a[key], b[key])) * dir,
      );
    }
    return rows;
  }, [server, q, data, columns, quickFilters, activeQF, sortState, colByKey]);

  // client pagination (optional — morning-datagrid parity). Page size comes
  // from the per-table pref (user's footer choice) else the prop default.
  const [page, setPage] = useState(1);
  const [pageSizePref, setPageSizePref] = useState<number | null>(
    () => loadPrefs(tableId).pageSize ?? null,
  );
  const effPageSize = pageSizePref ?? pageSizeProp ?? null;
  useEffect(() => setPage(1), [q, data, effPageSize]);
  const total = server ? (rowCount ?? data.length) : view.length;
  const pageCount = effPageSize ? Math.max(1, Math.ceil(total / effPageSize)) : 1;
  const safePage = Math.min(page, pageCount);
  const pageView = useMemo(
    () =>
      server || !effPageSize
        ? view
        : view.slice((safePage - 1) * effPageSize, safePage * effPageSize),
    [server, view, effPageSize, safePage],
  );

  // server mode: emit state changes (search debounced) — the DataGrid contract
  const onStateRef = useRef(onState);
  onStateRef.current = onState;
  useEffect(() => {
    if (!server) return;
    const t = window.setTimeout(() => {
      onStateRef.current?.({ page: safePage, pageSize: effPageSize, search: q, sort: sortState });
    }, q ? 350 : 0);
    return () => window.clearTimeout(t);
  }, [server, safePage, effPageSize, q, sortState]);

  // MUTATION CONTAINMENT (root fix, not a patch): RevoGrid commits edits by
  // mutating its source rows in place — so it gets COPIES, never `view`'s own
  // objects. Parent data stays pristine, which makes everything downstream
  // trivial: "previous value" is simply read from `view`, and revert/repaint
  // is one nonce bump that re-mints fresh copies.
  const [sourceNonce, setSourceNonce] = useState(0);
  const source = useMemo(
    () => pageView.map((r) => ({ ...r })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [pageView, sourceNonce],
  );
  const refreshSource = useCallback(() => setSourceNonce((n) => n + 1), []);

  // WRAPPER BRIDGE: the Stencil React wrapper re-syncs `columns` on prop change
  // but NOT `source` (verified live: fresh copies never reached the element).
  // One explicit effect keeps the element's data deterministically bound to
  // React state — the single place element state is written.
  // Replacing `source` makes RevoGrid rebuild its viewport and reset scroll to
  // 0, so the horizontal position is re-anchored across the assignment. The
  // anchor is the distance from the RTL reading start (= scroll max in the LTR
  // engine): a grid that was at the reading start stays there when server data
  // lands, and a user who scrolled away keeps their place on refreshes.
  useEffect(() => {
    const el = gridEl;
    if (!el) return;
    const vpOf = () =>
      [...el.querySelectorAll('revogr-viewport-scroll')].sort(
        (a, b) => b.clientWidth - a.clientWidth,
      )[0] as HTMLElement | undefined;
    const vp = vpOf();
    const fromStart = vp
      ? Math.max(0, vp.scrollWidth - vp.clientWidth - vp.scrollLeft)
      : 0;
    let tries = 0;
    let raf = 0;
    const apply = () => {
      (el as unknown as { source?: unknown }).source = source;
      // restore over the frames the rebuild spans (bounded, same rAF pattern
      // as the first-paint orchestration)
      raf = requestAnimationFrame(function tick() {
        const v = vpOf();
        if (v) {
          const max = v.scrollWidth - v.clientWidth;
          const want = Math.max(0, max - fromStart);
          if (max > 0 && Math.abs(v.scrollLeft - want) > 1) v.scrollLeft = want;
        }
        if (++tries < 8) raf = requestAnimationFrame(tick);
      });
    };
    // an editor left open across a source swap makes RevoGrid's teardown emit
    // a phantom afteredit with val:'' (verified live — it PATCHed a row);
    // clearFocus() closes the editor WITHOUT emitting afteredit
    const editing = el.querySelector('revogr-edit');
    if (editing) {
      (el as unknown as { clearFocus: () => Promise<void> })
        .clearFocus()
        .then(apply, apply);
    } else {
      apply();
    }
    return () => cancelAnimationFrame(raf);
  }, [gridEl, source]);

  // ── edit pipeline: validate → persist → rollback/undo ──────────────────────
  // the cell whose editor is actually open (set on beforeeditstart). RevoGrid
  // has a teardown race: commit with Enter + an immediate outside click makes
  // it re-save the dying editor's EMPTY value against the newly-focused next
  // row (verified live — it PATCHed a row the user never touched). afteredit
  // is honored only for the cell an editor was opened on.
  const editCellRef = useRef<{ rowIndex: number; prop: string } | null>(null);

  useEffect(() => {
    const el = gridEl;
    if (!el) return;

    const onEditStart = (e: Event) => {
      const d = (e as CustomEvent).detail as
        | { rowIndex?: number; prop?: string }
        | undefined;
      if (d && d.prop != null && typeof d.rowIndex === 'number')
        editCellRef.current = { rowIndex: d.rowIndex, prop: String(d.prop) };
    };

    const onAfterEdit = (e: Event) => {
      const d = (e as CustomEvent).detail as
        | { rowIndex?: number; prop?: string; val?: unknown }
        | undefined;
      if (!onEdit || !d || d.prop == null || typeof d.rowIndex !== 'number') return;
      const key = String(d.prop);
      const opened = editCellRef.current;
      editCellRef.current = null;
      if (!opened || opened.prop !== key || opened.rowIndex !== d.rowIndex) {
        refreshSource(); // phantom save — repaint pristine data, persist nothing
        return;
      }
      // `view` is pristine (RevoGrid mutated only its copy) — prev is right here
      const row = pageView[d.rowIndex] as Record<string, unknown> | undefined;
      const id = row?.[rowKey];
      const prev = row?.[key];
      if (String(d.val ?? '') === String(prev ?? '')) return;

      const col = colByKey.get(key);
      const err = col?.validate?.(d.val);
      if (err) {
        refreshSource(); // fresh copies of pristine data = the cell reverts
        tell('bad', `${col?.label ?? key}: ${err}`);
        return;
      }

      Promise.resolve(onEdit(id, key, d.val))
        .then(() => {
          tell('ok', 'נשמר', () => {
            Promise.resolve(onEdit(id, key, prev))
              .then(() => tell('ok', 'השינוי בוטל'))
              .catch(() => tell('bad', 'ביטול השינוי נכשל'));
          });
        })
        .catch((ex: unknown) => {
          refreshSource(); // rollback — never show a value the DB rejected
          tell('bad', ex instanceof Error ? ex.message : 'השמירה נכשלה');
        });
    };

    let lastPointer = 0;
    const onPointer = () => {
      lastPointer = performance.now();
    };
    const onFocus = (e: Event) => {
      const d = (e as CustomEvent).detail as
        | { rowIndex?: number; prop?: string; column?: { prop?: string } }
        | undefined;
      if (!d || typeof d.rowIndex !== 'number') return;
      focusRow.current = d.rowIndex;
      // afterfocus has no top-level prop — the column key lives at column.prop
      const prop = d.prop ?? d.column?.prop;
      // focus moving off the edited cell means its editor closed (e.g. Escape)
      const ec = editCellRef.current;
      if (ec && (ec.rowIndex !== d.rowIndex || ec.prop !== prop))
        editCellRef.current = null;
      // row open: a focus caused by an actual click (not keyboard), off the
      // selection gutter — the morning drawer / detail-page hook
      if (onRowClick && prop !== '__sel' && performance.now() - lastPointer < 400) {
        const row = pageView[d.rowIndex];
        if (row) onRowClick(row, prop != null ? String(prop) : undefined);
      }
    };

    // the wrapper owns ALL sorting (see sortState): cancel the engine sort in
    // both modes and cycle key asc→desc→off on header click
    const onBeforeSortApply = (e: Event) => {
      e.preventDefault();
      const d = (e as CustomEvent).detail as { column?: { prop?: string } } | undefined;
      const key = d?.column?.prop != null ? String(d.column.prop) : null;
      if (!key || key === '__sel') return;
      setPage(1);
      setSortState((cur) =>
        !cur || cur.key !== key
          ? { key, dir: 'asc' }
          : cur.dir === 'asc'
            ? { key, dir: 'desc' }
            : null,
      );
    };

    // persist column widths per table
    const onResize = (e: Event) => {
      const d = (e as CustomEvent).detail as Record<string, { prop?: string; size?: number }>;
      if (!d || !tableId) return;
      const sizes = { ...loadPrefs(tableId).sizes };
      for (const item of Object.values(d)) {
        if (item?.prop != null && typeof item.size === 'number') sizes[String(item.prop)] = item.size;
      }
      savePrefs(tableId, { sizes, manual: true });
    };

    el.addEventListener('pointerdown', onPointer);
    el.addEventListener('beforeeditstart', onEditStart);
    el.addEventListener('afteredit', onAfterEdit);
    el.addEventListener('afterfocus', onFocus);
    el.addEventListener('aftercolumnresize', onResize);
    el.addEventListener('beforesortingapply', onBeforeSortApply);
    return () => {
      el.removeEventListener('pointerdown', onPointer);
      el.removeEventListener('beforeeditstart', onEditStart);
      el.removeEventListener('afteredit', onAfterEdit);
      el.removeEventListener('afterfocus', onFocus);
      el.removeEventListener('aftercolumnresize', onResize);
      el.removeEventListener('beforesortingapply', onBeforeSortApply);
    };
  }, [gridEl, onEdit, pageView, rowKey, colByKey, refreshSource, tableId, onRowClick, server]);

  // ORCHESTRATED FIRST PAINT: when columns overflow, the grid must open at the
  // RTL reading start (= scroll max in the LTR engine). RevoGrid re-creates its
  // viewport during init (resetting scroll), so the grid stays INVISIBLE for its
  // first frames while we pin the position until it sticks; then reveal. The
  // first VISIBLE frame is always correct — nothing ever jumps on screen.
  // Bounded (≤ ~1s) and runs once per mount.
  const [ready, setReady] = useState(false);
  useEffect(() => {
    if (!gridEl) return;
    let stable = 0;
    let tries = 0;
    let raf = 0;
    const tick = () => {
      const vp = [...gridEl.querySelectorAll('revogr-viewport-scroll')].sort(
        (a, b) => b.clientWidth - a.clientWidth,
      )[0] as HTMLElement | undefined;
      const max = vp ? vp.scrollWidth - vp.clientWidth : 0;
      if (vp && max > 0 && vp.scrollLeft < max - 1) {
        vp.scrollLeft = max;
        stable = 0;
      } else {
        stable++;
      }
      tries++;
      if (stable >= 3 || tries > 60) {
        setReady(true);
        return;
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [gridEl]);

  // a11y semantics on the grid element
  useEffect(() => {
    const el = gridEl;
    if (!el) return;
    el.setAttribute('role', 'grid');
    el.setAttribute('aria-rowcount', String(view.length));
    el.setAttribute('aria-colcount', String(columns.length));
    el.setAttribute('aria-label', 'טבלת נתונים');
  }, [gridEl, view.length, columns.length]);

  // header sort indicators + aria-sort — painted by US (the engine never
  // applies sorting, so its own .asc/.desc classes never appear). Re-asserted
  // over several frames: RevoGrid re-renders headers asynchronously after a
  // columns/source assignment and wipes the classes. Headers are matched by
  // LABEL text — column virtualization renders only a subset of header cells,
  // so index math against the full columns array misidentifies them.
  useEffect(() => {
    const el = gridEl;
    if (!el) return;
    const sortLabel = sortState ? (colByKey.get(sortState.key)?.label ?? null) : null;
    let frames = 0;
    let raf = requestAnimationFrame(function tick() {
      const heads = [...el.querySelectorAll('revogr-header [class*=rgHeaderCell]')];
      heads.forEach((hd) => {
        const text = hd.querySelector('.header-content')?.textContent?.trim() ?? '';
        const active = !!(sortLabel && text === sortLabel);
        hd.classList.toggle('asc', active && sortState!.dir === 'asc');
        hd.classList.toggle('desc', active && sortState!.dir === 'desc');
        hd.setAttribute(
          'aria-sort',
          active ? (sortState!.dir === 'asc' ? 'ascending' : 'descending') : 'none',
        );
        const ind = hd.querySelector('.sort-indicator i');
        if (ind) {
          const want = active ? sortState!.dir : 'sort-off';
          if (ind.className !== want) ind.className = want;
        }
      });
      if (++frames < 12) raf = requestAnimationFrame(tick);
    });
    return () => cancelAnimationFrame(raf);
  }, [gridEl, sortState, colByKey, source]);

  // ── export (CSV, UTF-8 BOM so Hebrew opens correctly in Excel) ─────────────
  // exports the SELECTION when rows are selected, otherwise the current view
  const exportCsv = useCallback(() => {
    const esc = (v: unknown) => {
      const s = v == null ? '' : typeof v === 'object' ? JSON.stringify(v) : String(v);
      return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };
    const rows =
      selRef.current.size > 0
        ? view.filter((r) => selRef.current.has(String(r[rowKey])))
        : view;
    const lines = [
      columns.map((c) => esc(c.label)).join(','),
      ...rows.map((r) => columns.map((c) => esc(r[c.key])).join(',')),
    ];
    const blob = new Blob(['﻿' + lines.join('\n')], { type: 'text/csv;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `${tableId || 'table'}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  }, [columns, view, tableId, rowKey]);

  // ── bulk delete of the selection (asked once) ───────────────────────────────
  const deleteSelected = useCallback(async () => {
    if (!onDeleteRows || selRef.current.size === 0) return;
    const ids = [...selRef.current];
    // (one is said as one here too: the question about ONE row names it — by the first of its cells that says
    //  something, the way a person calls it; its key only when none does — and the notice counts as the toolbar does)
    const single = ids.length === 1;
    const row = single ? view.find((r) => String(r[rowKey]) === ids[0]) : undefined;
    const name = row && columns.filter((c) => c.key !== rowKey).map((c) => row[c.key])
      .find((v) => (typeof v === 'string' && v.trim() !== '') || typeof v === 'number');
    if (!(await ask({ title: single ? 'למחוק את השורה שנבחרה?' : 'למחוק את השורות שנבחרו?',
                      facts: [[single ? 'שורה' : 'שורות', single ? String(name ?? ids[0]) : String(ids.length)]], ok: 'מחיקה', danger: true })))
      return;
    const res = await onDeleteRows(ids);
    clearSel();
    tell(res.fail ? 'bad' : 'ok', countDone(res.ok, 'נמחקה', 'נמחקו') + countFailed(res.fail));
  }, [onDeleteRows, clearSel, view, columns, rowKey]);

  const selectAllView = useCallback(() => {
    selRef.current = new Set(view.map((r) => String(r[rowKey])));
    setSelCount(selRef.current.size);
    refreshSource(); // re-mint copies → checkbox cells re-render
  }, [view, rowKey, refreshSource]);

  // ── import (CSV / XLSX via SheetJS; headers matched by column label or key) ─
  const fileRef = useRef<HTMLInputElement | null>(null);
  const [importing, setImporting] = useState(false);
  const importFile = useCallback(
    async (file: File) => {
      if (!onImportRows) return;
      setImporting(true);
      try {
        const XLSX = await import('xlsx');
        const wb = XLSX.read(await file.arrayBuffer());
        const ws = wb.Sheets[wb.SheetNames[0]];
        const raw = XLSX.utils.sheet_to_json<Record<string, unknown>>(ws, { defval: '' });
        const byLabel = new Map(columns.map((c) => [c.label, c.key]));
        const keys = new Set(columns.map((c) => c.key));
        const rows = raw
          .map((r) => {
            const out: Record<string, unknown> = {};
            for (const [h, v] of Object.entries(r)) {
              const k = keys.has(h) ? h : byLabel.get(h);
              if (k && v !== '') out[k] = v;
            }
            return out;
          })
          .filter((r) => Object.keys(r).length > 0);
        if (rows.length === 0) {
          tell('bad', 'לא נמצאו שורות תואמות בקובץ');
          return;
        }
        const res = await onImportRows(rows);
        tell(res.fail ? 'bad' : 'ok', 'ייבוא: ' + countDone(res.ok, 'נוספה', 'נוספו') + countFailed(res.fail));
      } catch (e: unknown) {
        tell('bad', e instanceof Error ? e.message : 'הייבוא נכשל');
      } finally {
        setImporting(false);
        if (fileRef.current) fileRef.current.value = '';
      }
    },
    [onImportRows, columns],
  );

  const delFocused = useCallback(() => {
    const i = focusRow.current;
    if (i == null) return tell('bad', 'בחרו תא בשורה למחיקה');
    const id = pageView[i]?.[rowKey];
    if (id != null && onDeleteRow) onDeleteRow(id);
  }, [pageView, rowKey, onDeleteRow]);

  const toggleDensity = useCallback(() => {
    setRowSize((s) => {
      const next = s === ROW_COMFORT ? ROW_COMPACT : ROW_COMFORT;
      savePrefs(tableId, { compact: next === ROW_COMPACT });
      return next;
    });
  }, [tableId]);

  const showToolbar = searchable || onAddRow || onDeleteRow;

  const pickerEnabled =
    columnPicker ?? (columns.some((c) => c.hidden) || hiddenKeys.length > 0);
  const qfCounts = useMemo(() => {
    if (!quickFilters || server) return {};
    const m: Record<string, number> = {};
    for (const f of quickFilters) m[f.key] = data.filter((r) => f.fn(r)).length;
    return m;
  }, [quickFilters, data, server]);

  return (
    <div className={`bt-card${onRowClick ? ' bt-rowclick' : ''}${fill ? ' bt-card-fill' : ''}${
      availW != null && availW <= 466 ? ' bt-narrow' : '' /* a card 520px wide or less (availW is its width less 54) */
    }`}>
      {quickFilters && quickFilters.length > 0 && (
        <div className="bt-chipsrow" role="tablist">
          <button
            className={`bt-chip${activeQF == null ? ' active' : ''}`}
            onClick={() => setActiveQF(null)}
          >
            הכל <span className="num">{data.length}</span>
          </button>
          {quickFilters.map((f) => (
            <button
              key={f.key}
              className={`bt-chip${activeQF === f.key ? ' active' : ''}`}
              onClick={() => setActiveQF((cur) => (cur === f.key ? null : f.key))}
            >
              {f.label} <span className="num">{qfCounts[f.key] ?? ''}</span>
            </button>
          ))}
        </div>
      )}
      {showToolbar && (
        <div className="bt-toolbar">
          {searchable && (
            <input
              className="bt-search"
              placeholder={searchPlaceholder}
              value={q}
              onChange={(e) => setQ(e.target.value)}
              aria-label="חיפוש בטבלה"
            />
          )}
          {/* The selection's controls and «בחר הכל» stand in ONE place of one size: both are laid in the same
              cell (.bt-selzone) and the one that is not said is hidden, not removed. Removed, the three that
              replace the one took a new line of a toolbar that wraps, and the first tick moved every row
              34px down under the finger that had made it. */}
          {withSelection && (
            <span className="bt-selzone">
              <span className={selCount > 0 ? '' : 'off'}>
                {/* (one is said as one — «1 נבחרו» stood here — and in as few letters as any other count: a longer
                    sentence for one widens the zone and moves the rows. The number is its own token, and `data-n`.) */}
                <span className="bt-selcount" data-n={selCount}>{selCount === 1 ? 'נבחרה' : 'נבחרו'} <span className="num">{selCount}</span></span>
                {onDeleteRows && (
                  <button className="btn sm ghost danger" onClick={deleteSelected}>
                    מחק נבחרות
                  </button>
                )}
                <button
                  className="btn sm ghost"
                  onClick={() => {
                    clearSel();
                    refreshSource();
                  }}
                >
                  נקה בחירה
                </button>
              </span>
              <span className={selCount === 0 && view.length > 1 ? '' : 'off'}>
                <button className="btn sm ghost" onClick={selectAllView}>
                  בחר הכל
                </button>
              </span>
            </span>
          )}
          <span className="bt-spacer" />
          {/* IN A NARROW CARD — a phone, a small window — what is done to ROWS stays in sight (the search, the
              selection, «הוסף») and what is done to the TABLE goes behind one control. The toolbar wrapped
              instead: five lines of it, and under them ONE row of the table on a phone. The card's own measured
              width decides (`bt-narrow`, below) — a table stands in a phone's frame and in a 380px window of the
              desktop alike; wide, `.bt-tools` is not a box at all and nothing moved. */}
          <button className="btn sm ghost bt-more" aria-expanded={toolsOpen} title="כלי הטבלה: צפיפות, עמודות, ייצוא, ייבוא"
                  onClick={() => setToolsOpen((o) => !o)}>
            עוד
          </button>
          <span className={`bt-tools${toolsOpen ? ' open' : ''}`}>
          <button className="btn sm ghost" title="צפיפות שורות" onClick={toggleDensity}>
            {rowSize === ROW_COMFORT ? 'צפוף' : 'מרווח'}
          </button>
          {pickerEnabled && (
            <span className="bt-colpick">
              <button className="btn sm ghost" onClick={() => setPickerOpen((o) => !o)}>
                עמודות ({columns.length - hiddenKeys.length}/{columns.length})
              </button>
              {pickerOpen && (
                <span className="bt-colpick-menu" onMouseLeave={() => setPickerOpen(false)}>
                  {columns.map((c) => (
                    <label key={c.key} className="bt-colpick-item">
                      <input
                        type="checkbox"
                        checked={!hiddenKeys.includes(c.key)}
                        onChange={() => {
                          setHiddenKeys((cur) => {
                            const next = cur.includes(c.key)
                              ? cur.filter((k) => k !== c.key)
                              : [...cur, c.key];
                            savePrefs(tableId, { hidden: next });
                            return next;
                          });
                        }}
                      />
                      <span>{c.label}</span>
                    </label>
                  ))}
                </span>
              )}
            </span>
          )}
          {exportable && (
            <button className="btn sm ghost" onClick={exportCsv} title="ייצוא CSV (נפתח באקסל)">
              ייצוא
            </button>
          )}
          {onImportRows && (
            <>
              <input
                ref={fileRef}
                type="file"
                accept=".csv,.xlsx,.xls"
                style={{ display: 'none' }}
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) importFile(f);
                }}
              />
              <button
                className="btn sm ghost"
                disabled={importing}
                onClick={() => fileRef.current?.click()}
                title="ייבוא שורות מקובץ CSV / Excel"
              >
                {importing ? 'מייבא…' : 'ייבוא'}
              </button>
            </>
          )}
          {onDeleteRow && (
            <button className="btn sm ghost" onClick={delFocused} title="מחק את השורה שבמיקוד">
              מחק שורה
            </button>
          )}
          </span>
          {onAddRow && (
            <button className="btn sm bt-add" onClick={() => onAddRow()}>
              <Ic p={IC.plus} /> {addLabel}
            </button>
          )}
        </div>
      )}
      <div ref={wrapRef} className={'bina-table' + (fill ? ' bt-fill' : '')}
           style={fill ? { position: 'relative' } : { height, position: 'relative' }}>
        {/* render only once the container width is measured — the grid paints
            ONCE with correctly fitted columns (no visible resize/jump on load) */}
        {availW != null && (
        <div style={{ visibility: ready ? 'visible' : 'hidden', height: '100%' }}>
        {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
        <RevoGrid
          ref={bindGrid as any}
          columns={revoColumns as any}
          source={source as any}
          readonly={false}
          theme={theme}
          resize
          range
          filter={FILTER_CONFIG as any}
          canMoveColumns
          rowHeaders
          rowSize={rowSize}
        />
        </div>
        )}
        {loading && (
          <div className="bt-loading">
            <span className="bt-spinner" /> טוען נתונים…
          </div>
        )}
        {!loading && view.length === 0 && (
          <div className="bt-empty">
            {data.length === 0
              ? 'אין רשומות עדיין.'
              : 'לא נמצאו רשומות תואמות — נסו חיפוש אחר או נקו את הסינון.'}
          </div>
        )}
      </div>
      {/* footer — record count; optional client pager (morning-datagrid parity) */}
      <div className="bt-foot">
        <span className="bt-count num">
          {total === 1 ? 'רשומה אחת' : `${total.toLocaleString('he-IL')} רשומות`}
          {!server && q && view.length !== data.length
            ? ` מתוך ${data.length.toLocaleString('he-IL')}`
            : ''}
        </span>
        {effPageSize ? (
          <span className="bt-pager">
            <label className="bt-pagesize">
              שורות לעמוד{' '}
              <select
                value={effPageSize}
                onChange={(e) => {
                  const n = Number(e.target.value) || 25;
                  setPageSizePref(n);
                  savePrefs(tableId, { pageSize: n });
                }}
              >
                {[10, 25, 50, 100].map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </label>
            {/* the four buttons and the page they frame are one piece, each named and drawn — as in the
                office's shared grid (platform-base/bina-ui/bina-table.js) */}
            <span className="bt-pgnav">
              <button type="button" className="bt-pgbtn" aria-label="העמוד הראשון" title="העמוד הראשון"
                disabled={safePage <= 1} onClick={() => setPage(1)}>
                <Ic p={IC.first} />
              </button>
              <button type="button" className="bt-pgbtn" aria-label="העמוד הקודם" title="העמוד הקודם"
                disabled={safePage <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>
                <Ic p={IC.prev} />
              </button>
              <span className="bt-pageinfo num">
                עמוד {safePage} מתוך {pageCount}
              </span>
              <button type="button" className="bt-pgbtn" aria-label="העמוד הבא" title="העמוד הבא"
                disabled={safePage >= pageCount} onClick={() => setPage((p) => Math.min(pageCount, p + 1))}>
                <Ic p={IC.next} />
              </button>
              <button type="button" className="bt-pgbtn" aria-label="העמוד האחרון" title="העמוד האחרון"
                disabled={safePage >= pageCount} onClick={() => setPage(pageCount)}>
                <Ic p={IC.last} />
              </button>
            </span>
          </span>
        ) : (
          <span className="bt-foot-hint">גלילה חופשית — כל הרשומות זמינות</span>
        )}
      </div>
    </div>
  );
}
