import { useEffect, useRef, useState } from 'react';
import { api, InstanceAccount, InstanceDetail, NewInstanceSpec } from '../api';
import { Ic } from './DataGrid';
import { IC } from '../icons';

/** A new instance starts in the office's olive. The colour picker needs it as a value, so it is READ
 *  from the palette the page carries rather than written here a second time. */
const olive = () => getComputedStyle(document.documentElement).getPropertyValue('--olive').trim();
const blankSpec = (): NewInstanceSpec => ({ label: '', company: '', color: olive(), backend: 'supabase', table: '' });

/**
 * INDOX instance switcher — the top-bar chip.
 *
 * An *instance* is a fully duplicated INDOX: its own target table, its own settings, its own sync
 * registry, its own companies and tag rules. Exactly one is active at a time, and every no-param
 * endpoint (`/config/settings`, `/sync/registry`, `/sync/status`) resolves against it — which is what
 * makes switching feel like changing companies rather than picking a repo.
 *
 * WHY THIS LIVES IN THE APP AND NOT THE SHELL. In the simulation the chip is drawn by the console
 * shell (`overlay/switcher.js`) and INDOX only exposes `window.__indoxReload` for it to call. The
 * live console has no such switcher for ANY app yet, so a shell-only chip would mean the instances
 * surface exists in the API and nowhere in the UI. Rendering it here makes the surface real today and
 * costs nothing later: `App.tsx` still installs `__indoxReload`, so when the shell does grow a chip
 * both drive the same refresh path.
 *
 * The panel also carries "פרטי המופע" — backend, target table, column count and per-table row counts.
 * That is the information RepoDetailPage shows one navigation away; surfacing it in the switcher is
 * what let the sim delete that screen. Live keeps the screen too, so here it is simply the faster
 * route to the same facts.
 *
 * DEGRADES TO NOTHING. The instances endpoints are additive; against a BFF that does not serve
 * `/accounts` the fetch fails and the chip renders `null`, leaving the rest of the app untouched.
 */
