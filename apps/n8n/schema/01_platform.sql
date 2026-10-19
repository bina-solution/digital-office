-- Platform schema (layer 2) — what the PLATFORM owns, and nothing else.
--
-- Everything an app owns now lives with that app: apps/indox/blueprint/fixtures/schema.sql and
-- apps/drive/blueprint/fixtures/schema.sql. What is left here is genuinely platform-wide: the shared
-- log stream, and the updated_at trigger function that any app's table can attach to.
--
-- APPLY ORDER: this -> every apps/*/blueprint/fixtures/schema.sql. There is no third step.
--
-- There used to be one — `99_grants.sql`, the second orphan of commit 0f69eb7e's three-way split —
-- and it is DELETED rather than re-homed. It held blanket PostgREST grants ("all tables in schema
-- public" to anon/authenticated/service_role) plus `notify pgrst, 'reload schema'`. Two reasons, and
-- the first is the one that survives a change to the second:
--
--   1. WRONG MECHANISM. A one-shot `grant on all tables` covers the tables that exist at the instant
--      it runs and nothing created afterwards. That is precisely the property the grants needed, and
--      it is why the file kept failing to find a home: no position in the hook order is "after every
--      app, forever" — the next app to be installed lands after it either way. The mechanism that
--      actually solves it is ALTER DEFAULT PRIVILEGES, and the supabase image already installs it.
--
--   2. PROVABLY INERT TODAY. Measured against the live stack (2026-07-30, supabase-db):
--        * `pg_default_acl` for schema `public`, object type `table`, carries
--          `anon=arwdDxt / authenticated=arwdDxt / service_role=arwdDxt` for BOTH owner roles that
--          create tables here (`postgres` and `supabase_admin`). Every grant the file issued was a
--          strict SUBSET of that.
--        * Applying the file wholesale changed ZERO relacl entries across all 25 relations in
--          `public` and ZERO rows of `pg_default_acl` (before/after diff, empty).
--        * A table created afterwards already carries all three roles with full DML — no grant step.
--        * `notify pgrst` is redundant: the `pgrst_ddl_watch` / `pgrst_drop_watch` event triggers
--          fire the same NOTIFY on every DDL command.
--
-- The risk that kept it alive was "supabase changes its defaults and this silently becomes
-- load-bearing". An unapplied file protects against nothing, so that risk is answered where it can
-- actually be observed: `apps/n8n/hooks/push` now ASSERTS the default privileges are in
-- place and fails the push loudly if they are not. A checked assumption, not a dormant file.

create table if not exists public.app_logs (
  "id" bigint generated always as identity primary key,
  "stream" TEXT not null, "payload" JSONB not null, "ts" timestamptz default now());

create index if not exists app_logs_stream_ts on public.app_logs (stream, ts desc);


-- auto-touch updated_at
-- single-quoted body (NOT dollar-quoted): the n8n postgres driver (pg-promise) treats the
-- dollar sign as its own variable syntax, and this file is applied by the Test Fixtures workflow
create or replace function public.touch_updated_at() returns trigger as
'begin new."updated_at" = now(); return new; end;' language plpgsql;

-- run_sql — the SQL RPC the incoming-documents supabase transport requires for repo provisioning
-- (POST /rest/v1/rpc/run_sql, single text param `query`; see HttpxSupabaseTransport._exec_sql).
-- Row-returning statements come back as a jsonb array; DDL/utility statements (which cannot be
-- wrapped in a subquery — that raises syntax_error at plan time, before anything runs) fall back
-- to a bare EXECUTE and return []. SECURITY DEFINER + service_role-only: PostgREST exposes every
-- function in `public`, so without the revoke the anon key could run arbitrary SQL through it.
-- Single-quoted body for the same pg-promise reason as touch_updated_at above.
create or replace function public.run_sql(query text) returns jsonb as
'declare result jsonb;
begin
  begin
    execute ''select coalesce(jsonb_agg(t), to_jsonb(array[]::int[])) from ('' || query || '') as t''
      into result;
    return result;
  exception when syntax_error or feature_not_supported then
    execute query;
    return to_jsonb(array[]::int[]);
  end;
end' language plpgsql security definer set search_path = public;

revoke all on function public.run_sql(text) from public;
grant execute on function public.run_sql(text) to service_role;
