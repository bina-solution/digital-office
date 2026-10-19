/**
 * INDOX's display vocabulary — ONE owner for "how this app words and colours its enums".
 *
 * Before this module the same four enums were spelled out in four places: DashboardPage had
 * STATUS/TYPE/SOURCE maps, DocumentBrowserPage rendered raw English into grid cells and into
 * the header filter's option list, and DocumentDetailPage printed the raw STATUS beside a
 * dropdown of raw values. The consequences were visible on screen — `IRRELEVANT` and
 * `API_TOOLS_FAILED` in a Hebrew UI — and structural: a status added to one map silently
 * stayed English everywhere else.
 *
 * RULES
 *  - `*_LABEL` maps are DISPLAY ONLY. Never filter, compare or persist a label; the raw enum
 *    is the value that travels to the server.
 *  - An UNMAPPED value renders as itself, never blank and never swallowed — a new status from
 *    the pipeline must stay countable and clickable the day it appears.
 *  - `statusKind` is the single colour rule, so a status is the same colour on the dashboard,
 *    in the grid and on the detail page.
 */

/** Hebrew label per document STATUS. */
const STATUS_LABEL: Record<string, string> = {
  COMPLETED: 'הושלם',
  MISSING_COMPANY_ID: 'חסר מזהה חברה',
  UNKNOWN_COMPANY: 'חברה לא מזוהה',
  MISSING_TYPE: 'חסר סוג',
  MISSING_LINK: 'חסר קישור',
  EXTRACTION_FAILED: 'חילוץ נכשל',
  PRIORITY_SYNC_FAILED: 'סנכרון לפריוריטי נכשל',
  MAX_ITERATIONS: 'חריגת ניסיונות',
  DOUBLE: 'כפילות',
  OLD: 'ישן',
  PAUSE: 'מושהה',
  NEEDS_REVIEW: 'לבדיקה',
  FROM_OFFICE: 'מהמשרד',
  IN_PROGRESS: 'בעיבוד',
  ACTION_RESTART: 'הפעלה מחדש',
  ACTION_REQUIRED: 'דורש פעולה',
  MISSING_SHIPMENT: 'חסרה תעודת משלוח',
  TRASH: 'אשפה',
  // delivered by sync, awaiting extraction — the thin-pipe resting state, not a failure
  TO_EXTRACT: 'ממתין לעיבוד',
  // terminal RESOLVED outcomes (not failures)
  MERGED: 'מוזג למסמך אחר',
  GARBAGE: 'מסמך לא קריא',
  // the apitools leg gave up on this document — it was reaching the UI as a bare English enum
  API_TOOLS_FAILED: 'כשל בעיבוד',
  '(ריק)': 'ללא סטטוס',
};

/** Hebrew label per document TYPE. */
const TYPE_LABEL: Record<string, string> = {
  INVOICE: 'חשבונית',
  BALANCE_SHEET: 'דוח גיול',
  SHIPMENT: 'תעודת משלוח',
  ORDER: 'הזמנה',
  RECEIPT: 'קבלה',
  UNKNOWN: 'לא מזוהה',
  // classified as "not a business document we act on" — was rendering as raw English
  IRRELEVANT: 'לא רלוונטי',
  // GARBAGE is BOTH a TYPE and a STATUS: BaseDocEx01 stamps both on the same row.
  GARBAGE: 'לא קריא',
  '(ללא סוג)': 'ללא סוג',
};

/** Hebrew label per SOURCE_TYPE — where the document entered INDOX from.
 *  BALANCE_SHEET / INVOICE genuinely appear here: they are document types that leaked into
 *  the source axis via those ingestion lanes, so they are labelled as the LANE they are,
 *  never folded into another bucket. */
const SOURCE_LABEL: Record<string, string> = {
  GOOGLE_DRIVE_FOLDER: 'תיקיית דרייב',
  GOOGLE_DRIVE_FILE: 'קובץ בדרייב',
  MAIL_ATTACHMENT: 'קובץ מצורף במייל',
  GMAIL: 'מייל',
  WHATSAPP: 'וואטסאפ',
  BALANCE_SHEET: 'מסלול דוח גיול',
  INVOICE: 'מסלול חשבוניות',
  '': 'ללא מקור',
};

const label = (map: Record<string, string>, v: unknown): string => {
  const s = v == null ? '' : String(v);
  return map[s] ?? map[s.toUpperCase()] ?? s;
};

export const statusLabel = (v: unknown): string => label(STATUS_LABEL, v);
export const typeLabel = (v: unknown): string => label(TYPE_LABEL, v);
export const sourceLabel = (v: unknown): string => label(SOURCE_LABEL, v);

