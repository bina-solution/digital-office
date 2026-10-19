import { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api, ColumnDef, RepoConfig } from '../api';
import { tell } from '../ask';
import { IC, Ic } from '../icons';
import { wordOf } from '../words';

type Row = Record<string, unknown>;
const EVENT_HE: Record<string, string> = { insert: 'נוצר', update: 'עודכן', delete: 'נמחק' };
const when = (v: unknown): string => {
  const d = new Date(String(v));
  return isNaN(d.getTime()) ? String(v) : d.toLocaleString('he-IL', { dateStyle: 'short', timeStyle: 'short' });
};
/** how one value of a column READS: a domain's value by its word (words.tsx), a moment as a person writes it,
 *  nothing as «ריק» */
const say = (c: ColumnDef, v: unknown): string =>
  v == null || v === '' ? 'ריק' : c.enum_values ? wordOf(c, v) : /^\d{4}-\d\d-\d\dT/.test(String(v)) ? when(v) : String(v);
/** the columns an event changed, against the row before it — but for the row's own stamp of that very event */
const changed = (cols: readonly ColumnDef[], e: Row, before: Row): ColumnDef[] => {
  const a = (e.row ?? {}) as Row, b = (before.row ?? {}) as Row;
  return cols.filter((c) => String(a[c.name] ?? '') !== String(b[c.name] ?? '') && String(a[c.name]) !== String(e.occurred_at));
};

export default function DocumentDetailPage() {
  const { repo, id } = useParams<{ repo: string; id: string }>();
  const [cfg, setCfg] = useState<RepoConfig | null>(null);
  const [row, setRow] = useState<Record<string, unknown> | null>(null);
  const [history, setHistory] = useState<Record<string, unknown>[]>([]);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [err, setErr] = useState<string | null>(null);

  // What could not be read is SAID, with a way to ask again: the three reads had no failure path at all, so a
  // document whose service was silent stood on «טוען…» for good.
  const load = useCallback(() => {
    if (!repo || !id) return;
    setErr(null);
    Promise.all([api.getRepo(repo), api.getDocument(repo, id), api.documentHistory(repo, id)])
      .then(([r, d, h]) => {
        setCfg(r.repo);
        setRow(d.row);
        setHistory(h.events);
      })
      .catch((e: unknown) => setErr(e instanceof Error ? e.message : 'אין תשובה מהשירות'));
  }, [repo, id]);
  useEffect(load, [load]);

  if (err)
    return (
      <div className="callout bad">
        <b>המסמך לא נטען.</b> {err}{' '}
        <button className="btn sm ghost" onClick={load}>נסה שוב</button>
      </div>
    );
  if (!repo || !id || !cfg || !row) return <div className="spin">טוען…</div>;

  // …and what was done, or what failed, is said by the office's notice: «נשמר» stood as grey text beside the
  // button, and a save that was refused threw past everything on the page and said nothing.
  async function save() {
    const patch: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(edits)) {
      if (v !== String(row?.[k] ?? '')) patch[k] = v;
    }
    if (Object.keys(patch).length === 0) return tell('ok', 'אין שינויים לשמור');
    try {
      await api.patchDocument(repo!, id!, patch);
    } catch (e: unknown) {
      return tell('bad', `השמירה נכשלה — ${e instanceof Error ? e.message : 'אין תשובה מהשירות'}`);
    }
    tell('ok', 'נשמר');
    setEdits({});
    load();
  }

  return (
    <div>
      <div className="toolbar">
        <Link to={`/repos/${repo}/documents`} className="link" title="חזרה לטבלת המסמכים"><Ic p={IC.arrowRight} /> מסמכים</Link>
        <h1 className="mono">{id}</h1>
      </div>
      {/* one under the other in a narrow frame: side by side at 390px each card was 170px wide — a name cut in its
          field, «מה שהיה ← מה שנהיה» on three lines */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="card">
          <h3>עריכה</h3>
          <div>
            {cfg.columns.map((c) => {
              const isPK = c.name === cfg.primary_key;
              const current = String(row[c.name] ?? '');
              // a field is headed as the documents table heads its column (what the service says of it, words.tsx);
              // the name it has in the database and its type are one hover away. A column with no heading stays
              // what it is — a name, set as one
              const label = c.label;
              return (
                <div key={c.name} className="field">
                  <label className={label ? undefined : 'mono'} title={`${c.name} · ${c.type}`}>
                    {label || c.name}
                  </label>
                  {/* A field of a value domain is CHOSEN, in the words the service says its values read by — what
                      is saved is still the value the database holds. It was a text box holding «INVOICE»,
                      «IN_PROGRESS», to be retyped letter for letter. A value the domain does not know stays itself. */}
                  {c.enum_values ? (
                    <select
                      defaultValue={current}
                      disabled={isPK}
                      onChange={(e) => setEdits((s) => ({ ...s, [c.name]: e.target.value }))}
                    >
                      {!(current in c.enum_values) && <option value={current}>{current || 'לא נקבע'}</option>}
                      {Object.keys(c.enum_values).map((v) => (
                        <option key={v} value={v}>{wordOf(c, v)}</option>
                      ))}
                    </select>
                  ) : (
                    <input
                      type="text"
                      defaultValue={current}
                      disabled={isPK}
                      onChange={(e) =>
                        setEdits((s) => ({ ...s, [c.name]: e.target.value }))
                      }
                      className="mono"
                    />
                  )}
                </div>
              );
            })}
          </div>
          <button onClick={save} className="btn" style={{ marginTop: 8 }}>
            שמירה
          </button>
        </div>
        <div className="card">
          <h3>היסטוריה ({history.length})</h3>
          <div className="space-y-2" style={{ maxHeight: 384, overflowY: 'auto' }}>
            {history.length === 0 && <div className="muted small">אין אירועים עדיין</div>}
            {history.map((e, i) => {
              // WHAT CHANGED, in words: each event against the one before it (the list is newest first), a
              // column by its heading and a value as the page says it. The whole row as it was stored — the
              // JSON that was all this card showed — stays one press away, set as code is set.
              const before = history[i + 1];
              const diff = before ? changed(cfg.columns, e, before) : [];
              return (
                <div key={i} style={{ borderBottom: '1px solid var(--line)', paddingBottom: 8, marginBottom: 8 }}>
                  {/* what happened and when, as a person reads them: «update» and «2026-10-10T00:52:23.987Z» stood here */}
                  <div className="flex justify-between">
                    <span style={{ fontWeight: 600 }} title={String(e.event_type)}>
                      {EVENT_HE[String(e.event_type)] || String(e.event_type)}
                    </span>
                    <span className="muted small num" title={String(e.occurred_at)}>{when(e.occurred_at)}</span>
                  </div>
                  {diff.map((c) => (
                    <div key={c.name} className="kv">
                      <dt title={c.name}>{c.label || c.name}</dt>
                      <dd>{say(c, (before?.row as Row | undefined)?.[c.name])} ← {say(c, (e.row as Row | undefined)?.[c.name])}</dd>
                    </div>
                  ))}
                  {before && diff.length === 0 && <div className="muted small">נשמר בלי שינוי בשדות</div>}
                  <details className="rowas">
                    <summary className="muted small">השורה כפי שנשמרה</summary>
                    <pre className="codeblock" style={{ fontSize: 10, marginTop: 4 }}>{JSON.stringify(e.row, null, 2)}</pre>
                  </details>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
