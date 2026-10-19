import { useEffect, useRef, useState } from 'react';
import { api, ApiError, DrainAccepted, DrainRequest, PipelineStatus } from '../api';
import { Ic } from './DataGrid';
import { IC } from '../icons';

/* feather chevron-down — the card's minimize control, same stroke language as the grid */
const IC_COLLAPSE = IC.chevronDown;

/**
 * THE PIPELINE, ON EVERY SCREEN.
 *
 * Until now the console could watch the state machine but never drive it: starting a drain meant
 * a basic-auth n8n webhook the browser cannot call, and answering "is anything even running" meant
 * SQL against two different databases. This strip is the always-visible half of that: one poll,
 * one row, and one button that is allowed to start exactly one drainer.
 *
 * Four decisions worth stating, because each could reasonably have gone the other way:
 *
 * 1. EVERY NUMBER IS THE SERVER'S, INCLUDING THE CLOCK. `as_of` is `now()` from the INDOX
 *    database. The browser here renders ~3h ahead of it, so "עודכן …" built from `Date.now()`
 *    would be a freshness claim that is wrong by hours while looking precise. Elapsed is likewise
 *    `as_of - started_at`, two timestamps from the same database, never one of each.
 *
 * 2. THE DRAIN BAR IS INDETERMINATE, AND STAYS THAT WAY. A drain does not know its denominator —
 *    it discovers work as lanes report back — so there is no honest percentage to draw. Same rule
 *    RunProgress applies to a sync pass that has not planned its units yet: an indeterminate bar
 *    says "working, extent unknown", which is the true statement. The n8n link is rendered from
 *    the first poll onward for the same reason it is there: the run you most want to open is the
 *    one that has not come back yet.
 *
 * 3. A 409 IS NOT AN ERROR HERE. The server enforces the single-drainer rule (a second drainer
 *    multiplies the lane ceiling rather than adding throughput). When it refuses, the useful
 *    response is not "your click failed" — it is the run that already exists, with its link.
 *
 * 4. A NUMBER NOBODY KNOWS RENDERS AS "—". The payload flags which of its three sources answered
 *    (`db_available` / `n8n_available` / `locks_available`); an unreachable n8n reporting "0
 *    drivers, 0 errors" is the false-clean this product keeps having to un-learn.
 */

/** Poll cadence. Fast while something is running, slow while nothing is, and NOTHING at all
 *  while the tab is hidden — a background tab polling every 5s for hours buys no one anything. */
const POLL_RUNNING_MS = 5000;
const POLL_IDLE_MS = 20000;
/** Cheap, network-free re-check while hidden, so a missed `visibilitychange` cannot freeze the
 *  bar for the life of the page. */
const HIDDEN_RECHECK_MS = 5000;
/** Polls a "sent"/"already running" notice survives once no drain is visible. */
const NOTICE_POLLS = 3;

/** The server adds these to `PipelineStatus`: which of its three sources actually answered.
 *  Declared here rather than in api.ts because the CONTRACT is the shared shape; this is the
 *  degradation detail only the renderer needs. */
type PipelineStatusFull = PipelineStatus & {
  db_available?: boolean;
  n8n_available?: boolean;
  locks_available?: boolean;
};

/** The 409 body — the drain that is already running. */
interface DrainConflict {
  error?: string;
  message?: string;
  execution_id?: string;
  mode?: string;
  started_at?: string;
  n8n_url?: string;
}

const MODES: {
  key: string;
  label: string;
  hint: string;
  mode: DrainRequest['mode'];
  dry: boolean;
}[] = [
  { key: 'all', label: 'הכל', hint: 'עובר על כל הטבלה', mode: 'all', dry: false },
  { key: 'changed', label: 'שהשתנו', hint: 'רק מסמכים שהשתנו לאחרונה', mode: 'changed', dry: false },
  { key: 'dry', label: 'יבש', hint: 'עובר על הכל, לא משגר שום פעולה', mode: 'all', dry: true },
];

/**
 * What the operator asked for, in the words of the picker.
 *
 * TWO VOCABULARIES, and the second one is not this app's. When the server knows which INDOX mode
 * a drain was fired with it says `all` / `changed` / `ids`; when it does not — a drain one of the
 * schedules started, or someone else's webhook call — it falls back to n8n's own TRIGGER mode,
 * which is a different fact. Both are named here so neither leaks a raw English token into a
 * Hebrew bar. `all + dry` and `all` are the same mode with very different meanings, hence the flag.
 */
