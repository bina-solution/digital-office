import { Dispatch, SetStateAction, useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  api,
  ConfigRow,
  SettingRow,
  SyncRegistryEntry,
} from '../api';
import { ask, tell } from '../ask';
import BinaTable, { BinaColumn } from '../components/BinaTable';
import ExtractionQueries from '../components/ExtractionQueries';

// ── section model ────────────────────────────────────────────────────────────
type SectionKey = 'sync' | 'queries' | 'system' | 'companies' | 'tags';
const SECTIONS: { key: SectionKey; label: string }[] = [
  { key: 'sync', label: 'תצורת סנכרון' },
  { key: 'queries', label: 'שאילתות חילוץ' },
  { key: 'system', label: 'הגדרות מערכת' },
  { key: 'companies', label: 'חברות' },
  { key: 'tags', label: 'חוקי תיוג' },
];

// n8n/settings values are TEXT — treat these two literals as a boolean toggle.
const isBoolish = (v: string | null | undefined): boolean =>
  v === 'true' || v === 'false';

// why a request did not do what was asked, in the words the request itself came back with (api.ts words them)
const whyNot = (e: unknown): string => (e instanceof Error ? e.message : 'אין תשובה מהשירות');

const cell = (v: unknown): string => {
  if (v == null || v === '') return '—';
  if (typeof v === 'object') {
    try {
      return JSON.stringify(v);
    } catch {
      return String(v);
    }
  }
  return String(v);
};

// ── (b) one editable system-setting row ──────────────────────────────────────
function EditableSetting({
  row,
  onSaved,
}: {
  row: SettingRow;
  onSaved: (key: string, value: string) => void;
}) {
  const boolish = isBoolish(row.value);
  const [draft, setDraft] = useState<string>(row.value ?? '');
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [ok, setOk] = useState(false);

  useEffect(() => {
    setDraft(row.value ?? '');
  }, [row.value]);

  const save = useCallback(
    async (value: string) => {
      setSaving(true);
      setErr(null);
      setOk(false);
      // WHY a setting was not saved is SAID, by the office's notice: it stood in the tooltip of a pill that read
      // «שגיאה» — and a finger has no tooltip.
      const failed = (why: string) => {
        setErr(why);
        tell('bad', `ההגדרה לא נשמרה — ${why}`);
      };
      try {
        const res = await api.putConfigSetting(row.key, boolish ? value === 'true' : value);
        if (res.reachable === false) {
          failed(res.error || 'השירות אינו זמין כרגע');
          return;
        }
        const saved = res.setting?.value ?? value;
        setDraft(saved);
        onSaved(row.key, saved);
        setOk(true);
        setTimeout(() => setOk(false), 2000);
      } catch (e: unknown) {
        const body = (e as { body?: { message?: string } })?.body;
        failed(body?.message || (e instanceof Error ? e.message : 'אין תשובה מהשירות'));
      } finally {
        setSaving(false);
      }
    },
    [row.key, boolish, onSaved],
  );

  const dirty = draft !== (row.value ?? '');

  return (
    <div className="setrow">
      <span className="key">{row.key}</span>
      <div className="ctl">
        {boolish ? (
          <button
            className={`switch${draft === 'true' ? ' on' : ''}`}
            disabled={saving}
            aria-label={row.key}
            onClick={() => save(draft === 'true' ? 'false' : 'true')}
          >
            <span className="knob" />
          </button>
        ) : (
          <>
            <input
              className="mono"
              value={draft}
              disabled={saving}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && dirty) save(draft);
              }}
            />
            <button
              className="btn sm"
              disabled={saving || !dirty}
              onClick={() => save(draft)}
            >
              {saving ? <span className="spinner" /> : 'שמור'}
            </button>
          </>
        )}
        {ok && <span className="pill ok">נשמר</span>}
        {err && <span className="pill bad" title={err}>לא נשמר</span>}
      </div>
    </div>
  );
}

