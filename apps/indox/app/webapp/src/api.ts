// Thin typed fetch wrapper for the /incomingDocuments API.
// Designed to mirror the OpenAPI spec served at /incomingDocuments/openapi.json.

// The SPA is served at the app's mount root and can be embedded same-origin in
// the console under `/a/incoming/`. We resolve the mount prefix from the
// injected `<base>` (present when embedded) or fall back to `/` (standalone),
// then build an ABSOLUTE `<mount>/incomingDocuments` prefix. Absolute (not
// bare-relative) keeps API + SSE URLs correct regardless of the current
// client-side route — `document.baseURI` follows `history.pushState` when no
// `<base>` is present, which would otherwise break bare-relative fetches after
// in-app navigation.
export const BASE_PATH: string = (() => {
  if (typeof document !== 'undefined') {
    const el = document.querySelector('base');
    if (el) {
      try {
        return new URL(el.href).pathname;
      } catch {
        /* fall through to default */
      }
    }
  }
  return '/';
})();

const API_PREFIX = BASE_PATH.replace(/\/+$/, '') + '/incomingDocuments';

export interface ColumnDef {
  name: string;
  type: string;
  nullable?: boolean;
  /* ── DISPLAY METADATA, served with the schema ───────────────────────────────────────────
     The BFF introspects the instance schema for WHAT EXISTS and merges
     blueprint/schema/display.json for WHAT IT MEANS, so a screen no longer keeps a private
     label map and a column added to the pipeline reaches the operator named, not shouting in
     English. `type` is the LOGICAL type from the catalog — 15 of this table's 16 booleans are
     physically TEXT, which is exactly the knowledge Postgres cannot hold. An unlabelled column
     still arrives; it simply renders as its raw name. */
  label?: string | null;
  enum?: string | null;
  enum_values?: Record<string, { label?: string; kind?: string }> | null;
  visible?: boolean | null;
  searchable?: boolean | null;
  align?: 'start' | 'end' | 'center' | null;
  deprecated?: boolean | null;
  description?: string | null;
  /** bespoke cell rendering: image | link | error. Everything else is drawn from `type` or
   *  `enum`, so the grid keys renderers off TYPES and never off a column's name. */
  ui_type?: string | null;
}

/** LAYER 2 — a named view: which columns a screen opens with, in what order, how wide, and how
 *  the rows are sorted. Shipped in views.json; the operator's deviation lives in the URL. */
export interface RepoView {
  label?: string;
  type?: string;
  description?: string;
  sort?: [string, string][];
  columns: { key: string; width?: number }[];
}

export interface RepoViewCatalog {
  default_view?: string | null;
  views: Record<string, RepoView>;
}

export interface RepoConfig {
  name: string;
  backend: 'gsheet' | 'supabase';
  primary_key: string;
  columns: ColumnDef[];
  priority_sync_columns?: string[];
  active?: boolean;
  poll_interval_seconds?: number;
  gsheet?: {
    sheet_name: string;
    spreadsheet_id?: string;
    spreadsheet_title?: string;
    gid?: number | null;
    editors?: string[];
  };
  supabase?: {
    schema?: string;
    schema_?: string;
    table?: string;
    rls?: boolean;
    service_key_env?: string;
    studio_url?: string;
  };
  /** the named views for this table, served with the schema so a screen never needs a column
   *  name to lay itself out */
  view_catalog?: RepoViewCatalog;
  created_at?: string | null;
  updated_at?: string | null;
}

/**
 * Build a human-friendly target label + (optional) external URL for the
 * repo's backend. Used by the repo list and the repo detail / browser pages
 * so users can jump straight to the underlying spreadsheet or table.
 */
export function repoSource(cfg: RepoConfig): {
  label: string;
  url: string | null;
  kind: 'gsheet' | 'supabase';
} {
  if (cfg.backend === 'gsheet' && cfg.gsheet) {
    const id = cfg.gsheet.spreadsheet_id;
    const title = cfg.gsheet.spreadsheet_title;
    const sheet = cfg.gsheet.sheet_name;
    const label = title ? `${title} → ${sheet}` : sheet;
    if (!id) return { label, url: null, kind: 'gsheet' };
    const gid = cfg.gsheet.gid;
    const url =
      `https://docs.google.com/spreadsheets/d/${id}/edit` +
      (gid != null ? `#gid=${gid}` : '');
    return { label, url, kind: 'gsheet' };
  }
  if (cfg.backend === 'supabase' && cfg.supabase) {
    const schema = cfg.supabase.schema ?? cfg.supabase.schema_ ?? 'public';
    const table = cfg.supabase.table ?? '';
    // Intentionally NO external link: the old deep-link went to Supabase Studio
    // (an external admin tool, and its URL pointed at the remote prod host → 404
    // here). This app IS the self-developed view of the same table, so the source
    // is shown as an informative label only — the grid below is where you read it.
    return { label: `${schema}.${table}`, url: null, kind: 'supabase' };
  }
  return { label: cfg.backend, url: null, kind: cfg.backend as 'gsheet' | 'supabase' };
}

export interface AuthMe {
  authenticated: boolean;
  username: string | null;
  email: string | null;
  groups: string[];
  is_admin: boolean;
}

/** STATUS enum values on public.incoming_documents — canonical list. Editable via the
 *  existing `PATCH /repos/<repo>/documents/<id>` endpoint (patchDocument below) like any
 *  other field; there is no separate status-transition endpoint. Shared by the documents
 *  grid's inline enum editor and the document detail page's status control so the two
 *  never drift. */
export const DOCUMENT_STATUS_VALUES = [
  'COMPLETED', 'DOUBLE', 'MISSING_COMPANY_ID', 'MISSING_TYPE', 'MISSING_LINK',
  'ACTION_RESTART', 'UNKNOWN_COMPANY', 'OLD', 'EXTRACTION_FAILED', 'MAX_ITERATIONS', 'PAUSE',
  // delivered by sync, not yet picked up for extraction (A2, 2026-08-06) — the thin-pipe
  // resting state between delivery and extraction. Not a failure, not attention.
  'TO_EXTRACT',
  // terminal resolved outcomes: MERGED = the losing row of an adjudicated merge (tombstone,
  // carries MERGED_INTO); GARBAGE = BaseDocEx01's <3-word blank/unreadable verdict.
  'MERGED', 'GARBAGE',
  // [2026-08-12] FOUR STATUSES THE PIPELINE PRODUCES THAT THIS LIST DID NOT KNOW.
  // Measured on the live table: NEEDS_REVIEW 3,131 · IN_PROGRESS 1,711 · API_TOOLS_FAILED 56 ·
  // ACTION_REQUIRED 7 — 4,905 documents, ~19% of the table. The consequences were not cosmetic:
  // the grid's status dropdown could not express the state ~1 in 5 documents were IN, and
  // `validate` actively REJECTED those values as "ערך לא ברשימת הסטטוסים המוכרים" — so an
  // operator could open such a row and be refused permission to save the status it already had.
  // Found by the UI harness (S64), which noticed the cell rendering raw English because the
  // label map is keyed off this list.
  'NEEDS_REVIEW', 'IN_PROGRESS', 'API_TOOLS_FAILED', 'ACTION_REQUIRED',
  // [2026-08-23] Added the same day the status was: the priority_sync action now parks a
  // failed sync here instead of leaving the document armed forever (both action routers,
  // `Build: Batch Update - priority_sync`). The live table holds 0 of these right now only
  // because the 45 that existed were restarted and drained — the moment one recurs, the
  // rejection above would refuse an operator permission to save the status the row is in.
  'PRIORITY_SYNC_FAILED',
] as const;
export type DocumentStatus = (typeof DOCUMENT_STATUS_VALUES)[number];

// status → colour and status → Hebrew now live together in `src/vocab.ts`, which is the one
// owner of this app's display vocabulary. This module stays transport-only: types, endpoints
// and the raw enum LIST above (which is data the server validates against, not presentation).

export interface UpsertResult {
  success: boolean;
  updated: unknown[];
  created: unknown[];
  skipped: unknown[];
  stats: {
    incoming: number;
    updated: number;
    created: number;
    noop: number;
    events_published: number;
  };
}

export interface QueryResult {
  rows: Record<string, unknown>[];
  count: number;
  /** exact total matching the filter/search (only when `with_count`); else null. */
  total: number | null;
  truncated: boolean;
  next_offset: number | null;
}

/** One column + direction for server-side sort (matches the BFF Query.order). */
export interface OrderClause {
  col: string;
  dir: 'asc' | 'desc';
}

/** Body accepted by POST /documents/query (grid-aware superset). */
export interface QueryBody {
  offset?: number;
  limit?: number;
  mode?: 'single' | 'by_ids' | 'filter' | 'all';
  ids?: string[];
  filter?: Record<string, unknown>;
  select?: string[];
  order?: OrderClause[];
  search?: string;
  search_columns?: string[];
  with_count?: boolean;
}

