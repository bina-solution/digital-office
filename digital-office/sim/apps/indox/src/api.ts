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
  /* how the column READS — said by the service from the app's display catalog (words.tsx): its heading, the
     value domain it is of, and that domain's values with the word and the colour of each */
  label?: string;
  enum?: string;
  enum_values?: Record<string, { label?: string; kind?: string }> | null;
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

export interface RepoStats {
  name: string;
  backend: string;
  row_count: number | null;
  columns: ColumnDef[];
  row_count_stale?: boolean;
}

export interface AuthMe {
  authenticated: boolean;
  username: string | null;
  email: string | null;
  groups: string[];
  is_admin: boolean;
}

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

/** Per-sync 4-state counts (values may arrive as strings from n8n). */
export interface SyncCounts {
  to_sync?: number | string;
  in_progress?: number | string;
  synced?: number | string;
  failed?: number | string;
  partial?: boolean;   // counts unavailable for this sync (e.g. gmail — needs the pipeline path)
}

/** Response of GET /sync/status (computed directly from supabase; source:'supabase'). */
export interface SyncStatus {
  ok?: boolean;
  action?: string;
  at_rest?: boolean;
  waiting?: number | string;
  in_progress?: number | string;
  per_sync?: Record<string, SyncCounts>;
  source?: string;         // 'supabase' when computed directly (n8n-independent)
  gmail_partial?: boolean; // some gmail syncs have unavailable live counts
  // graceful-degradation envelope when supabase is unreachable:
  reachable?: boolean;
  error?: string;
}

/** One entry of settings.sync_registry. */
export interface SyncRegistryEntry {
  name: string;
  source?: 'drive' | 'gmail';
  engine?: string | null;
  processor_wf?: string | null;
  type_hint?: string | null;
  batch?: {
    take?: number;
    chunk?: number;
    timeout_min?: number;
    schedule_min?: number;
  };
  pairs?: unknown[];
  labels?: Record<string, string>;
  claim_label?: string;
  dest_folder?: string;
  /** which platform connection this pipe pulls from (INDOX-SYNC.md §6 — connection first) */
  connection?: string | null;
  /** paused pipes keep their config but are skipped by the scheduler and by run-all */
  enabled?: boolean;
  last_run?: string | null;
  /** live state, served alongside the config so the page needs one read, not two */
  counts?: { to_sync: number; in_progress: number; synced: number; failed: number };
  /** claimed longer ago than batch.timeout_min — nothing is coming back for these */
  stuck?: number;
  /** failures grouped by cause, so one action can clear a whole class */
  failures?: { code: string; he: string; group: string; n: number }[];
  /** the type to assume when extraction cannot classify — the pipe's location IS the answer */
  fallback_type?: string | null;
  /** health of the connection this pipe pulls from (spine-owned, same as Drive/Mail show) */
  connection_label?: string | null;
  connection_identity?: string | null;
  connection_status?: 'ok' | 'warning' | 'error';
  connection_reason?: string;
  [k: string]: unknown;
}

export interface SyncRegistryResult {
  registry: SyncRegistryEntry[];
  reachable: boolean;
  error?: string;
}

/** The four states an item moves through. Counts are derived from items, never stored. */
export type SyncItemState = 'to_sync' | 'in_progress' | 'synced' | 'failed';

/** One real thing waiting to be, or already, ingested — the unit a user can act on. */
export interface SyncItem {
  id: string;
  sync: string;
  title: string;
  company?: string;
  kind: string;
  /** false ⇒ extraction could not classify it; the pipe's fallback_type is what would resolve it */
  detected?: boolean;
  source: 'gmail' | 'drive';
  connection?: string | null;
  size_kb: number;
  state: SyncItemState;
  updated_at: string;
  /** when it was CLAIMed into in_progress — a claim older than the pipe timeout means STUCK */
  claimed_at?: string | null;
  stuck?: boolean;
  error?: string | null;
  /** machine code so failures can be grouped and bulk-actioned by CAUSE, not one at a time */
  error_code?: string | null;
  /** fixable | type | terminal — what kind of action could plausibly help */
  error_group?: string | null;
  fallback_type?: string | null;
}

/** A connection a pipe can pull from — the platform's own Drive/Mail accounts. */
export interface SyncConnection {
  id: string;
  source: 'gmail' | 'drive';
  label: string;
  identity?: string;
  color?: string;
}

