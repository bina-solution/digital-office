import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api, ExtractionDoc, ExtractionHistoryEntry, ExtractionResult } from '../api';
import { ScorePill, SCOPE_LABEL, fmtTime, typeLabel } from './ExtractionPage';
import { IC, Ic } from '../icons';

// Full-document extraction view: original ↔ apitools-drawn overlay toggle,
// extracted values vs ground truth, backend context (hash / workflow / timing)
// and the exact settings queries (q_v3_*) each field ran — everything the
// operator needs to understand and tune one document's extraction.

const CATEGORY: Record<string, string> = {
  invoice: 'invoice',
  shipment: 'shipment',
  balance_sheet: 'bs',
};
const HOOK: Record<string, string> = {
  invoice: 'jqexv3-run-invoice',
  shipment: 'jqexv3-run-shipment',
  balance_sheet: 'jqexv3-run-bs',
};

export default function ExtractionDocPage() {
  const { type = '', name = '' } = useParams();
  const docId = `${type}/${name}`;
  const [doc, setDoc] = useState<ExtractionDoc | null>(null);
  const [queries, setQueries] = useState<Record<string, unknown> | null>(null);
  const [pane, setPane] = useState<'draw' | 'tokens' | 'doc'>('draw');
  const [rerunning, setRerunning] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [drawKey, setDrawKey] = useState(0); // cache-buster after rerun
  const [history, setHistory] = useState<ExtractionHistoryEntry[] | null>(null);
  const [viewing, setViewing] = useState<ExtractionResult | null>(null); // historical result

  const loadHistory = useCallback(() => {
    api
      .getExtractionDocHistory(docId)
      .then((r) => setHistory(r.history))
      .catch(() => setHistory([]));
  }, [docId]);

  const load = useCallback(async () => {
    try {
      const d = await api.getExtractionDataset();
      const found =
        d.docs.find((x) => x.id === docId) || d.uploads.find((x) => x.id === docId) || null;
      setDoc(found);
      if (!found) setErr('המסמך לא נמצא במאגר');
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, [docId]);

  useEffect(() => {
    load();
    loadHistory();
    api
      .getExtractionQueries()
      .then((r) => setQueries(r.queries))
      .catch(() => setQueries(null));
  }, [load, loadHistory]);

  const rerun = useCallback(
    async (fresh = false) => {
      setRerunning(true);
      setErr(null);
      setViewing(null);
      try {
        const r: ExtractionResult = await api.rerunExtractionDoc(docId, fresh);
        setDoc((prev) => (prev ? { ...prev, result: r } : prev));
        // fresh = re-OCR + draw cache cleared server-side: bust the <img> caches too
        setDrawKey((k) => k + 1);
        loadHistory();
      } catch (e: unknown) {
        setErr(e instanceof Error ? e.message : String(e));
      } finally {
        setRerunning(false);
      }
    },
    [docId, loadHistory],
  );

  const r = viewing || doc?.result || null;
  const effType = doc?.type === 'upload' ? r?.detected_type || 'invoice' : doc?.type || 'invoice';
  const category = r?.draw_category || CATEGORY[effType] || 'invoice';
  const isImage = /\.(jpe?g|png)$/i.test(name);
  const fileUrl = api.extractionFileUrl(docId);
  const drawUrl = `${api.extractionDrawUrl(docId, category)}${category ? '&' : '?'}v=${drawKey}`;
  const tokensUrl = `${api.extractionTokensUrl(docId)}?v=${drawKey}`;

  // field -> settings query key, from the live routing (base + this category)
  const fieldQueryMap: Record<string, string> = useMemo(() => {
    const routing = (queries?.q_v3_routing || {}) as Record<string, Record<string, string>>;
    return { ...(routing.base || {}), ...(routing[category] || {}) };
  }, [queries, category]);

  const scored = (r?.values || []).filter((v) => v.ok !== null);
  const extras = (r?.values || []).filter((v) => v.ok === null);

  return (
    <div>
      <div className="app-header">
        <div>
          <h1 className="mono" style={{ direction: 'ltr', textAlign: 'end' }}>
            {name}
          </h1>
          <div className="sub" style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <Link className="link" to="/extraction" title="חזרה לרשימת מאגר הדגימה"><Ic p={IC.arrowRight} /> חילוץ מסמכים</Link>
            {doc && <span className="pill unset">{typeLabel(doc)}</span>}
            {r?.detected_type && (
              <span className={`pill ${r.type_ok === false ? 'bad' : 'ok'}`}>
                זוהה: {r.detected_type}
              </span>
            )}
            <ScorePill r={r} />
          </div>
        </div>
        <div className="actions">
          <button
            className="btn ghost"
            onClick={() => rerun(true)}
            disabled={rerunning}
            title="מאלץ OCR מחדש (עוקף מטמון) ומנקה את מטמון הסימון — הרצה נקייה מובטחת אחרי שינוי מנוע"
          >
            {rerunning ? <span className="spinner" /> : <Ic p={IC.trash} />} אפס מטמון והרץ
          </button>
          <button className="btn" onClick={() => rerun(false)} disabled={rerunning}>
            {rerunning ? <span className="spinner" /> : <Ic p={IC.refresh} />} הרץ מחדש
          </button>
        </div>
      </div>

      {err && (
        <div className="callout bad">
          <b>שגיאה.</b> {err}
        </div>
      )}
      {r?.error && (
        <div className="callout bad">
          <b>החילוץ נכשל.</b> {r.error}
        </div>
      )}
      {viewing && (
        <div className="callout" style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <b>מציג תוצאה היסטורית</b>
          <span className="num small">{fmtTime(viewing.at)}</span>
          <button className="link" onClick={() => setViewing(null)} style={{ marginInlineStart: 'auto' }}>
            חזרה לתוצאה האחרונה
          </button>
        </div>
      )}

      <div className="dash-grid dash-grid-wide">
        {/* ── viewer: original ↔ drawn overlay ── */}
        <div className="card" style={{ margin: 0 }}>
          <div className="subnav" style={{ marginTop: 0 }}>
            <button className={`stab${pane === 'draw' ? ' active' : ''}`} onClick={() => setPane('draw')}>
              חילוץ מסומן
            </button>
            <button className={`stab${pane === 'tokens' ? ' active' : ''}`} onClick={() => setPane('tokens')}>
              זיהוי תווים
            </button>
            <button className={`stab${pane === 'doc' ? ' active' : ''}`} onClick={() => setPane('doc')}>
              מסמך מקורי
            </button>
            <a
              className="stab"
              href={pane === 'doc' ? fileUrl : pane === 'tokens' ? tokensUrl : drawUrl}
              target="_blank"
              rel="noreferrer"
              style={{ marginInlineStart: 'auto', textDecoration: 'none' }}
            >
              פתח בחלון <Ic p={IC.external} />
            </a>
          </div>
          <div
            style={{
              background: 'var(--surface-2)',
              border: '1px solid var(--line)',
              borderRadius: 12,
              overflow: 'auto',
              maxHeight: '76vh',
              display: 'flex',
              justifyContent: 'center',
              // flex cross-axis default is STRETCH — it vertically distorts the
              // document image; keep natural aspect and let the pane scroll
              alignItems: 'flex-start',
            }}
          >
            {pane === 'draw' ? (
              r ? (
                <img
                  key={drawKey}
                  src={drawUrl}
                  alt="חילוץ מסומן"
                  // natural size capped to the pane — upscaling the 1px-per-point
                  // raster blurs/"stretches" the document
                  style={{ maxWidth: '100%', width: 'auto', height: 'auto', display: 'block', margin: '0 auto' }}
                />
              ) : (
                <div className="empty">הרץ חילוץ כדי לראות את הסימון על המסמך</div>
              )
            ) : pane === 'tokens' ? (
              <img
                key={`t${drawKey}`}
                src={tokensUrl}
                alt="זיהוי תווים"
                style={{ maxWidth: '100%', width: 'auto', height: 'auto', display: 'block', margin: '0 auto' }}
              />
            ) : isImage ? (
              <img
                src={fileUrl}
                alt={name}
                style={{ maxWidth: '100%', width: 'auto', height: 'auto', display: 'block', margin: '0 auto' }}
              />
            ) : (
              <iframe
                src={fileUrl}
                title={name}
                style={{ width: '100%', height: '74vh', border: 'none' }}
              />
            )}
          </div>
          <div className="muted small" style={{ marginTop: 8 }}>
            {pane === 'tokens'
              ? 'זיהוי תווים (/documentOcrDraw): כל מילה שמנוע ה-OCR קרא, ממוסגרת עם הטקסט שזוהה — לפני שכל שאילתה רצה. מה שלא מסומן כאן, החילוץ לא יכול למצוא.'
              : 'הסימון מצויר על ידי apitools עצמו (/documentDraw): עוגן ירוק, ערך כחול — לכל שדה השאילתה שלו, קריאה אחת לערך.'}
          </div>
        </div>

        {/* ── values + context ── */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div className="card" style={{ margin: 0 }}>
            <h3>ערכים מול אמת־יסוד</h3>
            {!r && <div className="muted small">לא הורץ עדיין.</div>}
            {r && (
              <div className="tbl-scroll">
                <table className="table">
                  <thead>
                    <tr>
                      <th>שדה</th>
                      <th>חולץ</th>
                      <th>אמת</th>
                      <th style={{ width: 50 }}></th>
                    </tr>
                  </thead>
                  <tbody>
                    {scored.map((v) => (
                      <tr key={v.field}>
                        <td className="mono small">{v.field}</td>
                        <td className="num" style={{ fontWeight: 700 }}>{v.got ?? '—'}</td>
                        <td className="num muted">{v.want ?? '—'}</td>
                        <td>
                          {v.ok ? (
                            <span className="pill ok" title="תואם לאמת-היסוד" aria-label="תואם" style={{ display: 'inline-flex' }}><Ic p={IC.check} /></span>
                          ) : (
                            <span className="pill bad" title="שונה מאמת-היסוד" aria-label="שונה" style={{ display: 'inline-flex' }}><Ic p={IC.x} /></span>
                          )}
                        </td>
                      </tr>
                    ))}
                    {extras.map((v) => (
                      <tr key={v.field}>
                        <td className="mono small muted">{v.field}</td>
                        <td className="num">{v.got ?? '—'}</td>
                        <td className="muted small">ללא אמת</td>
                        <td></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className="card" style={{ margin: 0 }}>
            <h3>הקשר טכני</h3>
            <div className="kv">
              <dt>hash (apitools)</dt>
              <dd className="mono small num">{r?.hash || '—'}</dd>
            </div>
            <div className="kv">
              <dt>תהליך n8n</dt>
              <dd className="mono small">jqexv3-run-base → {HOOK[effType] || '—'}</dd>
            </div>
            <div className="kv">
              <dt>קטגוריית שאילתות</dt>
              <dd className="mono small">{category}</dd>
            </div>
            <div className="kv">
              <dt>משך חילוץ</dt>
              <dd className="num">{r?.elapsed_s != null ? `${r.elapsed_s}s` : '—'}</dd>
            </div>
            <div className="kv">
              <dt>קריאות API</dt>
              <dd>אחת לכל ערך (fallbacks בתוך השאילתה)</dd>
            </div>
            {/* OCR provenance — stamped inside the ocr_json at OCR time, survives the
                cache: a cached OCR still reports the engine/build/time that produced it */}
            <div className="kv">
              <dt>מנוע OCR</dt>
              <dd className="mono small">
                {r?.ops?.ocr_engine || '—'}
                {r?.ops?.ocr_ms != null && ` · ${(r.ops.ocr_ms / 1000).toFixed(1)}s`}
                {r?.ops?.ocr_at && ` · ${r.ops.ocr_at.replace('T', ' ').replace('+00:00', 'Z')}`}
              </dd>
            </div>
            <div className="kv">
              <dt>גרסת apitools</dt>
              <dd className="mono small">
                {r?.ops?.apitools_version || '—'}
                {r?.ops?.ocr_apitools_version &&
                  r?.ops?.ocr_apitools_version !== r?.ops?.apitools_version &&
                  ` (OCR נוצר ע"י ${r.ops.ocr_apitools_version})`}
              </dd>
            </div>
            {(r?.ops?.base_hook_s != null || r?.ops?.type_hook_s != null) && (
              <div className="kv">
                <dt>זמני תהליכים</dt>
                <dd className="num small">
                  base {r?.ops?.base_hook_s != null ? `${r.ops.base_hook_s}s` : '—'}
                  {r?.ops?.type_hook_s != null && ` · ${HOOK[effType] || 'type'} ${r.ops.type_hook_s}s`}
                </dd>
              </div>
            )}
            {r?.ops?.value_ms && Object.keys(r.ops.value_ms).length > 0 && (
              <div className="kv">
                <dt>זמן לכל ערך</dt>
                <dd className="mono small num" style={{ lineHeight: 1.7 }}>
                  {Object.entries(r.ops.value_ms as Record<string, number>).map(([f, ms]) => (
                    <div key={f}>{f}: {(ms / 1000).toFixed(1)}s</div>
                  ))}
                </dd>
              </div>
            )}
          </div>

          <div className="card" style={{ margin: 0 }}>
            <h3>היסטוריית חילוצים</h3>
            {history === null && <div className="muted small">טוען היסטוריה…</div>}
            {history !== null && history.length === 0 && (
              <div className="muted small">אין חילוצים קודמים למסמך זה.</div>
            )}
            {history !== null && history.length > 0 && (
              <div className="tbl-scroll" style={{ maxHeight: 300, overflowY: 'auto' }}>
                <table className="table">
                  <thead>
                    <tr>
                      <th>זמן</th>
                      <th>היקף</th>
                      <th>ציון</th>
                      <th>משך</th>
                      <th style={{ width: 60 }}></th>
                    </tr>
                  </thead>
                  <tbody>
                    {history.map((h, i) => {
                      const hr = h.result;
                      const key = `${h.run_id}-${i}`;
                      const isShown = viewing != null && viewing.at === hr.at;
                      const isLatest = i === 0;
                      return (
                        <tr key={key} style={isShown ? { background: 'var(--surface-2)' } : undefined}>
                          <td className="num small">
                            {fmtTime(hr.at || h.started)}
                            {isLatest && <span className="tag" style={{ marginInlineStart: 6 }}>אחרון</span>}
                          </td>
                          <td>
                            <span className="tag">{SCOPE_LABEL[h.scope || ''] || h.scope || '—'}</span>
                          </td>
                          <td>
                            <ScorePill r={hr} />
                          </td>
                          <td className="num small muted">
                            {hr.elapsed_s != null ? `${hr.elapsed_s}s` : '—'}
                          </td>
                          <td style={{ textAlign: 'end' }}>
                            {isShown || (isLatest && !viewing) ? (
                              <span className="muted small">מוצג</span>
                            ) : (
                              <button
                                className="link"
                                onClick={() => setViewing(isLatest ? null : hr)}
                              >
                                הצג
                              </button>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
            {history !== null && history.length > 1 && (
              <div className="muted small" style={{ marginTop: 8 }}>
                בחירת שורה מציגה את הערכים שחולצו באותה הרצה — להשוואה מול המצב הנוכחי.
              </div>
            )}
          </div>

          <div className="card" style={{ margin: 0 }}>
            <h3>שאילתות (מההגדרות)</h3>
            {!queries && <div className="muted small">טוען שאילתות…</div>}
            {queries &&
              Object.entries(fieldQueryMap)
                .filter(([f]) => f !== 'TYPE')
                .map(([field, qkey]) => (
                  <details className="rosetting" key={field}>
                    <summary>
                      <span style={{ fontWeight: 700 }}>{field}</span>
                      <span className="len">{qkey}</span>
                    </summary>
                    <pre className="codeblock" style={{ direction: 'ltr', textAlign: 'left', maxHeight: 300, overflow: 'auto', marginTop: 8 }}>
                      {JSON.stringify(queries[qkey], null, 2)}
                    </pre>
                  </details>
                ))}
            <div className="muted small" style={{ marginTop: 8 }}>
              עריכת השאילתות נעשית בטבלת settings (מפתחות q_v3_*) — ללא שינוי בתהליכים.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
