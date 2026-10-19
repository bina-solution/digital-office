import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import { IC, Ic } from '../icons';

// שאילתות חילוץ — the q_v3_* settings rows, properly visualised and editable.
// Each query is a PIPELINE: a primary step plus ordered fallbacks; the first
// step that yields a validated value wins. The read view renders that pipeline
// (action, anchors, geometry, regex, validations, fulltext) as structured
// chips; the edit view is a validated pretty-JSON editor saved via
// PUT /extraction/queries/<key> — queries load fresh from settings on every
// n8n run, so a save takes effect on the very next extraction.

type Q = Record<string, unknown>;

// ── domain grouping + Hebrew labels ──────────────────────────────────────────
const QUERY_META: Record<string, { label: string; group: string }> = {
  q_v3_type: { label: 'זיהוי סוג מסמך', group: 'בסיס (כל מסמך)' },
  q_v3_company: { label: 'ח"פ / עוסק (ספק)', group: 'בסיס (כל מסמך)' },
  q_v3_date_base: { label: 'תאריך (בסיס)', group: 'בסיס (כל מסמך)' },
  q_v3_invoice_id: { label: 'מספר חשבונית', group: 'חשבונית' },
  q_v3_date_invoice: { label: 'תאריך חשבונית', group: 'חשבונית' },
  q_v3_amount_invoice: { label: 'סכום לתשלום', group: 'חשבונית' },
  q_v3_shipment_id: { label: 'מספר תעודת משלוח (מזהה המסמך)', group: 'תעודת משלוח' },
  q_v3_date_shipment: { label: 'תאריך תעודה', group: 'תעודת משלוח' },
  q_v3_amount_shipment: { label: 'סכום (אם מודפס)', group: 'תעודת משלוח' },
  q_v3_linked_shipment: { label: 'תעודת משלוח מקושרת (על חשבונית)', group: 'הפניות מקושרות' },
  q_v3_linked_order: { label: 'הזמנת לקוח מקושרת (הזמנתכם)', group: 'הפניות מקושרות' },
  q_v3_order_id: { label: 'מספר הזמנה (מזהה המסמך)', group: 'הזמנת רכש' },
  q_v3_date_bs: { label: 'תאריך דוח', group: 'דוח גיול / כרטסת' },
  q_v3_amount_bs: { label: 'יתרה', group: 'דוח גיול / כרטסת' },
};
const GROUP_ORDER = [
  'בסיס (כל מסמך)',
  'חשבונית',
  'תעודת משלוח',
  'הפניות מקושרות',
  'הזמנת רכש',
  'דוח גיול / כרטסת',
  'אחר',
];

const ACTION_HE: Record<string, string> = {
  'find after': 'אחרי עוגן',
  'find below': 'מתחת לעוגן',
  'find near': 'בסביבת עוגן',
  'find regex': 'תבנית regex',
  'find option': 'בחירה מרשימה',
};
const SCOPE_HE: Record<string, string> = {
  row: 'שורה',
  column: 'עמודה',
  below: 'מתחת',
  block: 'בלוק',
};
const SELECT_HE: Record<string, string> = {
  top: 'העליון',
  bottom: 'התחתון',
  nearest: 'הקרוב ביותר',
};

function validationLabel(v: Q): string {
  const t = String(v.validation_type ?? '');
  const val = v.validation_value;
  switch (t) {
    case 'has_number': return 'מכיל ספרה';
    case 'length_greater_than': return `אורך > ${val}`;
    case 'length_less_than': return `אורך < ${val}`;
    case 'length_equals': return `אורך = ${val}`;
    case 'not_starts_with': return `לא מתחיל ב-${val}`;
    case 'not_contains': return `לא מכיל "${val}"`;
    case 'starts_with': return `מתחיל ב-${val}`;
    case 'equals': return `שווה ל-${val}`;
    case 'matches_regex': return `regex: ${val}`;
    case 'is_money': return 'סכום כספי';
    default: return `${t}${val != null ? `: ${val}` : ''}`;
  }
}