/** One entry of settings.sync_registry. */
export interface SyncRegistryEntry {
  name: string;
  source?: 'drive' | 'gmail';
  engine?: string | null;
  type_hint?: string | null;
  /** how much `type_hint` is worth to the base selector (SelectBase01's type vote) — one scale,
      lowest first. 'fallback' applies only when neither engine classified the document (what a
      lone `fallback_type` has always meant); 'hint' (the default, and what every pipe written
      before 2026-08-31 means) scores alongside the two engines and can break a disagreement
      between them; 'decisive' outranks both, for a location that only ever receives one kind of
      document. A Drive folder can be decisive; a mail label generally cannot, since one message
      carries several documents. */
  type_authority?: 'fallback' | 'hint' | 'decisive' | null;
  batch?: {
    take?: number;
    chunk?: number;
    timeout_min?: number;
    schedule_min?: number;
  };
  pairs?: unknown[];
  labels?: Record<string, string>;
  dest_folder?: string;
  /** where the engine puts what it could not process. Seeded on every drive pipe since the
      beginning and read by no UI until phase 5 — the one folder an operator opens when something
      is wrong was the one the editor would not name. */
  failed_folder?: string;
  /** which platform connection this pipe pulls from (INDOX-SYNC.md §6 — connection first) */
  connection?: string | null;
  /** paused pipes keep their config but are skipped by the scheduler and by run-all */
  enabled?: boolean;
  /** the latest of: the run button's stamp, the last discovery, the last delivery */
  last_run?: string | null;
  /** THE SYNC ITEM counts (view `sync_item_counts`), served with the config so the page needs one
   *  read. `null` + `counts_computed:false` = the view could not be read — unknown is not zero. */
  counts?: SyncItemCounts | null;
  counts_computed?: boolean;
  last_discovered_at?: string | null;
  last_delivered_at?: string | null;
  /** the most recent error text among this pipe's failed / needs_review items */
  last_error?: string | null;
  /** the lag metric: when the OLDEST item still owed (discovered / failed / claimed) was
   *  discovered — needs_review is a dead-letter state and is not counted; null = nothing owed */
  oldest_waiting_at?: string | null;
  waiting?: number;
  /** COMPAT MIRROR of `type_hint`, kept because the board's one-click reclassify and
      `POST /sync/<name>/reclassify` still read it. No longer separately editable: the editor
      writes it from `type_hint`, and `type_authority: 'fallback'` is how "only when extraction
      cannot classify" is now expressed. Legacy entries carrying only this field are migrated by
      the BFF's `_normalise_entry`. */
  fallback_type?: string | null;
  /** the connection this pipe pulls from, as the BFF names it (its id today; the sibling app's
   *  label is read by the browser — see siblings.ts). Health is NOT served here: the BFF talks
   *  to no other app, so the card probes the connection itself. */
  connection_label?: string | null;
  /** which sibling app the connection belongs to — decides which list names its locations */
  connection_kind?: 'gmail' | 'drive' | null;
  /** minutes between passes for this pipe (the scheduler's cadence, or the pipe's own
   *  `batch.schedule_min` when it is longer) */
  cadence_min?: number | null;
  /** the top reasons over this pipe's failed + needs_review items (ledger group-by) */
  reasons?: SyncReason[];
  /** the run button's last execution — the debug link for the run that just said it did nothing */
  last_run_execution?: string | null;
  last_run_url?: string | null;
  /** gmail pipes: the drive connection + folder the attachments are written to */
  drive_connection_id?: string | null;
  drive_profile_id?: string | null;
  [k: string]: unknown;
}

/** one reason over a pipe's red items: the text the delivery recorded, how many carry it, and when
 *  the latest was recorded */
export interface SyncReason { reason: string; count: number; last_at?: string | null }

/** ONE sync item of a pipe (a `sync_ledger` row), as the items drawer lists it. `listing` is the
 *  source's own metadata the discovery kept (a file name or a mail subject, the sender, the date,
 *  the size) — empty on the 2026-08-28 migration rows, which is why `reason` carries `[legacy]`. */
export interface SyncItem {
  platform_id: string;
  status: 'discovered' | 'claimed' | 'delivered' | 'failed' | 'needs_review' | string;
  reason?: string | null;
  attempts?: number | null;
  discovered_at?: string | null;
  delivered_at?: string | null;
  not_before?: string | null;
  doc_id?: string | null;
  listing?: {
    name?: string | null;
    subject?: string | null;
    from?: string | null;
    date?: string | null;
    size?: number | string | null;
    hasAttachment?: boolean | null;
    [k: string]: unknown;
  } | null;
}

/** the page-level facts the registry read carries beside the entries */
export interface SyncSummary {
  totals?: {
    to_sync?: number; in_progress?: number; synced?: number; failed?: number; needs_review?: number;
    sources?: number;
  };
  /** the last reconcile pass the scheduler ran (null when none is recorded) */
  last_pass?: {
    started_at?: string | null;
    execution_id?: string | null;
    url?: string | null;
    /** what the pass said about itself (its outline) */
    note?: string | null;
    seconds?: number | null;
    units?: number | null;
  } | null;
  /** when the scheduler will fire next (ISO), from app_schedule_state */
  next_pass_at?: string | null;
  cadence_min?: number | null;
  /** the ledger begins here — nothing before it was imported (N10) */
  history_since?: string | null;
  /** the DB clock at read time, when the BFF stamps one (the honest "as of") */
  as_of?: string | null;
}

/** The sync item's status vocabulary, counted per pipe (sync_item_counts). "synced" == delivered. */
export interface SyncItemCounts {
  discovered: number;
  claimed: number;
  delivered: number;
  failed: number;
  needs_review: number;
  total: number;
}

export interface SyncRegistryResult {
  registry: SyncRegistryEntry[];
  reachable: boolean;
  error?: string;
  /** the browser-reachable n8n address, for turning execution ids into links */
  n8n_base?: string;
  summary?: SyncSummary | null;
}

// ----- Config tables (supabase settings/companies via the BFF) --------------

/** One row of the `settings` key/value table. Values can be large JSON. */
export interface SettingRow {
  key: string;
  value: string | null;
}

export interface ConfigSettingsResult {
  settings: SettingRow[];
  /** keys the basic editor is allowed to PUT (scalars/toggles only). */
  editable_keys: string[];
  reachable: boolean;
  error?: string;
}

/** companies rows are schema-flexible (SELECT *) — render generically. */
export type ConfigRow = Record<string, unknown>;

export interface ConfigCompaniesResult {
  companies: ConfigRow[];
  reachable: boolean;
  error?: string;
}

export interface PutSettingResult {
  success?: boolean;
  setting?: SettingRow;
  reachable: boolean;
  error?: string;
}

// ----- Dashboard (aggregated incoming_documents overview) -------------------

export interface DashStatus { status: string; count: number; group: string }
export interface DashType { type: string; count: number }
/** WHERE a document came from — the `SOURCE_TYPE` column. Full distribution like
 *  `by_type`, never a top-N, so the bars sum to `total`. */
export interface DashSource { source: string; count: number }
export interface DashCompany { name: string; count: number }
/** `pct` is a PERCENTAGE (`unit: '%'`) of `applicable` — the completed documents this field
 *  applies to (an amount applies to invoices and aging reports, not to shipments), not `total`.
 *  `hint` names the column(s) the percentage actually reads, so a bar can say what it measures
 *  instead of leaving the operator to guess. */
export interface DashExtractionField {
  key: string;
  label: string;
  pct: number;
  hint?: string;
  unit?: string;
  /** the field's own denominator — how many completed documents it was measured over */
  applicable?: number;
}
export interface DashRecent {
  id?: string | null;
  name?: string | null;
  status?: string | null;
  type?: string | null;
  company?: string | null;
  date?: string | null;
}
/** One candidate driving column for the dashboard's time window.
 *  `available:false` entries are rendered DISABLED with their `reason`, not hidden — a control
 *  that silently lacks an option looks broken; one that explains itself is a finding. */
export interface DashBasis {
  id: string;
  label: string;
  available: boolean;
  /** what this column means (available entries). */
  hint?: string;
  /** why it cannot be offered (unavailable entries) — measured, e.g. mixed date formats. */
  reason?: string;
  /** 'instant' for a timestamp column, 'day' for a BUSINESS DATE (doc_date_norm), which has no
   *  time of day. A 'day' basis cannot express the sub-day windows at all — the server floors
   *  them to the start of the day and reports `win_effective`, and this flag is what lets the
   *  WINDOW control disable them up front instead of showing a day's numbers under a 15m label.
   *  Server-supplied for the same reason the option list is: it is a property of the DATA. */
  granularity?: 'instant' | 'day';
  /** narrowest window this basis can actually express (present when granularity is 'day'). */
  min_win?: string;
}

