import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useInstanceLink } from '../instancesContext';
import { DRILL_PARAM, SOURCE_BLANK } from '../urlVocab';
import { api, DashBasis, DashboardStats } from '../api';
import { Ic } from '../components/DataGrid';
import { IC } from '../icons';
import WindowPicker, { SUBDAY_WINDOWS, loadWin, saveWin } from '../components/WindowPicker';
import { GROUP_CLASS, sourceLabel, statusKind, statusLabel, typeLabel } from '../vocab';

const POLL_MS = 15000;

/* The blank-source bucket travels as an empty SOURCE_TYPE, which cannot survive a URL query
   parameter — so it drills down through this sentinel, which DocumentBrowserPage turns into a
   real `{op:'is_null'}` filter. Linking `?source=` with an empty value would open a table of
   zero rows while the bar claimed 159. */
// SOURCE_BLANK moved to urlVocab.ts — one vocabulary for writer, parser and chips.

const nn = (v: unknown) => (Number.isFinite(Number(v)) ? Number(v) : 0);
const he = (n: number) => n.toLocaleString('he-IL');

/* ── the time window ──
   The control itself now lives in components/WindowPicker.tsx, because יומן פעולות is a
   second view under the same window and two copies of a segmented control drift. What stays
   here is what is TRUE OF THIS PAGE: the window is SERVER-SIDE (/dashboard/stats pushes it
   into a `<basis> >= …` WHERE clause, so a narrow window means the server never reads the rest
   of the table), and because the whole payload is recomputed under it, every number on this
   page — KPIs, bars, companies, recent — describes the SAME row set. A toggle that filtered
   the list but not the counts would read as broken. */

/* ── the window's DRIVING COLUMN ──
   Same segmented control, same visual language, sitting next to the window it
   modifies — because it is a modifier OF that window, not a second independent
   filter. Reading the pair right-to-left gives the sentence the operator wants:
   "עודכן · 30 דק׳" = rows UPDATED in the last 30 minutes.

   Why this control exists: the window used to cut on `created_at` only. When
   sync halts, nothing is CREATED, so "30 דק׳" read 0 across the whole board
   while the state machine was busy executing actions on 123 documents. The
   numbers were right about the wrong column.

   The option LIST comes from the server (`stats.bases`), not from a constant
   here, for two reasons: the set of usable columns is a property of the DATA
   (measured formats), and columns that cannot be offered still render, disabled,
   with the measured reason in their tooltip. A dropdown that silently omits
   DOC_DATE looks broken; one that says "פורמטים מעורבים" is an explanation.
   BASIS_FALLBACK only covers the first paint, before any response has arrived. */
const BASIS_FALLBACK: DashBasis[] = [
  { id: 'created_at', label: 'נוצר', available: true },
  { id: 'updated_at', label: 'עודכן', available: true },
];
const BASIS_KEY = 'dashBasis';
const BASIS_DEFAULT = 'created_at';
function loadBasis(): string {
  try {
    return localStorage.getItem(BASIS_KEY) || BASIS_DEFAULT;
  } catch {
    return BASIS_DEFAULT;
  }
}

function BigStat({
  k,
  v,
  sub,
  cls,
}: {
  k: string;
  v: number | string;
  sub?: string;
  cls?: string;
}) {
  return (
    <div className={`bigstat${cls ? ` ${cls}` : ''}`}>
      <div className="k">{k}</div>
      <div className="v num">{v}</div>
      {sub && <div className="bs-sub">{sub}</div>}
    </div>
  );
}

/** One labelled horizontal bar (label · track · value). */
/* `to` is what phase 8 adds: every observation opens the documents table filtered to EXACTLY the
   rows it counted. Without it a dashboard is a set of numbers you cannot act on — it can tell you
   23 documents failed and offer no way to reach those 23, so the next step is a manual search that
   may or may not reproduce the same set. Optional on purpose: a row with no answer to "which
   documents are these" stays a plain bar rather than a link that lands somewhere approximate. */
/* `unit` (N9): the extraction bars are PERCENTAGES and used to print as bare counts — "94" under
   a label, indistinguishable from the 94 documents the row beside it counted. A bar says its unit. */