// ── config table on the platform-standard <BinaTable> (RevoGrid) ──────────────
// Full CRUD: inline edit (PATCH), add row (POST), delete row (DELETE). RevoGrid
// brings sort/filter/reorder/resize for free; we only supply columns + the save
// hooks. `order` gives an explicit RTL column order (first = rightmost).
// THE ROWS HAVE ONE OWNER — the page, which also counts them on the tab. The grid kept a copy of its own: a row
// added or deleted did not move the tab's number, and leaving the tab and returning drew the copy afresh from the
// page's rows — the deleted row was back, the added one gone, an edited cell showed what it held before (the
// service had the change; the screen did not).
function BinaConfigGrid({
  rows,
  setRows,
  table,
  pk = 'id',
  denyKeys = [],
  order,
  hideKeys = [],
}: {
  rows: ConfigRow[];
  setRows: Dispatch<SetStateAction<ConfigRow[]>>;
  table: string;
  pk?: string;
  denyKeys?: string[];
  order?: string[];
  hideKeys?: string[];
}) {
  const keys = useMemo(() => {
    const seen: string[] = [];
    for (const r of rows) {
      for (const k of Object.keys(r)) if (!seen.includes(k)) seen.push(k);
    }
    return seen; // noise columns start hidden (column.hidden) — the picker can re-show them
  }, [rows]);

  // explicit order first (only those present), then any remaining keys
  const ordered = useMemo(() => {
    if (!order) return keys;
    const head = order.filter((k) => keys.includes(k));
    const tail = keys.filter((k) => !order.includes(k));
    return [...head, ...tail];
  }, [keys, order]);

  const columns: BinaColumn[] = useMemo(
    () =>
      ordered.map((k) => ({
        key: k,
        label: k,
        width: k === pk ? 64 : k.length > 12 ? 240 : 150,
        editable: k !== pk && !denyKeys.includes(k),
        filter: true,
        validate: validatorFor(k),
        hidden: hideKeys.includes(k), // starts hidden; column picker can re-show
        // numeric-ish columns end-aligned (ERP convention)
        align: /^מזהה|^id$/.test(k) ? ('end' as const) : undefined,
      })),
    [ordered, pk, denyKeys, hideKeys],
  );

  // display JSON/object cells (e.g. `extra` jsonb) as text, not "[object Object]"
  const data = useMemo(
    () =>
      rows.map((r) => {
        const o: Record<string, unknown> = {};
        for (const [k, v] of Object.entries(r)) {
          o[k] = v !== null && typeof v === 'object' ? JSON.stringify(v) : v;
        }
        return o;
      }),
    [rows],
  );

  const onEdit = useCallback(
    async (id: unknown, key: string, value: unknown) => {
      const res = await api.patchConfigRow(table, String(id), key, value);
      if (!res || res.ok === false) throw new Error(res?.error || 'השמירה נכשלה');
      setRows((rs) =>
        rs.map((r) => (String(r[pk]) === String(id) ? { ...r, [key]: value } : r)),
      );
    },
    [table, pk, setRows],
  );

  // A REFUSAL IS SAID, of a row added and of a row deleted. Both are called by the table without being waited for:
  // a request that failed was thrown past everything on the page, and an answer that was not «ok» was passed over
  // in silence — the row was not there (or still was) and nothing told why.
  const onAddRow = useCallback(async () => {
    try {
      const res = await api.addConfigRow(table, {});
      if (res?.ok && res.row) setRows((rs) => [res.row as ConfigRow, ...rs]);
      else tell('bad', `השורה לא נוספה — ${res?.error || 'הבקשה נדחתה'}`);
    } catch (e: unknown) {
      tell('bad', `השורה לא נוספה — ${whyNot(e)}`);
    }
  }, [table, setRows]);

  const onDeleteRow = useCallback(
    async (id: unknown) => {
      // what a person calls the row: its first two filled cells, in the order the screen shows them
      const row: ConfigRow = rows.find((r) => String(r[pk]) === String(id)) || {};
      const told = ordered.filter((k) => k !== pk).map((k) => cell(row[k])).filter((v) => v !== '—').slice(0, 2);
      if (!(await ask({ title: 'למחוק את השורה?', facts: [['שורה', told.join(' · ') || String(id)]], ok: 'מחיקה', danger: true })))
        return;
      try {
        const res = await api.deleteConfigRow(table, String(id));
        if (res?.ok) setRows((rs) => rs.filter((r) => String(r[pk]) !== String(id)));
        else tell('bad', `השורה לא נמחקה — ${res?.error || 'הבקשה נדחתה'}`);
      } catch (e: unknown) {
        tell('bad', `השורה לא נמחקה — ${whyNot(e)}`);
      }
    },
    [table, pk, rows, ordered, setRows],
  );

  // bulk delete of selected rows (asked by BinaTable). ONLY the rows the service deleted leave the table: every
  // ticked row left it, and a refused delete looked done until the next reload put the row back — beside a notice
  // that counted it as failed. (The live app's settings page had this corrected; the fork had not.)
  const onDeleteRows = useCallback(
    async (ids: unknown[]) => {
      const gone = new Set<string>();
      let fail = 0;
      for (const id of ids) {
        try {
          const res = await api.deleteConfigRow(table, String(id));
          if (res?.ok) gone.add(String(id));
          else fail++;
        } catch {
          fail++;
        }
      }
      setRows((rs) => rs.filter((r) => !gone.has(String(r[pk]))));
      return { ok: gone.size, fail };
    },
    [table, pk, setRows],
  );

  // bulk import (CSV/XLSX rows already mapped to column keys by BinaTable)
  const onImportRows = useCallback(
    async (imported: Record<string, unknown>[]) => {
      let ok = 0;
      let fail = 0;
      const added: ConfigRow[] = [];
      for (const seed of imported) {
        try {
          const res = await api.addConfigRow(table, seed);
          if (res?.ok && res.row) {
            added.push(res.row as ConfigRow);
            ok++;
          } else fail++;
        } catch {
          fail++;
        }
      }
      if (added.length) setRows((rs) => [...added, ...rs]);
      return { ok, fail };
    },
    [table, setRows],
  );

  // ops quick-filters: incomplete records jump out (chips with live counts)
  const quickFilters = useMemo(
    () =>
      table === 'companies'
        ? [
            {
              key: 'no-id',
              label: 'חסרי מזהה',
              fn: (r: Record<string, unknown>) => !String(r['מזהה 1'] ?? '').trim(),
            },
            {
              key: 'no-mail',
              label: 'חסרי מייל',
              fn: (r: Record<string, unknown>) => !String(r['מייל 1'] ?? '').trim(),
            },
          ]
        : undefined,
    [table],
  );

  return (
    <BinaTable
      columns={columns}
      data={data}
      rowKey={pk}
      tableId={table}
      quickFilters={quickFilters}
      onEdit={onEdit}
      onAddRow={onAddRow}
      onDeleteRow={onDeleteRow}
      onDeleteRows={onDeleteRows}
      onImportRows={onImportRows}
      addLabel="הוסף שורה"
      height={560}
    />
  );
}

