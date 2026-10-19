import { useCallback, useEffect, useMemo, useRef, useState, ReactNode } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useInstanceLink } from '../instancesContext';
import {
  api,
  ConfigRow,
  PipelineStatus,
  SettingRow,
} from '../api';
import DataGrid, { GridColumn, GridRow, Ic, useToasts } from '../components/DataGrid';
import { ConfirmFact, useConfirm } from '../components/ConfirmModal';
import ExtractionQueries from '../components/ExtractionQueries';
import NewRowDrawer from '../components/NewRowDrawer';
import { IC } from '../icons';
import { mailOrganizerUrl } from '../siblings';

// ── section model ────────────────────────────────────────────────────────────
// (the 'sync' section was REMOVED 2026-09-02 — sync configuration lives on the סנכרון screen only;
//  the 'tags' section was REMOVED with N1 — the mail app's organizer is the ONE store of label rules)
// הגדרות מערכת comes first: the master switches and the pipeline knobs are what this screen is
// opened for during an incident; the query editor is the tuning bench.
type SectionKey = 'system' | 'queries' | 'companies';
const SECTIONS: { key: SectionKey; label: string }[] = [
  { key: 'system', label: 'הגדרות מערכת' },
  { key: 'queries', label: 'שאילתות חילוץ' },
  { key: 'companies', label: 'חברות' },
];
const isSection = (v: unknown): v is SectionKey => SECTIONS.some((s) => s.key === v);

// n8n/settings values are TEXT — treat these two literals as a boolean toggle.
const isBoolish = (v: string | null | undefined): boolean =>
  v === 'true' || v === 'false';

/* ── THE PIPELINE KNOBS, TYPED AND EXPLAINED ──────────────────────────────────────────────────
 *
 * These four keys decide how much of INDOX runs at once. They were sitting in an alphabetical
 * list of 66 rows between `GmailToWhatsappAllowedMails` and `invoice_kws`, as bare key/value
 * pairs — `indox.statemachine.driver.batch` `500` — with nothing on screen to say that the number
 * is a MEMORY lever, that its neighbour is a concurrency ceiling, or what happens at either end.
 * An operator tuning throughput during an incident had to already know all of it.
 *
 * Everything asserted below is measured and lives in
 * apps/indox/issues/drain-pool-consolidation-plan.md; the ranges are the ones the pipeline was
 * actually proven at, not round numbers.
 */
interface KnobSpec {
  key: string;
  label: string;
  help: ReactNode;
  kind: 'switch' | 'int' | 'choice';
  min?: number;
  max?: number;
  /** `choice` only: the closed vocabulary, `[storedValue, Hebrew label]`. A setting whose legal
      values are a short closed list is a dropdown, not a free-text box — the pipeline compares
      these literally, so a typo means the setting silently keeps its old meaning. */
  options?: [string, string][];
  /** what the pipeline was proven at — shown beside the field, never auto-applied */
  proven?: string;
  unit?: string;
}

const PIPELINE_KNOBS: KnobSpec[] = [
  {
    key: 'indoxOn',
    label: 'מתג ראשי — INDOX',
    kind: 'switch',
    help: (
      <>
        המתג של כל המערכת. כשהוא כבוי לא מתקיים סנכרון ולא ניקוז מתוזמן — שני המתגים שמתחתיו
        נשארים כפי שהם, ומתחשבים רק כשהמתג הזה דלוק; ריצות שכבר התחילו מסתיימות. שורה חסרה
        נקראת כדלוק (שני המסלולים עושים COALESCE ל-true).
      </>
    ),
  },
  {
    key: 'indoxSyncOn',
    label: 'מתג ראשי — סנכרון',
    kind: 'switch',
    help: (
      <>
        כשהוא דלוק, כל סבב סנכרון (כל 15 דקות, וגם הרצה ידנית מהמסך «סנכרון») מגלה פריטים
        חדשים במקורות ומוסר אותם למכונת המצבים. כשהוא כבוי לא מתגלה ולא נמסר דבר — משלוחים
        שכבר יצאו לדרך מסתיימים. עצירת החירום מכבה גם אותו. שורה חסרה נקראת כדלוקה
        (הסנכרון עושה COALESCE ל-true).
      </>
    ),
  },
  {
    key: 'indoxDrainOn',
    label: 'מתג ראשי — ניקוז',
    kind: 'switch',
    help: (
      <>
        כשהוא דלוק, שני מנגנונים מזינים את מכונת המצבים: <b>טיק מצטבר כל 2 דקות</b> שאוסף מה
        שהשתנה, ו<b>סריקה מלאה לילית</b> שעוברת על כל הטבלה. כשהוא כבוי לא נכנסת עבודה חדשה —
        ריצות שכבר התחילו ממשיכות עד הסוף. זהו המתג שעצירת החירום מכבה, וזה המתג שמדליקים כדי
        לחדש. שורה חסרה נקראת כדלוקה (הניקוז עושה COALESCE ל-true).
      </>
    ),
  },
  {
    key: 'indox.statemachine.drain.parallel',
    label: 'מסלולים במקביל (P)',
    kind: 'int',
    min: 1,
    max: 8,
    proven: '4',
    help: (
      <>
        כמה מסלולי דרייבר רצים במקביל בכל ניקוז. זו <b>תקרת המקביליות בפועל</b>: בתוך מסלול
        הפעולות סדרתיות לחלוטין, ולכן הרחבה כאן היא הדרך היחידה להוסיף תפוקה — ופעולה זולה
        שמחכה מאחורי פעולה יקרה באותו מסלול תמתין לה.
      </>
    ),
  },
  {
    key: 'indox.statemachine.driver.batch',
    label: 'מסמכים למסלול (B)',
    kind: 'int',
    min: 50,
    max: 5000,
    proven: '500',
    unit: 'מסמכים',
    help: (
      <>
        כמה מסמכים כל מסלול מקבל. זהו <b>מנוף הזיכרון</b>, לא מנוף המהירות: n8n שומר את הפלט של
        כל צומת לאורך כל ההרצה, ולכן הערימה גדלה עם <i>רוחב</i> המסלול. נמדד: מסלול של 9,790
        מסמכים עלה כ-1,060MB, ושניים כאלה על אותו worker חצו את תקרת 2,600MB של V8 — מה שנראה
        כמו קריסה אקראית ולא כמו חריגת זיכרון.
      </>
    ),
  },
  {
    key: 'indox.statemachine.driver.max',
    label: 'מפסק כניסה לדרייבר',
    kind: 'int',
    min: 100,
    max: 20000,
    proven: '2000',
    unit: 'מסמכים',
    help: (
      <>
        מעל הכמות הזו הדרייבר מסרב להתחיל. הוא קיים כדי שקריאה ישירה (או ניקוז שקיבל רשימה
        ענקית) לא תוכל להזרים את כל הטבלה למסלול אחד; הניקוז ממילא חותך כל מסלול ל-B שלמעלה.
      </>
    ),
  },
];
const PIPELINE_KNOB_KEYS = new Set(PIPELINE_KNOBS.map((k) => k.key));

