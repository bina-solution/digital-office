-- 2026-08-31_drop_public_compat_views.sql — THE CUTOVER'S LAST STEP. DESTRUCTIVE, RUN ONCE.
--
-- Drops the 20 public compatibility views the tenancy migration created by hand: 17 table-compat
-- views over instance one plus the 3 shared views that are now TENANT-LOCAL (each indox_<id>
-- schema owns its own copy via blueprint/fixtures/schema.sql; verified identical to the hand-made
-- ones before the fixture took ownership).
--
-- PRECONDITIONS — all had to be true before this file was written, and stay true before running:
--   * zero production workflows address public.<tenant table> (the 2026-08-31 conversion waves;
--     the throwing-IIFE census is empty),
--   * the BFF resolves every tenant read/write per request (?instance= / repo_for / run_sql),
--   * the suites run against indox_test (test-registry-scope-lint G64 R7: PASS),
--   * onboarding/seeding/ops tooling is per-tenant (apply-schema is the one door).
--
-- AFTER this runs, anything still reading public.<tenant table> fails with `relation does not
-- exist` — which is the point: the dual state ends, loudly. RE-CREATION IS FORBIDDEN: a view
-- recreated here silently re-opens the cross-tenant read this migration closed.
--
-- Apply (operator, deliberately not automated):
--   docker exec -i supabase-db-<DEPLOYMENT_NAME> psql -U postgres -d postgres \
--     -v ON_ERROR_STOP=1 < scripts/ops/migrations/2026-08-31_drop_public_compat_views.sql
--
-- Each DROP names VIEW explicitly: if any of these is unexpectedly a TABLE on some estate,
-- the statement fails rather than destroying data. RESTRICT (the default) refuses if anything
-- still depends on the view — a dependent object is a missed conversion, not a reason to CASCADE.

begin;

-- The four hash/signature helpers carry VIEW-TYPED overloads — signatures taking
-- public.incoming_documents (the view's rowtype) as a composite parameter, created by
-- apply-schema's "view-typed overload ready" step so callers through the compat view kept
-- working. They depend on the view, so RESTRICT would refuse the drop below; and once the view
-- is gone they are meaningless. The TENANT-typed overloads (indox_<id>.incoming_documents)
-- live per schema and are untouched.
drop function if exists public.indox_base_selection_hash(public.incoming_documents);
drop function if exists public.indox_line_hash(public.incoming_documents);
drop function if exists public.indox_priority_signature(public.incoming_documents);
drop function if exists public.indox_selection_hash(public.incoming_documents);

drop view if exists public.bs_extracted_lines;
drop view if exists public.companies;
drop view if exists public.company_registry;
drop view if exists public.extraction_queries;
drop view if exists public.incoming_documents;
drop view if exists public.incoming_documents_archive;
drop view if exists public.indox_action_execution_log;
drop view if exists public.indox_dashboard_stats;
drop view if exists public.indox_priority_local;
drop view if exists public.indox_sync_stats;
drop view if exists public.merge_audit;
drop view if exists public.settings;
drop view if exists public.settings_history;
drop view if exists public.sync_attempt;
drop view if exists public.sync_cursor;
drop view if exists public.sync_ledger;
drop view if exists public.sync_pipe_state;
drop view if exists public.tag_rules;
drop view if exists public.trusted_suppliers;
drop view if exists public.v_indox_priority_local_dupes;

commit;