export interface DashboardStats {
  reachable: boolean;
  error?: string;
  /** the time window the SERVER actually applied ('all'|'15m'|'30m'|'1h'|'today'|'month') —
   *  echoed so the UI proves the scope of the numbers rather than trusting the one it asked for. */
  win?: string;
  /** the window the chosen basis can ACTUALLY express. Equal to `win` for every instant basis;
   *  on a day-granularity basis (doc_date_norm) the sub-day windows come back as 'today', because
   *  a business date has no time of day. Reported rather than hidden — a board carrying a day's
   *  numbers under a "15 דק׳" label is exactly the mislabelling this whole endpoint avoids. */
  win_effective?: string;
  /** UTC instant the window starts (null for 'all'). */
  since?: string | null;
  /** the bound that actually went into the WHERE clause, rendered in the basis column's own
   *  shape (24-char ISO text for TIMESTAMP; day-floored midnight UTC for doc_date_norm). Differs
   *  from `since` only where the basis needs a different shape — so "what did the server
   *  compare against" is answerable from the response instead of inferred. */
  since_applied?: string | null;
  /** the column the SERVER actually cut the window on
   *  ('created_at'|'updated_at'|'TIMESTAMP'|'doc_date_norm').
   *  Echoed for the same reason `win` is — an unrecognised basis falls back to 'created_at'
   *  rather than erroring, so the UI must read what happened, not assume. */
  basis?: string;
  /** false under win='all', which applies no time filter at all: the selection is remembered
   *  but no column is driving anything. Distinguishes "same numbers" from "wrong numbers". */
  basis_active?: boolean;
  /** every candidate date column, INCLUDING the ones that cannot be offered, each with the
   *  measured reason — so "why can't I window by DOC_DATE?" is answerable from the UI. */
  bases?: DashBasis[];
  /** rows the chosen basis cannot place on the timeline at all (null/empty/unparseable). They are
   *  EXCLUDED from every number above, never counted as matching. Surfaced so an empty window is
   *  distinguishable from a basis that simply has no data. Present only when a window applies. */
  basis_excluded?: number;
  /** rows that DO carry a usable value for the chosen basis. */
  basis_eligible?: number;
  /** rows in the table, unfiltered — the denominator for the two above. */
  basis_rows?: number;
  /** true once the maintained read model has actually computed this table at least once (see
   *  GET /dashboard/stats). Absent/false only on a genuinely fresh table the background
   *  refresher has not reached yet — everything below is still the honest last-known payload. */
  computed?: boolean;
  /** when the numbers below were computed — this is a snapshot from the maintained stats table,
   *  not a live-as-of-this-request read, so a UI that cares can show its own age. */
  computed_at?: string | null;
  total: number;
  completed: number;
  attention: number;
  failed: number;
  companies: number;
  groups: { done: number; attention: number; failed: number; other: number };
  by_status: DashStatus[];
  by_type: DashType[];
  /** optional: a persisted read-model payload written before this existed is served
   *  verbatim until the background refresher recomputes it. */
  by_source?: DashSource[];
  top_companies: DashCompany[];
  /** `scored` = the panel's denominator (documents that COMPLETED — the same set the
   *  "הושלמו" KPI counts); `skipped` = the rest of `total`, i.e. rows still in flight or
   *  stuck. Optional because a persisted read-model payload written before these existed
   *  is still served verbatim until the background refresher recomputes it. */
  extraction: {
    fields: DashExtractionField[];
    overall: number;
    scored?: number;
    skipped?: number;
    /** "ודאות ההתאמה" — the mean SELECTION_CERTAINTY over the `rows` that carry one; its own
     *  denominator, deliberately separate from the coverage score beside it */
    certainty?: { mean: number | null; rows: number } | null;
  };
  recent: DashRecent[];
}

// ----- יומן פעולות (the action-log timeline) --------------------------------
//
// One stamp appended by one n8n node to one document's ACTION_LOG, parsed out of that
// cumulative column server-side (GET /dashboard/actions). This is the pipeline's own
// progress trail: ~6,300 of these an hour on the live table.

/** The three visual classes. `progress` = work that moved the document forward; `blocked` =
 *  a lane that could not run because another held its lock; `no_action` = the state machine
 *  looked and deliberately did nothing. Classified by the SERVER (prefix rule) so a new
 *  `BLOCKED BY LOCK <lane>` colours correctly the day it first fires. */
export type ActionClass = 'progress' | 'blocked' | 'no_action';

export interface ActionEntry {
  /** epoch milliseconds — the ACTION's own instant, parsed from the stamp. */
  ts: number;
  /** the raw label the workflow wrote, e.g. 'STATUS COMPLETED', 'BLOCKED BY LOCK find_link'. */
  label: string;
  cls: ActionClass;
  /** the document ("line") id this action was performed on. */
  id: string;
  name: string;
  status: string;
  /** the n8n execution id, when the writer stamped one — 41% of stamps carry none. */
  exec?: string | null;
  /** pg bracket source only: dispatch duration in seconds (null while running) and
   *  completion state (null on the legacy ACTION_LOG source, which has no brackets). */
  dur_s?: number | null;
  done?: boolean | null;
}

export interface ActionLogResult {
  reachable: boolean;
  error?: string;
  instance?: string;
  table?: string;
  /** the window the SERVER applied, echoed like /dashboard/stats echoes its own. */
  win?: string;
  since?: string | null;
  /** the epoch the rows were actually cut on, so the panel's claim is checkable. */
  since_ms?: number | null;
  scanned_at?: string;
  /** documents read to build this timeline (the coarse pre-filter's cost). */
  scanned_rows?: number;
  /** the pre-filter hit its own row ceiling — `window_total` is then a floor. */
  rows_capped?: boolean;
  /** PARSE COVERAGE over everything scanned: timestamp-shaped tokens seen, stamps attributed to
   *  an action, and the difference. `unparsed` is stamps whose label was never written — real
   *  events that cannot be shown as actions because they do not name one (measured live: 285 of
   *  440,810, 0.065%). Reported so "the timeline is complete" is a number, not a claim. */
  ts_tokens?: number;
  stamps_parsed?: number;
  unparsed?: number;
  /** EVERY action in the window (exact, even past the retention cap). */
  window_total?: number;
  /** how many of them are pageable here. Equals window_total unless `truncated`. */
  retained?: number;
  truncated?: boolean;
  /** how many survive the active filters — the pager's denominator. */
  matched?: number;
  limit?: number;
  offset?: number;
  /** the filters the SERVER applied, echoed back as it read them (arrays: both are
   *  multi-select, driven by the grid's header filter). */
  cls?: string[];
  label?: string[];
  q?: string;
  sort?: string;
  dir?: 'asc' | 'desc';
  /** label vocabulary WITH counts, for the filter menu (counted over `retained`). */
  labels?: { label: string; cls: ActionClass; count: number }[];
  classes?: Record<ActionClass, number>;
  /** pg source only: (doc, action) pairs seen in MORE than one execution in the window —
   *  should always be 0; a positive number is a real double-run and the UI screams. */
  dup?: boolean;
  dup_pairs?: number | null;
  dup_rows?: number | null;
  rows?: ActionEntry[];
}

/** ONE document's whole action history (GET /dashboard/actions/document/<id>) — the drill-down
 *  behind a row of the timeline. Not windowed: it answers "what happened to this document, in
 *  order, from the beginning".
 *
 *  `trimmed` is not a detail. The DB trigger `incdoc_action_log_append` middle-trims any log past
 *  6,000 chars, so on a busy document the MIDDLE of its history is gone from the source itself.
 *  When it is true the UI must say the story has a hole in it rather than present what survived
 *  as the whole of it. */
export interface ActionDocResult {
  reachable: boolean;
  error?: string;
  found?: boolean;
  id?: string;
  name?: string;
  status?: string;
  rows?: {
    ts: number;
    /** the stamp exactly as the writer wrote it — epoch ms, or ISO for the stamps the one-off
     *  repair scripts left behind. Kept so a history written entirely by those scripts is
     *  identifiable as such from the drawer itself. */
    ts_raw?: string;
    label: string;
    cls: ActionClass;
    exec?: string | null;
  }[];
  total?: number;
  classes?: Record<ActionClass, number>;
  first_ts?: number | null;
  last_ts?: number | null;
  trimmed?: boolean;
  log_chars?: number;
  /** timestamp-shaped tokens in THIS document's log that name no action. */
  unparsed?: number;
}

// ----- Test suites (INDOX n8n E2E suites, driven through the BFF) -----------

/** One n8n E2E test suite + its last-run summary (GET /tests/suites).
 *  A "case" is one lane of the suite; case_count is the suite's lane count. */
export interface TestSuite {
  name: string; // suite key, e.g. "sync_kernel"
  label?: string; // Hebrew display label from the BFF
  group?: string; // subsystem group key: "sync" | "statemachine"
  description?: string;
  case_count?: number | null;
  cases_passed?: number | null;
  all_passed?: boolean | null;
  last_run?: string | null;
  failures?: string[];
}

export interface TestSuitesResult {
  suites: TestSuite[];
  groups?: Record<string, string>; // group key -> Hebrew label
  reachable: boolean;
  error?: string;
}

/** One failed assertion inside a case. */
export interface FailedAssertion {
  name?: string;
  expected?: unknown;
  actual?: unknown;
  operator?: string;
}

/** Per-case result (filled in on run completion). */
export interface TestCaseResult {
  suite?: string | null;
  name?: string | null;
  status?: string | null;
  passed: boolean;
  assertions_passed?: number;
  assertions_total?: number;
  duration_s?: number | null;
  failed_assertions?: FailedAssertion[];
}

/**
 * Live progress of a test run (GET /tests/run/{run_id}).
 *
 * Progress is GENUINELY incremental: each n8n suite lane is one case, so
 * `cases_done`, `passed`, `failed` and `per_case` grow as lanes complete.
 */
export interface TestRun {
  run_id: string;
  suite: string | null;
  status: 'running' | 'done' | 'error' | 'unknown';
  started?: string | null;
  finished?: string | null;
  cases_total?: number | null;
  cases_done?: number;
  passed?: number;
  failed?: number;
  per_case?: TestCaseResult[];
  error?: string | null;
}