/** Labels for a grid column's enum options, so a cell and its header filter read the same words
 *  the dashboard does.
 *
 *  Returns EVERY status this module knows, not just the ones passed in. The caller supplies the
 *  *editable* list, which is necessarily narrower than what the pipeline can produce — and a
 *  value missing from it still has to RENDER, in Hebrew. Keying the labels off the editable list
 *  alone is exactly how `NEEDS_REVIEW` reached the screen as raw English on 3,131 documents. */
export const statusLabels = (values: readonly string[]): Record<string, string> => ({
  ...STATUS_LABEL,
  ...Object.fromEntries(values.map((v) => [v, statusLabel(v)])),
});

/** THE colour rule for a status, shared by the dashboard bars, the grid pill and the detail
 *  page. Anything unlisted is `warn` on purpose: an unrecognised status is a thing to look at,
 *  and defaulting it to `ok` would paint an unknown state as success. */
export function statusKind(v: unknown): 'ok' | 'warn' | 'bad' | 'muted' {
  const s = String(v ?? '').toUpperCase();
  if (s === 'COMPLETED') return 'ok';
  if (s === 'EXTRACTION_FAILED' || s === 'MAX_ITERATIONS' || s === 'API_TOOLS_FAILED'
      || s === 'PRIORITY_SYNC_FAILED') return 'bad';
  if (s === 'DOUBLE' || s === 'OLD' || s === 'TO_EXTRACT' || s === 'IN_PROGRESS'
      || s === 'MERGED' || s === 'GARBAGE' || s === 'TRASH') return 'muted';
  return 'warn';
}

/** WHAT a status means for the pipeline, as four words rather than four colours.
 *
 *  The palette above has exactly four tones and they are shared with the dashboard, so
 *  `IN_PROGRESS` (in flight) and `MERGED` (a tombstone) necessarily wear the same grey.
 *  That is fine on a bar chart and not fine on a row an operator is deciding about, so the
 *  grid's pill carries this as its tooltip: same colour rule everywhere, plus the sentence
 *  that separates two states the colour cannot. */
export type StatusGroup = 'terminal' | 'parked' | 'inflight' | 'failed' | 'attention';

const STATUS_GROUP: Record<string, StatusGroup> = {
  COMPLETED: 'terminal',
  MERGED: 'terminal',
  GARBAGE: 'terminal',
  TRASH: 'terminal',
  IRRELEVANT: 'terminal',
  OLD: 'parked',
  DOUBLE: 'parked',
  PAUSE: 'parked',
  FROM_OFFICE: 'parked',
  TO_EXTRACT: 'inflight',
  IN_PROGRESS: 'inflight',
  ACTION_RESTART: 'inflight',
  EXTRACTION_FAILED: 'failed',
  MAX_ITERATIONS: 'failed',
  API_TOOLS_FAILED: 'failed',
  PRIORITY_SYNC_FAILED: 'failed',
};

export const statusGroup = (v: unknown): StatusGroup =>
  STATUS_GROUP[String(v ?? '').toUpperCase()] ?? 'attention';

const STATUS_GROUP_LABEL: Record<StatusGroup, string> = {
  terminal: 'סופי — הצינור סיים עם המסמך',
  parked: 'מוקפא — לא ירוץ עד שמישהו יחליט',
  inflight: 'בתנועה — הצינור מטפל בו עכשיו',
  failed: 'כשל — נעצר על שגיאה',
  attention: 'דורש טיפול — חסר משהו כדי להמשיך',
};

/** the pill's tooltip: the Hebrew status, what it means, and the raw enum it really is */
export const statusTitle = (v: unknown): string =>
  `${statusLabel(v)} · ${STATUS_GROUP_LABEL[statusGroup(v)]} · ${String(v ?? '') || '(ריק)'}`;

/** Hebrew label per COLUMN of the documents table.
 *
 *  The grid used to print raw column names as headers, so a narrow column showed
 *  "…ORT_DOC_ID" / "…PANY_NAME" — a clipped English identifier, in a Hebrew UI, with no
 *  tooltip to recover the rest of it. Same rule as the enum maps above: DISPLAY ONLY, an
 *  unmapped column renders as its own raw name (never blank), and the raw name always
 *  travels to the server and always stays reachable through the header tooltip. */