const MODE_LABELS: Record<string, string> = {
  all: 'הכל',
  changed: 'שהשתנו',
  ids: 'לפי מזהים',
  // n8n trigger modes — what STARTED the run, not what it was asked to cover
  trigger: 'מתוזמן',
  webhook: 'חיצוני',
  manual: 'ידני',
  retry: 'ניסיון חוזר',
};

function modeLabel(mode: string | undefined, dry?: boolean): string {
  if (dry) return 'יבש';
  const key = String(mode || '').toLowerCase();
  return MODE_LABELS[key] || key;
}

/**
 * Postgres hands back `2026-08-23 16:45:00.296501+00`; `Date` wants the `T` and a two-digit
 * offset. Returns null rather than an Invalid Date, so a caller renders nothing instead of "NaN"
 * — an unparsed timestamp must not become a confident wrong duration.
 */
function dbDate(raw: string | null | undefined): Date | null {
  if (!raw) return null;
  const iso = String(raw).trim().replace(' ', 'T').replace(/([+-]\d{2})$/, '$1:00');
  const ms = Date.parse(iso);
  return Number.isNaN(ms) ? null : new Date(ms);
}

function elapsed(from: string | undefined, to: string | undefined): string | null {
  const a = dbDate(from);
  const b = dbDate(to);
  if (!a || !b) return null;
  const s = Math.max(0, Math.round((b.getTime() - a.getTime()) / 1000));
  const hh = Math.floor(s / 3600);
  const mm = Math.floor((s % 3600) / 60);
  const ss = s % 60;
  const pad = (n: number) => String(n).padStart(2, '0');
  return hh ? `${hh}:${pad(mm)}:${pad(ss)}` : `${mm}:${pad(ss)}`;
}

