import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : SelectBase01 — base selection (company / type / date)
// Nodes   : 6  |  Connections: 5
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// RowIn                              executeWorkflowTrigger
// LoadSelectionConfig                 postgres                   [onError→regular] [creds] [alwaysOutput] [executeOnce]
// RestoreRow                         code
// NameCompanyMatch                   postgres                   [onError→regular] [creds] [alwaysOutput]
// Select                             code
// Return_                            set
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// RowIn
//    → LoadSelectionConfig
//      → RestoreRow
//        → NameCompanyMatch
//          → Select
//            → Return_
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"Row In":{"main":[[{"node":"Load Selection Config","type":"main","index":0}]]},"Load Selection Config":{"main":[[{"node":"Restore Row","type":"main","index":0}]]},"Restore Row":{"main":[[{"node":"NAME Company Match","type":"main","index":0}]]},"NAME Company Match":{"main":[[{"node":"Select","type":"main","index":0}]]},"Select":{"main":[[{"node":"Return","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: null,
    /*__n8n__*/ pinData: {},
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-08-25T13:36:07.352Z","createdAt":"2026-08-25T13:36:07.352Z","role":"workflow:owner","workflowId":"SelectBase01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'SelectBase01',
    name: 'SelectBase01 — base selection (company / type / date)',
    active: true,
    isArchived: false,
    tags: ['app:indox'],
    settings: { errorWorkflow: 'errorHandler01', executionOrder: 'v1' },
})
export class Selectbase01BaseSelectionCompanyTypeDateWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'selb-in-01',
        name: 'Row In',
        /*__n8n__*/ notes: "THE WHOLE ROW ARRIVES HERE: LOCAL_*/AI_* from the base extraction, the filename (NAME), the source, and whatever COMPANY_ID / TYPE / DOC_DATE the row already holds. Pure function of that row -- no file, no OCR, no model.",
        type: 'n8n-nodes-base.executeWorkflowTrigger',
        version: 1.1,
        position: [0, 0],
    })
    RowIn = {
        inputSource: 'passthrough',
    };

    @node({
        id: 'selb-typepri-01',
        name: 'Load Selection Config',
        /*__n8n__*/ notes: "The TWO settings this selector reads, in ONE executeOnce query. (1) indox.extraction.type_priority -- which READER leads when both engines return a REAL but different type. AI is the default since 2026-08-31 (owner order): measured over the estate the two engines disagree on 905 documents, and the local engine's failure mode is the expensive one -- it reads an aging report's LINE ITEMS and calls the report an invoice. The value is normalized to LOCAL/AI on write, so anything else here means the row was hand-edited. (2) sync_registry -- the pipe definitions, for each pipe's `type_hint` and `type_authority`. The registry is read LIVE rather than trusted from the row's stored TYPE_BY_SOURCE, so re-pointing a folder's declared type in the settings UI changes the next selection instead of only the next ingest. Read here rather than inherited from a caller, so this workflow answers identically however it is invoked (the router, fullDocEx01, or a bulk re-selection).",
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [224, 0],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
        executeOnce: true,
    })
    LoadSelectionConfig = {
        operation: 'executeQuery',
        query: `=SELECT UPPER(COALESCE((SELECT value FROM {{ (() => { const i = String($json.__instance || ''); if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error('SelectBase01: no valid __instance — public fallback removed at the 2026-08-31 cutover'); } return 'indox_' + i; })() }}.settings
         WHERE key = 'indox.extraction.type_priority'), 'AI')) AS type_priority,
       COALESCE((SELECT value FROM {{ (() => { const i = String($json.__instance || ''); if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error('SelectBase01: no valid __instance — public fallback removed at the 2026-08-31 cutover'); } return 'indox_' + i; })() }}.settings
         WHERE key = 'sync_registry'), '[]') AS sync_registry;`,
        options: {},
    };

    @node({
        id: 'selb-restore-01',
        name: 'Restore Row',
        /*__n8n__*/ notes: "'Load Selection Config' is executeOnce and REPLACES the item stream with its single settings row, so the document rows are re-emitted here before the per-row NAME query. Same idiom as 'Restore Router Payload' in indoxV2ActionsGlobal01.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [448, 0],
    })
    RestoreRow = {
        jsCode: `return $('Row In').all();
`,
    };

    @node({
        id: 'selb-namematch-01',
        name: 'NAME Company Match',
        /*__n8n__*/ notes: "[B31 2026-08-09, ported verbatim] Link-independent company resolution from the FILENAME: anchored prefix, min length 5, unambiguous only, longest match wins. It is the FILL-ONLY third company leg, consulted only when both OCR legs produced nothing, so it can never override an extracted value. One result row per input item; 'Select' pairs by index and refuses a count mismatch.",
        type: 'n8n-nodes-base.postgres',
        version: 2.6,
        position: [672, 0],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
    })
    NameCompanyMatch = {
        operation: 'executeQuery',
        query: `=-- [B31 2026-08-09, moved 2026-08-17, ported 2026-08-25] Company from the FILENAME.
-- [multi-instance 2026-08-28] Schema resolved from __instance; absent resolves to public, which
-- is today's behaviour and becomes a loud failure once the compatibility views are dropped.
-- Anchored prefix only, min length 5, unambiguous only, longest match wins.
-- Mirrors indoxSettings01/'Companies' map construction (identifier fields + blacklist,
-- primary = first non-blank) so this and the settings map cannot drift on identity.
--
-- [source contract 2026-08-25, owner order] THE SELECTOR DERIVES, THE SYNC ONLY REPORTS.
-- The sync now settles the source facts (SENDER, SYNC_REGISTRY_ID, ATTACHMENT_TEXT, SEND_DATE)
-- and decides nothing. Here they become two more CANDIDATES, computed the same way every other
-- leg is and stored as first-class columns (COMPANY_BY_SENDER, TYPE_BY_SOURCE) so the choice is
-- auditable against them. Both keep this node's rules: minimum length, UNAMBIGUOUS ONLY,
-- longest match wins, one result row per input item.
--   sender_* : company from SENDER against companies."מייל 1"/"מייל 2", which already hold an
--              address OR a bare domain — matched by containment so both forms work, and against
--              the whole ordered candidate chain at once. The map has existed since the schema
--              was written and nothing has ever read it.
--   text_*   : company named in ATTACHMENT_TEXT — the text that arrived WITH the item. Measured
--              need: intermediary mail (invoice-one / morning) puts the SaaS letterhead on the
--              PDF and the supplier name in the SUBJECT; that lane is 46% company-less today.
-- ONE parameter carries all three inputs, separated by ' ||| ': a comma-separated
-- queryReplacement would break on the first filename or subject containing a comma.
with args as (
  select split_part($1, ' ||| ', 1) as nm,
         split_part($1, ' ||| ', 2) as src_text,
         lower(split_part($1, ' ||| ', 3)) as senders
),
idents as (
  select c.id as cid, c."שם חברה" as cname, v.ord, v.ident
  from {{ (() => { const i = String($json.__instance || ''); if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error('SelectBase01: no valid __instance — public fallback removed at the 2026-08-31 cutover'); } return 'indox_' + i; })() }}.companies c,
       lateral (values (1, c."מזהה 1"), (2, c."מזהה 2"), (3, c."שם ספק מפריוריטי")) v(ord, ident)
  where v.ident is not null and v.ident <> ''
    and position('פריוריטי' in v.ident) = 0
),
prim as (
  select distinct on (cid) cid, cname, ident as primary_ident
  from idents order by cid, ord
),
hit as (
  select p.primary_ident, p.cname, length(p.cname) as len
  from prim p, args a
  where p.cname is not null
    and length(p.cname) >= 5
    and position(p.cname in coalesce(a.nm, '')) = 1
),
text_hit as (
  select p.primary_ident, p.cname, length(p.cname) as len
  from prim p, args a
  where p.cname is not null
    and length(p.cname) >= 4
    and a.src_text <> ''
    and position(p.cname in a.src_text) > 0
),
sender_hit as (
  -- CHAIN ORDER DECIDES, not unambiguity. SENDER is an ORDERED list (display-name unwrap, then
  -- the forwarded chain, then the raw From) and a forwarded chain legitimately contains several
  -- real parties — supplier, the instance, an accountant. The BS lane's rule has always been
  -- "first candidate that resolves wins", so the earliest match in the list is the answer;
  -- requiring a single global match would throw away exactly the mail this leg exists for.
  -- pos is where the mapping matched inside the comma-joined list, so ascending pos IS chain
  -- order; the longer mapping wins a tie (a full address beats a bare domain).
  select pr.primary_ident, c."שם חברה" as cname,
         position(lower(m.mail) in a.senders) as pos,
         length(m.mail) as mlen
  from {{ (() => { const i = String($json.__instance || ''); if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error('SelectBase01: no valid __instance — public fallback removed at the 2026-08-31 cutover'); } return 'indox_' + i; })() }}.companies c
  join prim pr on pr.cid = c.id
  cross join args a
  cross join lateral (values (c."מייל 1"), (c."מייל 2")) m(mail)
  where m.mail is not null and length(m.mail) >= 5
    and a.senders <> ''
    and position(lower(m.mail) in a.senders) > 0
)
select
  case when (select count(distinct primary_ident) from hit) = 1
       then (select primary_ident from hit order by len desc limit 1) end as company_id,
  case when (select count(distinct primary_ident) from hit) = 1
       then (select cname from hit order by len desc limit 1) end as matched_name,
  (select count(distinct primary_ident) from hit) as candidates,
  case when (select count(distinct primary_ident) from text_hit) = 1
       then (select primary_ident from text_hit order by len desc limit 1) end as text_company_id,
  case when (select count(distinct primary_ident) from text_hit) = 1
       then (select cname from text_hit order by len desc limit 1) end as text_matched_name,
  (select count(distinct primary_ident) from text_hit) as text_candidates,
  (select primary_ident from sender_hit order by pos asc, mlen desc limit 1) as sender_company_id,
  (select cname from sender_hit order by pos asc, mlen desc limit 1) as sender_matched_name,
  (select count(distinct primary_ident) from sender_hit) as sender_candidates;`,
        options: {
            queryBatching: 'independently',
            queryReplacement:
                "={{ ($json.NAME || '') + ' ||| ' + ($json.ATTACHMENT_TEXT || '') + ' ||| ' + ($json.SENDER || '') }}",
        },
    };

    @node({
        id: 'selb-select-01',
        name: 'Select',
        /*__n8n__*/ notes: "ONE selector for COMPANY_ID / TYPE / DOC_DATE. Ported from BaseDocEx01/'Select Base' (which carried the NAME_MATCH leg and the future-date refusal) AND indoxV2ActionsGlobal01/'Select Base Values' (which carried type_priority and the carry-forward) -- the two copies that had silently diverged, with the router's copy overwriting the extractor's and dropping both of its guards. Neither guard is optional: NAME_MATCH is the last company resolver a linkless document has, and an impossible future date is silently terminal because it can age the row to OLD, which never re-evaluates.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [896, 0],
    })
    Select = {
        jsCode: `// SelectBase01/Select -- the base selector. PURE: row in, decision out.
const has = v => v !== null && v !== undefined && String(v).trim() !== '';

// A TYPE of 'unknown' IS A NON-ANSWER, NOT A VALUE -- both spellings occur in this schema.
const canonType = v => String(v).trim().toUpperCase();
const NON_ANSWER_TYPE = ['UNKNOWN', 'UNKNWON'];
const realType = v => (has(v) && NON_ANSWER_TYPE.indexOf(canonType(v)) < 0) ? v : null;

// normalizeDate -- ported verbatim from SelectType01, which took it from 'Selection & Scoring
// Logic1'. [uniform DOC_DATE 2026-08-26, owner order] Select is the only writer of DOC_DATE, so
// it is also the only place that can guarantee its shape, and the legs do not share one: LOCAL_
// and AI_ are dd/mm/yyyy, the ledger leg is yyyy-mm-dd, and a value that has round-tripped
// through the derived doc_date_norm column comes back as a full ISO timestamp. Map Request
// assumes dd/mm/yyyy and truncates anything longer to "2026-00Z". Unparseable input is returned
// as it came: a shape we do not recognise is not a reason to erase a date the extractor did read.
function normalizeDate(val) {
  if (!has(val)) return null;
  let s = String(val).trim().replace(/\\s+/g, '');
  let day, month, year, match;
  if (/^\\d{5}(\\.\\d+)?$/.test(s)) {
    const dateObj = new Date(Math.round((parseFloat(s) - 25569) * 86400 * 1000));
    day = String(dateObj.getDate()).padStart(2, '0');
    month = String(dateObj.getMonth() + 1).padStart(2, '0');
    year = dateObj.getFullYear();
  } else if (match = s.match(/^(\\d{1,2})[\\/\\.\\-](\\d{1,2})[\\/\\.\\-](\\d{2,4})$/)) {
    day = match[1].padStart(2, '0');
    month = match[2].padStart(2, '0');
    year = match[3].length === 2 ? '20' + match[3] : match[3];
  } else if (match = s.match(/^(\\d{4})[\\/\\.\\-](\\d{1,2})[\\/\\.\\-](\\d{1,2})$/)) {
    year = match[1]; month = match[2].padStart(2, '0'); day = match[3].padStart(2, '0');
  } else {
    const parsed = new Date(s);
    if (isNaN(parsed.getTime())) return s;
    day = String(parsed.getDate()).padStart(2, '0');
    month = String(parsed.getMonth() + 1).padStart(2, '0');
    year = parsed.getFullYear();
  }
  return day + '/' + month + '/' + year;
}

// EQUALITY IS DETECTED ON THE CANONICAL FORM, NEVER ON THE RAW STRING. 'canon' is optional, is
// passed PER FIELD, and touches ONLY the equality test -- pick() still returns the raw winner, so
// it changes provenance LABELS and can never change a written value. TYPE gets one (the local leg
// emits 'shipment', Gemini emits 'SHIPMENT', so AGREE was structurally unreachable and every
// two-legged row was mislabelled DISAGREE). COMPANY_ID and DOC_DATE deliberately get none:
// measured over the fleet, folding changes nothing for them and could mask a real difference.
function pick(local, ai, canon) {
  const l = has(local) ? String(local).trim() : null;
  const a = has(ai) ? String(ai).trim() : null;
  if (l && a) return { val: l, source: (canon ? canon(l) === canon(a) : l === a) ? 'AGREE' : 'DISAGREE_PREFER_LOCAL' };
  if (l) return { val: l, source: 'LOCAL_ONLY' };
  if (a) return { val: a, source: 'AI_ONLY' };
  return { val: null, source: 'NONE' };
}

// [A1 date guard 2026-08-13] Reject an AI date that is IMPOSSIBLE, not merely surprising.
// Gemini mis-reads two-digit years two ways -- order flip (23/06/26 -> 26/06/2023) and wrong
// decade (25 -> 2015) -- and pick() already prefers LOCAL when both legs answer, so these all
// arrive down the AI_ONLY branch. Only a FUTURE date is refused: a document cannot be dated after
// the instant it is read. No "implausibly old" bound, because 308 rows sit at a 2-3 year gap and
// may be genuine back-filed invoices. Storing nothing re-opens the document for another pass;
// storing a date we know is wrong is silently terminal -- it can age the row out as OLD.
const dateImpossible = (s) => {
  if (!has(s)) return false;
  const m = String(s).trim().match(/^(\\d{1,2})\\/(\\d{1,2})\\/(\\d{4})$/);
  if (!m) return false;
  const dd = +m[1], mm = +m[2], yy = +m[3];
  if (mm < 1 || mm > 12 || dd < 1 || dd > 31) return false;
  const when = new Date(yy, mm - 1, dd);
  if (isNaN(when.getTime())) return false;
  return when.getTime() > Date.now() + 86400000;   // one day of slack for timezone skew
};

// ONE default, spelled the same in all three places it can be reached from: this initializer (a
// failed read), the SQL COALESCE (a missing row) and the shipped fixture (a fresh instance).
// They disagreed before -- and a default that means different things depending on HOW it was
// missed is the kind of thing you only discover while reading an incident backwards.
let TYPE_PRIORITY = 'AI';
// [source authority 2026-08-31, owner order] THE PIPE'S OWN DECLARATION OF WHAT IT CARRIES.
// A sync pipe knows something no engine can read off the page: WHERE the document came from.
// A Drive folder an operator only ever uploads aging reports into is not guessing -- it is
// stating a fact about every file in it. A mail label is not, because one message legitimately
// carries an invoice, its delivery note and a statement at once. So the registry entry carries
// BOTH the value and its strength:
//   type_hint      -- the declared type ('BALANCE_SHEET', ...), already written and editable in
//                     the sync editor, already stored on the row at birth as TYPE_BY_SOURCE.
//   type_authority -- how much that is worth, lowest first:
//                     'fallback' only when NEITHER engine classified the document (weight 0, so
//                                it can never outrank a real reading) -- what a lone
//                                lone fallback_type has always meant;
//                     'hint'     (default, DEFAULT-PRESERVING: what every pipe written before
//                                this field means) votes beside the engines;
//                     'decisive' the location settles it and outranks both readers.
// Read live from settings.sync_registry so changing a pipe's declaration changes the NEXT
// selection, not only the next ingest. It does NOT enter BASE_SELECTION_HASH -- that hash is a
// SQL function over nine document columns (public.indox_base_selection_hash) and the two must
// stay byte-identical or every row reads as changed forever. Re-typing a pipe's back catalogue
// is therefore a deliberate select_base dispatch, which is the same rule every other config
// change here already follows.
let PIPES = {};
try {
  const cfg = $('Load Selection Config').first().json;
  TYPE_PRIORITY = String(cfg.type_priority || 'AI').toUpperCase();
  let reg = cfg.sync_registry;
  if (typeof reg === 'string') reg = JSON.parse(reg || '[]');
  for (const e of (Array.isArray(reg) ? reg : [])) {
    const nm = String((e && e.name) || '').trim().toLowerCase();
    if (!nm) continue;
    const th = (e.type_hint === null || e.type_hint === undefined) ? '' : String(e.type_hint).trim();
    const auth = String(e.type_authority || 'hint').trim().toLowerCase();
    PIPES[nm] = { type_hint: th ? th.toUpperCase() : null,
                  // anything unrecognised reads as 'hint' -- the historical meaning, and the one
                  // level that neither suppresses the pipe's knowledge nor overrides an engine
                  weight: auth === 'decisive' ? 100 : (auth === 'fallback' ? 0 : 2) };
  }
} catch (e) {}

// INDEX PAIRING, REFUSED ON ANY MISMATCH. The NAME matcher returns exactly one row per input, in
// order. This is the same contract that, when it was violated elsewhere, stamped one document's
// API_TOOLS_ID onto 601 others: a loud failure is recoverable, a silent re-attribution of one
// client's company onto another's document is not.
const rows = $('Row In').all();
const nm = $input.all();
if (nm.length !== rows.length) {
  throw new Error('SelectBase01: item-count mismatch (rows=' + rows.length +
    ', NAME match=' + nm.length + '). Refusing to pair by index.');
}

// The four base selection inputs. Same POST-WRITE rule as SelectType01's hash: a field this node
// declines to write keeps the value already on the row, because indoxApi01's clean() drops null.
function baseHash(row, out) {
  const eff = (k) => (out[k] !== undefined && out[k] !== null && String(out[k]) !== '')
    ? out[k] : row[k];
  return [row.LOCAL_COMPANY_ID, row.AI_COMPANY_ID, eff('COMPANY_ID'),
          row.LOCAL_TYPE, row.AI_TYPE, eff('TYPE'),
          row.LOCAL_DOC_DATE, row.AI_DOC_DATE, eff('DOC_DATE')]
    .map(v => (v === null || v === undefined) ? '' : String(v)).join('|');
}

return rows.map((item, i) => {
  const d = item.json || {};
  const out = { ID: d.ID };

  let companyPick = pick(d.LOCAL_COMPANY_ID, d.AI_COMPANY_ID);
  // FILL-ONLY third company leg: the filename matcher. Only consulted when BOTH OCR legs produced
  // nothing, so it can never override an extracted value. It is the ONLY company resolver a
  // linkless document has -- measured: 62 of 63 such rows were terminalised MISSING_COMPANY_ID
  // with no company resolution ever attempted.
  const nmRow = (nm[i] && nm[i].json) || {};
  if (!companyPick.val && nmRow.company_id) {
    companyPick = { val: String(nmRow.company_id), source: 'NAME_MATCH ' + String(nmRow.matched_name || '') };
  }
  // [source contract 2026-08-25, owner order] THE DERIVED SOURCE LEGS.
  // COMPANY_BY_SENDER is computed here (never by a sync) and STORED, so it stands beside
  // LOCAL_COMPANY_ID / AI_COMPANY_ID as one of the options this pick chooses from — and so the
  // choice stays auditable against it. Order: the page's own engines first, then the operator-
  // curated sender fact, then the company named in the text that came with the item. The measured
  // record is why the source legs fill rather than outrank: on 68 gmail-bs rows the OCR agreed 50
  // times, RESCUED a failed sender 17 times, and overrode a good one once.
  out.COMPANY_BY_SENDER = nmRow.sender_company_id ? String(nmRow.sender_company_id) : null;
  if (!companyPick.val && out.COMPANY_BY_SENDER) {
    companyPick = { val: out.COMPANY_BY_SENDER,
                    source: 'BY_SENDER ' + String(nmRow.sender_matched_name || '') };
  }
  if (!companyPick.val && nmRow.text_company_id) {
    companyPick = { val: String(nmRow.text_company_id),
                    source: 'BY_TEXT ' + String(nmRow.text_matched_name || '') };
  }

  let datePick = pick(d.LOCAL_DOC_DATE, d.AI_DOC_DATE);
  if (datePick.source === 'AI_ONLY' && dateImpossible(datePick.val)) {
    datePick = { val: null, source: 'AI_REFUSED_FUTURE_DATE' };
  }

  // [source contract 2026-08-25, owner order] TYPE_BY_SOURCE — derived here, stored, then used.
  // The source evidence, STRONGEST FIRST:
  //   1. the pipe's own DECLARATION (registry type_hint) — config, read live, and the only leg
  //      that can be decisive, because only the operator knows a folder is single-purpose;
  //   2. the TYPE_BY_SOURCE the sync stamped at birth — still answers after a pipe is renamed or
  //      pruned out of the registry, which is most of the estate (SYNC_NAME resolved against the
  //      live registry on 7.2% of rows, measured 2026-08-21);
  //   3. the registry-id convention (a pipe whose name says 'bs' carries balance sheets);
  //   4. the vocabulary of the text that came with the item. Same vocabulary the label engine
  //      already routes on (tag_rules BS_TO_SYNC keys on "דוח גיול"/"כרטסת"), so a document whose
  //      own subject says what it is stops depending on the OCR reading it off the page.
  // 3 and 4 are INFERENCES about the source, never declarations by it, so they are always a hint.
  const srcText = String(d.ATTACHMENT_TEXT || '');
  const regId = String(d.SYNC_REGISTRY_ID || '').trim().toLowerCase();
  const pipe = PIPES[regId] || null;
  // The derived legs (STORED / REGID / TEXT) are inferences, so they get the plain hint weight;
  // only a pipe that DECLARED its strength gets anything else.
  let typeBySource = null, sourceWeight = 2, sourceWhy = null;
  if (pipe && pipe.type_hint) {
    typeBySource = pipe.type_hint;
    sourceWeight = pipe.weight;
    sourceWhy = 'PIPE:' + regId;
  }
  if (!typeBySource && realType(d.TYPE_BY_SOURCE)) {
    typeBySource = canonType(d.TYPE_BY_SOURCE); sourceWhy = 'STORED';
  }
  if (!typeBySource && regId.indexOf('bs') >= 0) { typeBySource = 'BALANCE_SHEET'; sourceWhy = 'REGID'; }
  if (!typeBySource && srcText) {
    const TEXT_TYPE = [
      ['BALANCE_SHEET', ['דוח גיול', 'כרטסת', 'גיול חובות', 'יתרות']],
      ['SHIPMENT', ['תעודת משלוח', 'תעודות משלוח']],
      ['INVOICE', ['חשבונית', 'חש-מס']],
    ];
    for (const pair of TEXT_TYPE) {
      if (pair[1].some(function (k) { return srcText.indexOf(k) >= 0; })) {
        typeBySource = pair[0]; sourceWhy = 'TEXT'; break;
      }
    }
  }
  out.TYPE_BY_SOURCE = typeBySource;

  // [type vote 2026-08-31, owner order] THREE LEGS, ONE WEIGHTED VOTE — NOT A FILL-ONLY FALLBACK.
  // The source leg used to be consulted ONLY when neither engine answered, which threw away the
  // evidence that is often the most reliable one on the row. Measured on doc_mth6cc0lfmf5hy: the
  // pipe said BALANCE_SHEET (drive-bs — a Drive folder that receives nothing else), Gemini said
  // BALANCE_SHEET, and the local reader said invoice because an aging report's LINE ITEMS are
  // invoices and its rows literally read "חשבונית מס מרכזת". Two-against-one lost, because the
  // third vote was never counted. Now every leg scores and the highest total wins:
  //   READER            2   an engine that actually read the document
  //   LEAD READER       3   the engine indox.extraction.type_priority names (AI by default)
  //   SOURCE FALLBACK   0   type_authority='fallback' — present, but never beats a real reading
  //   SOURCE HINT       2   the location's declaration/inference — enough to break a 3-2 split
  //   SOURCE DECISIVE 100   type_authority='decisive': the location settles it, full stop
  // The weights are chosen so THE OLD BEHAVIOUR IS EXACTLY PRESERVED wherever the old inputs were
  // all there was: with no source evidence a disagreement is still 3-2 for the lead reader, a lone
  // answer still wins alone, and agreement is still agreement. What changes is only the case the
  // old code had no answer for — a source that knows something the page does not say plainly.
  // Weight 0 is a REAL vote, not an absent one: it registers the type as a candidate, so it wins
  // when it is the ONLY candidate and loses to every engine that read the page. That is precisely
  // what a lone fallback_type has always meant, now on the same dial as the rest.
  const lt = canonType(realType(d.LOCAL_TYPE) || '');
  const at = canonType(realType(d.AI_TYPE) || '');
  const st = typeBySource ? canonType(typeBySource) : '';
  const score = {}, why = {};
  const vote = (t, w, tag) => {
    if (!t) return;
    score[t] = (score[t] || 0) + w;
    why[t] = why[t] ? why[t] + '+' + tag : tag;
  };
  vote(lt, TYPE_PRIORITY === 'AI' ? 2 : 3, 'LOCAL');
  vote(at, TYPE_PRIORITY === 'AI' ? 3 : 2, 'AI');
  vote(st, sourceWeight,
       sourceWeight >= 100 ? 'SOURCE!' : (sourceWeight === 0 ? 'SOURCE?' : 'SOURCE'));
  // Object.keys is insertion order and Array.prototype.sort is stable, so a TIE falls to the leg
  // that voted first — LOCAL, then AI, then the source. An engine that opened the document beats a
  // hint that did not, which is exactly the precedence the fill-only version had.
  const ranked = Object.keys(score).sort((a, b) => score[b] - score[a]);
  let typePick = { val: null, source: 'NONE' };
  if (ranked.length) {
    const top = ranked[0], runner = ranked[1];
    typePick = { val: top,
                 source: why[top] + '(' + score[top] + ')' +
                         (runner ? ' over ' + why[runner] + '(' + score[runner] + ')' : '') +
                         (sourceWhy ? ' [' + sourceWhy + ']' : '') };
  }
  // NON-ANSWER FALLBACK, unchanged: when NO leg produced a REAL type, the raw legs are used so
  // 'UNKNOWN' is still written and the row terminalises on it instead of looping.
  if (!typePick.val) typePick = pick(d.LOCAL_TYPE, d.AI_TYPE, canonType);

  // CARRY THE PRE-SELECTION VALUES FORWARD. A pass that resolved nothing must not blank a value
  // the row already holds -- and because the upsert drops null keys, "carry forward" and "write
  // nothing" are the same act. Written explicitly so the decision is visible rather than implied.
  if (companyPick.val) out.COMPANY_ID = companyPick.val;
  // canonical TYPE is UPPERCASE -- every consumer compares it literally.
  if (typePick.val) out.TYPE = String(typePick.val).trim().toUpperCase();
  if (datePick.val) out.DOC_DATE = normalizeDate(datePick.val) || datePick.val;

  // [two-point rule 2026-08-17, owner order] BOTH stamps are UNCONDITIONAL: base is the only
  // sanctioned resolution point for COMPANY_ID and TYPE. Unresolved values terminalize via
  // MISSING_COMPANY_ID / MISSING_TYPE instead of churning out-of-band extractors.
  out.FIGURE_COMPANY_COMPLETED = true;
  out.FIGURE_TYPE_COMPLETED = true;
  // Every action ALWAYS stamps its own completion, or decide re-dispatches it forever.
  out.BASE_SELECTION_COMPLETED = true;
  out.BASE_SELECTION_HASH = baseHash(d, out);
  out.SELECTION_DEBUG_BASE = JSON.stringify({
    COMPANY_ID: companyPick.source, TYPE: typePick.source, DOC_DATE: datePick.source,
    TYPE_PRIORITY: TYPE_PRIORITY,
    LOCAL_STATUS: d.LOCAL_STATUS || null, AI_STATUS: d.AI_STATUS || null,
  });
  return { json: out };
});
`,
    };

    @node({
        id: 'selb-return-01',
        name: 'Return',
        /*__n8n__*/ notes: "Pure passthrough, mirroring the extractors' own 'Return'.",
        type: 'n8n-nodes-base.set',
        version: 3.4,
        position: [1120, 0],
    })
    Return_ = {
        assignments: {
            assignments: [],
        },
        includeOtherFields: true,
        options: {},
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.RowIn.out(0).to(this.LoadSelectionConfig.in(0));
        this.LoadSelectionConfig.out(0).to(this.RestoreRow.in(0));
        this.RestoreRow.out(0).to(this.NameCompanyMatch.in(0));
        this.NameCompanyMatch.out(0).to(this.Select.in(0));
        this.Select.out(0).to(this.Return_.in(0));
    }
}