/* ── THE COLUMN LABEL MAP LIVED HERE AND IS GONE ───────────────────────────────────────────
   It held ~76 hand-written Hebrew labels plus seven prefix/suffix family rules, and it was the
   reason a column added to the pipeline reached the operator as an English shout: the schema
   grew, this file did not, and nothing connected the two.

   Those labels now live in `apps/indox/blueprint/schema/display.json` and are merged into the
   columns the BFF serves, so the grid, the detail page, the filter chips and the bulk-edit verbs
   all read one word for one column — and adding a label is a JSON edit that is live on the next
   page load, with no frontend change and no deploy.

   What stayed in this file is what is genuinely a FRONTEND vocabulary: the status/type/source
   words and their colour rule, which the cells still key off. Those follow the same path next.
   Do not reintroduce a column-name map here; if a header reads wrong, fix display.json. */


/** The dashboard's four health groups → the bar/segment class. Kept beside `statusKind` so the
 *  two colour rules on this screen are read together rather than drifting apart.
 *
 *  The classes are the sync page's state names, borrowed for their colour in the office's legend:
 *  what needs attention WAITS (lime, `to_sync`), and «other» only informs (the sky, `in_progress`).
 *  The dashboard names a colour only through this map. */
export const GROUP_CLASS: Record<string, string> = {
  done: 'synced',
  attention: 'to_sync',
  failed: 'failed',
  other: 'in_progress',
};

/* ── WHAT THE ROUTER DID, IN HEBREW ───────────────────────────────────────────────────────────
   The dispatch ledger is the one place an operator sees the state machine act, and it was showing
   the machine's own vocabulary as the reading line: `source_feedback_0`, `mark_completed`,
   `select_type`. Those are English identifiers on a Hebrew page — the platform's second law — and
   they read as a log file rather than as a record of what happened to this document.

   Every key here is a real `ACTION` value counted in the live ledger (34 distinct names,
   2026-09-02), and the keys are spelled EXACTLY as production spells them, typo included
   (`update_status_unknwon_company`): the name is the join to the engine, not prose, and
   "correcting" it would silently stop matching.

   An action nobody has translated yet is NOT guessed at — `actionLabel` returns null and the
   caller renders the raw name as a mono LTR token, visibly machine vocabulary, with the same
   name in the tooltip. A wrong Hebrew label is worse than an honest identifier. */
const ACTION_LABEL: Record<string, string> = {
  // extraction
  extract_base_doc: 'חילוץ נתוני בסיס',
  extract_per_type: 'חילוץ לפי סוג המסמך',
  select_base: 'בחירת ערכי הבסיס',
  select_type: 'בחירת סוג המסמך',
  select_invoice_values: 'בחירת ערכי החשבונית',
  get_api_tools_id: 'העלאה למנוע העיבוד',
  get_short_doc_id: 'חישוב מזהה מקוצר',
  get_company_name: 'איתור שם החברה',
  update_name: 'עדכון שם המסמך',
  update_company_doc_id: 'עדכון מזהה המסמך אצל החברה',
  // linking and matching
  find_link: 'איתור הקישור למקור',
  link_documents: 'קישור מסמכים',
  link_documents_r1: 'קישור מסמכים, סבב נוסף',
  action_merge_doubles: 'מיזוג כפילויות',
  check_from_office: 'בדיקה: האם המסמך מהמשרד',
  // sync out
  action_priority_sync: 'סנכרון לפריוריטי',
  restart_priority_sync: 'הרצה חוזרת: סנכרון לפריוריטי',
  apply_gmail_labels: 'סימון תוויות בגימייל',
  source_feedback_0: 'סימון חזרה במקור',
  file_to_failed_folder: 'העברה לתיקיית הכשלים',
  // restarts
  restart_base: 'הרצה חוזרת: מעבר הבסיס',
  restart_gdoc: 'הרצה חוזרת: מסמך גוגל',
  restart_balance_sheet: 'הרצה חוזרת: דוח גיול',
  // status writes
  mark_completed: 'סימון כהושלם',
  mark_max_iterations: 'סימון: מוצו המעברים',
  update_status_old_doc: 'עדכון סטטוס: מסמך ישן',
  update_status_double: 'עדכון סטטוס: כפילות',
  update_status_garbage: 'עדכון סטטוס: מסמך לא קריא',
  update_status_missing_link: 'עדכון סטטוס: חסר קישור',
  update_status_missing_company: 'עדכון סטטוס: חסרה חברה',
  update_status_missing_type: 'עדכון סטטוס: חסר סוג',
  update_status_unknwon_company: 'עדכון סטטוס: חברה לא מזוהה',
  update_status_api_tools_failed: 'עדכון סטטוס: כשל בעיבוד הקובץ',
  update_status_extraction_failed: 'עדכון סטטוס: כשל בחילוץ',
};

/** The Hebrew name of a router action, or `null` when it has none — never a guess. */
export function actionLabel(v: unknown): string | null {
  const k = String(v ?? '').trim();
  return ACTION_LABEL[k] ?? null;
}