/**
 * Every read this BFF serves is now backed by a maintained stats table (dashboard/sync) or a
 * config-only read — none of them should ever take seconds, let alone hang. This bounds every
 * call so a regression (or an environment this fix has not shipped to yet) degrades to a visible,
 * dismissable error after `CALL_TIMEOUT_MS` instead of an infinite "טוען…" spinner — see
 * DashboardPage / SyncStatePage / SyncBoard's loading states, which is where that used to be
 * indistinguishable from a genuine hang.
 */
const CALL_TIMEOUT_MS = 12000;

/**
 * Per-call override for the bound above, for the few endpoints whose work is genuinely large and
 * MEASURED — not as a way to paper over a slow one.
 *
 * `/dashboard/actions` under `הכל` parses every ACTION_LOG in the table: 32,530 rows, 19.9 MB,
 * 440,525 stamps, measured at ~8s of server CPU on top of the read. Twelve seconds is the right
 * guard for a call that should take 300ms and the wrong one for this — it would abort a request
 * that was going to succeed, and the user would see a timeout error on a healthy stack. The
 * server caches that scan for 60s, so only the first viewer in a minute pays it at all.
 */
/* ── THE INSTANCE THIS TAB IS LOOKING AT ────────────────────────────────────────────────────────
   Held here, at the ONE place every request already passes through, rather than threaded into a
   few dozen call sites. The BFF resolves `?instance=` once per request (its before_request hook)
   and every read helper follows it, so a request that omits the parameter reads `public` — which
   was harmless only while `public` still held compatibility views over instance one. Once those are
   dropped, an omitted instance is not a default, it is an error; and before they are dropped, an
   omitted instance is a screen quietly showing another instance's data. Both failure modes are fixed
   by the same rule: EVERY request carries the instance.

   Deliberately not persisted to localStorage: which client an operator is looking at should be a
   visible, deliberate choice each session, not something a browser remembers and silently reapplies
   to a screen whose header they are not reading. */
let CURRENT_INSTANCE: string | null = null;

/** Set the instance every subsequent request is scoped to. Null clears it (reads become un-scoped,
 *  which after the compat views are dropped will fail loudly rather than answer for instance one). */
export function setInstance(id: string | null): void {
  CURRENT_INSTANCE = id && id.trim() ? id.trim() : null;
}

/** Append `instance=` unless the caller already named one explicitly — a per-call instance (the
 *  repo/instance admin screens pass their own) must always win over the ambient one.
 *
 *  READS AND WRITES BOTH, as of 2026-08-28. It was reads-only for a few hours, and the reason is
 *  worth keeping: PostgREST serves only the schemas in PGRST_DB_SCHEMAS, so a write to a instance
 *  schema went out as `Content-Profile: indox_hacohen` and came back 406 PGRST106 — scoping writes
 *  then would not have written to the wrong instance, it would have failed every settings save in
 *  the console. The transport now routes upsert/update/insert/delete through `public.run_sql` the
 *  same way it already routed select/count, so both halves are scoped and the method check is
 *  gone. Verified end to end: an upsert against indox_levi lands in levi and not in hacohen. */

function withInstance(path: string, init?: RequestInit): string {
  if (!CURRENT_INSTANCE) return path;
  const [p, q = ''] = path.split('?', 2);
  const params = new URLSearchParams(q);
  if (params.has('instance')) return path;
  params.set('instance', CURRENT_INSTANCE);
  return `${p}?${params.toString()}`;
}

/** the document assets the BFF serves as bytes: the page raster, the two overlays, the preview */
export type DocAssetKind = 'file' | 'draw' | 'tokens' | 'thumbnail';

/**
 * A FULL, TENANT-SCOPED URL FOR ONE DOCUMENT ASSET — the only way this app names one.
 *
 * These urls are RENDERED (an `<img src>`, an `<a href>`), never fetched through `call()`, and
 * that asymmetry is exactly where the instance went missing: `call()` applies `withInstance()`,
 * a hand-built template literal does not. Every document asset route on the BFF is
 * tenant-scoped (`_bind_instance_schema` for the two overlays and the page image, `repo_for(...)`
 * for the preview), so an un-scoped url is not a url with a default — it is a url that reads the
 * wrong schema, or none at all.
 *
 * `params` is merged BEFORE the instance, so a cache-buster (`v`) or a render scale can never
 * displace it.
 */
function docAssetUrl(
  docId: string,
  kind: DocAssetKind,
  params?: Record<string, string | number>,
): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params ?? {})) {
    if (v !== '' && v != null) q.set(k, String(v));
  }
  const qs = q.toString();
  const path = `/documents/${encodeURIComponent(docId)}/${kind}${qs ? `?${qs}` : ''}`;
  return `${API_PREFIX}${withInstance(path)}`;
}

async function call<T>(path: string, init?: RequestInit, timeoutMs = CALL_TIMEOUT_MS): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let res: Response;
  try {
    res = await fetch(`${API_PREFIX}${withInstance(path, init)}`, {
      headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
      signal: controller.signal,
      ...init,
    });
  } catch (e: unknown) {
    if (e instanceof DOMException && e.name === 'AbortError') {
      throw new ApiError(0, { message: `הבקשה ל-${path} ארכה יותר מ-${timeoutMs / 1000} שניות ובוטלה` });
    }
    throw new ApiError(0, null);          // not sent, or no answer: the browser's «Failed to fetch» was the screen's sentence
  } finally {
    clearTimeout(timer);
  }
  if (!res.ok) throw await refusal(res);
  // (an answer that is ok and not JSON — the sign-in page, once the session ran out — was the parser's «Unexpected token '<'»)
  return (await res.json().catch(() => { throw new ApiError(res.status, null); })) as T;
}

/**
 * What a refusal SAID: its envelope when the body is JSON, its text when it is not — read ONCE. `json()`
 * and then `text()` threw «Failed to execute 'text' on 'Response': body stream already read» for every
 * refusal that was not JSON (the 502 page a proxy answers while this service restarts), and every
 * `catch (e) { show(e.message) }` put that sentence on the screen.
 */
async function refusal(res: Response): Promise<ApiError> {
  const text = await res.text().catch(() => '');
  let body: unknown = text;
  try { body = JSON.parse(text); } catch { /* not an envelope */ }
  return new ApiError(res.status, body);
}
/** A refusal with no sentence of its own, in the office's words (platform-base/bina-ui/bina-said.js) — «API 502»
 *  is a number, and a request that got no answer at all has not even that. */
const said = (status: number): string => (!status ? 'אין תשובה מהשירות'
  : status < 300 ? 'התשובה אינה מה שהמסך ציפה לו — רענן את הדף'
  : status === 401 ? 'הכניסה פגה — רענן את הדף' : status === 403 ? 'אין הרשאה לפעולה הזאת'
  : status === 404 ? 'השירות לא מכיר את הבקשה הזאת'
  : status > 501 && status < 505 ? 'השירות אינו זמין כרגע' : status >= 500 ? 'השירות נתקל בשגיאה'
  : 'הבקשה נדחתה');

/**
 * The BFF's canonical error envelope is `{success, error, message, details}` — `error` is a STABLE
 * MACHINE CODE (`validation_error`, `repo_not_found`, …) and `message` is the sentence written for a
 * human. See incoming_documents/core/errors.py.
 *
 * This class used to set `Error.message` to `API ${status}`, so every `catch (e) { show(e.message) }`
 * in the app — which is all of them — showed "API 400" and threw the sentence away. Pausing a pipe
 * and pressing run reported `ההרצה נכשלה — API 400` when the server had said
 * "sync 'drive-bs' is paused — enable it before running". The one thing that would tell the operator
 * what to do next was the one thing discarded.
 *
 * So unwrap it here, once, rather than at each call site: `message` prefers the envelope's sentence,
 * falls back to the code, and only then to the office's words for the status (`said`). `code` is kept
 * separate for the cases that want to branch on it — never render `code` when `message` exists.
 */
/** see `call`'s doc comment — the action-log scan's measured worst case is ~8s of server CPU
 *  plus a 19.9 MB read, and only on the widest window. */
const ACTIONS_TIMEOUT_MS = 30000;
/** A run / retry of one pipe answers only after the engine's pass on that pipe REPORTED (the BFF
 *  waits on the scan outcome, bounded by its INDOX_SCAN_TIMEOUT_S=120). Under the 12 s default the
 *  browser cancelled the request while the server carried on — measured 2026-09-02 on gmail-doc's
 *  113-item retry: toast "ארכה יותר מ-12 שניות ובוטלה", rows already reset, pass already running.
 *  A cancel the server does not honour is a lie; the budget matches the server's. */
const SYNC_PASS_TIMEOUT_MS = 150000;

export class ApiError extends Error {
  status: number;
  body: unknown;
  /** the envelope's machine code, when the body was one. Branch on this; don't display it. */
  code?: string;
  constructor(status: number, body: unknown) {
    const env = (body && typeof body === 'object' ? body : {}) as {
      message?: unknown; error?: unknown;
    };
    const human = typeof env.message === 'string' && env.message.trim() ? env.message : null;
    const code = typeof env.error === 'string' && env.error.trim() ? env.error : undefined;
    super(human || code || said(status));
    this.status = status;
    this.body = body;
    this.code = code;
  }
}

/**
 * An INDOX **instance** — a fully duplicated INDOX, not just a repo. Each one owns its own final
 * table, its own settings (key/value store + companies + tag rules + extraction queries) and its own
 * sync registry; switching instance swaps all of them together. Same account contract Drive/Mail/Chat
 * use, so the shared top-bar switcher stays generic (see sim/CONNECTED-INSTANCES.md).
 */
