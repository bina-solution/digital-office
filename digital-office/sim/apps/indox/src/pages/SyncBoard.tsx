import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, LEGAL_MOVES, MOVE_LABEL, SyncItem, SyncItemState, SyncRegistryEntry } from '../api';
import { tell } from '../ask';
import { columnOf, useColumns, wordOf } from '../words';

/**
 * INDOX · סנכרון · לוח פריטים — the operator's board.
 *
 * At 3,000+ documents a month across 8 pipes, nobody fixes items one at a time: they work by CAUSE
 * and in bulk. So the board is built around three moves —
 *   1. see everything not yet done, grouped the way it actually fails,
 *   2. select a lot of it at once (click, shift-range, select-all-matching),
 *   3. drag it to where it belongs, or hit one bulk action.
 * Illegal targets never accept a drop (see api.ts LEGAL_MOVES), so the board cannot put an item into
 * a state the pipeline can't honour.
 */

const STATE_LABELS: Record<SyncItemState, string> = {
  to_sync: 'לסנכרון',
  in_progress: 'בתהליך',
  synced: 'סונכרן',
  failed: 'נכשל',
};
const ORDER: SyncItemState[] = ['to_sync', 'in_progress', 'failed', 'synced'];
// the office's legend, as fills: what waits is lime, what is in motion is the sky, done is olive, failed is plum
const COL_TINT: Record<SyncItemState, string> = {
  to_sync: 'var(--lime)',
  in_progress: 'var(--sky)',
  failed: 'var(--red)',
  synced: 'var(--ok)',
};

const PAGE = 120;

function ago(iso?: string | null): string {
  if (!iso) return '';
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (m < 1) return 'עכשיו';
  if (m < 60) return `${m} דק׳`;
  if (m < 1440) return `${Math.round(m / 60)} שע׳`;
  const d = Math.round(m / 1440);               // (one is said as one: «1 ימים» is «יום»)
  return d === 1 ? 'יום' : `${d} ימים`;
}

type ColState = { items: SyncItem[]; total: number; allIds: string[]; loading: boolean };
const emptyCol = (): ColState => ({ items: [], total: 0, allIds: [], loading: true });

