import { workflow, node, links } from '@n8n-as-code/transformer';

// <workflow-map>
// Workflow : Sync Item API
// Nodes   : 4  |  Connections: 3
//
// NODE INDEX
// ──────────────────────────────────────────────────────────────────
// Property name                    Node type (short)         Flags
// WhenCalled                         executeWorkflowTrigger
// BuildSql                           code
// PgExecute                          postgres                   [creds] [alwaysOutput] [retry]
// Reply                              code
//
// ROUTING MAP
// ──────────────────────────────────────────────────────────────────
// WhenCalled
//    → BuildSql
//      → PgExecute
//        → Reply
// </workflow-map>

// =====================================================================
// METADATA DU WORKFLOW
// =====================================================================

@workflow({
    /*__n8n__*/ description: null,
    /*__n8n__*/ isArchived: false,
    /*__n8n__*/ connections: {"When Called":{"main":[[{"node":"Build SQL","type":"main","index":0}]]},"Build SQL":{"main":[[{"node":"PG Execute","type":"main","index":0}]]},"PG Execute":{"main":[[{"node":"Reply","type":"main","index":0}]]}},
    /*__n8n__*/ tags: [{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"51804d94-1071-4213-980b-a06491a07895","name":"role:api"},{"updatedAt":"2026-08-16T14:20:49.737Z","createdAt":"2026-08-16T14:20:49.737Z","id":"93ff3a3f-6b78-5d0a-a4de-2948ea161953","name":"app:indox"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"a659438c-0898-428d-aebd-72033caaefe4","name":"sync-v3"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"c7d4bdbd-9cb8-4595-90d4-b200420c3fd2","name":"role:sync"},{"updatedAt":"2026-07-30T23:42:19.465Z","createdAt":"2026-07-30T23:42:19.465Z","id":"d84b71a8-a6dd-4cc4-9ec4-44d6af9c8f76","name":"indox"},{"updatedAt":"2026-08-05T22:56:59.007Z","createdAt":"2026-08-05T22:56:59.007Z","id":"edad0600-cc86-4f33-b016-311b555b8f4e","name":"indox-app"}],
    /*__n8n__*/ versionMetadata: {"name":null,"description":null},
    /*__n8n__*/ meta: {},
    /*__n8n__*/ pinData: {},
    /*__n8n__*/ staticData: {"node:Reaper Schedule 5m":{"recurrenceRules":[]}},
    /*__n8n__*/ shared: [{"updatedAt":"2026-07-30T23:42:27.037Z","createdAt":"2026-07-30T23:42:27.037Z","role":"workflow:owner","workflowId":"syncLedgerApi01","projectId":"2xKn4WH08LyAOk2y","project":{"updatedAt":"2026-07-30T23:40:17.073Z","createdAt":"2026-07-30T23:33:30.049Z","id":"2xKn4WH08LyAOk2y","name":"Admin User <shlomo@local.dev>","type":"personal","icon":null,"description":null,"creatorId":"544b7ec6-5907-4ee2-a94b-c5676e56835c"}}],
    id: 'syncLedgerApi01',
    name: 'Sync Item API',
    active: true,
    isArchived: false,
    tags: ['role:api', 'app:indox', 'sync-v3', 'role:sync', 'indox', 'indox-app'],
    settings: {
        errorWorkflow: 'errorHandler01',
        executionOrder: 'v1',
        executionTimeout: 300,
        callerPolicy: 'workflowsFromSameOwner',
        binaryMode: 'separate',
    },
})
export class SyncItemApiWorkflow {
    // =====================================================================
    // CONFIGURATION DES NOEUDS
    // =====================================================================

    @node({
        id: 'sia-trig',
        name: 'When Called',
        type: 'n8n-nodes-base.executeWorkflowTrigger',
        version: 1.1,
        position: [0, 0],
    })
    WhenCalled = {
        inputSource: 'passthrough',
    };