/* ── EXTRACTION knobs ─────────────────────────────────────────────────────────────────────────
   Typed the same way the pipeline knobs are, and for the same reason: a bare key/value row says
   what a setting IS but never what it DOES, and these are read during an incident by whoever is
   looking at one wrongly-typed document. They live in the חילוץ bucket rather than in a card of
   their own — same subject as the two engine switches next to them. */
const EXTRACTION_KNOBS: KnobSpec[] = [
  {
    key: 'indox.extraction.type_priority',
    label: 'מי מוביל בזיהוי סוג',
    kind: 'choice',
    options: [
      ['AI', 'בינה מלאכותית (ברירת מחדל)'],
      ['LOCAL', 'זיהוי מקומי'],
    ],
    help: (
      <>
        משפיע <b>רק כששני המנועים החזירו סוג אמיתי ושונה זה מזה</b>. תשובה של מנוע יחיד מנצחת
        לבדה תמיד, ו-<span className="mono">unknown</span> אינו תשובה. בבחירת הסוג המוביל שווה{' '}
        <b>3 נקודות</b> והשני 2, ולכן ההגדרה הזו מכריעה מחלוקת 3–2 ותו לא: <b>רמז מתצורת
        הסנכרון</b> שווה 2 נקודות נוספות ויכול להפוך את התוצאה, ומקור המוגדר <b>החלטי</b> גובר על
        שניהם. הכלל נועד לכך שראיה נוספת תיספר — ולא שהגדרה אחת תדרוס את כל השאר.
      </>
    ),
  },
];

/** every typed knob by key — the bucket cards look here so a knob is explained wherever it lands,
    instead of only inside the one card that happens to enumerate its list. */
const KNOB_BY_KEY = new Map<string, KnobSpec>(
  [...PIPELINE_KNOBS, ...EXTRACTION_KNOBS].map((k) => [k.key, k]),
);

/* per-action router caps — EDITABLE, same as any other pipeline knob.
 * They were read-only for one reason: the server's allowlist is a fixed SET, and this is an open
 * key FAMILY (one row per action name), so no set could name them. The server now matches them by
 * pattern and range-checks the value, so a real input belongs here — these are the numbers an
 * operator changes mid-incident, and sending them to psql to do it was the odd part. */
const ROUTER_CAP_PREFIX = 'indox.statemachine.action_router.';
/** kept in step with _ROUTER_CAP_MIN/_ROUTER_CAP_MAX in the BFF; the server rejects the rest */
const ROUTER_CAP_MIN = 1;
const ROUTER_CAP_MAX = 20000;
const ROUTER_CAP_NOTES: Record<string, ReactNode> = {
  extract_base_doc: (
    <>
      מוגבל ל-5 בכוונה: ה-p95 של הפעולה הזו הוא 183 שניות לשורה, מול{' '}
      <span className="mono">executionTimeout</span> של 3,600 שניות בראוטר. קבוצה רחבה יותר
      נהרגת באמצע — ואז היא סוגרת <b>אפס</b> שורות שיגור, כך שהניסיון כולו נעלם מהיומן.
    </>
  ),
};

/** the typed knob for one cap row — the label, the meaning and the range, derived from the key */
function routerCapSpec(key: string): KnobSpec {
  const tail = key.slice(ROUTER_CAP_PREFIX.length);
  const action = tail === 'max' ? null : tail.replace(/\.max$/, '');
  return {
    key,
    label: action ? `תקרה · ${action}` : 'תקרת ברירת מחדל',
    kind: 'int',
    min: ROUTER_CAP_MIN,
    max: ROUTER_CAP_MAX,
    unit: 'שורות',
    // no `proven` on an override: what is right for one action says nothing about the next.
    // The default's 2,000 IS the driver's built-in COALESCE fallback, so it is worth stating.
    proven: action ? undefined : '2000',
    help: action ? (
      ROUTER_CAP_NOTES[action] ?? (
        <>דריסה לפעולה הזו בלבד; שאר הפעולות ממשיכות בתקרת ברירת המחדל.</>
      )
    ) : (
      <>התקרה שכל פעולה מקבלת אלא אם יש לה דריסה משלה.</>
    ),
  };
}

/* ── WHICH SETTINGS BELONG WHERE ──────────────────────────────────────────────────────────────
   66 rows in one alphabetical list put `sync_registry_bak_prune_20260821` (a 9,674-character
   snapshot somebody took before a prune) at the same visual weight as the master drain switch.
   Buckets, not sorting, is the fix: internal blobs are behind a disclosure, the rest reads as
   two subjects. */
const isInternalKey = (k: string): boolean =>
  /_bak_|_backup_|^_/.test(k) || k === 'sync_registry' || /^fixture_/i.test(k);

const isExtractionKey = (k: string): boolean =>
  /^q_/.test(k) ||
  /^extraction_/.test(k) ||
  /^indox\.extraction\./.test(k) ||   // dotted spelling of the same subject (type_priority)
  /_kws$|_strong$|_labels$/.test(k) ||
  k === 'max_iterations_per_doc';

type Bucket = 'pipeline' | 'extraction' | 'system' | 'internal';
function settingBucket(k: string): Bucket {
  if (isInternalKey(k)) return 'internal';
  if (PIPELINE_KNOB_KEYS.has(k) || k.startsWith(ROUTER_CAP_PREFIX)) return 'pipeline';
  if (isExtractionKey(k)) return 'extraction';
  return 'system';
}

const BUCKET_HE: Record<'extraction' | 'system', string> = {
  extraction: 'חילוץ',
  system: 'מערכת',
};