export default function SyncBoard({
  registry,
  onChanged,
}: {
  registry: SyncRegistryEntry[];
  onChanged: () => void;
}) {
  const typeCol = columnOf(useColumns(), 'TYPE');     // a document's type, worded as the service says it reads
  const [cols, setCols] = useState<Record<SyncItemState, ColState>>({
    to_sync: emptyCol(), in_progress: emptyCol(), failed: emptyCol(), synced: emptyCol(),
  });
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [selState, setSelState] = useState<SyncItemState | null>(null);
  const [pipe, setPipe] = useState('');
  const [code, setCode] = useState('');
  const [q, setQ] = useState('');
  const [stuckOnly, setStuckOnly] = useState(false);
  const [dragOver, setDragOver] = useState<SyncItemState | null>(null);
  const [dragging, setDragging] = useState(false);
  const [ghost, setGhost] = useState<{ x: number; y: number } | null>(null);
  const drag = useRef<{ id: string; x: number; y: number; on: boolean } | null>(null);
  // set only when a drag actually rendered, so a plain click is never swallowed by the threshold
  const dragHappened = useRef(false);
  const [busy, setBusy] = useState(false);
  const lastClicked = useRef<string | null>(null);

  // Below the board breakpoint the four columns would stack, and dragging a card down past three
  // other columns is a miserable phone gesture. So on narrow screens the board shows ONE state at a
  // time behind a segmented control, and the bulk bar — which is already the fastest path even on
  // desktop — becomes the whole interaction. Nothing is removed on mobile; it is re-shaped.
  const [narrow, setNarrow] = useState(
    typeof window !== 'undefined' ? window.matchMedia('(max-width:700px)').matches : false,
  );
  useEffect(() => {
    const mq = window.matchMedia('(max-width:700px)');
    const on = () => setNarrow(mq.matches);
    mq.addEventListener('change', on);
    return () => mq.removeEventListener('change', on);
  }, []);
  const [oneCol, setOneCol] = useState<SyncItemState>('failed');

  const loadCol = useCallback(
    async (st: SyncItemState) => {
      const r = await api.listSyncItems({
        sync: pipe || undefined, state: st, code: code || undefined,
        q: q || undefined, stuck: stuckOnly || undefined, limit: PAGE,
      });
      setCols((c) => ({ ...c, [st]: { items: r.items, total: r.total, allIds: r.all_ids || [], loading: false } }));
    },
    [pipe, code, q, stuckOnly],
  );

  const loadAll = useCallback(() => {
    setCols({ to_sync: emptyCol(), in_progress: emptyCol(), failed: emptyCol(), synced: emptyCol() });
    ORDER.forEach((st) => { loadCol(st).catch(() => undefined); });
  }, [loadCol]);

  useEffect(() => { loadAll(); }, [loadAll]);
  useEffect(() => { setSel(new Set()); setSelState(null); }, [pipe, code, q, stuckOnly]);

  // Selection is single-state by design: a bulk move is only meaningful when everything selected
  // shares a source state, and it keeps the legal-target set unambiguous.
  function toggle(it: SyncItem, ev: React.MouseEvent) {
    const st = it.state;
    // Computed here rather than inside a setState updater: the updater would read a stale `selState`,
    // and StrictMode double-invokes updaters, which made shift-ranges collapse to a single item.
    const sameState = selState === st;
    const next = sameState ? new Set(sel) : new Set<string>();
    const list = cols[st].items;
    const anchor = lastClicked.current;
    let ranged = false;

    if (ev.shiftKey && anchor && sameState) {
      const a = list.findIndex((x) => x.id === anchor);
      const b = list.findIndex((x) => x.id === it.id);
      if (a !== -1 && b !== -1) {
        for (let i = Math.min(a, b); i <= Math.max(a, b); i++) next.add(list[i].id);
        ranged = true;
      }
    }
    if (!ranged) {
      if (next.has(it.id)) next.delete(it.id); else next.add(it.id);
    }

    setSelState(next.size ? st : null);
    setSel(next);
    // a shift-range keeps its anchor, so you can widen the same range repeatedly
    if (!ev.shiftKey) lastClicked.current = it.id;
  }

  const clearSel = () => { setSel(new Set()); setSelState(null); };
  const allLoadedSelected = (st: SyncItemState) =>
    selState === st && cols[st].items.length > 0 && cols[st].items.every((i) => sel.has(i.id));

  function selectAllLoaded(st: SyncItemState) {
    setSelState(st);
    setSel(new Set(cols[st].items.map((i) => i.id)));
  }
  function selectAllMatching(st: SyncItemState) {
    setSelState(st);
    setSel(new Set(cols[st].allIds));
  }

  const selectedItems = useMemo(() => {
    if (!selState) return [];
    return cols[selState].items.filter((i) => sel.has(i.id));
  }, [cols, sel, selState]);

  /** Items may span pipes, so a bulk move is issued per pipe. */
  async function moveSelected(to: SyncItemState) {
    if (!sel.size || !selState) return;
    setBusy(true);
    try {
      const bySync = new Map<string, string[]>();
      const ids = new Set(sel);
      ORDER.forEach((st) => cols[st].items.forEach((it) => {
        if (ids.has(it.id)) bySync.set(it.sync, [...(bySync.get(it.sync) || []), it.id]);
      }));
      // ids selected via "all matching" may not be loaded — fall back to the filtered pipe
      if (!bySync.size && pipe) bySync.set(pipe, Array.from(ids));
      let moved = 0;
      for (const [s, list] of bySync) {
        const r = await api.moveSyncItems(s, list, to);
        moved += r.moved;
      }
      tell('ok', `${moved} פריטים הועברו ל${STATE_LABELS[to]}`);
      setSel(new Set()); setSelState(null);
      loadAll(); onChanged();
    } finally { setBusy(false); }
  }

  /** The one-click fix for the biggest failure class — apply the pipe's fallback type and re-queue. */
  async function applyFallback() {
    const groups = new Map<string, string[]>();
    selectedItems.forEach((it) => groups.set(it.sync, [...(groups.get(it.sync) || []), it.id]));
    setBusy(true);
    try {
      let n = 0; let t = '';
      for (const [s, ids] of groups) {
        const r = await api.applyFallbackType(s, ids);
        n += r.applied; t = r.type;
      }
      tell('ok', `${n} פריטים סווגו כ־${t} והוחזרו לסנכרון`);
      setSel(new Set()); setSelState(null);
      loadAll(); onChanged();
    } catch (e) {
      tell('bad', e instanceof Error ? e.message : 'הפעולה נכשלה');
    } finally { setBusy(false); }
  }

  // Offered only when EVERY selected item is an unclassified failure AND its pipe actually declares a
  // fallback type — a pipe without one has no location-implied answer, so there is nothing to apply.
  const canFallback =
    selState === 'failed'
    && selectedItems.length > 0
    && selectedItems.every((i) => i.error_code === 'type' && !!i.fallback_type);

  // failure causes present across the (filtered) registry — the board's fastest triage handle
  const causes = useMemo(() => {
    const m = new Map<string, { code: string; he: string; n: number }>();
    registry.forEach((e) => {
      if (pipe && e.name !== pipe) return;
      (e.failures || []).forEach((f) => {
        const cur = m.get(f.code) || { code: f.code, he: f.he, n: 0 };
        cur.n += f.n; m.set(f.code, cur);
      });
    });
    return Array.from(m.values()).sort((a, b) => b.n - a.n);
  }, [registry, pipe]);

  const legalTargets = selState ? LEGAL_MOVES[selState] : [];

  // ── dragging ────────────────────────────────────────────────────────────────
  // Pointer events, not HTML5 drag-and-drop: HTML5 DnD never fires on touch devices, which would
  // have made the board's headline gesture desktop-only. Pointer events cover mouse, pen and touch
  // with one code path, and let us render our own drag ghost.
  useEffect(() => {
    if (!dragging) return undefined;
    function colAt(x: number, y: number): SyncItemState | null {
      const el = document.elementFromPoint(x, y) as HTMLElement | null;
      const col = el?.closest('[data-col]') as HTMLElement | null;
      return (col?.dataset.col as SyncItemState) || null;
    }
    const move = (e: PointerEvent) => {
      e.preventDefault();
      setGhost({ x: e.clientX, y: e.clientY });
      const st = colAt(e.clientX, e.clientY);
      setDragOver(st && selState && (LEGAL_MOVES[selState] || []).includes(st) ? st : null);
    };
    const up = (e: PointerEvent) => {
      const st = colAt(e.clientX, e.clientY);
      setDragging(false); setGhost(null); setDragOver(null);
      drag.current = null;
      dragHappened.current = true;
      if (st && selState && (LEGAL_MOVES[selState] || []).includes(st)) moveSelected(st);
    };
    window.addEventListener('pointermove', move, { passive: false });
    window.addEventListener('pointerup', up);
    window.addEventListener('pointercancel', up);
    return () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      window.removeEventListener('pointercancel', up);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dragging, selState]);

  function onItemPointerDown(it: SyncItem, e: React.PointerEvent) {
    if (e.button != null && e.button !== 0) return;
    // Touch never arms a drag. A finger always wobbles a few pixels, so any movement threshold either
    // swallows taps (selection silently stops working) or triggers accidental drags while scrolling.
    // On touch the board is tap-to-select + the bulk bar, which is the faster path anyway.
    if (e.pointerType !== 'touch') {
      drag.current = { id: it.id, x: e.clientX, y: e.clientY, on: false };
    }
    // NOTE: pointerdown must NOT change the selection. It used to select the card here, and then the
    // click that followed ran toggle() on an already-selected card and immediately deselected it —
    // so clicking appeared to do nothing at all. Selection belongs to click; drag-start (below)
    // selects only when the drag actually begins on an unselected card.
  }
  function onItemPointerMove(e: React.PointerEvent) {
    const d = drag.current;
    if (!d || d.on) return;
    if (Math.abs(e.clientX - d.x) + Math.abs(e.clientY - d.y) > 6) {
      d.on = true;
      // dragging an unselected card drags just that card; dragging a selected one drags the selection
      const it = ORDER.flatMap((s2) => cols[s2].items).find((x) => x.id === d.id);
      if (it && !(sel.has(it.id) && selState === it.state)) {
        setSelState(it.state);
        setSel(new Set([it.id]));
      }
      setDragging(true);
      setGhost({ x: e.clientX, y: e.clientY });
    }
  }

  return (
    <div className="sb" data-sel={sel.size} data-narrow={String(narrow)}>
      <style>{`
        .sb-filters{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:10px 0 14px}
        .sb-filters select,.sb-filters input{padding:7px 10px;border:1px solid var(--line);border-radius:9px;font:inherit;background:var(--surface);color:var(--ink)}
        .sb-chip{padding:5px 11px;border-radius:999px;border:1px solid var(--line);background:var(--surface);cursor:pointer;font:inherit;font-size:12px;font-weight:600}
        .sb-chip.on{background:var(--accent-soft);border-color:var(--accent);color:var(--accent-d)}
        .sb-cols{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;align-items:start}
        .sb-col{background:var(--surface-2);border:1px solid var(--line);border-radius:14px;padding:10px;min-height:220px;transition:background .12s,border-color .12s}
        .sb-col.drop{border-color:var(--accent);background:var(--accent-soft);box-shadow:0 0 0 3px color-mix(in srgb,var(--accent) 15%,transparent)}
        .sb-col.no{opacity:.45}
        .sb-colh{display:flex;align-items:center;gap:8px;margin-bottom:8px}
        .sb-dot{width:10px;height:10px;border-radius:50%;flex:none}
        .sb-colh b{font-size:13px}
        .sb-colh .n{margin-inline-start:auto;font-size:12px;color:var(--muted)}
        .sb-list{display:flex;flex-direction:column;gap:6px;max-height:56vh;overflow-y:auto}
        .sb-it{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:8px 9px;cursor:pointer;user-select:none;display:flex;gap:8px;align-items:flex-start}
        .sb-body{flex:1;min-width:0}
        .sb-cb{width:17px;height:17px;flex:none;margin-top:2px;pointer-events:none}
        .sb-all{width:17px;height:17px;flex:none;cursor:pointer}
        .sb-selrow{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:7px}
        .sb-mini{padding:4px 9px;border:1px solid var(--line);border-radius:8px;background:var(--surface);font:inherit;font-size:11px;font-weight:600;cursor:pointer;color:var(--ink)}
        .sb-mini:hover{border-color:var(--accent);color:var(--accent-d)}
        .sb-mini.strong{background:var(--accent-soft);border-color:var(--accent);color:var(--accent-d)}
        .sb-it:hover{border-color:var(--accent)}
        .sb-it.sel{border-color:var(--accent);background:var(--accent-soft);box-shadow:0 0 0 2px color-mix(in srgb,var(--accent) 18%,transparent)}
        .sb-it.stuck{border-inline-start:3px solid var(--lime)}
        .sb-it .t{font-size:12.5px;font-weight:600;line-height:1.35}
        .sb-it .m{font-size:11px;color:var(--muted);margin-top:3px;display:flex;gap:6px;flex-wrap:wrap;align-items:center}
        .sb-it .er{font-size:11px;color:var(--red);margin-top:3px}
        .sb-more{text-align:center;font-size:11px;color:var(--muted);padding:6px}
        .sb-bulk{position:sticky;bottom:0;z-index:5;margin-top:12px;background:var(--olive);color:var(--olive-ink);border-radius:12px;padding:10px 14px;display:flex;align-items:center;gap:10px;flex-wrap:wrap;box-shadow:var(--shadow-lg)}
        .sb-bulk .btn{background:var(--surface);border:none;color:var(--ink)}
        .sb-bulk .gh{background:transparent;border:1px solid var(--side-line);color:inherit}
        .sb-ghost{position:fixed;z-index:80;pointer-events:none;background:var(--accent);color:var(--accent-ink);padding:7px 13px;border-radius:999px;font-size:12px;font-weight:700;box-shadow:var(--shadow-lg)}
        .sb-it{touch-action:pan-y}
        @media(max-width:1100px){.sb-cols{grid-template-columns:repeat(2,1fr)}}
        .sb-seg{display:flex;gap:6px;overflow-x:auto;padding-bottom:4px;margin-bottom:10px}
        .sb-segb{display:flex;align-items:center;gap:6px;padding:9px 12px;min-height:44px;border:1px solid var(--line);border-radius:999px;background:var(--surface);font:inherit;font-size:12px;font-weight:600;white-space:nowrap;cursor:pointer}
        .sb-segb.on{background:var(--accent-soft);border-color:var(--accent);color:var(--accent-d)}
        .sb-segb b{font-variant-numeric:tabular-nums}
        @media(max-width:700px){.sb-cols{grid-template-columns:1fr}.sb-list{max-height:none}
          .sb-it{padding:11px 12px}.sb-bulk .btn{min-height:44px}}
      `}</style>

      <div className="sb-filters">
        <select value={pipe} onChange={(e) => setPipe(e.target.value)} aria-label="מקור">
          <option value="">כל המקורות ({registry.length})</option>
          {registry.map((e) => <option key={e.name} value={e.name}>{e.name}</option>)}
        </select>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="חיפוש לפי שם או חברה…" style={{ minWidth: 220 }} />
        <button className={`sb-chip${stuckOnly ? ' on' : ''}`} onClick={() => setStuckOnly((v) => !v)}>
          תקועים בלבד
        </button>
        {causes.map((c) => (
          <button
            key={c.code}
            className={`sb-chip${code === c.code ? ' on' : ''}`}
            onClick={() => setCode(code === c.code ? '' : c.code)}
            title={c.he}
          >
            {c.he} · {c.n}
          </button>
        ))}
        <span className="muted" style={{ fontSize: 11, marginInlineStart: 'auto' }}>
          לחצו על פריט לבחירה · Shift לטווח · גררו לעמודה
        </span>
        {(pipe || code || q || stuckOnly) && (
          <button className="sb-chip" onClick={() => { setPipe(''); setCode(''); setQ(''); setStuckOnly(false); }}>
            נקה סינון
          </button>
        )}
      </div>

      {narrow && (
        <div className="sb-seg">
          {ORDER.map((st) => (
            <button
              key={st}
              className={`sb-segb${oneCol === st ? ' on' : ''}`}
              onClick={() => setOneCol(st)}
            >
              <span className="sb-dot" style={{ background: COL_TINT[st] }} />
              {STATE_LABELS[st]}
              <b>{cols[st].loading ? '…' : cols[st].total.toLocaleString('he-IL')}</b>
            </button>
          ))}
        </div>
      )}

      <div className="sb-cols">
        {ORDER.filter((st) => !narrow || st === oneCol).map((st) => {
          const col = cols[st];
          const isLegal = !!selState && (LEGAL_MOVES[selState] || []).includes(st);
          const dimmed = !!selState && selState !== st && !isLegal;
          return (
            <div
              key={st}
              data-col={st}
              className={`sb-col${dragOver === st && isLegal ? ' drop' : ''}${dimmed ? ' no' : ''}`}
            >
              <div className="sb-colh">
                {/* Selection has to be visible to be used. A checkbox is the affordance everyone
                    already knows; the previous micro-links read as captions, not controls. */}
                {!col.loading && col.items.length > 0 && (
                  <input
                    type="checkbox"
                    className="sb-all"
                    aria-label={`בחר הכל ב${STATE_LABELS[st]}`}
                    checked={allLoadedSelected(st)}
                    onChange={(e) => (e.target.checked ? selectAllLoaded(st) : clearSel())}
                  />
                )}
                <span className="sb-dot" style={{ background: COL_TINT[st] }} />
                <b>{STATE_LABELS[st]}</b>
                <span className="n">{col.loading ? '…' : col.total.toLocaleString('he-IL')}</span>
              </div>

              {!col.loading && col.items.length > 0 && (
                <div className="sb-selrow">
                  <button className="sb-mini" onClick={() => selectAllLoaded(st)}>
                    בחר {col.items.length}
                  </button>
                  {col.total > col.items.length && (
                    <button className="sb-mini strong" onClick={() => selectAllMatching(st)}>
                      בחר את כל {col.total.toLocaleString('he-IL')}
                    </button>
                  )}
                  {selState === st && sel.size > 0 && (
                    <button className="sb-mini" onClick={clearSel}>נקה</button>
                  )}
                </div>
              )}

              <div className="sb-list">
                {col.loading && <div className="muted small" style={{ padding: 8 }}>טוען…</div>}
                {!col.loading && !col.items.length && (
                  <div className="muted small" style={{ padding: 8 }}>אין פריטים</div>
                )}
                {col.items.map((it) => (
                  <div
                    key={it.id}
                    className={`sb-it${sel.has(it.id) && selState === st ? ' sel' : ''}${it.stuck ? ' stuck' : ''}`}
                    onPointerDown={(e) => onItemPointerDown(it, e)}
                    onPointerMove={onItemPointerMove}
                    onClick={(e) => { if (dragHappened.current) { dragHappened.current = false; return; } toggle(it, e); }}
                    title={it.company}
                  >
                    <input
                      type="checkbox"
                      className="sb-cb"
                      tabIndex={-1}
                      readOnly
                      checked={sel.has(it.id) && selState === st}
                      aria-hidden="true"
                    />
                    <div className="sb-body">
                    <div className="t">{it.title}</div>
                    <div className="m">
                      <span className="tag" title={it.kind}>{wordOf(typeCol, it.kind)}</span>
                      {!it.detected && <span className="tag" style={{ color: 'var(--amber)' }}>לא סווג</span>}
                      {it.stuck && <span className="tag" style={{ color: 'var(--amber)' }}>תקוע</span>}
                      <span>{it.sync}</span>
                      <span>· {ago(it.updated_at)}</span>
                    </div>
                    {it.error && <div className="er">{it.error}</div>}
                    </div>
                  </div>
                ))}
                {!col.loading && col.total > col.items.length && (
                  <div className="sb-more">
                    מוצגים {col.items.length} מתוך {col.total.toLocaleString('he-IL')}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {sel.size > 0 && selState && (
        <div className="sb-bulk">
          <b>{sel.size.toLocaleString('he-IL')}</b>
          <span>נבחרו מתוך {STATE_LABELS[selState]}</span>
          {canFallback && (
            <button className="btn" disabled={busy} onClick={applyFallback}>
              סווג לפי המקור והחזר לסנכרון
            </button>
          )}
          {legalTargets.map((t) => (
            <button key={t} className="btn" disabled={busy} onClick={() => moveSelected(t)}>
              {MOVE_LABEL[`${selState}>${t}`] || `העבר ל${STATE_LABELS[t]}`}
            </button>
          ))}
          <button className="gh btn" onClick={() => { setSel(new Set()); setSelState(null); }}>בטל בחירה</button>
          <span className="muted small" style={{ marginInlineStart: 'auto', color: 'inherit', opacity: .75 }}>
            אפשר גם לגרור לעמודה
          </span>
        </div>
      )}

      {dragging && ghost && (
        <div className="sb-ghost" style={{ left: ghost.x + 12, top: ghost.y + 12 }}>
          {sel.size.toLocaleString('he-IL')} פריטים · שחררו על עמודה
        </div>
      )}

    </div>
  );
}