    @node({
        id: 'sia-build',
        name: 'Build SQL',
        /*__n8n__*/ notes: "THE OP TABLE. Every op is one statement against <instance>.sync_ledger (+ sync_cursor for the two cursor ops). UPSERT: discovery writes rows (on conflict do nothing — a second listing of the same item is free). TAKE: NEXT+CLAIM in one race-safe statement (for update skip locked) — the old DIFF anti-join is gone because the todo is now a WHERE, not a set difference. RECORD / FAIL: the two delivery outcomes; FAIL carries the retry budget and the equal-jitter backoff, and promotes to needs_review at max_attempts or when terminal. RELEASE: a claim handed back untouched (not a failure). RESET: re-drive from ROWS — flips status back to discovered and clears the cursor; purge:true deletes (test teardown only). REAP: claims that outlived their timeout are failed-with-backoff (or promoted), in one statement. GATE: counts. A request without a valid __instance THROWS: there is no public fallback and never will be — schema selection is the only tenant boundary in this table.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [220, 0],
    })
    BuildSql = {
        jsCode: `const esc=s=>String(s).replace(/'/g,"''");
const bad=v=>v===undefined||v===null||v==='';
const v=x=>bad(x)?'null':"'"+esc(x)+"'";
const j0=$input.first().json||{};
const p=(j0.params&&typeof j0.params==='object')?j0.params:j0;
// indox01 dispatches the reaper by JOB name (its Mark Dispatched node cannot carry an op)
const JOB_OP={ledger_reaper:'REAP'};
const op=String(j0.op||p.op||JOB_OP[String(p.job||j0.job||'')]||'').toUpperCase();
const __i=String(j0.__instance||p.__instance||'');
if(!/^[a-z][a-z0-9_]*$/.test(__i)) throw new Error('syncLedgerApi01: no valid __instance (op '+op+') — no public fallback');
const S='indox_'+__i;
const T=S+'.sync_ledger';
// FULL jitter (random in [0, backoff]) — AWS measured it beating equal jitter on both completion
// time and total work; the pass cadence (Run once per pass) already bounds how soon a retry can run.
const jit=b=>"(random()*("+b+"))";
// per-source policy from the registry: max_attempts and the claim timeout (floor 14 min)
const POL="with pol as (select s.instance || '/' || (e->>'name') as src, coalesce(nullif(e->>'max_attempts','')::int,5) as max_att, greatest(coalesce(nullif(e->'batch'->>'timeout_min','')::int,14),14) as tmin from "+S+".settings s cross join lateral jsonb_array_elements(s.value::jsonb) e where s.key like '%registry')";
const unq=(col)=>"regexp_replace("+col+",'^[^/]*/','')";
let sql=null;
switch(op){
  case 'UPSERT': {
    if(bad(p.source)) throw new Error('UPSERT requires source');
    const items=(Array.isArray(p.items)?p.items:[]).filter(it=>it&&!bad(it.platform_id))
      .map(it=>({platform_id:String(it.platform_id), listing:(it.listing&&typeof it.listing==='object')?it.listing:{}}));
    if(!items.length){ sql="select 0::int as discovered, 0::int as listed"; break; }
    const arr=esc(JSON.stringify(items));
    // A row that already exists keeps its STATUS (discovered / claimed / delivered / failed /
    // needs_review are the item's own history) but a non-delivered one takes the FRESH listing:
    // a legacy row migrated with listing '{}' becomes deliverable the moment discovery sees the
    // file again, and a renamed file carries its new name to the next delivery.
    sql="with src as (select x->>'platform_id' as pid, coalesce(x->'listing','{}'::jsonb) as listing from jsonb_array_elements('"+arr+"'::jsonb) x),"+
      " ins as (insert into "+T+" as l (source, platform_id, status, discovered_at, listing, instance)"+
      " select "+v(p.source)+", pid, 'discovered', now(), listing, "+v(p.instance)+" from src where pid<>''"+
      " on conflict (source, platform_id) do update set listing = excluded.listing"+
      " where l.status <> 'delivered' and l.listing is distinct from excluded.listing"+
      " returning (xmax = 0) as inserted)"+
      " select (select count(*) filter (where inserted) from ins)::int as discovered,"+
      " (select count(*) filter (where not inserted) from ins)::int as refreshed,"+
      " (select count(*) from src)::int as listed";
    break; }
  case 'TAKE': {
    if(bad(p.source)) throw new Error('TAKE requires source');
    const n=Math.max(1,Math.min(500,Math.floor(Number(p.limit))||25));
    // THE AGE BOUND AT TAKE TIME (owner rule + sync best practice on "zombie" items): an item
    // whose own source time (Drive createdTime / mail date, ISO only) has fallen out of the
    // OldDocumentMonthsBack window since it was discovered — a narrowed setting, or a long backlog —
    // is retired to needs_review with a reason, never delivered years late. 'months' rides on the
    // request from Main's one config read; absent = no expiry. The same predicate keeps such rows
    // out of this pass's candidates (a data-modifying CTE is invisible to its siblings).
    const m=Number(p.months)>0?Math.floor(Number(p.months)):0;
    const srcT="coalesce(nullif(l.listing->>'createdTime',''), nullif(l.listing->>'date',''))";
    const isOld=m?"("+srcT+" ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}' and ("+srcT+")::timestamptz < now() - make_interval(months => "+m+"))":"false";
    const EXP=m?" exp as (update "+T+" l set status='needs_review', claimed_at=null, last_error='[expired] older than OldDocumentMonthsBack ("+m+" months) at take time'"+
      " where l.source="+v(p.source)+" and l.status in ('discovered','failed') and "+isOld+" returning 1),":"";
    // THE UNLISTED DEAD-LETTER (measured live 2026-09-02: eight legacy rows with an empty listing
    // sat in 'failed' for four weeks — discovery runs before every take, so a row still empty a
    // day after it was discovered is one the source no longer lists (moved or deleted). Such a row
    // can never be taken (the guard below) and must not wait forever: it retires to needs_review
    // with the reason; a retry re-discovers it if the file ever returns.
    const UNL=" unl as (update "+T+" l set status='needs_review', claimed_at=null, last_error='[unlisted] no listing a day after discovery: the source no longer lists this item (moved or deleted)'"+
      " where l.source="+v(p.source)+" and l.status in ('discovered','failed') and l.listing = '{}'::jsonb"+
      " and l.discovered_at < now() - interval '1 day' returning 1),";
    sql=POL+","+EXP+UNL+" cand as (select l.platform_id from "+T+" l left join pol on pol.src=l.source"+
      " where l.source="+v(p.source)+" and l.status in ('discovered','failed')"+
      " and l.listing <> '{}'::jsonb"+   // nothing to deliver FROM yet (a legacy row awaiting re-discovery)
      " and (l.not_before is null or l.not_before<=now())"+
      " and l.attempts < coalesce(pol.max_att,5)"+
      " and not "+isOld+
      " order by (l.status='failed') desc, l.discovered_at limit "+n+" for update of l skip locked)"+
      " update "+T+" l set status='claimed', claimed_at=now() from cand"+
      " where l.source="+v(p.source)+" and l.platform_id=cand.platform_id"+
      " returning l.platform_id, l.listing, l.attempts, l.discovered_at";
    break; }
  case 'RECORD': {
    for(const k of ['source','platform_id']) if(bad(p[k])) throw new Error('RECORD requires '+k);
    const st=String(p.status||'delivered');
    if(!['delivered','needs_review'].includes(st)) throw new Error('RECORD bad status '+st);
    // THE REASON TRAVELS WITH THE VERDICT (owner 2026-09-02: 186 needs_review rows carried no reason,
    // so "נסה שוב" and the card had nothing to say). A terminal needs_review RECORD carries its
    // reason in last_error; a delivered RECORD clears it.
    const reason=st==='needs_review'?v(String(p.reason||p.error||'needs review').slice(0,500)):'null';
    sql="insert into "+T+" as l (source, platform_id, status, doc_id, content_hash, delivered_at, discovered_at, last_error)"+
      " values ("+v(p.source)+","+v(p.platform_id)+","+v(st)+","+v(p.doc_id)+","+v(p.content_hash)+", now(), now(), "+reason+")"+
      " on conflict (source, platform_id) do update set status="+v(st)+", doc_id=excluded.doc_id, content_hash=excluded.content_hash,"+
      " delivered_at=now(), claimed_at=null, attempts=0, not_before=null, last_error="+reason+
      " where l.status<>'delivered' returning platform_id, status";
    break; }
  case 'FAIL': {
    for(const k of ['source','platform_id']) if(bad(p[k])) throw new Error('FAIL requires '+k);
    const max=Math.max(1,Number(p.max_attempts)||5), base=Math.max(1,Number(p.base_backoff_s)||60), cap=3600;
    const terminal=p.terminal===true;
    const bn="least("+cap+","+base+"*power(2,attempts))";
    sql="update "+T+" set attempts=attempts+1, last_error="+v(String(p.error||'delivery failed').slice(0,500))+", claimed_at=null,"+
      " not_before=now()+"+jit(bn)+"*interval '1 second',"+
      " status=case when "+(terminal?'true':'false')+" or attempts+1>="+max+" then 'needs_review' else 'failed' end"+
      " where source="+v(p.source)+" and platform_id="+v(p.platform_id)+" and status in ('claimed','discovered','failed')"+
      " returning platform_id, attempts, status";
    break; }
  case 'RELEASE': {
    if(bad(p.source)) throw new Error('RELEASE requires source');
    const ids=(p.ids||[]).map(String).filter(Boolean);
    if(!ids.length&&p.all!==true){ sql="select null::text as platform_id where false"; break; }
    const only=ids.length?" and platform_id=any(array["+ids.map(i=>"'"+esc(i)+"'").join(',')+"]::text[])":"";
    sql="update "+T+" set status='discovered', claimed_at=null where source="+v(p.source)+" and status='claimed'"+only+" returning platform_id";
    break; }
  case 'RESET': {
    let pred;
    if(!bad(p.source_like)) pred=" like '"+esc(p.source_like)+"'"; else if(!bad(p.source)) pred=" = '"+esc(p.source)+"'"; else throw new Error('RESET requires source or source_like');
    // statuses: which rows to re-drive. Absent = every non-discovered row (a full re-drive, the CLI's
    // meaning); the board's "retry failed" sends ['failed','needs_review'] so delivered work is never
    // re-delivered by a button.
    const ST=(Array.isArray(p.statuses)?p.statuses:[]).map(String).filter(s=>['claimed','delivered','failed','needs_review'].includes(s));
    // the status filter belongs to the LEDGER statement only (sync_cursor has no status), and a
    // scoped retry keeps the cursor: only a FULL re-drive re-walks the source from the bottom.
    const stPred=ST.length?" and status = any(array["+ST.map(s=>"'"+s+"'").join(',')+"]::text[])":"";
    const cursorSql=ST.length?"select 1 where false":"delete from "+S+".sync_cursor where "+unq('source')+pred+" returning 1";
    if(p.purge===true){
      sql="with a as (delete from "+T+" where "+unq('source')+pred+stPred+" returning 1),"+
        " c as ("+cursorSql+")"+
        " select (select count(*) from a)::int as purged, (select count(*) from c)::int as cursors_deleted, true as purge";
    } else {
      // EVERY matching row goes back to discovered (owner 2026-09-02: a retry that silently kept
      // 186 rows red was worse than none). A row with no listing is reported as no_listing: the
      // pass that follows re-lists it if the source still has it (UPSERT refreshes the listing and
      // TAKE delivers), and TAKE retires it with the [unlisted] reason if the source does not.
      sql="with a as (update "+T+" set status='discovered', attempts=0, not_before=null, claimed_at=null, last_error=null"+
        " where "+unq('source')+pred+stPred+" and status<>'discovered' returning (listing = '{}'::jsonb) as no_listing),"+
        " c as ("+cursorSql+")"+
        " select (select count(*) from a)::int as reset, (select count(*) filter (where no_listing) from a)::int as no_listing,"+
        " (select count(*) from c)::int as cursors_deleted, false as purge";
    }
    break; }
  case 'REAP': {
    const floorMin=Math.max(1,Number(p.timeout_min)||14);
    const bn="least(3600,60*power(2,l.attempts))";
    sql=POL+", stuck as (select l2.source, l2.platform_id, coalesce(p2.max_att,5) as max_att from "+T+" l2 left join pol p2 on p2.src=l2.source"+
      " where l2.status='claimed' and l2.claimed_at is not null and l2.claimed_at < now() - make_interval(mins => greatest(coalesce(p2.tmin,"+floorMin+"),"+floorMin+"))),"+
      " rel as (update "+T+" l set attempts=l.attempts+1, claimed_at=null, last_error='reaper: claim outlived timeout',"+
      " not_before=now()+"+jit(bn)+"*interval '1 second',"+
      " status=case when l.attempts+1>=k.max_att then 'needs_review' else 'failed' end"+
      " from stuck k where l.source=k.source and l.platform_id=k.platform_id and l.status='claimed' returning l.status)"+
      " select count(*) filter (where status='failed')::int as released, count(*) filter (where status='needs_review')::int as promoted_needs_review from rel";
    break; }
  case 'GATE': {
    if(bad(p.source)) throw new Error('GATE requires source');
    sql="select count(*) filter (where status='discovered')::int as discovered, count(*) filter (where status='claimed')::int as claimed,"+
      " count(*) filter (where status='delivered')::int as delivered, count(*) filter (where status='failed')::int as failed,"+
      " count(*) filter (where status='needs_review')::int as needs_review, count(*)::int as total"+
      " from "+T+" where source="+v(p.source);
    break; }
  case 'CURSOR_GET': {
    if(bad(p.source)) throw new Error('CURSOR_GET requires source');
    sql="select source, mode, walk_token, steady_cursor from "+S+".sync_cursor where source="+v(p.source);
    break; }
  case 'CURSOR_SET': {
    if(bad(p.source)) throw new Error('CURSOR_SET requires source');
    sql="insert into "+S+".sync_cursor (source, mode, walk_token, steady_cursor, updated_at)"+
      " values ("+v(p.source)+","+v(p.mode||'walk')+","+v(p.walk_token)+","+v(p.steady_cursor)+", now())"+
      " on conflict (source) do update set mode=excluded.mode, walk_token=excluded.walk_token, steady_cursor=excluded.steady_cursor, updated_at=now()"+
      " returning source, mode, walk_token, steady_cursor";
    break; }
  default: throw new Error('syncLedgerApi01: unknown op '+JSON.stringify(op));
}
return [{json:{sql, _op:op, _source:p.source||p.source_like||null, _instance:__i}}];`,
    };