const heNum = (n: number | null | undefined): string =>
  n == null ? '—' : n.toLocaleString('he-IL');

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
  spec,
}: {
  row: SettingRow;
  onSaved: (key: string, value: string) => void;
  /** typed knob: Hebrew label, help text and a RANGE. Absent = the plain key/value row. */
  spec?: KnobSpec;
}) {
  const boolish = spec ? spec.kind === 'switch' : isBoolish(row.value);
  const [draft, setDraft] = useState<string>(row.value ?? '');
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [ok, setOk] = useState(false);

  useEffect(() => {
    setDraft(row.value ?? '');
  }, [row.value]);

  const save = useCallback(
    async (value: string) => {
      /* RANGE FIRST, and locally: the server accepts any text for these keys, so a typo
         (`50000` for `5000`) is stored and then found by a worker running out of heap at 3am.
         The bound is stated on the field and enforced before the write, never after. */
      if (spec?.kind === 'int') {
        const n = Number(value);
        const lo = spec.min ?? 1;
        const hi = spec.max ?? Number.MAX_SAFE_INTEGER;
        if (!Number.isInteger(n) || n < lo || n > hi) {
          setErr(`ערך חייב להיות מספר שלם בין ${lo} ל-${hi}`);
          setOk(false);
          return;
        }
      }
      setSaving(true);
      setErr(null);
      setOk(false);
      try {
        const res = await api.putConfigSetting(row.key, boolish ? value === 'true' : value);
        if (res.reachable === false) {
          setErr(res.error || 'השרת אינו זמין');
          return;
        }
        const saved = res.setting?.value ?? value;
        setDraft(saved);
        onSaved(row.key, saved);
        setOk(true);
        setTimeout(() => setOk(false), 2000);
      } catch (e: unknown) {
        const body = (e as { body?: { message?: string } })?.body;
        setErr(body?.message || (e instanceof Error ? e.message : String(e)));
      } finally {
        setSaving(false);
      }
    },
    [row.key, boolish, onSaved, spec],
  );

  const dirty = draft !== (row.value ?? '');

  return (
    <div className="setrow" style={spec ? { alignItems: 'flex-start' } : undefined}>
      <span className="key" style={spec ? { fontFamily: 'inherit', maxWidth: 340 } : undefined}>
        {spec ? (
          <>
            {spec.label}
            {/* the raw key stays visible: it is what you grep for in the workflows, in the
                settings table and in every incident note ever written about this pipeline */}
            <div className="muted small mono" style={{ fontWeight: 400, marginTop: 2 }}>
              {row.key}
            </div>
            <div className="muted small" style={{ fontWeight: 400, marginTop: 6, lineHeight: 1.6 }}>
              {spec.help}
            </div>
          </>
        ) : (
          row.key
        )}
      </span>
      <div className="ctl">
        {spec?.kind === 'int' && (
          <span className="muted small">
            {spec.min}–{spec.max}
            {spec.unit ? ` ${spec.unit}` : ''}
            {spec.proven ? ` · מוכח: ${spec.proven}` : ''}
          </span>
        )}
        {spec?.kind === 'choice' ? (
          /* Saves on pick. There is no half-typed state to protect and no range to check, so the
             confirm button every text field needs would only be a second click. */
          <select
            value={draft}
            disabled={saving}
            aria-label={spec.label}
            onChange={(e) => {
              setDraft(e.target.value);
              save(e.target.value);
            }}
          >
            {(spec.options || []).map(([v, he]) => (
              <option key={v} value={v}>{he}</option>
            ))}
          </select>
        ) : boolish ? (
          <button
            className={`switch${draft === 'true' ? ' on' : ''}`}
            disabled={saving}
            aria-label={spec?.label || row.key}
            onClick={() => save(draft === 'true' ? 'false' : 'true')}
          >
            <span className="knob" />
          </button>
        ) : (
          <>
            <input
              className="mono num"
              type={spec?.kind === 'int' ? 'number' : 'text'}
              min={spec?.min}
              max={spec?.max}
              value={draft}
              disabled={saving}
              aria-label={spec?.label || row.key}
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
        {/* a rejected value must SAY what it wanted. The bare "שגיאה" pill with the sentence
            hidden in a tooltip is how a range violation reads as a server failure. */}
        {err &&
          (spec ? (
            <span className="small" style={{ color: 'var(--red)' }}>
              {err}
            </span>
          ) : (
            <span className="pill bad" title={err}>
              שגיאה
            </span>
          ))}
      </div>
    </div>
  );
}

/** one read-only setting row: the value, with what it means. Used for the per-action router caps,
 *  which the server's write allowlist does not include — rendering an input that is guaranteed to
 *  400 on save would be worse than saying so. */
function ReadOnlySetting({
  label,
  keyName,
  value,
  note,
}: {
  label: string;
  keyName: string;
  value: string;
  note?: ReactNode;
}) {
  return (
    <div className="setrow" style={{ alignItems: 'flex-start' }}>
      <span className="key" style={{ fontFamily: 'inherit', maxWidth: 340 }}>
        {label}
        <div className="muted small mono" style={{ fontWeight: 400, marginTop: 2 }}>
          {keyName}
        </div>
        {note && (
          <div className="muted small" style={{ fontWeight: 400, marginTop: 6, lineHeight: 1.6 }}>
            {note}
          </div>
        )}
      </span>
      <div className="ctl">
        <span className="mono num" style={{ fontWeight: 700 }}>
          {value}
        </span>
        <span className="pill muted" title="המפתח אינו ברשימת המפתחות שהשרת מאפשר לכתוב מכאן">
          לקריאה בלבד
        </span>
      </div>
    </div>
  );
}

/* ── WHAT THE PANIC BUTTONS ARE ABOUT TO DO ───────────────────────────────────────────────────
 *
 * Both buttons below are correct in one situation and destructive in another, and until now
 * neither could tell you which one you were in. On 2026-08-23 "שחרר הכל" would have been the right
 * repair at 15:44 (locks held, nothing running — a leak) and would have cut into live work at
 * 13:40 (four drivers mid-batch). Same button, same wording, opposite outcomes.
 *
 * `GET /pipeline/status` answers exactly that: held locks, how many are stale, live drivers, a
 * running drain, dispatches in the last five minutes. It is read ON DEMAND, when the button is
 * pressed, so the page carries no poll it does not need.
 *
 * IT IS ALSO ALLOWED NOT TO EXIST. The endpoint is new; a deployment without it answers 404, and
 * the correct behaviour then is a confirmation WITHOUT numbers plus a stated "not measured" —
 * never a confirmation showing zeros, which would say "nothing is running" on exactly the evidence
 * that nothing was looked at.
 */
async function readPipelineStatus(): Promise<PipelineStatus | null> {
  try {
    return await api.pipelineStatus();
  } catch {
    return null; // 404 / unreachable → the caller degrades to a numberless confirmation
  }
}

/** the facts both dialogs share, in the order an operator reads them */
function pipelineFacts(ps: PipelineStatus): ConfirmFact[] {
  return [
    {
      label: 'נעילות doc_action מוחזקות',
      value: heNum(ps.locks),
      kind: ps.locks > 0 ? 'warn' : 'muted',
      title: 'מפתחות n8n.process_lock.doc_action.* חיים כרגע',
    },
    {
      label: 'מהן ישנות (דליפה)',
      value: heNum(ps.locks_stale),
      kind: ps.locks_stale > 0 ? 'bad' : 'ok',
      title: 'נעילות שכבר עברו את הזמן שבו עבודה אמיתית הייתה משחררת אותן',
    },
    {
      label: 'דרייברים פעילים',
      value: heNum(ps.drivers),
      kind: ps.drivers > 0 ? 'bad' : 'ok',
    },
    {
      label: 'ניקוז רץ כרגע',
      value: ps.drain ? `כן · הרצה ${ps.drain.execution_id}` : 'לא',
      kind: ps.drain ? 'warn' : 'muted',
    },
    {
      label: 'שיגורים ב-5 הדקות האחרונות',
      value: heNum(ps.dispatch_5m),
      kind: ps.dispatch_5m > 0 ? 'warn' : 'muted',
    },
    { label: 'מתג הניקוז', value: ps.drain_on ? 'דלוק' : 'כבוי', kind: ps.drain_on ? 'ok' : 'muted' },
    { label: 'נכון לשעת מסד הנתונים', value: ps.as_of, kind: 'muted' },
  ];
}

/** in flight = anything that a release/stop would cut into, rather than clean up after */
const inFlight = (ps: PipelineStatus): boolean =>
  ps.drivers > 0 || ps.dispatch_5m > 0 || Boolean(ps.drain);

// ── operator action: release every doc_action process lock ───────────────────
// The locks are advisory (the driver's check_and_lock re-acquires; the dup-guard catches a
// double entry), so this is an escape hatch, not a data mutation — but it still confirms.
function UnlockAllButton() {
  const [busy, setBusy] = useState(false);
  const { push } = useToasts();
  const { ask, confirmUI } = useConfirm();
  const run = useCallback(async () => {
    setBusy(true);
    const ps = await readPipelineStatus();
    setBusy(false);
    const ok = await ask({
      title: 'שחרור כל נעילות הפעולה',
      danger: Boolean(ps && inFlight(ps)),
      consequence: (
        <>
          ישוחררו <b className="num">{ps ? heNum(ps.locks) : 'כל'}</b> נעילות{' '}
          <span className="mono">doc_action</span>. הנעילות מייעצות: עבודה שרצה תשלים ותנעל מחדש
          בעצמה, ושומר הכפילות עדיין תופס כניסה שנייה לאותו (מסמך · פעולה).
          {ps ? (
            inFlight(ps) ? (
              <>
                {' '}
                <b>אבל משהו עובד כרגע</b> — {heNum(ps.drivers)} דרייברים ו-
                {heNum(ps.dispatch_5m)} שיגורים בחמש הדקות האחרונות. שחרור עכשיו פותח את הדלת
                לדרייבר נוסף על אותם מסמכים בזמן שהראשון עוד באמצע. זה המצב שבו הכפתור הזה מזיק.
              </>
            ) : (
              <>
                {' '}
                <b>שום דבר לא בתעופה</b> — אין דרייברים פעילים, אין שיגורים בחמש הדקות האחרונות,
                ו-{heNum(ps.locks_stale)} מהנעילות כבר ישנות. זה בדיוק המצב שבו הכפתור הזה הוא
                התיקון הנכון: מה שנשאר הוא דליפה, לא עבודה.
              </>
            )
          ) : null}
        </>
      ),
      facts: ps ? pipelineFacts(ps) : undefined,
      unknown: ps
        ? undefined
        : 'לא ניתן לקרוא את מצב הצינור (‎/pipeline/status‎ אינו זמין בגרסה הזו), ולכן אי אפשר להראות כמה נעילות מוחזקות או האם משהו רץ. הפעולה עצמה תפעל — אך ללא המספרים שמבדילים בין תיקון לבין קטיעה של עבודה חיה.',
      confirmLabel: 'שחרר הכל',
    });
    if (!ok) return;
    setBusy(true);
    try {
      const r = await api.unlockAllLocks();
      if (!r.ok) push('bad', `השחרור נכשל: ${r.error || 'ללא פירוט'}`);
      else push('ok', `שוחררו ${r.released ?? 0} נעילות doc_action`);
    } catch (e) {
      push('bad', `השחרור נכשל: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  }, [ask, push]);
  return (
    <div className="setrow">
      {confirmUI}
      <span className="key">שחרור כל הנעילות (doc_action)</span>
      <div className="ctl">
        <button className="btn sm" disabled={busy} onClick={run} title="קורא את מצב הצינור ומבקש אישור לפני שחרור כל נעילות doc_action">
          {busy ? <span className="spinner" /> : 'שחרר הכל'}
        </button>
      </div>
    </div>
  );
}

// ── operator action: ONE-CLICK emergency stop of the whole INDOX pipeline ─────
// Server-side: indoxDrainOn=false + stop running n8n executions + flush the queue +
// release all locks. The result line reports what each stage did — partial degradation
// is shown, never hidden. Resuming is the indoxDrainOn toggle above.
function StopAllButton() {
  const [busy, setBusy] = useState(false);
  const { push } = useToasts();
  const { ask, confirmUI } = useConfirm();
  const run = useCallback(async () => {
    setBusy(true);
    const ps = await readPipelineStatus();
    setBusy(false);
    const ok = await ask({
      title: 'עצירת חירום — כל INDOX',
      danger: true,
      consequence: (
        <>
          ארבעה דברים, בסדר הזה: המתג <span className="mono">indoxDrainOn</span> ייכבה כך שלא
          תיכנס עבודה חדשה; ריצות n8n פעילות ייהרגו <b>באמצע</b> (מסמך שהיה בתוך פעולה יישאר
          בסטטוס שבו נתפס); התור יתרוקן; וכל הנעילות ישוחררו.
          {ps ? (
            <>
              {' '}
              כרגע ייהרגו <b className="num">{heNum(ps.drivers)}</b> דרייברים פעילים
              {ps.drain ? ' וניקוז שרץ' : ''}, וישוחררו <b className="num">{heNum(ps.locks)}</b>{' '}
              נעילות.
              {!inFlight(ps) && (
                <>
                  {' '}
                  שימו לב: לפי המדידה כרגע <b>שום דבר לא רץ</b> — עצירת חירום כאן בעיקר תכבה את
                  המתג. אם המטרה היא רק לעצור הזנה חדשה, המתג עצמו מספיק ואינו הורג כלום.
                </>
              )}
            </>
          ) : null}{' '}
          חידוש העבודה: הדלקת <span className="mono">indoxDrainOn</span> בכרטיס «צינור» שמעל.
        </>
      ),
      facts: ps ? pipelineFacts(ps) : undefined,
      unknown: ps
        ? undefined
        : 'לא ניתן לקרוא את מצב הצינור (‎/pipeline/status‎ אינו זמין בגרסה הזו) — כמה ריצות ייהרגו כאן אינו ידוע לפני הלחיצה.',
      confirmLabel: 'עצור הכל',
    });
    if (!ok) return;
    setBusy(true);
    try {
      const r = await api.stopAllIndox();
      const bits: string[] = [];
      if (r.gate === 'false') bits.push('מתג כבוי');
      if (typeof r.stopped === 'number') bits.push(`נעצרו ${r.stopped} ריצות`);
      if (typeof r.locks_released === 'number') bits.push(`שוחררו ${r.locks_released} נעילות`);
      const errs = [r.gate_error, r.stopped_error, r.queue_error, r.locks_error].filter(Boolean);
      /* partial degradation is a WARNING with the failed stages named — never a green "בוצע" over
         a stage that did not happen */
      if (errs.length) push('warn', `עצירת חירום חלקית: ${bits.join(' · ') || 'שום שלב לא דווח'} — נכשל: ${errs.join(' | ')}`);
      else if (!r.ok) push('bad', 'עצירת החירום לא בוצעה');
      else push('ok', `עצירת חירום בוצעה: ${bits.length ? bits.join(' · ') : 'כל השלבים דווחו'}`);
    } catch (e) {
      push('bad', `עצירת החירום נכשלה: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  }, [ask, push]);
  return (
    <div className="setrow">
      {confirmUI}
      <span className="key">עצירת חירום — כל INDOX</span>
      <div className="ctl">
        <button
          className="btn sm danger"
          disabled={busy}
          onClick={run}
          title="קורא את מצב הצינור ומבקש אישור לפני כיבוי המתג, הריגת ריצות, ריקון התור ושחרור הנעילות"
        >
          {busy ? <span className="spinner" /> : 'עצור הכל'}
        </button>
      </div>
    </div>
  );
}

// ── config table on <DataGrid> ────────────────────────────────────────────────
// Full CRUD: inline edit (PATCH), add row (POST), delete row (DELETE). The grid
// brings sort/filter/resize/paging and — via `tableId` — a per-browser memory of
// column widths and hidden columns; we supply columns, the save hooks, and the
// three affordances that are this screen's own rather than any grid's: bulk
// delete, CSV/XLSX import, and the quick filters.
// `order` gives an explicit RTL column order (first = rightmost).
function ConfigGrid({
  rows: initial,
  table,
  pk = 'id',
  denyKeys = [],
  order,
  hideKeys = [],
}: {
  rows: ConfigRow[];
  table: string;
  pk?: string;
  denyKeys?: string[];
  order?: string[];
  hideKeys?: string[];
}) {
  const [rows, setRows] = useState<ConfigRow[]>(initial);
  const { ask, confirmUI } = useConfirm();
  const { push } = useToasts();
  /** the active quick filter — this screen's own, so it does not belong inside a general-purpose
   *  grid. Results (import, bulk delete, add) go to the one notice channel. */
  const [quick, setQuick] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [adding, setAdding] = useState(false);
  const fileRef = useRef<HTMLInputElement | null>(null);
  useEffect(() => setRows(initial), [initial]);

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

  /** late-bound handle to `onDeleteRow`, defined below — keeps the column memo out of that
   *  callback's identity churn, which would otherwise rebuild every column on each row change. */
  const onDeleteRowRef = useRef<((id: unknown) => Promise<void>) | null>(null);

  const columns: GridColumn[] = useMemo(
    () => [
      ...ordered.map((k) => ({
        key: k,
        header: k,
        width: k === pk ? 64 : k.length > 12 ? 240 : 150,
        editable: k !== pk && !denyKeys.includes(k),
        validate: validatorFor(k),
        hidden: hideKeys.includes(k), // starts hidden; column picker can re-show
        // numeric-ish columns end-aligned (ERP convention)
        align: /^מזהה|^id$/.test(k) ? ('end' as const) : undefined,
      })),
      /* DELETE, as a cell rather than a row gesture. It is a real <button>, so it is
         reachable by keyboard and announced as an action; it stops propagation so it can
         never be mistaken for the click that starts an edit. */
      {
        key: '_del',
        header: '',
        width: 56,
        sortable: false,
        filter: false as const,
        text: () => '',
        render: (_v: unknown, row: GridRow) => (
          <button
            type="button"
            className="link cfg-del"
            title="מחיקת השורה הזו — אחרי אישור"
            aria-label="מחיקת שורה"
            onClick={(e) => {
              e.stopPropagation();
              void onDeleteRowRef.current?.(row[pk]);
            }}
          >
            <Ic p={IC.trash} />
          </button>
        ),
      },
    ],
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
    [table, pk],
  );

  /* ADD, as a record rather than a blank row.
     This used to POST `{}` and prepend whatever came back — which on `companies`
     did nothing visible even when it worked (a nameless row, under a name sort,
     on page 1 of 24) and nothing AT ALL when it did not: the server refused the
     insert, the handler read only `res.ok`, and the failure had nowhere to go.
     Both halves are fixed: the drawer collects the record before it exists, and
     a refused save now throws so the drawer can show the server's own words. */
  const onSubmitNewRow = useCallback(
    async (seed: Record<string, unknown>) => {
      const res = await api.addConfigRow(table, seed);
      if (!res?.ok || !res.row) throw new Error(res?.error || 'ההוספה נכשלה');
      setRows((rs) => [res.row as ConfigRow, ...rs]);
      /* the new row must be VISIBLE, not merely saved: a quick filter means
         "show me the incomplete ones", and a record just typed in full is
         exactly the row it would hide. */
      setQuick(null);
      push('ok', `נוספה שורה לטבלת ${table}`);
    },
    [table, push],
  );

  const onDeleteRow = useCallback(
    async (id: unknown) => {
      const row = rows.find((r) => String(r[pk]) === String(id));
      const label = String(row?.['שם חברה'] ?? row?.LABEL ?? row?.KEY ?? id);
      const ok = await ask({
        title: 'מחיקת שורה',
        danger: true,
        consequence: (
          <>
            השורה <b>{label}</b> תימחק מטבלת <span className="mono">{table}</span>. אין ביטול,
            ומסמכים שכבר סווגו לפיה לא ישתנו — רק סיווג עתידי יפסיק להסתמך עליה.
          </>
        ),
        facts: [
          { label: 'טבלה', value: <span className="mono">{table}</span> },
          { label: 'מפתח', value: <span className="mono">{String(id)}</span> },
        ],
        confirmLabel: 'מחק שורה',
      });
      if (!ok) return;
      try {
        const res = await api.deleteConfigRow(table, String(id));
        if (res?.ok) {
          setRows((rs) => rs.filter((r) => String(r[pk]) !== String(id)));
          push('ok', `השורה ${label} נמחקה מטבלת ${table}`);
        } else {
          /* a refused delete used to vanish: the row stayed and nothing said why */
          push('bad', `המחיקה נדחתה: ${res?.error || 'ללא פירוט'}`);
        }
      } catch (e) {
        push('bad', `המחיקה נכשלה: ${e instanceof Error ? e.message : String(e)}`);
      }
    },
    [table, pk, rows, ask, push],
  );
  onDeleteRowRef.current = onDeleteRow;

  /* bulk delete of selected rows (confirmed by the selection action that calls this). ONLY the
     rows the server actually deleted leave the grid — the old version dropped every selected
     row from view and discarded the {ok, fail} it had counted, so a refused delete looked done
     until the next reload put the row back. */
  const onDeleteRows = useCallback(
    async (ids: unknown[]) => {
      const gone = new Set<string>();
      const errors: string[] = [];
      for (const id of ids) {
        try {
          const res = await api.deleteConfigRow(table, String(id));
          if (res?.ok) gone.add(String(id));
          else errors.push(`${String(id)}: ${res?.error || 'נדחה'}`);
        } catch (e) {
          errors.push(`${String(id)}: ${e instanceof Error ? e.message : String(e)}`);
        }
      }
      setRows((rs) => rs.filter((r) => !gone.has(String(r[pk]))));
      return { ok: gone.size, fail: errors.length, errors };
    },
    [table, pk],
  );

  // bulk import (CSV/XLSX rows already mapped to column keys by `importFile`)
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
    [table],
  );

  // ops quick-filters: incomplete records jump out (chips with live counts)
  /* IMPORT (CSV / XLSX via SheetJS), lifted out of the grid and onto the screen that
     actually has it. Headers are matched against a column KEY or its header text, empty
     cells are dropped rather than written as '', and a file that matches nothing says so
     instead of silently importing zero rows. */
  const importFile = useCallback(
    async (file: File) => {
      setImporting(true);
      try {
        const XLSX = await import('xlsx');
        const wb = XLSX.read(await file.arrayBuffer());
        const ws = wb.Sheets[wb.SheetNames[0]];
        const raw = XLSX.utils.sheet_to_json<Record<string, unknown>>(ws, { defval: '' });
        const byHeader = new Map(columns.map((c) => [c.header, c.key]));
        const keys = new Set(columns.map((c) => c.key));
        const parsed = raw
          .map((r) => {
            const out: Record<string, unknown> = {};
            for (const [h, v] of Object.entries(r)) {
              const k = keys.has(h) ? h : byHeader.get(h);
              if (k && k !== '_del' && v !== '') out[k] = v;
            }
            return out;
          })
          .filter((r) => Object.keys(r).length > 0);
        if (parsed.length === 0) {
          push('bad', 'לא נמצאו שורות תואמות בקובץ — הכותרות לא תואמות לעמודות הטבלה');
          return;
        }
        const res = await onImportRows(parsed);
        if (res.fail > 0) push(res.ok ? 'warn' : 'bad', `ייבוא: ${res.ok} נוספו, ${res.fail} נכשלו`);
        else push('ok', `ייבוא: ${res.ok} שורות נוספו לטבלת ${table}`);
      } catch (e: unknown) {
        push('bad', `הייבוא נכשל: ${e instanceof Error ? e.message : String(e)}`);
      } finally {
        setImporting(false);
        if (fileRef.current) fileRef.current.value = '';
      }
    },
    [columns, onImportRows, push, table],
  );

  /* THE ONLY PER-TABLE PART OF "ADD". Everything else the drawer needs — which
     fields exist, their labels, their order, which are editable, how each one
     validates — it reads off `columns`, the same declaration the grid renders
     from. A page contributes only what a schema cannot know: which keys a HUMAN
     must fill for the record to mean anything, and what a collision looks like.
     A table with no entry here still gets a working drawer, unrequired. */
  const addSpec = useMemo(() => {
    if (table === 'companies') {
      return {
        title: 'הוספת חברה',
        hint: 'שם החברה הוא המינימום. מזהה ומייל אפשר להשלים אחר כך — הם מה שמאפשר לזהות מסמכים נכנסים אוטומטית.',
        required: ['שם חברה'],
        advanced: ['מזהה 2', 'מייל 2', 'הוראות לAI לחילוץ דוח גיול',
                   'SELECTION_CERTAINTY'],
        /* SOFT, on purpose: a repeated ח.פ is usually a mistake and occasionally
           a second branch of the same business. The product knows which rows
           exist; only the operator knows which case this is. */
        duplicateWarning: (seed: Record<string, string>) => {
          const id = (seed['מזהה 1'] ?? '').trim();
          const name = (seed['שם חברה'] ?? '').trim();
          if (id) {
            const hit = rows.find(
              (r) => String(r['מזהה 1'] ?? '').trim() === id ||
                     String(r['מזהה 2'] ?? '').trim() === id,
            );
            if (hit) return `המזהה ${id} כבר קיים אצל "${String(hit['שם חברה'] ?? '—')}". אפשר להוסיף בכל זאת.`;
          }
          if (name && rows.some((r) => String(r['שם חברה'] ?? '').trim() === name))
            return `כבר קיימת חברה בשם "${name}". אפשר להוסיף בכל זאת.`;
          return null;
        },
      };
    }
    return { title: 'הוספת שורה', hint: undefined, required: [] as string[],
             advanced: [] as string[], duplicateWarning: undefined };
  }, [table, rows]);

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

  /** the rows the grid actually shows: `data` with the active quick filter applied. Client
   *  side on purpose — these tables are hundreds of rows, and the predicate is a local
   *  question ("which of these is missing an id?"), not a query the server knows how to ask. */
  const viewRows = useMemo(() => {
    const qf = quickFilters?.find((q) => q.key === quick);
    return qf ? data.filter(qf.fn) : data;
  }, [data, quickFilters, quick]);


  return (
    <>
      {confirmUI}
      {adding && (
        <NewRowDrawer
          columns={columns}
          title={addSpec.title}
          hint={addSpec.hint}
          requiredKeys={addSpec.required}
          advancedKeys={addSpec.advanced}
          duplicateWarning={addSpec.duplicateWarning}
          onSubmit={onSubmitNewRow}
          onClose={() => setAdding(false)}
        />
      )}
      <DataGrid
        columns={columns}
        rows={viewRows}
        getRowId={(r) => String(r[pk] ?? '')}
        tableId={`indox:cfg:${table}`}
        /* THE ONE SCREEN THAT ASKED FOR UNDO. These are hand-typed config values a person
           corrects in place — a mistyped company id is caught by the eye a second later, and
           re-typing the old value from memory is exactly the recovery nobody has. */
        undoEdits
        onCellEdit={(id, key, value) => onEdit(id, key, value)}
        onAddRow={() => setAdding(true)}
        addRowLabel="הוסף שורה"
        selectable
        selectionActions={(ids, clear) => (
          <button
            type="button"
            className="btn sm ghost danger"
            title={`מחיקת ${ids.length} השורות שנבחרו — אחרי אישור; התוצאה מדווחת שורה-שורה`}
            onClick={async () => {
              const ok = await ask({
                title: 'מחיקת שורות',
                danger: true,
                consequence: (
                  <>
                    <b className="num">{ids.length}</b> שורות יימחקו מטבלת{' '}
                    <span className="mono">{table}</span>. אין ביטול.
                  </>
                ),
                facts: [{ label: 'שורות', value: String(ids.length) }],
                confirmLabel: 'מחק',
              });
              if (!ok) return;
              const res = await onDeleteRows(ids);
              /* the truth, not the intent: what was deleted, what was refused and why */
              if (res.fail === 0) push('ok', `נמחקו ${res.ok} שורות מטבלת ${table}`);
              else push(res.ok ? 'warn' : 'bad',
                `נמחקו ${res.ok} מתוך ${ids.length}; ${res.fail} לא נמחקו:\n${res.errors.slice(0, 3).join('\n')}${res.errors.length > 3 ? `\n…ועוד ${res.errors.length - 3}` : ''}`);
              clear();
            }}
          >
            <Ic p={IC.trash} /> מחק {ids.length}
          </button>
        )}
        /* Quick filters and import are this screen's, not the grid's — the toolbar slot is
           where a page adds its own verbs without every other table growing them too. */
        toolbarStart={
          <>
            {quickFilters?.map((q) => (
              <button
                key={q.key}
                type="button"
                className={`chip${quick === q.key ? ' on' : ''}`}
                aria-pressed={quick === q.key}
                onClick={() => setQuick((c) => (c === q.key ? null : q.key))}
              >
                {q.label}
              </button>
            ))}
            <button
              type="button"
              className="btn"
              disabled={importing}
              onClick={() => fileRef.current?.click()}
              title="בוחר קובץ CSV/XLSX; כותרות שתואמות לעמודות הטבלה מיובאות כשורות חדשות"
            >
              {importing ? <><span className="spinner" /> מייבא…</> : <><Ic p={IC.upload} /> ייבוא CSV/XLSX</>}
            </button>
            <input
              ref={fileRef}
              type="file"
              accept=".csv,.xlsx,.xls"
              style={{ display: 'none' }}
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void importFile(f);
              }}
            />
          </>
        }
        height={560}
      />
    </>
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
  if (key === 'SELECTION_CERTAINTY') {
    return (v) => {
      const s = String(v ?? '').trim();
      if (s === '') return null; // clearing is allowed — no fixed certainty
      const n = Number(s);
      return Number.isInteger(n) && n >= 0 && n <= 100
        ? null
        : 'ודאות קבועה חייבת להיות מספר שלם בין 0 ל-100';
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
  'SELECTION_CERTAINTY',
  'TRUSTED_SOURCE_TYPES',
  'extra',
  'instance',
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
  /* Links that must not leave the instance behind — see useInstanceLink. */
  const link = useInstanceLink();

  /* THE TAB LIVES IN THE URL (`?tab=`): a link to "the companies table" has to open the companies
     table, and a reload must not fall back to the first tab. Unknown values read as the default. */
  const [params, setParams] = useSearchParams();
  const tabParam = params.get('tab');
  const section: SectionKey = isSection(tabParam) ? tabParam : 'system';
  const setSection = useCallback(
    (key: SectionKey) => {
      setParams(
        (prev) => {
          const n = new URLSearchParams(prev);
          if (key === 'system') n.delete('tab'); else n.set('tab', key);
          return n;
        },
        { replace: true },
      );
    },
    [setParams],
  );
  const organizerUrl = mailOrganizerUrl();

  // settings
  const [settings, setSettings] = useState<SettingRow[]>([]);
  const [editableKeys, setEditableKeys] = useState<string[]>([]);
  const [setReach, setSetReach] = useState(true);
  const [setErr, setSetErr] = useState<string | undefined>();

  // companies
  const [companies, setCompanies] = useState<ConfigRow[]>([]);
  const [compReach, setCompReach] = useState(true);
  const [compErr, setCompErr] = useState<string | undefined>();

  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    Promise.allSettled([
      api.getConfigSettings(),
      api.getConfigCompanies(),
    ]).then(([set, comp]) => {
      if (!alive) return;
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

  /* ── THE 66-ROW LIST, BUCKETED ────────────────────────────────────────────────────────────
     Three cuts, in this order: the PIPELINE knobs (their own card, typed and explained), the
     INTERNAL blobs (behind a disclosure — nobody reads a 9,674-character registry snapshot by
     scrolling past it), and what remains, split into חילוץ and מערכת. Every row still appears
     somewhere; nothing is dropped, and the disclosure says how many it is holding. */
  const byKey = useMemo(() => new Map(settings.map((r) => [r.key, r])), [settings]);
  const routerCaps = useMemo(
    () =>
      settings
        .filter((r) => r.key.startsWith(ROUTER_CAP_PREFIX))
        // the DEFAULT first, then the per-action overrides: the overrides only mean something
        // once you know what they are overriding
        .sort((a, b) => {
          const da = a.key === `${ROUTER_CAP_PREFIX}max` ? 0 : 1;
          const db = b.key === `${ROUTER_CAP_PREFIX}max` ? 0 : 1;
          return da - db || a.key.localeCompare(b.key);
        }),
    [settings],
  );
  // q_v3_* rows get their own dedicated section (שאילתות חילוץ) with a proper
  // pipeline view + editor — keep them out of the raw structural dump
  const queryKeysCount = settings.filter((r) => r.key.startsWith('q_v3_')).length;
  const rest = useMemo(
    () =>
      settings
        .filter((r) => !r.key.startsWith('q_v3_') && settingBucket(r.key) !== 'pipeline')
        .sort((a, b) => a.key.localeCompare(b.key)),
    [settings],
  );
  const editableIn = useCallback(
    (bucket: Bucket) =>
      rest.filter((r) => editableKeys.includes(r.key) && settingBucket(r.key) === bucket),
    [rest, editableKeys],
  );
  const structuralIn = useCallback(
    (bucket: Bucket) =>
      rest.filter((r) => !editableKeys.includes(r.key) && settingBucket(r.key) === bucket),
    [rest, editableKeys],
  );
  /* every internal row, editable or not — the bucket is about WHO reads it, not about whether
     this page happens to be allowed to write it */
  const internalRows = useMemo(
    () => rest.filter((r) => settingBucket(r.key) === 'internal'),
    [rest],
  );
  const [showInternal, setShowInternal] = useState(false);

  const counts: Record<SectionKey, number> = {
    queries: queryKeysCount,
    system: settings.length - queryKeysCount,
    companies: companies.length,
  };

  return (
    <div>
      <div className="app-header">
        <div>
          <h1>הגדרות</h1>
          <div className="sub">
            הגדרות המערכת והצינור, שאילתות החילוץ וטבלת החברות. מקורות הסנכרון נערכים ב
            <Link className="link" to={link('/sync')}>מסך הסנכרון</Link>
            {/* N1: one rule store — the mail app's organizer. No copy of the rules lives here. */}
            {' · '}חוקי התיוג נערכים ב
            {organizerUrl ? (
              <a className="link" href={organizerUrl} title="מארגן התוויות של אפליקציית המייל — המאגר היחיד של חוקי התיוג">
                מארגן המייל <Ic p={IC.external} />
              </a>
            ) : (
              <span>מארגן התוויות שבתוך אפליקציית המייל</span>
            )}
          </div>
        </div>
      </div>

      <div className="subnav" role="tablist" aria-label="לשוניות ההגדרות">
        {SECTIONS.map((s) => (
          <button
            key={s.key}
            role="tab"
            aria-selected={section === s.key}
            className={`stab${section === s.key ? ' active' : ''}`}
            onClick={() => setSection(s.key)}
          >
            {s.label}
            {!loading && <span className="n num">{counts[s.key]}</span>}
          </button>
        ))}
      </div>

      {loading && <div className="spin">טוען הגדרות…</div>}

      {/* (a2) extraction queries — visual pipeline + JSON editor */}
      {!loading && section === 'queries' && <ExtractionQueries />}

      {/* (b) system settings — the pipeline card first, then the rest, bucketed */}
      {!loading && section === 'system' && (
        <>
          {!setReach && <Unreachable what="הגדרות המערכת" error={setErr} />}
          {setReach && (
            <>
              {/* ── צינור ─────────────────────────────────────────────────────────────────── */}
              <div className="card">
                <h3>צינור</h3>
                <div className="muted small" style={{ marginBottom: 10, lineHeight: 1.7 }}>
                  כמה מ-INDOX רץ בבת אחת. המבנה הוא <b>P מסלולים של B מסמכים</b>: הניקוז בוחר
                  מועמדים, חותך אותם למסלולים, וכל מסלול מריץ את הפעולות שלו בזו אחר זו. מכאן נובע
                  הדבר שהכי מבלבל בצינור הזה — הרחבת B לא מוסיפה מקביליות, רק זיכרון; רק P מוסיף
                  מסלולים.
                </div>
                {PIPELINE_KNOBS.map((spec) => {
                  const row = byKey.get(spec.key);
                  return row ? (
                    <EditableSetting
                      key={spec.key}
                      row={row}
                      spec={spec}
                      onSaved={onSettingSaved}
                    />
                  ) : (
                    /* a MISSING row is not a zero: the drainer COALESCEs to its built-in default,
                       so the knob is in force at a value that is nowhere in this table */
                    <ReadOnlySetting
                      key={spec.key}
                      label={spec.label}
                      keyName={spec.key}
                      value={spec.proven ? `ברירת מחדל ${spec.proven}` : 'ברירת מחדל'}
                      note={
                        <>
                          אין שורה כזו בטבלת ההגדרות, והצינור עובד לפי ברירת המחדל המובנית שלו
                          (COALESCE). {spec.help}
                        </>
                      }
                    />
                  );
                })}

                {routerCaps.length > 0 && (
                  <details className="rosetting" open style={{ marginTop: 10 }}>
                    <summary>
                      תקרות שיגור לפי פעולה (action_router)
                      <span className="len num">{routerCaps.length}</span>
                    </summary>
                    <div className="muted small" style={{ margin: '8px 0 4px', lineHeight: 1.7 }}>
                      כמה שורות הראוטר מוכן לקחת בקבוצה אחת של פעולה מסוימת.{' '}
                      <span className="mono">{ROUTER_CAP_PREFIX}max</span> היא ברירת המחדל, וכל
                      מפתח עם שם פעולה דורס אותה עבורה בלבד. שינוי כאן תופס בניקוז הבא.
                    </div>
                    {routerCaps.map((r) => (
                      <EditableSetting
                        key={r.key}
                        row={r}
                        spec={routerCapSpec(r.key)}
                        onSaved={onSettingSaved}
                      />
                    ))}
                  </details>
                )}
              </div>

              <div className="card">
                <h3>פעולות תפעול</h3>
                <div className="muted small" style={{ marginBottom: 6 }}>
                  שני הכפתורים האלה קוראים את מצב הצינור לפני שהם שואלים — כמה נעילות מוחזקות,
                  ומה רץ כרגע. זה ההבדל בין תיקון דליפה לבין קטיעת עבודה חיה.
                </div>
                <StopAllButton />
                <UnlockAllButton />
              </div>

              {/* ── the rest, as two subjects instead of one alphabet ────────────────────── */}
              {(['system', 'extraction'] as const).map((bucket) => {
                const ed = editableIn(bucket);
                const st = structuralIn(bucket);
                if (!ed.length && !st.length) return null;
                return (
                  <div className="card" key={bucket}>
                    <h3>
                      {BUCKET_HE[bucket]}{' '}
                      <span className="muted small num">
                        ({ed.length + st.length})
                      </span>
                    </h3>
                    {ed.map((r) => (
                      <EditableSetting
                        key={r.key}
                        row={r}
                        spec={KNOB_BY_KEY.get(r.key)}
                        onSaved={onSettingSaved}
                      />
                    ))}
                    {st.length > 0 && (
                      <details className="rosetting" style={{ marginTop: ed.length ? 10 : 0 }}>
                        <summary>
                          ערכים מבניים (לקריאה בלבד)
                          <span className="len num">{st.length}</span>
                        </summary>
                        <div style={{ marginTop: 6 }}>
                          {st.map((r) => {
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
                      </details>
                    )}
                  </div>
                );
              })}

              {/* ── internal blobs ──────────────────────────────────────────────────────────
                  Not secret, and not deleted: snapshots somebody took before a change, plus the
                  live sync registry (which is edited on its own screen). They are ~40% of this
                  list by row count and 100% noise to the question this page is usually open for,
                  so they are one click away instead of in the way. */}
              {internalRows.length > 0 && (
                <div className="card">
                  <h3>
                    פנימי{' '}
                    <span className="muted small num">({internalRows.length})</span>
                  </h3>
                  <div className="muted small" style={{ marginBottom: 8, lineHeight: 1.7 }}>
                    גיבויים ותצורות שנשמרו לפני שינוי (<span className="mono">*_bak_*</span>),
                    מפרטי סוגי מסמכים (<span className="mono">fixture_*</span>) ורשם הסנכרון
                    עצמו. הרשם החי נערך ב<Link className="link" to={link('/sync')}>מסך הסנכרון</Link>,
                    לא כאן.
                  </div>
                  <button className="btn sm ghost" onClick={() => setShowInternal((v) => !v)}>
                    {showInternal ? 'הסתר פנימיים' : 'הצג פנימיים'}
                  </button>
                  {showInternal && (
                    <div style={{ marginTop: 10 }}>
                      {internalRows.map((r) => {
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
                טבלת החברות — מיון, סינון ורוחב עמודות מובנים, והרוחב והעמודות
                המוסתרות נזכרים לפעם הבאה. לחיצה כפולה על תא לעריכה (עם ביטול
                בשנייה שאחריה); הוספה, ייבוא ומחיקה בסרגל. מזהה ותאריך יצירה נעולים.
              </div>
              <ConfigGrid
                rows={companies}
                table="companies"
                pk="id"
                /* `instance` is the column the SERVER scopes every read and write
                   by. Editing it in a cell would move the row into another
                   component's configuration — so it is locked and hidden, like the
                   generated id, rather than merely discouraged. */
                denyKeys={['id', 'created_at', 'instance']}
                order={COMPANIES_ORDER}
                hideKeys={['id', 'created_at', 'instance', 'extra', 'TRUSTED_SOURCE_TYPES']}
              />
            </>
          )}
        </>
      )}

      {/* the "חוקי תיוג" tab is GONE (N1): the mail app's organizer JSON is the one store of
          label rules; the header names the editor. Nothing about rules is shown or cached here. */}
    </div>
  );
}