// ── one pipeline step (primary or fallback) ──────────────────────────────────
function StepRow({ step, index }: { step: Q; index: number }) {
  const action = String(step.action ?? '');
  const anchors = Array.isArray(step.action_value)
    ? (step.action_value as unknown[]).map(String)
    : typeof step.action_value === 'string'
      ? [step.action_value]
      : [];
  const isRegexAction = action === 'find regex';
  const validations = Array.isArray(step.value_validations)
    ? (step.value_validations as Q[])
    : [];
  const scope = step.scope ? String(step.scope) : null;
  const select = step.select ? String(step.select) : null;
  const rowSide = step.row_side ? String(step.row_side) : null;
  const ftDisabled = step.fulltext_fallback === false;
  const returns = step.returns != null ? String(step.returns) : null;

  return (
    <div
      style={{
        display: 'flex',
        gap: 10,
        padding: '10px 12px',
        borderTop: index === 0 ? 'none' : '1px solid var(--line)',
        alignItems: 'baseline',
        flexWrap: 'wrap',
      }}
    >
      <span
        className="num"
        title={index === 0 ? 'השלב הראשי' : `נפילה לאחור ${index}`}
        style={{
          flex: '0 0 auto',
          width: 26,
          height: 26,
          borderRadius: 13,
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: 12,
          fontWeight: 700,
          background: index === 0 ? 'var(--accent-bg, var(--surface-2))' : 'var(--surface-2)',
          color: index === 0 ? 'var(--accent-d)' : 'var(--muted)',
          border: '1px solid var(--line)',
          alignSelf: 'center',
        }}
      >
        {index === 0 ? <Ic p={IC.star} /> : index}
      </span>
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
          <span className="pill unset">{ACTION_HE[action] || action}</span>
          {scope && <span className="tag">סריקה: {SCOPE_HE[scope] || scope}</span>}
          {select && <span className="tag">בחירה: {SELECT_HE[select] || select}</span>}
          {rowSide && <span className="tag">צד: {rowSide === 'after' ? 'אחרי התווית' : 'לפני התווית'}</span>}
          {returns && (
            <span className="tag">
              מחזיר: <b>{returns}</b>
            </span>
          )}
          {ftDisabled ? (
            <span className="tag" title="השלב לא נופל לסריקת טקסט-מלא — מרחבי בלבד">
              טקסט־מלא: כבוי
            </span>
          ) : action !== 'find regex' && action !== 'find option' ? (
            <span className="tag" style={{ opacity: 0.65 }}>טקסט־מלא: פעיל</span>
          ) : null}
        </div>
        {anchors.length > 0 && (
          <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', alignItems: 'center' }}>
            <span className="muted small" style={{ flex: '0 0 auto' }}>
              {isRegexAction ? 'תבנית:' : 'עוגנים:'}
            </span>
            {isRegexAction ? (
              <code className="mono small" style={{ direction: 'ltr' }}>{anchors[0]}</code>
            ) : (
              anchors.map((a, i) => (
                <span
                  key={i}
                  className="mono small"
                  style={{
                    background: 'var(--surface-2)',
                    border: '1px solid var(--line)',
                    borderRadius: 6,
                    padding: '1px 7px',
                  }}
                >
                  {a}
                </span>
              ))
            )}
          </div>
        )}
        {(typeof step.value_regex === 'string' || validations.length > 0) && (
          <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', alignItems: 'center' }}>
            <span className="muted small" style={{ flex: '0 0 auto' }}>ערך תקין:</span>
            {typeof step.value_regex === 'string' && (
              <code
                className="mono small"
                style={{ direction: 'ltr', color: 'var(--accent-d)' }}
                title="value_regex — צורת הערך"
              >
                {step.value_regex}
              </code>
            )}
            {validations.map((v, i) => (
              <span key={i} className="tag" style={{ direction: 'ltr' }}>
                {validationLabel(v)}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── JSON editor (pretty, validated) ──────────────────────────────────────────
function JsonEditor({
  qkey,
  value,
  onSaved,
  onCancel,
}: {
  qkey: string;
  value: unknown;
  onSaved: (v: unknown) => void;
  onCancel: () => void;
}) {
  const [text, setText] = useState(() => JSON.stringify(value, null, 2));
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const parsed = useMemo(() => {
    try {
      const v = JSON.parse(text);
      if (v === null || typeof v !== 'object' || Array.isArray(v))
        return { ok: false as const, error: 'השאילתה חייבת להיות אובייקט JSON' };
      return { ok: true as const, value: v as Q };
    } catch (e) {
      return { ok: false as const, error: e instanceof Error ? e.message : String(e) };
    }
  }, [text]);

  const dirty = useMemo(
    () => text !== JSON.stringify(value, null, 2),
    [text, value],
  );

  const save = useCallback(async () => {
    if (!parsed.ok) return;
    setSaving(true);
    setErr(null);
    try {
      await api.putExtractionQuery(qkey, parsed.value);
      onSaved(parsed.value);
    } catch (e: unknown) {
      const body = (e as { body?: { error?: string } })?.body;
      setErr(body?.error || (e instanceof Error ? e.message : String(e)));
    } finally {
      setSaving(false);
    }
  }, [qkey, parsed, onSaved]);

  return (
    <div style={{ padding: 12, borderTop: '1px solid var(--line)' }}>
      <textarea
        className="mono"
        spellCheck={false}
        value={text}
        onChange={(e) => setText(e.target.value)}
        style={{
          width: '100%',
          minHeight: 340,
          direction: 'ltr',
          textAlign: 'left',
          fontSize: 12.5,
          lineHeight: 1.55,
          padding: 12,
          borderRadius: 10,
          border: `1px solid ${parsed.ok ? 'var(--line)' : 'var(--red)'}`,
          background: 'var(--surface-2)',
          color: 'var(--text)',
          resize: 'vertical',
          tabSize: 2,
        }}
      />
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 8, flexWrap: 'wrap' }}>
        <button className="btn sm" disabled={!parsed.ok || !dirty || saving} onClick={save}>
          {saving ? <span className="spinner" /> : 'שמור'}
        </button>
        <button className="btn sm ghost" disabled={saving} onClick={onCancel}>
          ביטול
        </button>
        <button
          className="link"
          disabled={!parsed.ok}
          onClick={() => parsed.ok && setText(JSON.stringify(parsed.value, null, 2))}
        >
          סדר (format)
        </button>
        {!parsed.ok && (
          <span className="small" style={{ color: 'var(--red)', direction: 'ltr' }}>
            {parsed.error}
          </span>
        )}
        {err && (
          <span className="small" style={{ color: 'var(--red)' }}>
            השמירה נכשלה: {err}
          </span>
        )}
        <span className="muted small" style={{ marginInlineStart: 'auto' }}>
          נשמר להגדרות — חל מהריצה הבאה
        </span>
      </div>
    </div>
  );
}

// ── one query card: header + pipeline / editor ───────────────────────────────
function QueryCard({
  qkey,
  value,
  onSaved,
}: {
  qkey: string;
  value: Q;
  onSaved: (key: string, v: unknown) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [justSaved, setJustSaved] = useState(false);
  const meta = QUERY_META[qkey];
  const steps: Q[] = useMemo(() => {
    const fbs = Array.isArray(value.fallbacks) ? (value.fallbacks as Q[]) : [];
    const primary: Q = { ...value };
    delete (primary as Record<string, unknown>).fallbacks;
    return [primary, ...fbs];
  }, [value]);

  return (
    <div className="card" style={{ margin: 0, padding: 0, overflow: 'hidden' }}>
      <div
        style={{
          display: 'flex',
          gap: 8,
          alignItems: 'center',
          padding: '10px 12px',
          flexWrap: 'wrap',
          background: 'var(--surface-2)',
          borderBottom: '1px solid var(--line)',
        }}
      >
        <b>{meta?.label || qkey}</b>
        <span className="mono small muted" style={{ direction: 'ltr' }}>{qkey}</span>
        <span className="tag num">{steps.length} שלבים</span>
        {justSaved && <span className="pill ok">נשמר</span>}
        <button
          className="link"
          style={{ marginInlineStart: 'auto' }}
          onClick={() => setEditing((e) => !e)}
        >
          {editing ? 'תצוגה' : <><Ic p={IC.edit} /> עריכה</>}
        </button>
      </div>
      {editing ? (
        <JsonEditor
          qkey={qkey}
          value={value}
          onCancel={() => setEditing(false)}
          onSaved={(v) => {
            onSaved(qkey, v);
            setEditing(false);
            setJustSaved(true);
            setTimeout(() => setJustSaved(false), 2500);
          }}
        />
      ) : (
        steps.map((s, i) => <StepRow key={i} step={s} index={i} />)
      )}
    </div>
  );
}

// ── routing: field → query, per category ─────────────────────────────────────
const ROUTING_CAT_HE: Record<string, string> = {
  base: 'בסיס (כל מסמך)',
  invoice: 'חשבונית',
  shipment: 'תעודת משלוח',
  order: 'הזמנת רכש',
  bs: 'דוח גיול',
};

function RoutingCard({
  value,
  onSaved,
}: {
  value: Record<string, Record<string, string>>;
  onSaved: (v: unknown) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [justSaved, setJustSaved] = useState(false);
  return (
    <div className="card" style={{ margin: 0, padding: 0, overflow: 'hidden' }}>
      <div
        style={{
          display: 'flex',
          gap: 8,
          alignItems: 'center',
          padding: '10px 12px',
          flexWrap: 'wrap',
          background: 'var(--surface-2)',
          borderBottom: '1px solid var(--line)',
        }}
      >
        <b>ניתוב שדות לשאילתות</b>
        <span className="mono small muted" style={{ direction: 'ltr' }}>q_v3_routing</span>
        {justSaved && <span className="pill ok">נשמר</span>}
        <button className="link" style={{ marginInlineStart: 'auto' }} onClick={() => setEditing((e) => !e)}>
          {editing ? 'תצוגה' : <><Ic p={IC.edit} /> עריכה</>}
        </button>
      </div>
      {editing ? (
        <JsonEditor
          qkey="q_v3_routing"
          value={value}
          onCancel={() => setEditing(false)}
          onSaved={(v) => {
            onSaved(v);
            setEditing(false);
            setJustSaved(true);
            setTimeout(() => setJustSaved(false), 2500);
          }}
        />
      ) : (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill,minmax(230px,1fr))',
            gap: 0,
          }}
        >
          {Object.entries(value).map(([cat, fields]) => (
            <div key={cat} style={{ padding: '10px 12px', borderInlineEnd: '1px solid var(--line)' }}>
              <div className="muted small" style={{ marginBottom: 6, fontWeight: 700 }}>
                {ROUTING_CAT_HE[cat] || cat}
              </div>
              {Object.entries(fields || {}).map(([field, qk]) => (
                <div key={field} style={{ display: 'flex', gap: 6, alignItems: 'baseline', padding: '2px 0' }}>
                  <span className="mono small" style={{ direction: 'ltr' }}>{field}</span>
                  <span className="muted small" style={{ display: 'inline-flex' }} aria-label="מנותב אל"><Ic p={IC.arrowLeft} /></span>
                  <span className="mono small muted" style={{ direction: 'ltr' }}>{String(qk)}</span>
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── the section ──────────────────────────────────────────────────────────────
export default function ExtractionQueries() {
  const [queries, setQueries] = useState<Record<string, unknown> | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api
      .getExtractionQueries()
      .then((r) => setQueries(r.queries))
      .catch((e: unknown) => setErr(e instanceof Error ? e.message : String(e)));
  }, []);

  const onSaved = useCallback((key: string, v: unknown) => {
    setQueries((prev) => (prev ? { ...prev, [key]: v } : prev));
  }, []);

  const groups = useMemo(() => {
    if (!queries) return [];
    const byGroup = new Map<string, [string, Q][]>();
    for (const [k, v] of Object.entries(queries)) {
      if (k === 'q_v3_routing' || v === null || typeof v !== 'object' || Array.isArray(v)) continue;
      const g = QUERY_META[k]?.group || 'אחר';
      if (!byGroup.has(g)) byGroup.set(g, []);
      byGroup.get(g)!.push([k, v as Q]);
    }
    return GROUP_ORDER.filter((g) => byGroup.has(g)).map(
      (g) => [g, byGroup.get(g)!] as const,
    );
  }, [queries]);

  if (err)
    return (
      <div className="callout bad">
        <b>שאילתות החילוץ אינן זמינות.</b> {err}
      </div>
    );
  if (!queries) return <div className="spin">טוען שאילתות…</div>;

  const routing = queries.q_v3_routing as Record<string, Record<string, string>> | undefined;

  return (
    <>
      <div className="callout">
        לוגיקת החילוץ כולה — <b>קריאת apitools אחת לכל ערך</b>, כל שאילתה היא צינור:
        שלב ראשי (מסומן בכוכב) ואחריו נפילות-לאחור לפי הסדר; הערך הראשון שעובר את הוולידציות
        מנצח. עריכה נשמרת להגדרות וחלה על הריצה הבאה — ללא שינוי בתהליכי n8n.
      </div>
      {routing && (
        <div style={{ marginBottom: 16 }}>
          <RoutingCard value={routing} onSaved={(v) => onSaved('q_v3_routing', v)} />
        </div>
      )}
      {groups.map(([group, items]) => (
        <div key={group} style={{ marginBottom: 20 }}>
          <h3 style={{ margin: '0 0 10px' }}>{group}</h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {items.map(([k, v]) => (
              <QueryCard key={k} qkey={k} value={v} onSaved={onSaved} />
            ))}
          </div>
        </div>
      ))}
    </>
  );
}