export interface InstanceAccount {
  id: string;
  provider: 'indox';
  label: string;
  identity: string;          // the instance's actual target table / sheet
  color: string;
  builtin?: boolean;
  status: 'ok' | 'warning' | 'error';
  reason?: string;
  backend: 'gsheet' | 'supabase';
  /** Whether the registry has this instance switched on. DECLARED, because three call sites
   *  reached for it through `as unknown as { enabled?: boolean }` — a cast that reads a field the
   *  type does not have, so it compiled and was `undefined` forever. Every "first enabled
   *  instance" lookup therefore meant "first instance", and a disabled instance would have been
   *  chosen as the default. Absent on a BFF that predates the registry, hence optional. */
  enabled?: boolean;
  docs: number;
  registry: number;
  settings_count: number;
  companies: number;
  created_at?: string;
}

export interface InstanceDetail {
  account: InstanceAccount;
  repo: RepoConfig;
  target: string;
  columns: ColumnDef[];
  registry: SyncRegistryEntry[];
  settings: { key: string; value: string }[];
  counts: { docs: number; registry: number; settings: number; companies: number };
}

/** Spec for provisioning a new instance (identity + target table + chosen sync registries). */
export interface NewInstanceSpec {
  id?: string;
  label: string;
  company?: string;
  color?: string;
  backend?: 'gsheet' | 'supabase';
  table?: string;
  columns?: ColumnDef[];
  poll_interval_seconds?: number;
  registry?: SyncRegistryEntry[];
}

/** What a run REALLY did. Two values cannot express this: a pass that never started because
 *  another one held the reconcile lock is neither a success nor a failure, and calling it either
 *  is what let the run button report work that never happened. Branch on this, not on `success`. */
export type SyncRunStatus = 'ran' | 'skipped' | 'error' | 'none';

/** A pipe the run deliberately did NOT drive, and why. `reason` is machine-readable
 *  (`paused` | `engine_not_v3` | `lock_held` | …), `he` is the sentence to show. */
export interface SyncSkipNote { sync: string; reason: string; he: string; detail?: string | null }