// per-column edit validators (Hebrew errors) — bad input never reaches the API
function validatorFor(key: string): ((v: unknown) => string | null) | undefined {
  if (/^מזהה/.test(key)) {
    return (v) => {
      const s = String(v ?? '').trim();
      if (s === '') return null; // clearing is allowed
      return /^\d{5,15}$/.test(s) ? null : 'מזהה חייב להיות 5–15 ספרות';
    };
  }
  if (/^מייל/.test(key)) {
    return (v) => {
      const s = String(v ?? '').trim();
      if (s === '') return null;
      return /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(s) ? null : 'כתובת מייל לא תקינה';
    };
  }
  return undefined;
}

// explicit RTL column order for the companies table (first key = rightmost cell)
const COMPANIES_ORDER = [
  'שם חברה',
  'מזהה 1',
  'מזהה 2',
  'מייל 1',
  'מייל 2',
  'שם ספק מפריוריטי',
  'הוראות לAI לחילוץ דוח גיול',
  'TRUSTED_SOURCE_TYPES',
  'extra',
  'created_at',
  'id',
];

// ── unreachable / empty helpers ──────────────────────────────────────────────
function Unreachable({ what, error }: { what: string; error?: string }) {
  return (
    <div className="callout bad">
      <b>{what} אינו זמין.</b> לא ניתן לקרוא מ-supabase כרגע
      {error ? ` (${error})` : ''}.
    </div>
  );
}

