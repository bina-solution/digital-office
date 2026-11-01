import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, TestCaseResult, TestRun, TestSuite } from '../api';
import { Ic, useToasts } from '../components/DataGrid';
import { useConfirm } from '../components/ConfirmModal';
import { IC } from '../icons';

// The BFF drives the INDOX n8n E2E suites via their lane webhooks. Each suite
// lane is one "case", so progress is GENUINELY incremental — cases_done grows
// as lanes complete (see api.ts TestRun docs). We poll for that progress.
const POLL_MS = 1500;

const nn = (v: unknown): number => {
  const x = Number(v);
  return Number.isFinite(x) ? x : 0;
};

const fmtTime = (iso?: string | null): string => {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? '—'
    : d.toLocaleString('he-IL', { dateStyle: 'short', timeStyle: 'short' });
};

/** Compact last-run pass/fail meter for a suite row. */
function SuiteMeter({ suite }: { suite: TestSuite }) {
  const total = nn(suite.case_count);
  // never run yet → cases_passed is null and there is no last_run timestamp
  if (suite.cases_passed == null || suite.last_run == null || total === 0) {
    return <span className="muted small">לא הורץ</span>;
  }
  const passed = nn(suite.cases_passed);
  const pct = (passed / total) * 100;
  const allOk = suite.all_passed === true;
  return (
    <div className="meter-row">
      <div className="meter" title={`${passed}/${total} עברו`}>
        <div
          className={`fill${allOk ? '' : ' bad'}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className={`pill ${allOk ? 'ok' : 'bad'}`}>
        <span className="num">
          {passed}/{total}
        </span>
      </span>
    </div>
  );
}

/** One case (= one suite lane) row inside the live run panel. */
function CaseRow({ c, suiteLabel }: { c: TestCaseResult; suiteLabel?: string }) {
  const ok = c.passed;
  return (
    <div className="caserow">
      <span className={`mk ${ok ? 'ok' : 'bad'}`} title={ok ? 'עבר' : 'נכשל'} aria-label={ok ? 'עבר' : 'נכשל'} style={{ display: 'inline-flex' }}>
        <Ic p={ok ? IC.check : IC.x} />
      </span>
      <div>
        <span className="nm">{c.name || '—'}</span>
        {suiteLabel && (
          <span className="tag" style={{ marginInlineStart: 8 }}>
            {suiteLabel}
          </span>
        )}
        {c.assertions_total != null && c.assertions_total > 0 && (
          <span className="muted small" style={{ marginInlineStart: 8 }}>
            <span className="num">
              {nn(c.assertions_passed)}/{nn(c.assertions_total)}
            </span>{' '}
            בדיקות
          </span>
        )}
        {!ok && c.failed_assertions && c.failed_assertions.length > 0 && (
          <div className="fa">
            {c.failed_assertions.map((fa, i) => (
              <span className="row" key={i}>
                {fa.name}: צפוי {fa.operator}{' '}
                <span className="num">{String(fa.expected)}</span> — התקבל{' '}
                <span className="num">{String(fa.actual)}</span>
              </span>
            ))}
          </div>
        )}
      </div>
      {c.duration_s != null && (
        <span className="meta num">{Number(c.duration_s).toFixed(1)}s</span>
      )}
    </div>
  );
}

/** The live run panel — progress bar + counts + per-lane breakdown. */
function RunPanel({
  run,
  title,
  labelMap,
}: {
  run: TestRun;
  title: string;
  labelMap: Record<string, string>;
}) {
  const running = run.status === 'running';
  const errored = run.status === 'error';
  const total = nn(run.cases_total);
  const done = nn(run.cases_done);
  const passed = nn(run.passed);
  const failed = nn(run.failed);
  const pct = total > 0 ? Math.min((done / total) * 100, 100) : running ? 0 : 100;

  // failures first, then keep arrival order — most useful to eyeball
  const cases = (run.per_case || [])
    .slice()
    .sort((a, b) => Number(a.passed) - Number(b.passed));

  return (
    <div className="card runpanel">
      <div className="sync-meta">
        <span className="name">{title}</span>
        {running && (
          <span className="pill warn">
            <span className="spinner" style={{ marginInlineEnd: 6 }} />
            מריץ…
          </span>
        )}
        {run.status === 'done' && (
          <span className={`pill ${failed === 0 ? 'ok' : 'bad'}`}>
            {failed === 0 ? 'עבר' : 'נכשל'}
          </span>
        )}
        {errored && <span className="pill bad">שגיאה</span>}
        {run.finished && (
          <span className="muted small" style={{ marginInlineStart: 'auto' }}>
            הסתיים {fmtTime(run.finished)}
          </span>
        )}
      </div>

      <div className={`progress${running && done === 0 ? ' indet' : ''}`}>
        <div
          className={`bar${failed > 0 ? ' err' : ''}`}
          style={{ width: running && done === 0 ? undefined : `${pct}%` }}
        />
      </div>

      <div className="statelegend" style={{ marginTop: 11 }}>
        <span className="li">
          <span className="sw synced" />
          עברו<b className="num">{passed}</b>
        </span>
        <span className="li">
          <span className="sw failed" />
          נכשלו<b className="num">{failed}</b>
        </span>
        <span className="li">
          לוחות (lanes)
          <b className="num">
            {done}
            {total > 0 ? `/${total}` : ''}
          </b>
        </span>
      </div>

      {running && (
        <div className="callout" style={{ marginTop: 12 }}>
          רץ מול מנוע ה-n8n — כל לוח (lane) הוא הרצת E2E עצמאית; התוצאות נצברות בזמן
          אמת ככל שהלוחות מסתיימים.
        </div>
      )}

      {errored && (
        <div className="callout bad" style={{ marginTop: 12 }}>
          <b>ההרצה נכשלה.</b> {run.error || 'שגיאה לא ידועה'}
        </div>
      )}

      {cases.length > 0 && (
        <div className="caselist">
          {cases.map((c, i) => (
            <CaseRow
              key={`${c.suite}:${c.name}:${i}`}
              c={c}
              suiteLabel={
                run.suite ? undefined : (c.suite && labelMap[c.suite]) || undefined
              }
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default function TestsPage() {
  const [suites, setSuites] = useState<TestSuite[]>([]);
  const [groups, setGroups] = useState<Record<string, string>>({});
  const [reachable, setReachable] = useState(true);
  const [loading, setLoading] = useState(true);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [run, setRun] = useState<TestRun | null>(null);
  const [runTitle, setRunTitle] = useState('כל המערכים');
  const { push } = useToasts();
  const { ask, confirmUI } = useConfirm();

  const runIdRef = useRef<string | null>(null);
  const pollTimer = useRef<ReturnType<typeof setInterval> | undefined>(undefined);

  const labelMap = useMemo(
    () => Object.fromEntries(suites.map((s) => [s.name, s.label || s.name])),
    [suites],
  );

  // suites grouped by subsystem, preserving BFF order
  const grouped = useMemo(() => {
    const order: string[] = [];
    const byGroup: Record<string, TestSuite[]> = {};
    for (const s of suites) {
      const g = s.group || 'other';
      if (!byGroup[g]) {
        byGroup[g] = [];
        order.push(g);
      }
      byGroup[g].push(s);
    }
    return order.map((g) => ({ key: g, label: groups[g] || g, items: byGroup[g] }));
  }, [suites, groups]);

  const loadSuites = useCallback(async () => {
    try {
      const r = await api.listTestSuites();
      setSuites(Array.isArray(r.suites) ? r.suites : []);
      setGroups(r.groups || {});
      setReachable(r.reachable !== false);
      setLoadErr(
        r.reachable === false ? r.error || 'מנוע האוטומציה אינו זמין' : null,
      );
    } catch (e: unknown) {
      setReachable(false);
      setLoadErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSuites();
  }, [loadSuites]);

  const stopPolling = useCallback(() => {
    if (pollTimer.current) {
      clearInterval(pollTimer.current);
      pollTimer.current = undefined;
    }
  }, []);

  const pollRun = useCallback(async () => {
    const id = runIdRef.current;
    if (!id) return;
    try {
      const r = await api.getTestRun(id);
      setRun(r);
      if (r.status !== 'running') {
        stopPolling();
        runIdRef.current = null;
        loadSuites(); // refresh last-run stats on the suite rows
      }
    } catch (e: unknown) {
      stopPolling();
      runIdRef.current = null;
      setRun((prev) =>
        prev
          ? {
              ...prev,
              status: 'error',
              error: e instanceof Error ? e.message : String(e),
            }
          : prev,
      );
    }
  }, [loadSuites, stopPolling]);

  /* AN E2E RUN DRIVES THE LIVE n8n ENGINE — the suites mint their own `test` tenant, park and
     flip the master switches and restore them — so it confirms with the facts first: what runs,
     how many lanes, when it last ran and how that went. */
  const start = useCallback(
    async (opts: { suite?: string; group?: string }, title: string) => {
      if (runIdRef.current) return; // guard: never double-run
      const inScope = opts.suite
        ? suites.filter((s) => s.name === opts.suite)
        : opts.group
          ? suites.filter((s) => s.group === opts.group)
          : suites;
      const casesTotal = inScope.reduce((a, s) => a + nn(s.case_count), 0);
      const lastRun = inScope.map((s) => s.last_run).filter(Boolean).sort().pop() || null;
      const failing = inScope.filter((s) => s.all_passed === false).length;
      const ok = await ask({
        title: `הרצת בדיקות · ${title}`,
        consequence: (
          <>
            <b className="num">{inScope.length}</b> מערכים ({casesTotal} לוחות) ירוצו עכשיו מול מנוע ה-n8n
            החי. המערכים עובדים על מופע הבדיקה «test» — לא על נתוני הלקוח — אך הם משתפים את המנוע עם
            הצינור החי ומקפיאים זמנית את המתגים הראשיים ומחזירים אותם בסיום. תוצאות קודמות של המערכים
            האלה יוחלפו.
          </>
        ),
        facts: [
          { label: 'מערכים', value: String(inScope.length) },
          { label: 'לוחות', value: String(casesTotal) },
          { label: 'הורץ לאחרונה', value: lastRun ? fmtTime(lastRun) : 'לא הורץ' },
          ...(failing ? [{ label: 'מערכים שנכשלו בריצה האחרונה', value: String(failing), kind: 'bad' as const }] : []),
        ],
        confirmLabel: 'הרץ',
      });
      if (!ok) return;
      setRunTitle(title);
      setRun({
        run_id: '',
        suite: opts.suite ?? null,
        status: 'running',
        cases_total: casesTotal || null,
        cases_done: 0,
        passed: 0,
        failed: 0,
        per_case: [],
      });
      try {
        const { run_id } = await api.startTestRun(opts);
        runIdRef.current = run_id;
        setRun((prev) => (prev ? { ...prev, run_id } : prev));
        stopPolling();
        pollTimer.current = setInterval(pollRun, POLL_MS);
        pollRun(); // immediate first tick
        push('ok', `ההרצה «${title}» התחילה — ${casesTotal} לוחות`);
      } catch (e: unknown) {
        push('bad', `לא ניתן להתחיל הרצה: ${e instanceof Error ? e.message : String(e)}`);
        setRun(null);
        runIdRef.current = null;
      }
    },
    [pollRun, stopPolling, suites, ask, push],
  );

  // cleanup on unmount
  useEffect(() => () => stopPolling(), [stopPolling]);

  const running = run?.status === 'running';
  const runDisabled = running || !reachable;

  return (
    <div>
      {confirmUI}
      <div className="app-header">
        <div>
          <h1>בדיקות</h1>
          <div className="sub">
            מערכי ה-E2E של INDOX — סנכרון ומכונת המצבים (כולל מנתבי הפעולות) —
            הרצה ידנית מול מנוע ה-n8n עם התקדמות חיה.
          </div>
        </div>
        <div className="actions">
          <button
            className="btn"
            onClick={() => start({}, 'כל המערכים')}
            disabled={runDisabled || suites.length === 0}
            title="מריץ את כל מערכי הבדיקות מול מנוע ה-n8n — אחרי אישור עם המספרים"
          >
            {running && runTitle === 'כל המערכים' ? (
              <span className="spinner" />
            ) : (
              <Ic p={IC.play} />
            )}{' '}
            הרץ הכל
          </button>
        </div>
      </div>

      {/* first load */}
      {loading && <div className="spin">טוען מערכי בדיקות…</div>}

      {/* engine unreachable */}
      {!loading && !reachable && (
        <div className="callout bad">
          <b>מנוע האוטומציה אינו זמין.</b> לא ניתן להגיע ל-n8n כרגע
          {loadErr ? ` (${loadErr})` : ''}. נסה שוב מאוחר יותר.
        </div>
      )}

      {/* the live run panel (shown as soon as a run starts) */}
      {run && <RunPanel run={run} title={runTitle} labelMap={labelMap} />}

      {/* grouped suite list */}
      {!loading && reachable && (
        <>
          {suites.length === 0 ? (
            <div className="callout">אין מערכי בדיקות להצגה.</div>
          ) : (
            grouped.map((grp) => (
              <div key={grp.key} className="suitegroup">
                <div className="suitegroup-h">
                  <span className="group-label" style={{ margin: 0 }}>
                    {grp.label}
                  </span>
                  <button
                    className="btn sm ghost"
                    onClick={() => start({ group: grp.key }, grp.label)}
                    disabled={runDisabled}
                    title={`מריץ את כל מערכי ${grp.label} — אחרי אישור`}
                  >
                    {running && runTitle === grp.label ? 'רץ…' : <><Ic p={IC.play} /> הרץ קבוצה</>}
                  </button>
                </div>
                <table className="table">
                  <thead>
                    <tr>
                      <th>מערך</th>
                      <th>לוחות אחרונים</th>
                      <th>הורץ לאחרונה</th>
                      <th style={{ textAlign: 'end' }}>פעולה</th>
                    </tr>
                  </thead>
                  <tbody>
                    {grp.items.map((s) => {
                      const isThis = running && run?.suite === s.name;
                      const label = s.label || s.name;
                      return (
                        <tr key={s.name}>
                          <td>
                            <div
                              style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: 8,
                              }}
                            >
                              {isThis && <span className="spinner" />}
                              <span style={{ fontWeight: 700 }}>{label}</span>
                            </div>
                            <div className="muted small mono">{s.name}</div>
                            {s.description && (
                              <div
                                className="muted small"
                                style={{ marginTop: 2 }}
                              >
                                {s.description}
                              </div>
                            )}
                          </td>
                          <td>
                            <SuiteMeter suite={s} />
                          </td>
                          <td className="muted small num">
                            {fmtTime(s.last_run)}
                          </td>
                          <td style={{ textAlign: 'end' }}>
                            <button
                              className="btn sm ghost"
                              onClick={() => start({ suite: s.name }, label)}
                              disabled={runDisabled}
                              title={`מריץ את ${label} — אחרי אישור`}
                            >
                              {isThis ? 'רץ…' : <><Ic p={IC.play} /> הרץ</>}
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ))
          )}
        </>
      )}
    </div>
  );
}