export const api = {
  authMe: () => call<AuthMe>('/auth/me'),

  /* The instance every request is scoped to. Set once by the shell from the switcher's resolved
     value; read by `call()` for every endpoint, so a screen is instance-scoped by default instead of
     by its author remembering to pass a parameter. See withInstance() above.

     `selectInstance`/`getInstance` are GONE, deliberately: their last callers were replaced by the
     URL-hash instance binding in this same migration, and `selectInstance` was the one-liner that
     resurrected the active_instance.json global pointer — the cross-operator clobber this whole
     migration exists to remove. A future page must not find it importable. */
  setInstance,

  // ----- instances (a full INDOX each) ---------------------------------------
  listRepoAccountsLegacy: () =>
    call<{ accounts: InstanceAccount[]; active: string }>('/accounts'),
  addInstance: (spec: NewInstanceSpec) =>
    call<{ success: boolean; account: InstanceAccount; accounts: InstanceAccount[]; active: string }>(
      '/account/add',
      { method: 'POST', body: JSON.stringify(spec) },
    ),
  /* `removeInstance` is GONE (N14): no screen offered it, and the instance registry is
     `public.indox_instances`, managed by the instances agent — not a button in this app. */
  instanceDetail: () => call<InstanceDetail>('/account/detail'),

  listRepos: () => call<{ repos: RepoConfig[] }>('/repos'),
  /* THE INSTANCE REGISTRY — public.indox_instances, which is where instances are managed.
     Distinct from `listInstances` above, which derives "instances" from the repo registry and
     reports a GLOBAL active one held in active_instance.json. That file is a multi-instance bug:
     one operator switching changes what a colleague sees and what the CLI on that host targets.
     Nothing here reads or writes it — which instance you are looking at is view state, and it
     belongs in the URL, per user. */
  listInstances: () =>
    call<{ instances: { id: string; schema_name: string; label?: string; enabled?: boolean }[] }>(
      '/instances',
    ),
  instanceTables: (id: string, counts = false) =>
    call<{ instance: string; schema: string; tables: { name: string; rows?: number | null }[] }>(
      `/instances/${encodeURIComponent(id)}/tables${counts ? '?counts=1' : ''}`,
    ),

  getRepo: (name: string, instance?: string | null, table?: string | null) => {
    const q = new URLSearchParams();
    if (instance) q.set('instance', instance);
    if (table) q.set('table', table);
    const s = q.toString();
    return call<{ repo: RepoConfig }>(`/repos/${name}${s ? `?${s}` : ''}`);
  },
  /* createRepo / deleteRepo / patchRepo / repoStats / syncRepo are GONE (N14): the repo
     screens were removed with the instance switcher, and nothing in this tree called them. */

  upsertRows: (repo: string, rows: Record<string, unknown>[]) =>
    call<UpsertResult>(`/repos/${repo}/documents`, {
      method: 'PUT',
      body: JSON.stringify(rows),
    }),

  queryDocuments: (
    repo: string,
    body: QueryBody,
    instance?: string | null,
    table?: string | null,
  ) => {
    const q = new URLSearchParams();
    if (instance) q.set('instance', instance);
    if (table) q.set('table', table);
    const s = q.toString();
    return call<QueryResult>(`/repos/${repo}/documents/query${s ? `?${s}` : ''}`, {
      method: 'POST',
      body: JSON.stringify({ mode: 'all', limit: 50, offset: 0, ...body }),
    });
  },

  /**
   * Real server-side aggregate behind the document browser's month-navigation pills.
   * Used to be computed client-side by paging `queryDocuments(mode:'all')` and bucketing
   * in the browser — that relied on the query endpoint's `truncated` flag, which undercounts
   * (see `POST /documents/query`'s doc comment server-side): it compares the returned row
   * count against the CLIENT's requested limit, not against PostgREST's own silent
   * `db-max-rows` clamp, so the client-side loop stopped after the FIRST page every time.
   * This endpoint does one full paged read of just `date_col` on the SERVER (immune to that
   * bug — see `_paged_select`) and returns real per-month counts. `sampled: true` means the
   * corpus exceeded the server's row cap — the count is real for what was scanned, but not
   * provably the whole table; callers should say so rather than presenting it as exact.
   */
  monthIndex: (repo: string, dateCol: string) =>
    call<{
      buckets: { key: string; count: number }[];
      /** rows whose date column is EMPTY — exactly the set `{op:'is_null'}` returns, so the
       *  "ללא תאריך" bucket opens precisely what it advertises. */
      no_date: number;
      /** rows whose date is PRESENT but unparseable (e.g. '23/06/26'). Counted apart from
       *  `no_date` because no single PostgREST operator can select them — the UI states the
       *  number and offers no drill-down, rather than a link that under-delivers. */
      bad_date?: number;
      total: number;
      sampled: boolean;
    }>(`/repos/${repo}/documents/month-index`, {
      method: 'POST',
      body: JSON.stringify({ date_col: dateCol }),
    }),

  getDocument: (repo: string, id: string) =>
    call<{ row: Record<string, unknown> }>(`/repos/${repo}/documents/${id}`),

  patchDocument: (repo: string, id: string, patch: Record<string, unknown>) =>
    call<{ updated: unknown[]; created: unknown[]; events_published: number }>(
      `/repos/${repo}/documents/${id}`,
      { method: 'PATCH', body: JSON.stringify(patch) },
    ),

  documentHistory: (repo: string, id: string) =>
    call<{ events: Record<string, unknown>[] }>(
      `/repos/${repo}/documents/${id}/history`,
    ),

  // ----- INDOX sync — the registry, its counts, and the two actions ------------------------
  // DB-ONLY (owner rule 2026-09-02): every number here is the sync item (`sync_item_counts`); the
  // BFF never asks mail or drive anything. Degrades gracefully (never a 500).
  /** the registry + summary + reasons in one read. 30 s: the first read after the service (re)starts
   *  fills its caches (settings, the two ledger views over 30k rows) and measured past 12 s on the
   *  laptop — a red "cancelled" callout on the first paint after a deploy is the wrong first
   *  impression; the warm read is well under a second. */
  getSyncRegistry: () => call<SyncRegistryResult>('/sync/registry', undefined, 30000),

  /** Re-drive this pipe's failed + needs_review items from OUR rows (RESET through the sync API,
   *  D6: empty-listing rows too) and START a pass so the card moves within one. `{all:true}`
   *  re-drives every non-discovered row of the pipe. Nothing at the source moves.
   *  `reset` / `no_listing` are the honest split; `started` says whether the pass ran. */
  resetSyncEntry: (name: string, all = false) =>
    call<{
      success?: boolean;
      reset?: number | null;
      /** rows reset whose listing is empty — discovery re-lists what still exists */
      no_listing?: number | null;
      skipped?: number | null;
      error?: string | null;
      started?: {
        status?: 'ran' | 'skipped' | 'error' | string;
        execution?: { execution_id?: string | null; url?: string | null } | null;
        detail?: string | null;
      } | null;
      execution?: { execution_id?: string | null; url?: string | null } | null;
      n8n_base?: string;
      registry?: SyncRegistryEntry[];
    }>(
      `/sync/registry/${encodeURIComponent(name)}/reset`,
      { method: 'POST', body: JSON.stringify({ all }) },
      SYNC_PASS_TIMEOUT_MS,
    ),

  /** the pipe's items for the drawer — `status` narrows to one ledger state; `limit` bounds the
   *  read (the endpoint pages newest-first) */
  getSyncItems: (name: string, opts?: { status?: string; limit?: number }) => {
    const q = new URLSearchParams();
    if (opts?.status) q.set('status', opts.status);
    if (opts?.limit) q.set('limit', String(opts.limit));
    const s = q.toString();
    return call<{ items: SyncItem[]; reachable?: boolean; error?: string }>(
      `/sync/registry/${encodeURIComponent(name)}/items${s ? `?${s}` : ''}`,
    );
  },

  // ----- sync management (one surface: author pipes, watch them, act on them) --
  // See sim/INDOX-SYNC.md. The registry read already carries each pipe's live counts, so the page
  // never has to correlate a config list against a separate status list.
  createSyncEntry: (entry: Partial<SyncRegistryEntry> & { connection?: string }) =>
    call<{ success: boolean; entry: SyncRegistryEntry; registry: SyncRegistryEntry[] }>(
      '/sync/registry',
      { method: 'POST', body: JSON.stringify(entry) },
    ),
  patchSyncEntry: (name: string, patch: Record<string, unknown>) =>
    call<{ success: boolean; entry: SyncRegistryEntry; registry: SyncRegistryEntry[] }>(
      `/sync/registry/${encodeURIComponent(name)}`,
      { method: 'PATCH', body: JSON.stringify(patch) },
    ),
  /** Remove the pipe's config AND its ledger rows (D8/D9). `rows_removed` is what the purge
   *  deleted; `purge_error` is the honest half when the config went but the rows did not. */
  deleteSyncEntry: (name: string) =>
    call<{
      success?: boolean;
      deleted?: boolean;
      rows_removed?: number | null;
      purge_error?: string | null;
      error?: string | null;
      registry?: SyncRegistryEntry[];
    }>(
      `/sync/registry/${encodeURIComponent(name)}`,
      { method: 'DELETE' },
    ),
  /**
   * Run one pipe. `success:false` + `error` is a REAL possibility, not a transport failure — the
   * manage webhook answers HTTP 200 for a verb it does not implement, so the only way to know a run
   * happened is to read the flag. A caller that ignores it reports a no-op as a run, which is exactly
   * what this endpoint used to do to itself.
   *
   * `status` is the field to branch on. `success:false` + `status:'skipped'` means the engine turned
   * the request away because a reconcile pass was already running — nothing is broken, nothing ran,
   * and the operator needs to be told the second part. Rendering that as the red "failed" banner is
   * how two proof attempts were misread as pipeline failures.
   */
  runSyncEntry: (name: string) =>
    call<{ success: boolean; status?: SyncRunStatus; claimed: number; code?: string | null;
           error?: string; skipped?: SyncSkipNote[]; registry: SyncRegistryEntry[] }>(
      `/sync/registry/${encodeURIComponent(name)}/run`,
      { method: 'POST' },
      SYNC_PASS_TIMEOUT_MS,
    ),
  /** Run every enabled pipe. `errors[]` is per pipe; `ran` counts the ones that actually ran,
   *  `held` the ones the engine turned away because a pass was already in flight. */
  runAllSyncs: () =>
    call<{
      success: boolean; status?: SyncRunStatus; claimed: number;
      ran?: number; held?: number; attempted?: number;
      errors?: string[];
      /** NOT failures: paused pipes, v1 pipes SCAN does not drive, and pipes the engine turned
          away because another reconcile pass still held the lock. Reported so the run can say
          what it left alone, without colouring the whole run red for it. */
      skipped?: SyncSkipNote[];
      error?: string; registry: SyncRegistryEntry[];
    }>('/sync/run', { method: 'POST' }, SYNC_PASS_TIMEOUT_MS),
  // (the item board, manual moves, reconcile, flow, runs, engine, origin and the connection /
  //  location proxies were REMOVED 2026-09-02 — the BFF no longer reaches mail or drive; the
  //  sync editor asks the sibling apps directly, see `siblings` below.)

  // ----- INDOX config tables (supabase, via the BFF) -------------------------
  // All reads degrade gracefully ({reachable:false}) when supabase/a table is
  // unreachable; putConfigSetting only accepts the server-side allowlisted keys.
  getConfigSettings: () => call<ConfigSettingsResult>('/config/settings'),

  getConfigCompanies: () => call<ConfigCompaniesResult>('/config/companies'),

  /* getConfigTagRules is GONE (N1): the mail app's organizer JSON is the one store of label
     rules; the INDOX tab, its route and the `tag_rules` table retired with it. */

  putConfigSetting: (key: string, value: unknown) =>
    call<PutSettingResult>(`/config/settings/${encodeURIComponent(key)}`, {
      method: 'PUT',
      body: JSON.stringify({ value }),
    }),

  /** console > settings — release EVERY doc_action process lock (operator escape hatch).
   *  The locks are advisory (the driver's check_and_lock re-acquires; the dup-guard catches
   *  a double entry), so the worst case of a mid-work release is one loud, blocked repeat. */
  unlockAllLocks: () =>
    call<{ ok: boolean; released?: number; reachable?: boolean; error?: string }>(
      '/config/unlock-all', { method: 'POST' }),

  /** console > settings — ONE-CLICK EMERGENCY STOP: gate off (indoxDrainOn=false) + stop
   *  running n8n executions + flush the queue + release all locks. The server reports what
   *  each stage did; partial degradation is expected and shown, never hidden. */
  stopAllIndox: () =>
    call<{
      ok: boolean;
      gate?: string;
      gate_error?: string;
      stopped?: number;
      stopped_error?: string;
      queue_flushes?: number;
      queue_error?: string;
      locks_released?: number;
      locks_error?: string;
    }>('/config/stop-all', { method: 'POST' }),

  // Inline-edit one cell of an editable config table (companies).
  patchConfigRow: (table: string, id: string, key: string, value: unknown) =>
    call<{ ok: boolean; error?: string; row?: Record<string, unknown> }>(
      `/config/${encodeURIComponent(table)}/${encodeURIComponent(id)}`,
      { method: 'PATCH', body: JSON.stringify({ key, value }) },
    ),

  // Add a row (PK assigned by the DB) → returns the new row.
  addConfigRow: (table: string, seed: Record<string, unknown> = {}) =>
    call<{ ok: boolean; error?: string; row?: Record<string, unknown> }>(
      `/config/${encodeURIComponent(table)}`,
      { method: 'POST', body: JSON.stringify(seed) },
    ),

  // Delete a row by PK.
  deleteConfigRow: (table: string, id: string) =>
    call<{ ok: boolean; error?: string }>(
      `/config/${encodeURIComponent(table)}/${encodeURIComponent(id)}`,
      { method: 'DELETE' },
    ),

  // ----- Test suites (INDOX n8n E2E suites via the BFF) ----------------------
  // listTestSuites degrades gracefully ({reachable:false}); startTestRun kicks
  // off a background run and returns {run_id}; getTestRun polls live progress.
  // Pass {suite} for one suite, {group} for a whole subsystem, or {} for all.
  // The window travels SERVER-SIDE (`?win=`) so the WHERE clause — not the browser — cuts the
  // row set; `tz` is the browser's getTimezoneOffset(), required for the CALENDAR windows
  // (today/month) because only the client knows which day the viewer is actually in (the
  // container runs UTC, the viewer is in Asia/Jerusalem). 'all' sends nothing — byte-identical
  // to the pre-window request, so the cached read-model fast path is untouched.
  // `basis` is the COLUMN the window cuts on. It is appended only when it differs from the
  // server's default (`created_at`), so the default request stays byte-identical to the
  // pre-basis one — same URL, same cached read-model fast path, nothing to re-verify.
  dashboardStats: (win?: string, basis?: string) => {
    const q: string[] = [];
    if (win && win !== 'all') {
      q.push(`win=${encodeURIComponent(win)}`, `tz=${new Date().getTimezoneOffset()}`);
    }
    if (basis && basis !== 'created_at') q.push(`basis=${encodeURIComponent(basis)}`);
    return call<DashboardStats>(
      '/dashboard/stats' + (q.length ? `?${q.join('&')}` : ''),
    );
  },

  /** יומן פעולות — the action-log timeline for the SAME window the board above it is under.
   *
   * The window travels server-side exactly like `dashboardStats` (and carries `tz` for the
   * same reason: only the browser knows which calendar day the viewer is in). What it does
   * NOT send is `basis` — the server cuts this panel on the ACTION's own epoch, because an
   * action has a real instant and does not need a document date column to stand in for one.
   *
   * `limit`/`offset` page the timeline SERVER-SIDE: a 24h window is ~151,000 actions, which
   * is not a thing to hand a browser. `cls`/`label`/`q`/`sort` are applied there too, so the
   * count the pager shows is the count the server actually matched, and the order the grid
   * displays is the order the server actually produced — a client-side sort of one page would
   * reorder 100 rows out of 151,000 and look, from inside the page, exactly like a real sort. */
  dashboardActions: (opts: {
    win?: string;
    limit?: number;
    offset?: number;
    /** multi-select: sent as a comma-separated list */
    cls?: string[];
    label?: string[];
    q?: string;
    sort?: string;
    dir?: 'asc' | 'desc';
    /** pg source: only rows whose (doc, action) pair ran in >1 execution, grouped */
    dup?: boolean;
  }) => {
    const p: string[] = [];
    if (opts.win && opts.win !== 'all') {
      p.push(`win=${encodeURIComponent(opts.win)}`, `tz=${new Date().getTimezoneOffset()}`);
    }
    if (opts.limit) p.push(`limit=${opts.limit}`);
    if (opts.offset) p.push(`offset=${opts.offset}`);
    if (opts.cls?.length) p.push(`cls=${encodeURIComponent(opts.cls.join(','))}`);
    if (opts.label?.length) p.push(`label=${encodeURIComponent(opts.label.join(','))}`);
    if (opts.q) p.push(`q=${encodeURIComponent(opts.q)}`);
    // omitted when it is the default, so the common request stays byte-identical to the
    // pre-sort one — same URL, same cached scan, nothing to re-verify
    if (opts.sort && opts.sort !== 'ts') p.push(`sort=${encodeURIComponent(opts.sort)}`);
    if (opts.dir === 'asc') p.push('dir=asc');
    if (opts.dup) p.push('dup=1');
    return call<ActionLogResult>(
      '/dashboard/actions' + (p.length ? `?${p.join('&')}` : ''),
      undefined,
      ACTIONS_TIMEOUT_MS,
    );
  },

  /** One document's full action history, oldest first. See ActionDocResult.trimmed. */
  /** יומן פעולות — delete the dispatch-log rows of ONE time window (the page's red button).
   *  win uses the same vocabulary as dashboardActions; win='all' empties the whole table. */
  purgeActions: (opts: { win: string; tz?: string }) =>
    call<{ ok: boolean; deleted?: number; win?: string; error?: string }>(
      '/dashboard/actions/purge',
      { method: 'POST', body: JSON.stringify(opts) },
    ),

  dashboardActionsDocument: (docId: string) =>
    call<ActionDocResult>(`/dashboard/actions/document/${encodeURIComponent(docId)}`),

  listTestSuites: () => call<TestSuitesResult>('/tests/suites'),

  startTestRun: (opts?: { suite?: string; group?: string }) =>
    call<{ run_id: string }>('/tests/run', {
      method: 'POST',
      body: JSON.stringify(opts?.suite ? { suite: opts.suite } : opts?.group ? { group: opts.group } : {}),
    }),

  getTestRun: (runId: string) =>
    call<TestRun>(`/tests/run/${encodeURIComponent(runId)}`),

  // ----- חילוץ מסמכים (JsonQueryExV3 extraction runner) ----------------------
  // The BFF runs the live n8n JsonQueryExV3 workflows over the grounded demo
  // dataset (one apitools /documentJsonQuery call per value), scores against
  // dataset.csv ground truth, and proxies the apitools draw overlay.
  getExtractionDataset: () => call<ExtractionDataset>('/extraction/dataset'),

  startExtractionRun: (ids?: string[]) =>
    call<{ run_id: string; docs_total: number }>('/extraction/run', {
      method: 'POST',
      body: JSON.stringify(ids && ids.length ? { ids } : {}),
    }),

  /* Overlays for a REAL `incoming_documents` row, keyed by its own primary key.
     The `/extraction/*` builders below key on the extraction-TESTING dataset's
     `type/filename` namespace, which never contains a `doc_<hash>` id — so they
     404 for every production document (verified live 2026-08-05). These hit the
     doc-id routes instead, which resolve the apitools handle from the row's
     API_TOOLS_ID column.

     ALL FOUR GO THROUGH `docAssetUrl`, WHICH CARRIES THE INSTANCE. They used to
     interpolate the path themselves, and that was the whole bug: `withInstance()`
     is applied inside `call()`, so only FETCHED urls ever named a tenant, while a
     url that ends up in an `<img src>` — which is every one of these — did not.
     The BFF then resolved schema `public`, whose compatibility view was dropped on
     2026-08-28; PostgREST answered 404, Flask's catch-all turned that into a bare
     500, and the viewer, seeing an image that would not decode, fell back to a
     preview and captioned the document "no extraction drawing was produced".
     Measured live 2026-09-02 against doc_mtk56k1zbq1ws3 (console.hacohen):

         draw   500 application/json  →  200 image/png  33 KB   with ?instance=hacohen
         file   500 application/json  →  200 image/png  30 KB
         tokens 500 application/json  →  200 image/png  43 KB

     so nothing was wrong with the overlays; the page was asking for them without
     saying whose document it wanted. Keep every new document asset on this builder
     — one place to be right, instead of one more place to forget. */
  documentFileUrl: (docId: string) => docAssetUrl(docId, 'file'),

  documentDrawUrl: (docId: string) => docAssetUrl(docId, 'draw'),

  documentTokensUrl: (docId: string) => docAssetUrl(docId, 'tokens'),

  /** the small raster of a document's first page — image bytes, 404 when apitools holds no
   *  raster for it yet ("no preview yet", never an error). Replaces the retired THUMBNAIL column:
   *  no thumbnail files are generated any more, so the grid, the cards and the detail page's
   *  fallback all read this one endpoint. */
  documentThumbnailUrl: (docId: string) => docAssetUrl(docId, 'thumbnail'),

  /** THE builder for a document asset (see the note above). Exposed so a caller that needs a
   *  cache-buster or a render scale composes it here rather than concatenating its own query
   *  string onto a finished url — which is how the instance parameter got lost the first time. */
  docAssetUrl,

  getExtractionRun: (runId: string) =>
    call<ExtractionRun>(`/extraction/run/${encodeURIComponent(runId)}`),

  cancelExtractionRun: (runId: string) =>
    call<{ ok: boolean }>(`/extraction/run/${encodeURIComponent(runId)}/cancel`, {
      method: 'POST',
    }),

  rerunExtractionDoc: (docId: string, fresh = false) =>
    call<ExtractionResult>(`/extraction/rerun/${docId}${fresh ? '?fresh=1' : ''}`, {
      method: 'POST',
    }),

  uploadExtractionDoc: async (file: File): Promise<ExtractionResult> => {
    const fd = new FormData();
    fd.append('file', file);
    const res = await fetch(`${API_PREFIX}/extraction/upload`, {
      method: 'POST',
      body: fd,
    });
    if (!res.ok) throw await refusal(res);
    return (await res.json()) as ExtractionResult;
  },

  getExtractionQueries: () =>
    call<{ queries: Record<string, unknown> }>('/extraction/queries'),

  // edit ONE q_v3_* query (settings row) — takes effect on the next run
  putExtractionQuery: (key: string, value: unknown) =>
    call<{ success: boolean; key: string }>(
      `/extraction/queries/${encodeURIComponent(key)}`,
      { method: 'PUT', body: JSON.stringify({ value }) },
    ),

  // run history — every extraction (batch / selected / single rerun / upload)
  // is persisted on disk by the BFF and survives restarts
  listExtractionRuns: () => call<{ runs: ExtractionRun[] }>('/extraction/runs'),

  getExtractionRunFull: (runId: string) =>
    call<ExtractionRunFull>(`/extraction/runs/${encodeURIComponent(runId)}`),

  deleteExtractionRun: (runId: string) =>
    call<{ ok: boolean }>(`/extraction/runs/${encodeURIComponent(runId)}`, {
      method: 'DELETE',
    }),

  getExtractionDocHistory: (docId: string) =>
    call<{ history: ExtractionHistoryEntry[] }>(`/extraction/history/${docId}`),

  /* direct URLs (rendered by <img>/<iframe>, not fetched as JSON).
     Tenant-scoped for the same reason the document assets are: `/extraction/draw` resolves the
     q_v3_* query set through `_settings_queries()`, which reads the REQUEST's schema — so an
     un-scoped url draws one tenant's document with another tenant's queries. `v` (the
     cache-buster after a re-run) is a PARAMETER here rather than something the caller appends,
     because appending `?v=` to a finished url is what silently dropped the instance elsewhere. */
  extractionFileUrl: (docId: string) => extractionAssetUrl('file', docId),

  extractionDrawUrl: (docId: string, category?: string, v?: string | number) =>
    extractionAssetUrl('draw', docId, { ...(category ? { category } : {}), ...(v != null ? { v } : {}) }),

  // זיהוי תווים — every OCR token boxed on the document (raw recognition map)
  extractionTokensUrl: (docId: string, v?: string | number) =>
    extractionAssetUrl('tokens', docId, v != null ? { v } : undefined),

  /* ── PIPELINE COMMAND ────────────────────────────────────────────────────────
     The console could observe the state machine but never drive it: draining,
     restarting in bulk and previewing a verdict all required SQL, redis and a
     basic-auth webhook the browser cannot call. These three are that missing half.

     The single-drainer rule lives on the SERVER (409 drain_running), not in
     operator discipline — a drainer already runs its own pool of
     indox.statemachine.drain.parallel lanes, so a second one multiplies the
     configured ceiling rather than adding throughput. Measured 2026-08-23: six
     drains alive at once put four drivers on a six-core host at load 12. */

  /** Everything the pipeline bar needs, in one poll. */
  pipelineStatus: () => call<PipelineStatus>('/pipeline/status'),

  /** Fire exactly ONE drainer. 409 `drain_running` carries the live execution id. */
  startDrain: (body: DrainRequest) =>
    call<DrainAccepted>('/pipeline/drain', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  /** Bulk write through the same PATCH path every other edit uses — the state machine
      stays the only writer. [2026-08-24, owner order] ANY schema column (except the pk and
      the timestamps); the SELECTION is a selector — explicit ids or the view's own filter —
      resolved once, server-side, at execution time. */
  bulkPatchDocuments: (repo: string, selection: SelectionPayload, patch: Record<string, unknown>) =>
    call<BulkPatchResult>(`/repos/${encodeURIComponent(repo)}/documents/bulk`, {
      method: 'POST',
      body: JSON.stringify({ ...selection, patch }),
    }),

  /** Direct router dispatch on a selection — the console's face of the sanctioned manual
      dispatch (ACTION + full-row lines + TRIGGER 'console_manual'). Long call: the router
      runs the action inline per batch of 5, so give it room. */
  dispatchDocuments: (repo: string, selection: SelectionPayload, action: DispatchAction) =>
    call<DispatchResult>(
      `/repos/${encodeURIComponent(repo)}/documents/dispatch`,
      { method: 'POST', body: JSON.stringify({ ...selection, action }) },
      600000,
    ),

  /** [archive 2026-08-24] Move a selection into the repo's `-archive` twin — one server
      transaction (insert+delete), conflicts skipped and reported, no size cap. Runs on
      the LIVE repo; the destination is implied. */
  archiveDocuments: (repo: string, selection: SelectionPayload) =>
    call<ArchiveMoveResult>(
      `/repos/${encodeURIComponent(repo)}/documents/archive`,
      { method: 'POST', body: JSON.stringify({ ...selection }) },
      600000,
    ),

  /** The reverse move. Runs on the `-archive` repo; rows return to the live table
      (an id that meanwhile reappeared in the live table is skipped as a conflict). */
  unarchiveDocuments: (repo: string, selection: SelectionPayload) =>
    call<ArchiveMoveResult>(
      `/repos/${encodeURIComponent(repo)}/documents/unarchive`,
      { method: 'POST', body: JSON.stringify({ ...selection }) },
      600000,
    ),

  /** Streamed CSV of an ENTIRE selection — the server walks the same selector the bulk
      endpoints take, so the file holds every matching row, never just the visible page.
      Raw fetch (not `call`): the response is a byte stream, not a JSON envelope, and a
      large export must not be cut by the default timeout. */
  exportDocumentsCsv: async (
    repo: string,
    selection: SelectionPayload,
    columns?: string[],
  ): Promise<{ blob: Blob; filename: string; truncated: boolean }> => {
    const res = await fetch(`${API_PREFIX}/repos/${encodeURIComponent(repo)}/documents/export`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(columns?.length ? { ...selection, columns } : { ...selection }),
    });
    if (!res.ok) throw await refusal(res);
    const blob = await res.blob();
    const m = /filename="?([^";]+)"?/.exec(res.headers.get('Content-Disposition') ?? '');
    /* Truncation is IN-BAND: headers are on the wire before the server knows the row
       count, so a capped export ends with a final `__TRUNCATED__` row instead. Peek at
       the stream's tail — never the whole (possibly tens-of-MB) file. */
    const tail = await blob.slice(Math.max(0, blob.size - 400)).text();
    return {
      blob,
      filename: m?.[1] ?? `documents-${new Date().toISOString().slice(0, 10)}.csv`,
      truncated: /(^|\n)__TRUNCATED__/.test(tail),
    };
  },
};