    @node({
        id: 'sia-pg',
        name: 'PG Execute',
        /*__n8n__*/ notes: "alwaysOutputData: a zero-row result (an empty TAKE, a RELEASE of nothing) must still emit an item, or the caller's chain stops dead and reads as the API dying.",
        type: 'n8n-nodes-base.postgres',
        version: 2.5,
        position: [440, 0],
        credentials: { postgres: { id: 'yY8FYvp6Kz86pt2t', name: 'INDOX Supabase Postgres' } },
        alwaysOutputData: true,
        retryOnFail: true,
        maxTries: 3,
        waitBetweenTries: 1000,
    })
    PgExecute = {
        operation: 'executeQuery',
        query: '{{ $json.sql }}',
        options: {},
    };

    @node({
        id: 'sia-reply',
        name: 'Reply',
        /*__n8n__*/ notes: "Rows pass through with _op and the execution id (one click from an answer to the run that produced it). Zero rows -> one {success:true, rows:0} envelope; callers that iterate rows filter on platform_id so the envelope is never mistaken for work.",
        type: 'n8n-nodes-base.code',
        version: 2,
        position: [660, 0],
    })
    Reply = {
        jsCode: `const meta=$('Build SQL').first().json||{};
const rows=$input.all().map(i=>i&&i.json).filter(r=>r&&Object.keys(r).length);
let exec=null; try{exec=$execution.id;}catch(e){}
try{ $execution.customData.set('outline', String(meta._op||'op')+'_x'+rows.length); $execution.customData.set('exection_type','sync_item_api'); $execution.customData.set('instance', String(meta._instance||'')); }catch(e){}
if(!rows.length) return [{json:{success:true, op:meta._op, rows:0, _execution:exec}}];
return rows.map(r=>({json:{...r, _op:meta._op, _execution:exec}}));`,
    };

    // =====================================================================
    // ROUTAGE ET CONNEXIONS
    // =====================================================================

    @links()
    defineRouting() {
        this.WhenCalled.out(0).to(this.BuildSql.in(0));
        this.BuildSql.out(0).to(this.PgExecute.in(0));
        this.PgExecute.out(0).to(this.Reply.in(0));
    }
}