export default function PipelineBar() {
  const [status, setStatus] = useState<PipelineStatusFull | null>(null);
  const [err, setErr] = useState<string | null>(null);
  /* [2026-08-24, owner order] The strip became a FLOATING bar, minimized by default: the
     pipeline stays one glance away on every screen without spending a fixed row of the
     viewport on it. The choice persists per browser. */
  const [open, setOpen] = useState<boolean>(() => {
    try {
      return localStorage.getItem('indox.pipeline.open') === '1';
    } catch {
      return false;
    }
  });
  const toggleOpen = () =>
    setOpen((v) => {
      const next = !v;
      try {
        localStorage.setItem('indox.pipeline.open', next ? '1' : '0');
      } catch {
        /* private mode — the session just won't remember */
      }
      return next;
    });
  /** An older BFF simply 404s these routes. Hide the strip entirely rather than render a
   *  permanently broken one — and stop polling something that will never exist. */
  const [absent, setAbsent] = useState(false);
  const [hidden, setHidden] = useState(false);
  const [picker, setPicker] = useState(false);
  const [firing, setFiring] = useState(false);
  const [fired, setFired] = useState<(DrainAccepted & { n8n_url?: string }) | null>(null);
  const [conflict, setConflict] = useState<DrainConflict | null>(null);
  /** Set by the polling effect so a click can force the next poll NOW — the bar must reflect a
   *  drain it just started, not up to 20s later. */
  const poke = useRef<() => void>(() => {});
  const wrap = useRef<HTMLDivElement | null>(null);
  /** Polls observed since a notice was raised. A drain can finish between the click and the next
   *  poll — a dry run over an empty selection does — so "clear it once the drain is visible"
   *  alone would leave the notice on screen for the life of the page. */
  const noticeAge = useRef(0);

  useEffect(() => {
    let dead = false;
    let timer: number | null = null;

    const schedule = (ms: number) => {
      if (dead) return;
      timer = window.setTimeout(tick, ms);
    };

    async function tick() {
      if (dead) return;
      if (typeof document !== 'undefined' && document.hidden) {
        setHidden(true);
        schedule(HIDDEN_RECHECK_MS);
        return;
      }
      setHidden(false);
      try {
        const next = (await api.pipelineStatus()) as PipelineStatusFull;
        if (dead) return;
        setStatus(next);
        setErr(null);
        if (next.drain) {
          // The run the 409 pointed at is now the run this bar renders on its own — the notice
          // has nothing left to add.
          noticeAge.current = 0;
          setConflict(null);
          setFired(null);
        } else {
          noticeAge.current += 1;
          if (noticeAge.current >= NOTICE_POLLS) {
            setConflict(null);
            setFired(null);
          }
        }
        schedule(next.drain ? POLL_RUNNING_MS : POLL_IDLE_MS);
      } catch (e: unknown) {
        if (dead) return;
        if (e instanceof ApiError && e.status === 404) {
          setAbsent(true);
          return; // deliberately not rescheduled
        }
        setErr(e instanceof Error ? e.message : String(e));
        schedule(POLL_IDLE_MS);
      }
    }

    poke.current = () => {
      if (timer) window.clearTimeout(timer);
      timer = null;
      tick();
    };

    const onVisible = () => {
      if (typeof document !== 'undefined' && !document.hidden) poke.current();
    };
    document.addEventListener('visibilitychange', onVisible);

    tick();
    return () => {
      dead = true;
      document.removeEventListener('visibilitychange', onVisible);
      if (timer) window.clearTimeout(timer);
      poke.current = () => {};
    };
  }, []);

  // close the mode picker on an outside click or Escape — a menu that only closes by choosing is
  // a menu you cannot back out of
  useEffect(() => {
    if (!picker) return;
    const onDown = (ev: MouseEvent) => {
      if (wrap.current && !wrap.current.contains(ev.target as Node)) setPicker(false);
    };
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === 'Escape') setPicker(false);
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [picker]);

  async function fire(mode: DrainRequest['mode'], dry: boolean) {
    setPicker(false);
    setFiring(true);
    setErr(null);
    setConflict(null);
    noticeAge.current = 0;
    try {
      const accepted = await api.startDrain({ mode, dry });
      setFired(accepted as DrainAccepted & { n8n_url?: string });
      poke.current();
    } catch (e: unknown) {
      if (e instanceof ApiError && e.status === 409) {
        // Not an error: the server is holding the single-drainer rule and handing back the run
        // that already owns the lanes.
        setConflict((e.body || {}) as DrainConflict);
        poke.current();
      } else {
        setErr(e instanceof Error ? e.message : String(e));
      }
    } finally {
      setFiring(false);
    }
  }

  if (absent) return null;
  if (!status && !err) return null; // nothing true to say before the first answer

  const s = status;
  const n8nUp = s ? s.n8n_available !== false : false;
  const dbUp = s ? s.db_available !== false : false;
  const running = !!s?.drain;
  const num = (v: number | undefined, known: boolean) =>
    known && v !== undefined ? String(v) : '—';

  const runElapsed = s?.drain ? elapsed(s.drain.started_at, s.as_of) : null;
  const updated = dbDate(s?.as_of);
  const errCount = n8nUp ? (s?.errors_1h ?? 0) : 0;
  const dotKind = running ? 'run' : err || !n8nUp || !dbUp ? 'bad' : 'idle';

  /* ── collapsed: a quiet floating pill — state dot, one word, the error count ── */
  if (!open) {
    return (
      <button
        className="pipefab"
        onClick={toggleOpen}
        title={
          running
            ? `ניקוז רץ (${modeLabel(s?.drain?.mode)})${runElapsed ? ` · ${runElapsed}` : ''} — לחצו לפרטים`
            : err
              ? `שגיאת סטטוס: ${err} — לחצו לפרטים`
              : 'מצב הצנרת והפעלת ניקוז — לחצו לפתיחה'
        }
        aria-label="פתיחת בר הצנרת"
        aria-expanded={false}
      >
        <span className={`pipefab-dot ${dotKind}`} aria-hidden="true" />
        <span>{running ? `ניקוז רץ${runElapsed ? ` · ${runElapsed}` : ''}` : 'ניקוז'}</span>
        {errCount > 0 && (
          <b className="pipefab-err num" title="הרצות n8n שנכשלו בשעה האחרונה">
            {errCount}
          </b>
        )}
      </button>
    );
  }

  /* ── expanded: the full panel, floating in the same corner ── */
  return (
    <div
      ref={wrap}
      className="pipecard"
      role="region"
      aria-label="מצב הצנרת"
    >
      <div className="pipecard-h">
        <span className={`pipefab-dot ${dotKind}`} aria-hidden="true" />
        <b style={{ fontSize: 13 }}>צנרת · ניקוז</b>
        <span style={{ marginInlineStart: 'auto' }} />
        <button
          className="btn ghost sm dg-pgbtn"
          onClick={toggleOpen}
          aria-label="מזעור בר הצנרת"
          title="מזעור — הבר יישאר צף ומוקטן"
        >
          <Ic p={IC_COLLAPSE} />
        </button>
      </div>
      {/* ── drain state ─────────────────────────────────────────────────── */}
      {running && s?.drain ? (
        <span className="flex items-center gap-2">
          <span className="pill warn">ניקוז רץ</span>
          <span className="muted">{modeLabel(s.drain.mode)}</span>
          {runElapsed && <span className="mono num muted">{runElapsed}</span>}
          {s.drain.n8n_url ? (
            <a className="link" href={s.drain.n8n_url} target="_blank" rel="noreferrer">
              פתח ב-n8n <Ic p={IC.external} />
            </a>
          ) : (
            <span className="mono muted" title="לא הוגדרה כתובת n8n ציבורית">
              הרצה {s.drain.execution_id}
            </span>
          )}
        </span>
      ) : (
        <span className={`pill ${n8nUp ? 'muted' : 'degraded'}`}>
          {n8nUp ? 'אין ניקוז פעיל' : 'מצב הניקוז לא ידוע'}
        </span>
      )}

      {/* ── the button + its mode picker ────────────────────────────────── */}
      <span style={{ position: 'relative' }}>
        <button
          className="btn sm"
          disabled={firing || running || !n8nUp}
          onClick={() => setPicker((v) => !v)}
          title={
            running
              ? 'ניקוז כבר רץ — ניקוז שני מכפיל את תקרת המסלולים ולא מוסיף קצב'
              : !n8nUp
                ? 'מסד הנתונים של n8n אינו נקרא, ולכן אי אפשר לוודא שאין ניקוז פעיל'
                : 'הפעלת ניקוז אחד'
          }
        >
          {firing ? 'שולח…' : 'הרץ ניקוז'}
        </button>
        {picker && (
          <div
            style={{
              position: 'absolute',
              insetInlineStart: 0,
              // the card floats at the BOTTOM of the viewport — the menu opens upward
              bottom: 'calc(100% + 6px)',
              zIndex: 40,
              minWidth: 220,
              background: 'var(--surface)',
              border: '1px solid var(--line)',
              borderRadius: 12,
              boxShadow: 'var(--shadow-lg)',
              padding: 6,
              direction: 'rtl',
            }}
          >
            {MODES.map((m) => (
              <button
                key={m.key}
                onClick={() => fire(m.mode, m.dry)}
                style={{
                  display: 'block',
                  width: '100%',
                  textAlign: 'start',
                  background: 'transparent',
                  border: 'none',
                  borderRadius: 8,
                  padding: '7px 10px',
                  cursor: 'pointer',
                  fontFamily: 'inherit',
                  color: 'var(--ink)',
                }}
              >
                <b style={{ fontSize: 13 }}>{m.label}</b>
                <div className="muted small">{m.hint}</div>
              </button>
            ))}
          </div>
        )}
      </span>

      {/* ── counters ────────────────────────────────────────────────────── */}
      <span className="stat" title="מסלולי נהג פעילים מול תקרת המסלולים המוגדרת">
        מסלולים
        <b className="num">
          {num(s?.drivers, n8nUp)}/{num(s?.parallel, dbUp)}
        </b>
      </span>
      <span className="stat" title="מסמכים שטרם הגיעו למצב סופי">
        לא סופיים <b className="num">{num(s?.non_terminal, dbUp)}</b>
      </span>
      <span className="stat" title="ACTION_RESTART — ההרצה מחדש היחידה המאושרת">
        הרצה מחדש <b className="num">{num(s?.action_restart, dbUp)}</b>
      </span>
      <span className="stat" title="שיגורי פעולות שנפתחו בחמש הדקות האחרונות">
        שיגורים 5 דק׳ <b className="num">{num(s?.dispatch_5m, dbUp)}</b>
      </span>
      <span
        className="stat"
        title="הרצות n8n שנכשלו או קרסו בשעה האחרונה"
        style={n8nUp && (s?.errors_1h ?? 0) > 0 ? { borderColor: 'var(--red)' } : undefined}
      >
        שגיאות שעה
        <b
          className="num"
          style={n8nUp && (s?.errors_1h ?? 0) > 0 ? { color: 'var(--red)' } : undefined}
        >
          {num(s?.errors_1h, n8nUp)}
        </b>
      </span>
      {/* Locks are normal — they lapse on a TTL rather than being released — so this appears only
          when some are held, and calls out the stale ones, which are the leak signal. */}
      {s?.locks_available !== false && (s?.locks ?? 0) > 0 && (
        <span className="stat" title="נעילות doc_action מוחזקות; תקועות = כאלה שכמעט מיצו את החכירה">
          נעילות <b className="num">{s?.locks}</b>
          {(s?.locks_stale ?? 0) > 0 && (
            <b className="num" style={{ color: 'var(--red)' }}>
              {s?.locks_stale} תקועות
            </b>
          )}
        </span>
      )}

      {/* ── the master gate, DISPLAY ONLY (הגדרות owns the toggle) ──────── */}
      <span
        className="flex items-center gap-2"
        title="מתג הניקוז הראשי — נערך במסך הגדרות. הרצה ידנית כאן עוקפת אותו במכוון."
      >
        <span
          className={`switch${dbUp && s?.drain_on ? ' on' : ''}`}
          aria-hidden="true"
          /* `.switch` is styled for a <button>; this one only REPORTS the gate, so it must not
             advertise itself as clickable. הגדרות owns the write. */
          style={{ cursor: 'default' }}
        >
          <span className="knob" />
        </span>
        <span className="muted">{!dbUp ? 'מתג לא ידוע' : s?.drain_on ? 'ניקוז פעיל' : 'ניקוז כבוי'}</span>
      </span>

      <span style={{ marginInlineStart: 'auto' }} />

      {/* ── freshness, from the DATABASE's clock ────────────────────────── */}
      <span
        className={`live${hidden ? ' paused' : ''}`}
        style={{ cursor: 'default' }}
        title={hidden ? 'הלשונית מוסתרת — הסקר מושהה' : `שעון מסד הנתונים · ${s?.as_of || ''}`}
      >
        <span className="beat" />
        {updated
          ? `עודכן ${updated.toLocaleTimeString('he-IL', { hour12: false })}`
          : 'לא עודכן'}
      </span>

      {/* ── the indeterminate bar: a drain has no denominator ───────────── */}
      {running && (
        <div
          className="progress indet"
          style={{ flexBasis: '100%', height: 4, marginTop: 2 }}
          role="progressbar"
          aria-label="ניקוז פעיל"
        >
          <div className="bar" />
        </div>
      )}

      {/* ── notices ─────────────────────────────────────────────────────── */}
      {conflict && (
        <div className="callout warn" style={{ flexBasis: '100%', padding: '7px 12px' }}>
          {conflict.message || 'ניקוז כבר רץ.'}{' '}
          {conflict.n8n_url ? (
            <a className="link" href={conflict.n8n_url} target="_blank" rel="noreferrer">
              פתח את ההרצה הקיימת <Ic p={IC.external} />
            </a>
          ) : (
            conflict.execution_id && <span className="mono num">הרצה {conflict.execution_id}</span>
          )}
        </div>
      )}
      {fired && !running && (
        <div className="callout ok" style={{ flexBasis: '100%', padding: '7px 12px' }}>
          ניקוז נשלח ({modeLabel(fired.mode, fired.dry)}){' '}
          {fired.n8n_url ? (
            <a className="link" href={fired.n8n_url} target="_blank" rel="noreferrer">
              פתח ב-n8n <Ic p={IC.external} />
            </a>
          ) : (
            <span className="mono num">הרצה {fired.execution_id}</span>
          )}
        </div>
      )}
      {err && (
        <div className="callout bad" style={{ flexBasis: '100%', padding: '7px 12px' }}>
          {err}
        </div>
      )}
      {s && !dbUp && (
        <div className="callout warn" style={{ flexBasis: '100%', padding: '7px 12px' }}>
          מסד הנתונים של INDOX אינו נקרא — המספרים והשעון אינם זמינים.
        </div>
      )}
    </div>
  );
}
