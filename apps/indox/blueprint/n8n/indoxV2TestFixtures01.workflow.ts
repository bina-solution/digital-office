import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : INDOX Seed Fixtures
// Nodes   : 17  |  Connections: 16
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// WhenCalled                         executeWorkflowTrigger
// FetchSchema                        httpRequest                [retry]
// EnsureSchema                       postgres                   [creds] [alwaysOutput]
// EnsureBucket                       postgres                   [creds] [alwaysOutput]
// FetchCache                         httpRequest                [executeOnce] [retry]
// BuildCache                         code
// SeedCache                          executeWorkflow            [alwaysOutput] [retry]
// FetchSettings                      httpRequest                [executeOnce] [retry]
// BuildSettings                      code
// SeedSettings                       executeWorkflow            [alwaysOutput] [retry]
// FetchTagrules                      httpRequest                [executeOnce] [retry]
// BuildTagrules                      code
// SeedTagrules                       executeWorkflow            [alwaysOutput] [retry]
// ResyncTagrulesSeq                  postgres                   [creds] [alwaysOutput]
// FixturesReady                      code
// EnsureSenderCompany                postgres                   [onError→regular] [creds] [alwaysOutput]
// SeedSynthCompanies                 postgres                   [onError→regular] [creds] [alwaysOutput]
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// WhenCalled
//    → FetchSchema
//      → EnsureSchema
//        → EnsureBucket
//          → EnsureSenderCompany
//            → SeedSynthCompanies
//              → FetchCache
//                → BuildCache
//                  → SeedCache
//                    → FetchSettings
//                      → BuildSettings
//                        → SeedSettings
//                          → FetchTagrules
//                            → BuildTagrules
//                              → SeedTagrules
//                                → ResyncTagrulesSeq
//                                  → FixturesReady
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"When Called":{"main":[[{"node":"Fetch Schema","type":"main","index":0}]]},"Fetch Schema":{"main":[[{"node":"Ensure Schema","type":"main","index":0}]]},"Ensure Schema":{"main":[[{"node":"Ensure Bucket","type":"main","index":0}]]},"Ensure Bucket":{"main":[[{"node":"Ensure Sender Company","type":"main","index":0}]]},"Fetch Cache":{"main":[[{"node":"Build Cache","type":"main","index":0}]]},"Build Cache":{"main":[[{"node":"Seed Cache","type":"main","index":0}]]},"Seed Cache":{"main":[[{"node":"Fetch Settings","type":"main","index":0}]]},"Fetch Settings":{"main":[[{"node":"Build Settings","type":"main","index":0}]]},"Build Settings":{"main":[[{"node":"Seed Settings","type":"main","index":0}]]},"Seed Settings":{"main":[[{"node":"Fixtures Ready","type":"main","index":0}]]},"Ensure Sender Company":{"main":[[{"node":"Seed Synth Companies","type":"main","index":0}]]},"Seed Synth Companies":{"main":[[{"node":"Fetch Cache","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"edad0600-cc86-4f33-b016-311b555b8f4e","name":"indox-app"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"dcb770a3-465f-4ed5-b5d4-ca1ff6dcd994","name":"lifecycle:test"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: {"templateCredsSetupCompleted":true},
    /*__n8n__*/ pinData: {},
    /*__n8n__*/ staticData: null,
    /*__n8n__*/ shared: [{"updatedAt":"2026-07-30T23:42:27.037Z","createdAt":"2026-07-30T23:42:27.037Z","role":"workflow:owner","workflowId":"indoxV2TestFixtures01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'indoxV2TestFixtures01',
    name: 'INDOX Seed Fixtures',
    active: true,
    isArchived: false,
    tags: ['app:indox', 'indox-app', 'lifecycle:test'],
    settings: { executionOrder: 'v1', executionTimeout: 900, binaryMode: 'separate' },
})
export class IndoxSeedFixturesWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'a3e70faf-b8d2-4ce9-8e93-c21f408e6e51',
        name: 'When Called',
        type: 'n8n-nodes-base.executeWorkflowTrigger',
        version: 1.1,
        position: [0, 0],
    })
    WhenCalled = {
        inputSource: 'passthrough',
    };

    @node({
        id: 'bb4b0110-abc5-4155-8603-827adc3fd10d',
        name: 'Fetch Schema',
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [130, 0],
        retryOnFail: true,
        maxTries: 4,
        waitBetweenTries: 5000,
    })
    FetchSchema = {
        url: 'http://indox-demo-docs:8088/fixtures/schema.sql',
        options: {
            response: {
                response: {
                    responseFormat: 'text',
                },
            },
        },
    };

    @node({
        id: '44ca12f1-2577-4c98-ae22-3ab32d8038f0',
        name: 'Ensure Schema',
        type: 'n8n-nodes-base.postgres',
        version: 2.5,
        position: [260, 0],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        alwaysOutputData: true,
    })
    EnsureSchema = {
        operation: 'executeQuery',
        options: {},
        query: "=select 1 from {{ (() => { const i = String($('When Called').first().json.__instance || ''); if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error('indoxV2TestFixtures01: no valid __instance — public fallback removed at the 2026-08-31 cutover'); } return 'indox_' + i; })() }}.settings limit 1;",
    };

    @node({
        id: 'bdf9ee52-76d7-476b-9df4-96c92e7cca4e',
        name: 'Ensure Bucket',
        type: 'n8n-nodes-base.postgres',
        version: 2.5,
        position: [390, 0],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        alwaysOutputData: true,
    })
    EnsureBucket = {
        operation: 'executeQuery',
        options: {},
        query: "INSERT INTO storage.buckets (id, name, public) VALUES ('drive','drive',true) ON CONFLICT (id) DO NOTHING;",
    };

    @node({
        id: 'bab2f9f5-a7df-46fd-b6b1-06f7be3cb100',
        name: 'Fetch Cache',
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [400, 0],
        executeOnce: true,
        retryOnFail: true,
        maxTries: 4,
        waitBetweenTries: 5000,
    })
    FetchCache = {
        url: 'http://indox-demo-docs:8088/fixtures/ai-extraction-cache.json',
        options: {},
    };

    @node({
        id: 'c5b9e7c8-1603-4b9a-8128-8ba1cba3deaa',
        name: 'Build Cache',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [560, 0],
    })
    BuildCache = {
        jsCode: "return $input.all().flatMap(i=>Array.isArray(i.json)?i.json:[i.json]).map(r=>({json:{INLINE_ACTION:'TABLE_UPSERT', table:'ai_extraction_cache', cache_key:r.cache_key, kind:r.kind, value:r.value}}));",
    };

    @node({
        id: 'ac0dfc77-0d15-4542-b03f-0694616f5661',
        name: 'Seed Cache',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [720, 0],
        alwaysOutputData: true,
        retryOnFail: true,
        maxTries: 4,
        waitBetweenTries: 5000,
    })
    SeedCache = {
        workflowId: {
            __rl: true,
            value: 'indoxApi01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'passthrough',
        },
        options: {
            waitForSubWorkflow: true,
        },
    };

    @node({
        id: 'ac3a9dcd-db77-4741-b3d1-ca705e1473e8',
        name: 'Fetch Settings',
        type: 'n8n-nodes-base.httpRequest',
        version: 4.2,
        position: [1000, 0],
        executeOnce: true,
        retryOnFail: true,
        maxTries: 4,
        waitBetweenTries: 5000,
    })
    FetchSettings = {
        url: 'http://indox-demo-docs:8088/fixtures/settings.json',
        options: {},
    };

    @node({
        id: '32c58334-1bc9-4279-b1c0-a3deab4e568d',
        name: 'Build Settings',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [1160, 0],
    })
    BuildSettings = {
        jsCode: `// INSTANCE: the instance this row belongs to (phase 6.5). The chokepoint THROWS without it.
// Hardcoded to the first instance here because this is part of the v1/demo/test tail the
// plan scopes separately — these workflows seed or read fixtures for one known deployment.
// The v3 engine does NOT hardcode it: it carries the instance from the work item.
const INSTANCE='incoming-documents-main';

// ── OPERATIONAL KEYS ARE NEVER SEEDED FROM THE FIXTURE (2026-08-06) ──────────────────────────
// public.settings is not a demo table: it is the platform's live config store. This node emitted
// TABLE_UPSERT for every one of the fixture's 47 rows, so ANY run of this workflow — and it is
// called by IndoxResetFull01 plus seven test suites (indoxV2{BS,DocBase,GDoc,Pipeline}Test01,
// syncV3{Full,Kernel,Sources}Test01) — silently reset whatever an operator had configured.
//
// MEASURED CONSEQUENCE: the fixture shipped OldDocumentMonthsBack=1200 (100 years, i.e.
// effectively unbounded discovery; the seeded default is 6 since 2026-08-25 — the discovery
// window must hold out of the box too). It was configured to 6 and came back as 1200. The same exposure is live
// for the extraction_* tuning keys, which an operator had just changed (public.settings
// updated_at 2026-08-05 23:01:12) and which any test run would have reverted.
//
// This is the SAME defect scripts/ui-coverage/seed.sh was fixed for on 2026-08-05 ("INSERT-ONLY,
// NEVER CLOBBER"). That fix was applied to seed.sh only; this workflow is the second applier of
// the same fixture and kept the destructive semantics. One incident, two writers, one fixed.
//
// The keys stay IN the fixture file on purpose: seed.sh is insert-only, so a genuinely fresh
// install still gets sane defaults from them. What must never happen is re-asserting them over a
// configured system, which is exactly what a test/reset run does.
// [insert-only 2026-08-27, owner order] THE ALLOWLIST IS GONE — every key is now insert-only.
//
// OPERATIONAL_KEYS enumerated the keys to PROTECT, and an enumeration of what to protect always
// trails the next incident. It was added 2026-08-06 after OldDocumentMonthsBack came back as 1200,
// and it was STILL incomplete on 2026-08-26: a manual run of syncV3KernelTest01 at 20:28 re-asserted
// indox.actions.priority_sync.local='true' (not on the list), which routed 213 of a client's
// documents to the local stand-in instead of their ERP. The concurrency dials were unprotected too.
//
// So the default is inverted instead of the list extended: seeding CREATES what is absent and never
// re-asserts what exists. A fresh install still gets every default from the fixture; a configured
// system is never overwritten. Same semantics scripts/ui-coverage/seed.sh has had since 2026-08-05
// ("INSERT-ONLY, NEVER CLOBBER") — this workflow was the second applier of the same fixture and had
// kept the destructive half.
//
// Resetting a configured system to fixture values is still possible, but it is now an explicit
// operator verb rather than a side effect of any test or reset run.
const SCHEMA=String($('When Called').first().json.__instance||'');
const all = $input.all().flatMap(i=>Array.isArray(i.json)?i.json:[i.json]);
// [test-clock 2026-08-31] THE TEST TENANT IS CLOCK-INDEPENDENT. The fixture's seeded default
// (OldDocumentMonthsBack=6, the out-of-box discovery window) ages the REAL demo files the
// lifecycle lanes extract — they carry genuine 2025 document dates, so at 6 months every one
// of them parked OLD before selection could run (measured: doc_base exec 3736191, all four
// dbf_* rows STATUS=OLD, TYPE never written). Ageing behaviour itself is covered by explicit
// OLD cases seeded with explicit old dates; the lifecycle lanes must not silently expire as
// the corpus ages. 240 months, only when seeding the suites' own tenant — never a real one.
// FORCED for that one row, not if-absent: the per-run reset preserves settings (measured: the
// 03:40 value survived a 04:47 reset+seed), and insert-only exists to protect an OPERATOR's
// config — the test tenant is machine-owned, reset-bracketed and G64-pinned, so the seeder IS
// its operator. Every other row, and every real tenant, keeps insert-only semantics untouched.
const rows = SCHEMA==='test' ? all.map(r=>r.key==='OldDocumentMonthsBack'?{...r, value:'240', __force:true}:r) : all;
console.log('[fixtures] settings insert-if-absent=' + rows.length + ' (0 overwritten by design)');
return rows.map(r=>({json:{INLINE_ACTION:'TABLE_UPSERT', table:'settings', instance:INSTANCE, __instance:SCHEMA,
                          key:r.key, value:r.value, __if_absent:!r.__force}}));`,
    };

    @node({
        id: 'effcf209-cad8-45b0-a482-80f3fbb2638f',
        name: 'Seed Settings',
        type: 'n8n-nodes-base.executeWorkflow',
        version: 1.2,
        position: [1320, 0],
        alwaysOutputData: true,
        retryOnFail: true,
        maxTries: 4,
        waitBetweenTries: 5000,
    })
    SeedSettings = {
        workflowId: {
            __rl: true,
            value: 'indoxApi01',
            mode: 'id',
        },
        workflowInputs: {
            mappingMode: 'passthrough',
        },
        options: {
            waitForSubWorkflow: true,
        },
    };





    @node({
        id: '4d1e3c31-8540-45e8-a811-4b1884813d4c',
        name: 'Fixtures Ready',
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [2200, 0],
    })
    FixturesReady = {
        jsCode: "const n=(x)=>{try{return $(x).all().length;}catch(e){return 0;}};return [{json:{fixtures_seeded:true, ai_cache:n('Build Cache'), settings:n('Build Settings'), tag_rules:n('Build TagRules')}}];",
    };

    @node({
        id: 'fx-ensure-sender-company',
        name: 'Ensure Sender Company',
        type: 'n8n-nodes-base.postgres',
        version: 2.5,
        position: [520, 0],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
    })
    EnsureSenderCompany = {
        operation: 'executeQuery',
        options: {},
        query: `=-- gmail-bs figures COMPANY_ID from the SENDER, via settings.company_name_by_mail, which the
-- processor reads through /webhook/company?all — a response cached for 20 min. So the mail-carrying
-- company must exist BEFORE any suite warms that cache: here, at fixture time, not inside a lane.
-- Guarded: fires only when the whole table is mail-less (a real deployment never is).
-- id is GENERATED ALWAYS (see fixtures/schema.sql) — never supply it.
insert into {{ (() => { const i = String($('When Called').first().json.__instance || ''); if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error('indoxV2TestFixtures01: no valid __instance — public fallback removed at the 2026-08-31 cutover'); } return 'indox_' + i; })() }}.companies ("instance", "שם חברה", "מזהה 1", "מייל 1")
select 'incoming-documents-main', 'SV3S Sender Co', '998000111', 'sv3s-bs-sender@demo.indox'
-- the guard is per-instance too: "does a mail-carrying company already exist" has to mean
-- "...for THIS instance". Left global, the first instance's rows satisfy it forever and every
-- later instance silently never receives its fixture — a suite that then fails for a reason
-- nowhere near this line.
where not exists (select 1 from {{ (() => { const i = String($('When Called').first().json.__instance || ''); if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error('indoxV2TestFixtures01: no valid __instance — public fallback removed at the 2026-08-31 cutover'); } return 'indox_' + i; })() }}.companies
                  where "instance" = 'incoming-documents-main'
                    and (coalesce("מייל 1",'') <> '' or coalesce("מייל 2",'') <> ''));`,
    };

    @node({
        id: 'fx-synth-companies',
        name: 'Seed Synth Companies',
        /*__n8n__*/ notes: "[synthetic corpus 2026-08-31] The docGen corpus (synth-demo-docs/truth.json) draws every document from a fixed pool of 8 companies. Company-name resolution reads the TENANT's companies table, so a suite extracting a synthetic doc on a fresh test tenant answered 'unknown' -> UNKNOWN_COMPANY (measured: pipeline batch, 11 of 17). The registry for the corpus belongs to the FIXTURES layer -- one owner, every suite -- not to per-suite Seed Companies SQL. Insert-if-absent, per instance, generated verbatim from truth.json.",
        type: 'n8n-nodes-base.postgres',
        version: 2.5,
        position: [1760, 300],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        onError: 'continueRegularOutput',
        alwaysOutputData: true,
    })
    SeedSynthCompanies = {
        operation: 'executeQuery',
        options: {},
        query: `=insert into {{ (() => { const i = String($('When Called').first().json.__instance || ''); if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error('indoxV2TestFixtures01: no valid __instance — public fallback removed at the 2026-08-31 cutover'); } return 'indox_' + i; })() }}.companies ("instance", "שם חברה", "מזהה 1")
values ('incoming-documents-main', 'בניאס סחר בע"מ', '510605959'),
       ('incoming-documents-main', 'כהן פור ש.א. בע"מ', '511022493'),
       ('incoming-documents-main', 'אלקטרה מוצרי בנייה בע"מ', '511234567'),
       ('incoming-documents-main', 'אגן מפעלי הנדסה (1988) בע"מ', '511301129'),
       ('incoming-documents-main', 'דלתות תייר בע"מ', '511634388'),
       ('incoming-documents-main', 'דיאור יבוא ושיווק בע"מ', '513105494'),
       ('incoming-documents-main', 'פולירון תעשיות בע"מ', '513498345'),
       ('incoming-documents-main', 'מפעל מתכת כפר מנחם בע"מ', '570043745')
on conflict ("instance", "מזהה 1") do nothing;
-- [fixed certainty 2026-09-02, owner Decision 8] THREE of the eight synthetic companies carry the
-- per-company FIXED certainty (90) so the pipeline suite proves SelectType01's max(computed, fixed)
-- on live documents: their INVOICE / SHIPMENT rows must land with SELECTION_SOURCE =
-- FIXED_CERTAINTY. Three, so a 17-document batch drawn from the pool surely holds one.
-- Idempotent: set on every seed.
update {{ (() => { const i = String($('When Called').first().json.__instance || ''); if (!/^[a-z][a-z0-9_]*$/.test(i)) { throw new Error('indoxV2TestFixtures01: no valid __instance'); } return 'indox_' + i; })() }}.companies
   set "SELECTION_CERTAINTY" = 90
 where "instance" = 'incoming-documents-main' and "מזהה 1" in ('510605959', '511022493', '511234567');`,
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.WhenCalled.out(0).to(this.FetchSchema.in(0));
        this.FetchSchema.out(0).to(this.EnsureSchema.in(0));
        this.EnsureSchema.out(0).to(this.EnsureBucket.in(0));
        this.EnsureBucket.out(0).to(this.EnsureSenderCompany.in(0));
        this.FetchCache.out(0).to(this.BuildCache.in(0));
        this.BuildCache.out(0).to(this.SeedCache.in(0));
        this.SeedCache.out(0).to(this.FetchSettings.in(0));
        this.FetchSettings.out(0).to(this.BuildSettings.in(0));
        this.BuildSettings.out(0).to(this.SeedSettings.in(0));
        this.SeedSettings.out(0).to(this.FixturesReady.in(0));
        this.EnsureSenderCompany.out(0).to(this.SeedSynthCompanies.in(0));
        this.SeedSynthCompanies.out(0).to(this.FetchCache.in(0));
    }
}