/** [one-selector 2026-08-24] The selection IS a selector: explicit ids, or the view's own
 *  filter (the same object the query endpoint takes) minus explicit exceptions. The server
 *  resolves it once at execution time — what matches THEN is what is acted on. */
export type SelectionPayload =
  | { ids: string[] }
  | { filter: Record<string, unknown>; search?: string; search_columns?: string[]; except?: string[] };

/** Verbs the server allows for direct dispatch (restart is NOT here — ACTION_RESTART via
 *  STATUS stays the one sanctioned re-run door). */
export const DISPATCH_ACTIONS = [
  'extract_base_doc', 'extract_per_type', 'link_documents', 'find_link',
  'action_priority_sync', 'select_base', 'select_type',
] as const;
export type DispatchAction = (typeof DISPATCH_ACTIONS)[number];

export interface DispatchResult {
  action: string;
  dispatched: number;
  missing: string[];
  failed: { ids: string[]; message: string }[];
  trigger: string;
}

/** Outcome of an archive/unarchive move — per-id honesty, one transaction behind it. */
export interface ArchiveMoveResult {
  moved: number;
  direction: 'archive' | 'unarchive';
  source: string;
  destination: string;
  /** ids already present at the destination — skipped, never overwritten */
  conflicts: string[];
  /** ids the selection carried that no longer exist at the source */
  missing: string[];
  selection_truncated: boolean;
}