export default function SettingsPage() {
  const [section, setSection] = useState<SectionKey>('sync');

  // sync registry
  const [registry, setRegistry] = useState<SyncRegistryEntry[]>([]);
  const [regReach, setRegReach] = useState(true);
  const [regErr, setRegErr] = useState<string | undefined>();

  // settings
  const [settings, setSettings] = useState<SettingRow[]>([]);
  const [editableKeys, setEditableKeys] = useState<string[]>([]);
  const [setReach, setSetReach] = useState(true);
  const [setErr, setSetErr] = useState<string | undefined>();

  // companies / tag_rules
  const [companies, setCompanies] = useState<ConfigRow[]>([]);
  const [compReach, setCompReach] = useState(true);
  const [compErr, setCompErr] = useState<string | undefined>();
  const [tagRules, setTagRules] = useState<ConfigRow[]>([]);
  const [tagReach, setTagReach] = useState(true);
  const [tagErr, setTagErr] = useState<string | undefined>();

  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    Promise.allSettled([
      api.getSyncRegistry(),
      api.getConfigSettings(),
      api.getConfigCompanies(),
      api.getConfigTagRules(),
    ]).then(([reg, set, comp, tag]) => {
      if (!alive) return;
      if (reg.status === 'fulfilled') {
        setRegistry(Array.isArray(reg.value.registry) ? reg.value.registry : []);
        setRegReach(reg.value.reachable !== false);
        setRegErr(reg.value.error);
      } else {
        setRegReach(false);
        setRegErr(String(reg.reason));
      }
      if (set.status === 'fulfilled') {
        setSettings(Array.isArray(set.value.settings) ? set.value.settings : []);
        setEditableKeys(set.value.editable_keys || []);
        setSetReach(set.value.reachable !== false);
        setSetErr(set.value.error);
      } else {
        setSetReach(false);
        setSetErr(String(set.reason));
      }
      if (comp.status === 'fulfilled') {
        setCompanies(Array.isArray(comp.value.companies) ? comp.value.companies : []);
        setCompReach(comp.value.reachable !== false);
        setCompErr(comp.value.error);
      } else {
        setCompReach(false);
        setCompErr(String(comp.reason));
      }
      if (tag.status === 'fulfilled') {
        setTagRules(Array.isArray(tag.value.tag_rules) ? tag.value.tag_rules : []);
        setTagReach(tag.value.reachable !== false);
        setTagErr(tag.value.error);
      } else {
        setTagReach(false);
        setTagErr(String(tag.reason));
      }
      setLoading(false);
    });
    return () => {
      alive = false;
    };
  }, []);

  const onSettingSaved = useCallback((key: string, value: string) => {
    setSettings((prev) =>
      prev.map((r) => (r.key === key ? { ...r, value } : r)),
    );
  }, []);

  const editable = settings
    .filter((r) => editableKeys.includes(r.key))
    .sort((a, b) => a.key.localeCompare(b.key));
  // q_v3_* rows get their own dedicated section (שאילתות חילוץ) with a proper
  // pipeline view + editor — keep them out of the raw structural dump
  const queryKeysCount = settings.filter((r) => r.key.startsWith('q_v3_')).length;
  const structural = settings
    .filter((r) => !editableKeys.includes(r.key) && !r.key.startsWith('q_v3_'))
    .sort((a, b) => a.key.localeCompare(b.key));

  const counts: Record<SectionKey, number> = {
    sync: registry.length,
    queries: queryKeysCount,
    system: settings.length - queryKeysCount,
    companies: companies.length,
    tags: tagRules.length,
  };

  return (
    <div>
      <div className="app-header">
        <div>
          <h1>הגדרות</h1>
          <div className="sub">
            תצורת הצינור — מקורות סנכרון, הגדרות מערכת, חברות וחוקי תיוג. שינוי מבני
            (שאילתות, מקורות) נשמר מבינה ומוצג לקריאה בלבד.
          </div>
        </div>
      </div>

      <div className="subnav">
        {SECTIONS.map((s) => (
          <button
            key={s.key}
            className={`stab${section === s.key ? ' active' : ''}`}
            onClick={() => setSection(s.key)}
          >
            {s.label}
            {!loading && <span className="n num">{counts[s.key]}</span>}
          </button>
        ))}
      </div>

      {loading && <div className="spin">טוען הגדרות…</div>}

      {/* (a) sync registry — MOVED. Config and live state used to live in two different tabs, both
          read-only and neither actionable. They are now one surface under סנכרון, which also owns
          creating/editing pipes, running them and moving stuck items. See sim/INDOX-SYNC.md. */}
      {!loading && section === 'sync' && (
        <div className="callout">
          מקורות הסנכרון עברו ל<b>מסך הסנכרון</b> — שם הם מוצגים יחד עם המצב החי שלהם, וניתן
          להוסיף, לערוך, להשהות, להריץ ידנית ולהעביר פריטים בין מצבים.
          <div style={{ marginTop: 10 }}>
            <Link to="/sync" className="btn">מעבר לסנכרון</Link>
          </div>
        </div>
      )}

      {/* (a2) extraction queries — visual pipeline + JSON editor */}
      {!loading && section === 'queries' && <ExtractionQueries />}

      {/* (b) system settings — editable allowlist + read-only structural */}
      {!loading && section === 'system' && (
        <>
          {!setReach && <Unreachable what="הגדרות המערכת" error={setErr} />}
          {setReach && (
            <>
              <div className="card">
                <h3>מתגים והגדרות סקלריות</h3>
                {editable.length === 0 ? (
                  <div className="muted small">אין הגדרות הניתנות לעריכה.</div>
                ) : (
                  editable.map((r) => (
                    <EditableSetting key={r.key} row={r} onSaved={onSettingSaved} />
                  ))
                )}
              </div>

              {structural.length > 0 && (
                <div className="card">
                  <h3>
                    הגדרות מבניות{' '}
                    <span className="muted small">
                      ({structural.length}, לקריאה בלבד)
                    </span>
                  </h3>
                  {structural.map((r) => {
                    const val = r.value ?? '';
                    return (
                      <details key={r.key} className="rosetting">
                        <summary>
                          {r.key}
                          <span className="len num">{val.length} תווים</span>
                        </summary>
                        <pre className="codeblock" style={{ marginTop: 8 }}>
                          {val}
                        </pre>
                      </details>
                    );
                  })}
                </div>
              )}
            </>
          )}
        </>
      )}

      {/* (c) companies — editable data grid */}
      {!loading && section === 'companies' && (
        <>
          {!compReach ? (
            <Unreachable what="טבלת החברות" error={compErr} />
          ) : (
            <>
              <div className="callout">
                טבלת החברות — מיון, סינון וסידור
                עמודות מובנים. לחיצה כפולה על תא לעריכה; הוספה/מחיקה בסרגל. מזהה
                ותאריך יצירה נעולים.
              </div>
              <BinaConfigGrid
                rows={companies}
                setRows={setCompanies}
                table="companies"
                pk="id"
                denyKeys={['id', 'created_at']}
                order={COMPANIES_ORDER}
                hideKeys={['id', 'created_at', 'extra', 'TRUSTED_SOURCE_TYPES']}
              />
            </>
          )}
        </>
      )}

      {/* (d) tag_rules — editable data grid */}
      {!loading && section === 'tags' && (
        <>
          {!tagReach ? (
            <Unreachable what="טבלת חוקי התיוג" error={tagErr} />
          ) : (
            <>
              <div className="callout">
                חוקי תיוג (<b>bina-table</b>) — ניתנים לעריכה. לחיצה כפולה על תא
                כדי לערוך. מזהה ותאריך יצירה נעולים.
              </div>
              <BinaConfigGrid
                rows={tagRules}
                setRows={setTagRules}
                table="tag_rules"
                order={['EVENT', 'KEY', 'LABEL', 'RULE', 'TYPE', 'VALIDATION STATUS', 'VALIDATION ERRORS']}
                hideKeys={['id', 'created_at', 'row_number', 'label_id']}
                pk="id"
                denyKeys={['id', 'created_at']}
              />
            </>
          )}
        </>
      )}
    </div>
  );
}