/** A label (gmail) or folder (drive) that actually exists inside a connection. */
export interface ConnLocation {
  id: string;
  path: string;
  count: number;
}

/**
 * Which state moves a user may perform. Running is what promotes to_sync → in_progress, so it is
 * deliberately absent here: hand-placing an item into in_progress would invent a claim no worker
 * holds — precisely the stuck state that in_progress → to_sync ("שחרר") exists to clean up.
 */
export const LEGAL_MOVES: Record<SyncItemState, SyncItemState[]> = {
  to_sync: ['synced'],
  in_progress: ['to_sync'],
  synced: ['to_sync'],
  failed: ['to_sync'],
};

export const MOVE_LABEL: Record<string, string> = {
  'failed>to_sync': 'נסה שוב',
  'in_progress>to_sync': 'שחרר',
  'synced>to_sync': 'סנכרן מחדש',
  'to_sync>synced': 'דלג',
};

// ----- Config tables (supabase settings/companies/tag_rules via the BFF) ----

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

/** companies / tag_rules rows are schema-flexible (SELECT *) — render generically. */
export type ConfigRow = Record<string, unknown>;

export interface ConfigCompaniesResult {
  companies: ConfigRow[];
  reachable: boolean;
  error?: string;
}

export interface ConfigTagRulesResult {
  tag_rules: ConfigRow[];
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
export interface DashCompany { name: string; count: number }
export interface DashExtractionField { key: string; label: string; pct: number }
export interface DashRecent {
  id?: string | null;
  name?: string | null;
  status?: string | null;
  type?: string | null;
  company?: string | null;
  date?: string | null;
}
export interface DashboardStats {
  reachable: boolean;
  error?: string;
  total: number;
  completed: number;
  attention: number;
  failed: number;
  companies: number;
  groups: { done: number; attention: number; failed: number; other: number };
  by_status: DashStatus[];
  by_type: DashType[];
  top_companies: DashCompany[];
  extraction: { fields: DashExtractionField[]; overall: number };
  recent: DashRecent[];
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

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_PREFIX}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  }).catch(() => { throw new ApiError(0, null); });   // not sent, or no answer: «Failed to fetch» was the screen's sentence
  if (!res.ok) throw await refusal(res);
  // (an answer that is ok and not JSON — the sign-in page, once the session ran out — was the parser's «Unexpected token '<'»)
  return (await res.json().catch(() => { throw new ApiError(res.status, null); })) as T;
}

/* What a refusal SAID: its envelope when the body is JSON, its text when it is not — read ONCE. `json()` and
   then `text()` threw «Failed to execute 'text' on 'Response': body stream already read» for every refusal that
   was not JSON (the 502 page a proxy answers while the service restarts), and that was what the screen showed.
   The live app's own (apps/indox/app/webapp/src/api.ts). */
async function refusal(res: Response): Promise<ApiError> {
  const text = await res.text().catch(() => '');
  let body: unknown = text;
  try { body = JSON.parse(text); } catch { /* not an envelope */ }
  return new ApiError(res.status, body);
}
/* A refusal with no sentence of its own, in the office's words (platform-base/bina-ui/bina-said.js). */
const said = (status: number): string => (!status ? 'אין תשובה מהשירות'
  : status < 300 ? 'התשובה אינה מה שהמסך ציפה לו — רענן את הדף'
  : status === 401 ? 'הכניסה פגה — רענן את הדף' : status === 403 ? 'אין הרשאה לפעולה הזאת'
  : status === 404 ? 'השירות לא מכיר את הבקשה הזאת'
  : status > 501 && status < 505 ? 'השירות אינו זמין כרגע' : status >= 500 ? 'השירות נתקל בשגיאה'
  : 'הבקשה נדחתה');