/** A drain the server is willing to start, or the one already running. */
export interface DrainRequest {
  /** all = the whole table · changed = updated_at window · ids = a selector (see below) */
  mode: 'all' | 'changed' | 'ids';
  ids?: string[];
  /** [one-selector 2026-08-24] mode 'ids' also accepts the view's filter selector */
  filter?: Record<string, unknown>;
  search?: string;
  search_columns?: string[];
  except?: string[];
  repo?: string;
  /** decide only, dispatch nothing — this is "why is this row stuck" as a button */
  dry?: boolean;
}

export interface DrainAccepted {
  execution_id: string;
  mode: DrainRequest['mode'];
  dry: boolean;
  /** the browser-reachable execution link, when the server knows a public n8n address */
  n8n_url?: string | null;
}

/** One poll answers: is anything running, how much is left, is it healthy.
 *  `as_of` is the DB clock — this host runs hours ahead of it, so never render
 *  a freshness claim from the browser's own clock. */
export interface PipelineStatus {
  drain: { execution_id: string; mode: string; started_at: string; n8n_url: string } | null;
  drivers: number;
  /** the configured lane ceiling (indox.statemachine.drain.parallel) */
  parallel: number;
  non_terminal: number;
  action_restart: number;
  errors_1h: number;
  /** held doc_action locks; stale ones are the leak signal */
  locks: number;
  locks_stale: number;
  dispatch_5m: number;
  drain_on: boolean;
  as_of: string;
}

export interface BulkPatchResult {
  ok: number;
  failed: { id: string; status: number; message?: string }[];
}

function splitDocId(docId: string): [string, string] {
  const i = docId.indexOf('/');
  return i < 0 ? ['invoice', docId] : [docId.slice(0, i), docId.slice(i + 1)];
}

/** one extraction-DATASET asset url (`type/filename` namespace), tenant-scoped — see the
 *  builders that use it, and `docAssetUrl` for the production-document equivalent. */
function extractionAssetUrl(
  kind: 'file' | 'draw' | 'tokens',
  docId: string,
  params?: Record<string, string | number>,
): string {
  const [typ, name] = splitDocId(docId);
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params ?? {})) {
    if (v !== '' && v != null) q.set(k, String(v));
  }
  const qs = q.toString();
  const path = `/extraction/${kind}/${encodeURIComponent(typ)}/${encodeURIComponent(name)}${qs ? `?${qs}` : ''}`;
  return `${API_PREFIX}${withInstance(path)}`;
}

// ----- extraction types -------------------------------------------------------
export interface ExtractionValue {
  field: string;
  got: string | null;
  want: string | null;
  ok: boolean | null; // null = no ground truth (unscored)
  /** set when the value CALL died (e.g. timeout) — distinct from "not on the document" */
  error?: string;
}

export interface ExtractionOps {
  /** OCR provenance — stamped inside the ocr_json at OCR time, survives the cache */
  ocr_engine: string | null;
  ocr_ms: number | null;
  ocr_at: string | null;
  /** apitools build that PRODUCED the OCR (may be older than the one serving now) */
  ocr_apitools_version: string | null;
  /** apitools build that served this extraction */
  apitools_version: string | null;
  base_hook_s: number | null;
  type_hook_s: number | null;
  /** apitools-side query duration per extracted field, in ms */
  value_ms: Record<string, number>;
}

export interface ExtractionResult {
  id: string;
  type: string;
  file: string;
  hash: string | null;
  detected_type: string | null;
  type_ok: boolean | null;
  values: ExtractionValue[];
  ok: number;
  total: number;
  elapsed_s: number | null;
  at: number;
  error: string | null;
  ops?: ExtractionOps | null;
  draw_category?: string;
}

export interface ExtractionDoc {
  id: string;
  type: string;
  type_label: string;
  file: string;
  truth: Record<string, string>;
  result: ExtractionResult | null;
}

export interface ExtractionDataset {
  docs: ExtractionDoc[];
  uploads: ExtractionDoc[];
  dataset_dir: string;
  available: boolean;
  types: Record<string, string>;
}

export interface ExtractionRun {
  run_id: string;
  status: 'running' | 'done' | 'cancelled' | 'interrupted';
  scope?: 'all' | 'selected' | 'single' | 'upload';
  docs_total: number;
  done: number;
  ok: number;
  total: number;
  errors: number;
  current: string | null;
  started: number;
  finished: number | null;
}

export interface ExtractionRunFull extends ExtractionRun {
  results: Record<string, ExtractionResult>;
}

export interface ExtractionHistoryEntry {
  run_id: string;
  scope?: string;
  run_status?: string;
  started: number;
  result: ExtractionResult;
}