function BarRow({
  label,
  value,
  max,
  cls,
  hint,
  to,
  unit,
}: {
  label: string;
  value: number;
  max: number;
  cls?: string;
  hint?: string;
  to?: string;
  /** printed after the value ('%'); counts print bare */
  unit?: string;
}) {
  const pct = max > 0 ? Math.max(2, Math.round((value / max) * 100)) : 0;
  const body = (
    <>
      <div className="bar-label" title={hint || label}>
        <bdi>{label}</bdi>
      </div>
      <div className="bar-track">
        <div className={`bar-fill${cls ? ` ${cls}` : ''}`} style={{ width: `${pct}%` }} />
      </div>
      <div className="bar-val num">{unit ? `${he(Math.round(value))}${unit}` : he(value)}</div>
    </>
  );
  if (!to) return <div className="barrow">{body}</div>;
  return (
    <Link className="barrow" to={to} style={{ textDecoration: 'none', color: 'inherit' }}
          title={`הצג את ${he(value)} המסמכים האלה`}>
      {body}
    </Link>
  );
}

export default function DashboardPage() {
  /* Links that must not leave the instance behind — see useInstanceLink. */
  const link = useInstanceLink();

  const [d, setD] = useState<DashboardStats | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [updated, setUpdated] = useState<Date | null>(null);
  const [win, setWinState] = useState<string>(loadWin);
  const [basis, setBasisState] = useState<string>(loadBasis);
  const [winBusy, setWinBusy] = useState(false);
  const inFlight = useRef(false);

  const load = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      const r = await api.dashboardStats(win, basis);
      setD(r);
      setErr(r.reachable === false ? r.error || 'מקור הנתונים אינו זמין' : null);
      setUpdated(new Date());
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      inFlight.current = false;
      setLoading(false);
      setWinBusy(false); // any completed load un-dims the window control
    }
  }, [win, basis]);

  /* Switching windows is a SERVER-SIDE refetch, so it gets the optimistic
     treatment: paint the new selection immediately, then load. Re-selecting
     the ACTIVE window is a no-op — a second click on "היום" must not cost
     another aggregate round trip (mailview's exact rule). The refetch itself
     rides the [load] effect below: changing `win` recreates `load`, and the
     effect's first act is calling it. */
  /* The ACTIVE basis's own description, straight from the server — `granularity` is what the
     window control below consults, so "which columns are day-shaped" is never hard-coded here. */
  const basisOpts = d?.bases || BASIS_FALLBACK;
  const activeBasis = basisOpts.find((b) => b.id === basis);
  const dayBasis = activeBasis?.granularity === 'day';

  const setWin = (id: string) => {
    if (id === win || winBusy) return;
    if (dayBasis && SUBDAY_WINDOWS.includes(id)) return; // inert; belt-and-braces for the keyboard
    saveWin(id);
    setWinBusy(true);
    setWinState(id);
  };

  /* Switching the basis is the same optimistic server-side refetch as the
     window (it recreates `load` via the [win, basis] dep, and the effect below
     calls it). Unavailable options are inert — the button is `disabled`, so
     this guard is belt-and-braces for keyboard activation.

     Switching TO a day-granularity basis while a sub-day window is selected also moves the
     window to `min_win` (today) in the same state update. Leaving `30m` selected against a
     disabled button would strand the control in a state the user cannot click out of, and the
     server would answer that request with today's numbers anyway — so the visible selection is
     corrected to the thing that is actually being computed, in one refetch rather than two. */
  const setBasis = (id: string) => {
    if (id === basis || winBusy) return;
    const opt = basisOpts.find((b) => b.id === id);
    if (!opt || opt.available === false) return;
    const nextWin =
      opt.granularity === 'day' && SUBDAY_WINDOWS.includes(win)
        ? opt.min_win || 'today'
        : null;
    if (nextWin) saveWin(nextWin);
    try {
      localStorage.setItem(BASIS_KEY, id);
    } catch {
      /* storage disabled — the control still works for this session */
    }
    setWinBusy(true);
    if (nextWin) setWinState(nextWin);
    setBasisState(id);
  };

  // The visibility guard belongs to the POLL, never to `load` itself.
  //
  // It used to be the second line of `load` — before `inFlight`, before the fetch, and crucially
  // before `finally { setLoading(false) }`. So a mount that happened while the document reported
  // hidden returned immediately with `loading` still true, and this page sat on "טוען לוח בקרה…"
  // forever with a perfectly healthy API behind it: `/incomingDocuments/dashboard/stats` answered
  // 200 with real JSON in ~300ms the whole time. `document.hidden` is true far more often than
  // "the user switched tabs" suggests — a background tab, a restored session, and on Windows a
  // window that is merely OCCLUDED by another one all report hidden — so this was reachable just
  // by having the console open behind something else.
  //
  // Same shape the notifications and chat UIs already use: skip the TICK while hidden, never the
  // first load, and re-load on becoming visible so the page is fresh the moment it is looked at.
  useEffect(() => {
    load();
    const id = setInterval(() => {
      if (!document.hidden) load();
    }, POLL_MS);
    const onVisible = () => {
      if (!document.hidden) load();
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      clearInterval(id);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [load]);

  const statusMax = useMemo(
    () => Math.max(1, ...(d?.by_status || []).map((s) => s.count)),
    [d],
  );
  const typeMax = useMemo(
    () => Math.max(1, ...(d?.by_type || []).map((t) => t.count)),
    [d],
  );
  const compMax = useMemo(
    () => Math.max(1, ...(d?.top_companies || []).map((c) => c.count)),
    [d],
  );
  const sourceMax = useMemo(
    () => Math.max(1, ...(d?.by_source || []).map((s) => s.count)),
    [d],
  );

  if (loading && !d) return <div className="spin">טוען לוח בקרה…</div>;

  const g = d?.groups || { done: 0, attention: 0, failed: 0, other: 0 };
  const total = nn(d?.total);
  const donePct = total ? Math.round((g.done / total) * 100) : 0;
  /* The extraction panel's own denominator — the documents that COMPLETED, straight from
     the server. `null` — not 0 — when the payload predates it, so the subtitle degrades to
     the old wording instead of claiming a confident "0 documents". A persisted (all-time)
     read model written before this field existed is served verbatim until the background
     refresher recomputes. */
  const extScored =
    d?.extraction && typeof d.extraction.scored === 'number' ? d.extraction.scored : null;
  const extSkipped = nn(d?.extraction?.skipped);

  return (
    <div>
      <div className="app-header">
        <div>
          <h1>לוח בקרה</h1>
          <div className="sub">
            תמונת מצב חיה של המסמכים הנכנסים — סטטוס, סוגים, חברות וציון חילוץ.
          </div>
        </div>
        <div className="actions">
          {/* the shared control — same component יומן פעולות renders, so the two views
              cannot disagree about what "שעה" offers or how it looks */}
          <WindowPicker value={win} onChange={setWin} busy={winBusy} blockSubday={dayBasis} />
          {/* WHICH COLUMN that window cuts on. Same control, same class, placed
              immediately beside it: in RTL the pair reads "עודכן · 30 דק׳".
              Options come from the server so unusable columns can render
              disabled WITH their measured reason rather than vanishing. */}
          <span
            className={`winseg${winBusy ? ' busy' : ''}`}
            role="radiogroup"
            aria-label="עמודת התאריך שהטווח נמדד לפיה"
          >
            {(d?.bases || BASIS_FALLBACK).map((b) => (
              <button
                key={b.id}
                role="radio"
                aria-checked={b.id === basis}
                disabled={b.available === false}
                title={
                  b.available === false
                    ? `לא זמין — ${b.reason || ''}`
                    : b.hint || ''
                }
                className={b.id === basis ? 'on' : ''}
                onClick={() => setBasis(b.id)}
              >
                {b.label}
              </button>
            ))}
          </span>
          {/* Rows the chosen basis cannot place on the timeline: they are
              EXCLUDED from every number on this page, so the count has to be
              visible or an empty board is ambiguous — "nothing happened" and
              "this column has no data" look identical otherwise. Shown only
              when it is non-zero and a window is actually applied. */}
          {d?.basis_active && nn(d?.basis_excluded) > 0 && (
            <span
              className="muted small"
              title={`${he(nn(d?.basis_eligible))} מתוך ${he(nn(d?.basis_rows))} שורות נושאות ערך בעמודה זו — היתר לא נכללות בספירה`}
            >
              ‏{he(nn(d?.basis_excluded))} ללא ערך בעמודה זו
            </span>
          )}
          {updated && (
            <span className="muted small">
              עודכן {updated.toLocaleTimeString('he-IL')}
            </span>
          )}
          {/* «חי» beat on beside «שגיאת רענון» — the sync screen's chip says what this one now says too */}
          <span className={`live${err ? ' paused' : ''}`}>
            <span className="beat" />
            {err ? 'לא מעודכן' : 'חי'}
          </span>
        </div>
      </div>

      {err && (
        <div className="callout warn">
          <b>שגיאת רענון.</b> {err}
          {d ? '. מוצג הנתון האחרון.' : ''}
        </div>
      )}

      {d && d.reachable !== false && (
        <>
          {/* KPI strip */}
          <div className="hud">
            <BigStat k="סה״כ מסמכים" v={he(total)} />
            <BigStat
              k="הושלמו"
              v={he(g.done)}
              sub={`${donePct}% מהמסמכים`}
              cls="ok"
            />
            <BigStat
              k="דורשים טיפול"
              v={he(g.attention)}
              cls={g.attention ? 'wait' : undefined}
            />
            <BigStat k="נכשלו" v={he(g.failed)} cls={g.failed ? 'err' : undefined} />
            <BigStat k="חברות" v={he(nn(d.companies))} cls="run" />
            <BigStat
              k="ציון חילוץ"
              v={`${nn(d.extraction?.overall)}%`}
              sub={extScored != null ? `מתוך ${he(extScored)} שהושלמו` : undefined}
              cls={nn(d.extraction?.overall) >= 60 ? 'ok' : 'wait'}
            />
          </div>

          {/* status health + extraction scoring — side by side on desktop,
              stacks on narrow screens (responsive auto-fit, see .dash-grid) */}
          <div className="dash-grid dash-grid-wide">
            <div className="card">
              <h3>בריאות הצינור — לפי סטטוס</h3>
              <div className="statebar" role="img" aria-label="סטטוס">
                {(['done', 'attention', 'failed', 'other'] as const).map((k) =>
                  g[k] > 0 ? (
                    <div
                      key={k}
                      className={`seg ${GROUP_CLASS[k]}`}
                      style={{ width: `${(g[k] / Math.max(1, total)) * 100}%` }}
                      title={he(g[k])}
                    />
                  ) : null,
                )}
              </div>
              {/* (a number reads one way on one screen: the legend said «13243» under a tile that said «13,243») */}
              <div className="statelegend" style={{ marginBottom: 6 }}>
                <span className="li">
                  <span className={`sw ${GROUP_CLASS.done}`} />
                  הושלמו<b className="num">{he(g.done)}</b>
                </span>
                <span className="li">
                  <span className={`sw ${GROUP_CLASS.attention}`} />
                  דורשים טיפול<b className="num">{he(g.attention)}</b>
                </span>
                <span className="li">
                  <span className={`sw ${GROUP_CLASS.failed}`} />
                  נכשלו<b className="num">{he(g.failed)}</b>
                </span>
                <span className="li">
                  <span className={`sw ${GROUP_CLASS.other}`} />
                  אחר<b className="num">{he(g.other)}</b>
                </span>
              </div>
              <div className="barlist">
                {(d.by_status || []).map((s) => (
                  <BarRow
                    key={s.status}
                    label={statusLabel(s.status)}
                    hint={s.status}
                    value={s.count}
                    max={statusMax}
                    cls={GROUP_CLASS[s.group] || GROUP_CLASS.other}
                    to={link(`/documents?${DRILL_PARAM.STATUS}=${encodeURIComponent(s.status)}`)}
                  />
                ))}
              </div>
            </div>

            {/* This panel judges EXTRACTION, so its population is the documents that
                FINISHED it — the same rows the "הושלמו" KPI counts. Everything else in
                `total` is still in flight or stuck: counting it here made a big Drive
                delivery look like an extraction regression, which is the one reading the
                score must never support. The excluded count is stated rather than hidden —
                those documents are fully present everywhere else on the board, and an
                operator has to be able to see WHY this denominator is smaller than the
                total above it. */}
            <div className="card">
              <h3>ציון חילוץ — לפי שדה</h3>
              <div className="scorehero" style={{ flexWrap: 'wrap' }}>
                <div className="score-big num">{nn(d.extraction?.overall)}%</div>
                <div className="score-sub">
                  {extScored != null
                    ? `כיסוי הערכים הסופיים על פני השדות — ${he(extScored)} מסמכים שהושלמו`
                    : 'כיסוי הערכים הסופיים על פני השדות'}
                </div>
                {/* N9: "ודאות ההתאמה" — the mean SELECTION_CERTAINTY, beside the coverage score
                    and with its OWN denominator (only the rows that carry a certainty). Not folded
                    into the headline: a coverage and a confidence are two different questions. */}
                {d.extraction?.certainty && (
                  <div
                    className="stat"
                    style={{ marginInlineStart: 'auto' }}
                    title={`ממוצע SELECTION_CERTAINTY על ${he(nn(d.extraction.certainty.rows))} מסמכים שנושאים ודאות — מדד נפרד מציון הכיסוי`}
                  >
                    ודאות ההתאמה
                    <b className="num">
                      {d.extraction.certainty.mean != null && nn(d.extraction.certainty.rows) > 0
                        ? `${Math.round(nn(d.extraction.certainty.mean))}%`
                        : '—'}
                    </b>
                    <span className="muted small num">{he(nn(d.extraction.certainty.rows))} מסמכים</span>
                  </div>
                )}
                {extSkipped > 0 && (
                  <div
                    className="muted small"
                    style={{ flexBasis: '100%' }}
                    title="מסמכים שטרם הושלמו — עדיין בעיבוד, ממתינים או תקועים; אינם נספרים בציון החילוץ"
                  >
                    ‏{he(extSkipped)} שטרם הושלמו — לא נספרים
                  </div>
                )}
              </div>
              <div className="barlist">
                {(d.extraction?.fields || []).map((f) => (
                  <BarRow
                    key={f.key}
                    label={f.label}
                    hint={[f.hint, f.applicable != null ? `מתוך ${he(nn(f.applicable))} מסמכים שהשדה חל עליהם` : '']
                      .filter(Boolean).join(' · ') || undefined}
                    value={f.pct}
                    max={100}
                    unit={f.unit || '%'}
                    cls={GROUP_CLASS[f.pct >= 60 ? 'done' : f.pct >= 30 ? 'attention' : 'failed']}
                  />
                ))}
              </div>
            </div>
          </div>

          {/* type distribution + source distribution + top companies.
              .dash-grid is auto-fit/minmax(300px), so the third card needs no CSS: three
              columns where there is room, wrapping down on its own below that. */}
          <div className="dash-grid">
            <div className="card">
              <h3>לפי סוג מסמך</h3>
              <div className="barlist">
                {(d.by_type || []).map((t) => (
                  <BarRow
                    key={t.type}
                    label={typeLabel(t.type)}
                    value={t.count}
                    max={typeMax}
                    cls={GROUP_CLASS.done}
                    to={link(`/documents?${DRILL_PARAM.TYPE}=${encodeURIComponent(t.type)}`)}
                  />
                ))}
              </div>
            </div>
            {/* Rendered only once the server actually sends by_source: an all-time payload
                persisted before this field existed is served verbatim until the background
                refresher recomputes, and an empty card would read as "no sources". */}
            {(d.by_source || []).length > 0 && (
              <div className="card">
                <h3>לפי מקור</h3>
                <div className="barlist">
                  {(d.by_source || []).map((s) => (
                    <BarRow
                      key={s.source || SOURCE_BLANK}
                      label={sourceLabel(s.source)}
                      hint={s.source || 'SOURCE_TYPE ריק'}
                      value={s.count}
                      max={sourceMax}
                      cls={GROUP_CLASS.other}
                      to={link(`/documents?${DRILL_PARAM.SOURCE_TYPE}=${encodeURIComponent(s.source || SOURCE_BLANK)}`)}
                    />
                  ))}
                </div>
              </div>
            )}
            <div className="card">
              <h3>חברות מובילות</h3>
              {(d.top_companies || []).length === 0 ? (
                <div className="muted small" style={{ padding: '8px 2px' }}>
                  אין חברות מזוהות עדיין.
                </div>
              ) : (
                <div className="barlist">
                  {(d.top_companies || []).map((c) => (
                    <BarRow
                      key={c.name}
                      label={c.name}
                      value={c.count}
                      max={compMax}
                      cls="run"
                    />
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* recent documents */}
          <div className="card">
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}
            >
              <h3 style={{ margin: 0 }}>מסמכים אחרונים</h3>
              {/* /documents resolves to the ACTIVE instance's table (App.tsx). Never hardcode an
                  instance id here — it used to pin the dashboard to one company's table. */}
              <Link to={link('/documents')} className="link" title="טבלת המסמכים המלאה של המופע">
                לכל המסמכים <Ic p={IC.arrowLeft} />
              </Link>
            </div>
            <div className="tbl-scroll" style={{ marginTop: 12 }}>
            <table className="table" style={{ minWidth: 440 }}>
              <thead>
                <tr>
                  <th>שם</th>
                  <th>חברה</th>
                  <th>סוג</th>
                  <th>סטטוס</th>
                  <th>תאריך</th>
                </tr>
              </thead>
              <tbody>
                {(d.recent || []).length === 0 && (
                  <tr>
                    <td colSpan={5} className="empty">
                      אין מסמכים עדיין.
                    </td>
                  </tr>
                )}
                {(d.recent || []).map((r, i) => (
                  <tr key={`${r.id}:${i}`}>
                    <td className="mono small">{r.name || r.id || '—'}</td>
                    <td>{r.company || <span className="muted">—</span>}</td>
                    <td>{r.type ? typeLabel(r.type) : <span className="muted">—</span>}</td>
                    <td>
                      <span className={`pill ${statusKind(r.status)}`}>
                        {statusLabel(r.status)}
                      </span>
                    </td>
                    <td className="muted small num">{r.date || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