export default function InstanceSwitcher({
  accounts,
  active,
  onSwitched,
}: {
  /** Fetched ONCE by App.tsx and passed down — see instancesContext.tsx's doc comment. This
   *  component used to run its own `listInstances()` here, a second `GET /accounts` round trip
   *  through the console's single-threaded proxy for data the parent already has. */
  accounts: InstanceAccount[];
  active: string | null;
  onSwitched: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<InstanceDetail | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  // The new-instance wizard. Three steps, matching the simulation's flow: identity, then where the
  // documents are written, then which sync registries the instance starts with. It is a WIZARD and
  // not one long form because the three answers come from different people — a name is chosen by
  // whoever onboards the company, a target table by whoever owns the database, and the registries by
  // whoever knows where that company's documents actually arrive.
  const [wiz, setWiz] = useState<0 | 1 | 2 | 3>(0);
  const [spec, setSpec] = useState<NewInstanceSpec>(blankSpec);
  const boxRef = useRef<HTMLDivElement | null>(null);

  // Details are only worth a request once the panel is open — the chip itself needs nothing but the
  // account list, and this endpoint reads the whole instance (registry + settings + columns).
  useEffect(() => {
    if (!open) return;
    let alive = true;
    setDetail(null); // drop the previous instance's payload before asking for this one's
    api
      .instanceDetail()
      .then((d) => {
        if (alive) setDetail(d);
      })
      .catch(() => {
        if (alive) setDetail(null);
      });
    return () => {
      alive = false;
    };
  }, [open, active]);

  // Click-outside and Esc both close: a dropdown that can only be dismissed by re-clicking its own
  // trigger is the classic way to trap someone who opened it by accident.
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDoc);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  if (accounts.length === 0) return null;

  const current = accounts.find((a) => a.id === active) ?? accounts[0];

  async function select(id: string) {
    if (id === active) {
      setOpen(false);
      return;
    }
    setBusy(id);
    setErr(null);
    try {
      /* SWITCHING INSTANCE IS A URL CHANGE, NOT A SERVER WRITE.
         `api.selectInstance` wrote active_instance.json — a single global pointer on the host, so
         one operator switching changed what a colleague saw AND what the CLI on that box targeted.
         That is a multi-instance bug and the file is slated for deletion. Which instance you are
         looking at is view state: it belongs in the address bar, per user, and it makes the link
         you paste to a colleague open YOUR screen rather than theirs. */
      /* Write it where the route actually lives. Embedded, that is the SHELL's address bar —
         writing our own iframe hash would change nothing the shell or a shared link can see. */
      const target = (() => {
        try {
          if (window.parent && window.parent !== window) return window.parent;
        } catch {
          /* cross-origin parent */
        }
        return window;
      })();
      const [rawPath, query] = target.location.hash.replace(/^#/, '').split('?');
      // Swap the instance IN THE PATH — that is where it lives now. A switch from a page that has
      // no /i/ segment (dashboard, sync, settings) leaves the path alone and the app picks the
      // instance up from the query, which the document routes then normalise back into the path.
      const path = /\/i\/[^/?#]+/.test(rawPath)
        ? rawPath.replace(/\/i\/[^/?#]+/, `/i/${encodeURIComponent(id)}`)
        : rawPath;
      const q = new URLSearchParams(query || '');
      if (path === rawPath) q.set('instance', id);
      else q.delete('instance');
      q.delete('table');
      q.delete('page');
      q.delete('view');
      target.location.hash = `${path}?${q.toString()}`;
      setOpen(false);
      // One refresh path for both entry points (see the header comment) — this now also carries
      // the account LIST (App.tsx's refreshActive), not just `active`, so there is nothing left
      // for this component to separately re-fetch.
      const w = window as unknown as { __indoxReload?: () => void };
      if (w.__indoxReload) w.__indoxReload();
      else onSwitched();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(null);
    }
  }

  const dot = (s: InstanceAccount['status']) =>
    s === 'ok' ? 'var(--ok)' : s === 'warning' ? 'var(--amber)' : 'var(--red)';

  return (
    <div ref={boxRef} style={{ position: 'relative', marginInlineStart: 12 }}>
      <button
        type="button"
        className="btn ghost sm"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        title={`מופע פעיל: ${current.label} · ${current.identity}`}
        style={{ display: 'flex', alignItems: 'center', gap: 6, maxWidth: 220 }}
      >
        <span
          style={{
            width: 8,
            height: 8,
            borderRadius: 999,
            background: current.color || dot(current.status),
            flex: '0 0 auto',
          }}
        />
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {current.label}
        </span>
        <span aria-hidden style={{ opacity: 0.6, display: 'inline-flex' }}><Ic p={IC.chevronDown} /></span>
      </button>

      {open && (
        <div
          role="listbox"
          style={{
            position: 'absolute',
            insetInlineEnd: 0,
            top: 'calc(100% + 6px)',
            zIndex: 60,
            minWidth: 300,
            maxWidth: 380,
            background: 'var(--surface)',
            border: '1px solid var(--line)',
            borderRadius: 'var(--radius-sm, 9px)',
            boxShadow: 'var(--shadow-lg)',
            padding: 8,
          }}
        >
          <div className="group-label" style={{ padding: '2px 6px 6px' }}>
            מופעי INDOX
          </div>

          {accounts.map((a) => (
            <button
              key={a.id}
              type="button"
              role="option"
              aria-selected={a.id === active}
              disabled={busy != null}
              onClick={() => select(a.id)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                width: '100%',
                textAlign: 'start',
                background: a.id === active ? 'var(--accent-soft)' : 'transparent',
                border: 0,
                borderRadius: 8,
                padding: '7px 8px',
                cursor: busy ? 'progress' : 'pointer',
                font: 'inherit',
              }}
            >
              <span
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: 999,
                  background: a.color || dot(a.status),
                  flex: '0 0 auto',
                }}
              />
              <span style={{ flex: 1, minWidth: 0 }}>
                <span style={{ display: 'block', fontWeight: 700, fontSize: 13 }}>{a.label}</span>
                <span className="muted small mono" style={{ display: 'block' }}>
                  {a.identity}
                </span>
                {/* What the instance OWNS, not just where it writes. `/accounts` reported these three
                    as 0 for every instance (it never passed `counts` to the projector), so the
                    switcher had nothing true to say and said nothing — while the details panel below
                    showed the real numbers for the same instance. Now they agree. */}
                <span className="muted small" style={{ display: 'block' }}>
                  {a.registry} מקורות · {a.settings_count} הגדרות · {a.companies} חברות
                </span>
              </span>
              {/* `?? 0`: the account list now comes from the instance registry, where a count may not have
                  arrived yet. A missing number must render as 0, never crash the switcher — which is
                  the one control that has to work for a second instance to be reachable at all. */}
              <span className="muted small num">{(a.docs ?? 0).toLocaleString('he-IL')}</span>
              {a.id === active && <span className="pill healthy">פעיל</span>}
            </button>
          ))}

          {err && (
            <div className="callout bad" style={{ margin: '8px 0 0' }}>
              {err}
            </div>
          )}

          {/* פרטי המופע — the RepoDetailPage facts, without the navigation. */}
          <div style={{ borderTop: '1px solid var(--line)', margin: '8px 0 0', paddingTop: 8 }}>
            <div className="group-label" style={{ padding: '0 6px 6px' }}>
              פרטי המופע
            </div>
            {/* ONLY THIS INSTANCE'S OWN NUMBERS. `detail` survives an instance change while the
                refetch is in flight, so the panel used to paint the PREVIOUS instance's figures
                under the new one's name — observed: לוי's panel reading 26,006 מסמכים, which is
                הכהן's count, for as long as the request took. The payload names the instance it
                describes, so the render simply waits until that name is the one on screen. */}
            {detail && detail.account.id === active ? (
              <dl className="kv" style={{ padding: '0 6px' }}>
                <div className="kv">
                  <dt>מנוע</dt>
                  <dd>
                    <span className="tag">{detail.account.backend}</span>
                  </dd>
                </div>
                <div className="kv">
                  <dt>טבלת יעד</dt>
                  <dd className="mono small">{detail.target}</dd>
                </div>
                <div className="kv">
                  <dt>עמודות</dt>
                  <dd className="num">{detail.columns?.length ?? 0}</dd>
                </div>
                <div className="kv">
                  <dt>מסמכים</dt>
                  <dd className="num">{(detail.counts?.docs ?? 0).toLocaleString('he-IL')}</dd>
                </div>
                <div className="kv">
                  <dt>מקורות סנכרון</dt>
                  <dd className="num">{detail.counts?.registry ?? 0}</dd>
                </div>
              </dl>
            ) : (
              <div className="muted small" style={{ padding: '0 6px' }}>
                {detail === null ? 'טוען פרטי מופע…' : 'פרטי המופע אינם זמינים.'}
              </div>
            )}
          </div>

          <div
            style={{
              display: 'flex',
              gap: 8,
              borderTop: '1px solid var(--line)',
              margin: '8px 0 0',
              paddingTop: 8,
            }}
          >
            {/* the "כל המאגרים" link pointed at the removed repos-list screen — the
                switcher itself IS the instance picker now */}
            <span className="spacer" style={{ flex: 1 }} />
            <button
              type="button"
              className="btn ghost sm"
              onClick={() => {
                setErr(null);
                setSpec(blankSpec());
                setWiz(1);
              }}
              title="פותח אשף בן שלושה שלבים ליצירת מופע INDOX חדש"
            >
              <Ic p={IC.plus} /> מופע INDOX חדש
            </button>
          </div>
        </div>
      )}

      {wiz > 0 && (
        <div className="drawer-ov" role="dialog" aria-modal="true" aria-label="מופע INDOX חדש">
          <div className="scrim" onClick={() => setWiz(0)} />
          <div className="drawer" style={{ maxWidth: 460 }}>
            <div className="app-header">
              <h3 style={{ margin: 0 }}>מופע INDOX חדש</h3>
              <span className="spacer" style={{ flex: 1 }} />
              <span className="muted small">שלב {wiz} מתוך 3</span>
            </div>

            {wiz === 1 && (
              <div className="stack">
                <div className="muted small">
                  כל מופע הוא INDOX שלם — טבלה, הגדרות ורישומי סנכרון משלו.
                </div>
                <label className="field">
                  <span>שם המופע</span>
                  <input
                    autoFocus
                    value={spec.label}
                    placeholder="למשל: כהן ובניו"
                    onChange={(e) => setSpec({ ...spec, label: e.target.value })}
                  />
                </label>
                <label className="field">
                  <span>חברה</span>
                  <input
                    value={spec.company || ''}
                    placeholder="שם החברה המלא"
                    onChange={(e) => setSpec({ ...spec, company: e.target.value })}
                  />
                </label>
                <label className="field">
                  <span>צבע מזהה</span>
                  <input
                    type="color"
                    value={spec.color || olive()}
                    onChange={(e) => setSpec({ ...spec, color: e.target.value })}
                  />
                </label>
              </div>
            )}

            {wiz === 2 && (
              <div className="stack">
                <div className="muted small">
                  כאן ייכתבו המסמכים של המופע הזה — טבלה נפרדת לחלוטין.
                </div>
                <label className="field">
                  <span>סוג אחסון</span>
                  <select
                    value={spec.backend || 'supabase'}
                    onChange={(e) =>
                      setSpec({ ...spec, backend: e.target.value as 'supabase' | 'gsheet' })
                    }
                  >
                    <option value="supabase">Supabase (טבלה)</option>
                    <option value="gsheet">Google Sheets (גיליון)</option>
                  </select>
                </label>
                <label className="field">
                  <span>שם הטבלה / הגיליון</span>
                  <input
                    value={spec.table || ''}
                    onChange={(e) => setSpec({ ...spec, table: e.target.value })}
                  />
                </label>
              </div>
            )}

            {wiz === 3 && (
              <div className="stack">
                <div className="muted small">
                  המופע ייווצר עם רישומי סנכרון ריקים. אפשר להוסיף מקורות במסך הסנכרון לאחר היצירה.
                </div>
                <div className="kv">
                  <span className="muted small">שם</span>
                  <b>{spec.label}</b>
                </div>
                <div className="kv">
                  <span className="muted small">חברה</span>
                  <span>{spec.company || spec.label}</span>
                </div>
                <div className="kv">
                  <span className="muted small">יעד</span>
                  <span className="mono small">
                    {spec.backend} · {spec.table}
                  </span>
                </div>
              </div>
            )}

            {err && <div className="callout bad">{err}</div>}

            <div className="app-header" style={{ marginTop: 12 }}>
              <button type="button" className="btn ghost sm" onClick={() => setWiz(0)}>
                ביטול
              </button>
              <span className="spacer" style={{ flex: 1 }} />
              {wiz > 1 && (
                <button
                  type="button"
                  className="btn ghost sm"
                  onClick={() => setWiz((wiz - 1) as 1 | 2 | 3)}
                >
                  חזרה
                </button>
              )}
              <button
                type="button"
                className="btn sm"
                disabled={busy === 'add'}
                onClick={async () => {
                  setErr(null);
                  if (wiz === 1) {
                    if (!spec.label.trim()) return;
                    // The default table name stays ASCII on purpose: a Hebrew label must not turn
                    // into a Hebrew SQL identifier.
                    const slug = spec.label
                      .toLowerCase()
                      .replace(/[^a-z0-9]+/g, '_')
                      .replace(/^_+|_+$/g, '');
                    setSpec({
                      ...spec,
                      company: spec.company || spec.label,
                      table: spec.table || `indox_${slug || 'co'}`,
                    });
                    setWiz(2);
                    return;
                  }
                  if (wiz === 2) {
                    setWiz(3);
                    return;
                  }
                  setBusy('add');
                  try {
                    const r = await api.addInstance(spec);
                    // A degraded write answers 200 {success:false} rather than throwing — the same
                    // shape the rest of this service uses while its store is down. Closing on that
                    // would claim an instance that does not exist.
                    if (r && r.success === false) {
                      setErr('היצירה לא הושלמה — מסד הנתונים אינו זמין כרגע.');
                      return;
                    }
                    setWiz(0);
                    setOpen(false);
                    onSwitched();
                  } catch (e: unknown) {
                    setErr(e instanceof Error ? e.message : String(e));
                  } finally {
                    setBusy(null);
                  }
                }}
              >
                {wiz === 3 ? 'יצירת המופע' : 'המשך'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