export class ApiError extends Error {
  status: number;
  body: unknown;
  constructor(status: number, body: unknown) {
    // the service's own sentence when its answer carries one — never «API 502»
    const human = body && typeof body === 'object' ? (body as { message?: unknown }).message : null;
    super(typeof human === 'string' && human.trim() ? human : said(status));
    this.status = status;
    this.body = body;
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
  docs: number;
  registry: number;
  settings_count: number;
  companies: number;
  tag_rules: number;
  created_at?: string;
}

export interface InstanceDetail {
  account: InstanceAccount;
  repo: RepoConfig;
  target: string;
  columns: ColumnDef[];
  registry: SyncRegistryEntry[];
  settings: { key: string; value: string }[];
  counts: { docs: number; registry: number; settings: number; companies: number; tag_rules: number };
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

export const api = {
  authMe: () => call<AuthMe>('/auth/me'),

  // ----- instances (a full INDOX each) ---------------------------------------
  listInstances: () =>
    call<{ accounts: InstanceAccount[]; active: string }>('/accounts'),
  selectInstance: (id: string) =>
    call<{ success: boolean; active: string; account: InstanceAccount }>('/account/select', {
      method: 'POST',
      body: JSON.stringify({ id }),
    }),
  addInstance: (spec: NewInstanceSpec) =>
    call<{ success: boolean; account: InstanceAccount; accounts: InstanceAccount[]; active: string }>(
      '/account/add',
      { method: 'POST', body: JSON.stringify(spec) },
    ),
  removeInstance: (id: string) =>
    call<{ success: boolean; accounts: InstanceAccount[]; active: string }>('/account/remove', {
      method: 'POST',
      body: JSON.stringify({ id }),
    }),
  instanceDetail: () => call<InstanceDetail>('/account/detail'),

  listRepos: () => call<{ repos: RepoConfig[] }>('/repos'),
  getRepo: (name: string) => call<{ repo: RepoConfig }>(`/repos/${name}`),
  createRepo: (cfg: RepoConfig) =>
    call<{ repo: RepoConfig; provisioned: unknown }>(
      '/repos',
      { method: 'POST', body: JSON.stringify(cfg) },
    ),
  deleteRepo: (name: string) =>
    call<{ success: true }>(`/repos/${name}`, { method: 'DELETE' }),

  patchRepo: (name: string, patch: Partial<RepoConfig>) =>
    call<{ repo: RepoConfig }>(`/repos/${name}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),

  repoStats: (name: string) => call<RepoStats>(`/repos/${name}/stats`),

  upsertRows: (repo: string, rows: Record<string, unknown>[]) =>
    call<UpsertResult>(`/repos/${repo}/documents`, {
      method: 'PUT',
      body: JSON.stringify(rows),
    }),

  queryDocuments: (repo: string, body: QueryBody) =>
    call<QueryResult>(`/repos/${repo}/documents/query`, {
      method: 'POST',
      body: JSON.stringify({ mode: 'all', limit: 50, offset: 0, ...body }),
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

  // SSE — returns the EventSource so the caller can attach handlers and close().

  syncRepo: (repo: string) =>
    call<{ success: boolean; scanned: number; events_published: number; created: number; changed: number }>(
      `/repos/${repo}/sync`,
      { method: 'POST' },
    ),

  // ----- INDOX sync control plane (read-only) --------------------------------
  // The BFF proxies the n8n manage webhook (STATUS) and reads the registry from
  // supabase; both degrade gracefully (never throw a 500) so the board can
  // render a "webhook unreachable" state instead of erroring out.
  getSyncStatus: (sync?: string) =>
    call<SyncStatus>(
      `/sync/status${sync ? `?sync=${encodeURIComponent(sync)}` : ''}`,
    ),

  getSyncRegistry: () => call<SyncRegistryResult>('/sync/registry'),

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
  deleteSyncEntry: (name: string) =>
    call<{ success: boolean; registry: SyncRegistryEntry[] }>(
      `/sync/registry/${encodeURIComponent(name)}`,
      { method: 'DELETE' },
    ),
  runSyncEntry: (name: string) =>
    call<{ success: boolean; claimed: number; registry: SyncRegistryEntry[] }>(
      `/sync/registry/${encodeURIComponent(name)}/run`,
      { method: 'POST' },
    ),
  runAllSyncs: () =>
    call<{ success: boolean; claimed: number; registry: SyncRegistryEntry[] }>(
      '/sync/run',
      { method: 'POST' },
    ),
  /**
   * LIST(sync, state) — the sync-control-plane's one generic read (ai/context/indox-sync-control-plane.md).
   * Decomposes per source: drive `op:list` on `pairs[].{state}`, gmail `op:search label:{state}`.
   */
  listSyncItems: (
    opts: { sync?: string; state?: string; code?: string; q?: string; stuck?: boolean; limit?: number; offset?: number } = {},
  ) => {
    const p = new URLSearchParams();
    if (opts.sync) p.set('sync', opts.sync);
    if (opts.state) p.set('state', opts.state);
    if (opts.code) p.set('code', opts.code);
    if (opts.q) p.set('q', opts.q);
    if (opts.stuck) p.set('stuck', '1');
    if (opts.limit) p.set('limit', String(opts.limit));
    if (opts.offset) p.set('offset', String(opts.offset));
    const qs = p.toString();
    return call<{ items: SyncItem[]; total: number; all_ids: string[] }>(`/sync/items${qs ? `?${qs}` : ''}`);
  },
  /**
   * CLAIM / ADVANCE — moving an item between states IS the source-level primitive: drive `op:move`
   * between the pair folders, gmail add/removeLabels. State lives in the source; the table is
   * downstream, so this writes the source and the table follows.
   */
  moveSyncItems: (sync: string, ids: string[], to: SyncItemState) =>
    call<{ success: boolean; moved: number; refused: number; registry: SyncRegistryEntry[] }>(
      '/sync/items/move',
      { method: 'POST', body: JSON.stringify({ sync, ids, to }) },
    ),
  /** Classify by the pipe's own location (fallback_type) and re-queue — ADVANCE(to_sync) + type set. */
  applyFallbackType: (sync: string, ids: string[]) =>
    call<{ success: boolean; applied: number; type: string; registry: SyncRegistryEntry[] }>(
      '/sync/items/apply-fallback-type',
      { method: 'POST', body: JSON.stringify({ sync, ids }) },
    ),
  listConnections: () => call<{ connections: SyncConnection[] }>('/connections'),
  listLocations: (connId: string) =>
    call<{ kind: 'labels' | 'folders'; items: ConnLocation[] }>(
      `/connections/${encodeURIComponent(connId)}/locations`,
    ),
  createLocation: (connId: string, path: string) =>
    call<{ success: boolean; item: ConnLocation; created: boolean }>(
      `/connections/${encodeURIComponent(connId)}/locations`,
      { method: 'POST', body: JSON.stringify({ path }) },
    ),

  // ----- INDOX config tables (supabase, via the BFF) -------------------------
  // All reads degrade gracefully ({reachable:false}) when supabase/a table is
  // unreachable; putConfigSetting only accepts the server-side allowlisted keys.
  getConfigSettings: () => call<ConfigSettingsResult>('/config/settings'),

  getConfigCompanies: () => call<ConfigCompaniesResult>('/config/companies'),

  getConfigTagRules: () => call<ConfigTagRulesResult>('/config/tag_rules'),

  putConfigSetting: (key: string, value: unknown) =>
    call<PutSettingResult>(`/config/settings/${encodeURIComponent(key)}`, {
      method: 'PUT',
      body: JSON.stringify({ value }),
    }),

  // Inline-edit one cell of an editable config table (companies / tag_rules).
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
  dashboardStats: () => call<DashboardStats>('/dashboard/stats'),

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

  // direct URLs (rendered by <img>/<iframe>, not fetched as JSON)
  extractionFileUrl: (docId: string) => {
    const [typ, name] = splitDocId(docId);
    return `${API_PREFIX}/extraction/file/${encodeURIComponent(typ)}/${encodeURIComponent(name)}`;
  },
  extractionDrawUrl: (docId: string, category?: string) => {
    const [typ, name] = splitDocId(docId);
    const q = category ? `?category=${encodeURIComponent(category)}` : '';
    return `${API_PREFIX}/extraction/draw/${encodeURIComponent(typ)}/${encodeURIComponent(name)}${q}`;
  },
  // זיהוי תווים — every OCR token boxed on the document (raw recognition map)
  extractionTokensUrl: (docId: string) => {
    const [typ, name] = splitDocId(docId);
    return `${API_PREFIX}/extraction/tokens/${encodeURIComponent(typ)}/${encodeURIComponent(name)}`;
  },
};

function splitDocId(docId: string): [string, string] {
  const i = docId.indexOf('/');
  return i < 0 ? ['invoice', docId] : [docId.slice(0, i), docId.slice(i + 1)];
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
