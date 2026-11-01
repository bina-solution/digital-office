-- loadtest-50k-cleanup.sql
-- Removes every trace of the 50,000-row INDOX scale-test fixture.
-- Marker used by the fixture: "SYNC_NAME" = 'loadtest-50k' AND "ID" LIKE 'lt50k_%'
--                              sync_ledger/sync_pipe_state/sync_attempt/sync_cursor "source" = 'loadtest-50k'
--
-- Usage:
--   docker cp loadtest-50k-cleanup.sql supabase-db-shlomo-laptop:/tmp/loadtest-50k-cleanup.sql
--   docker exec supabase-db-shlomo-laptop psql -U postgres -d postgres -f /tmp/loadtest-50k-cleanup.sql
--
-- Does NOT touch any row belonging to a real pipe (gmail-doc, drive-gdoc, mail-private, etc.)
-- because every fake row/ledger entry carries the 'loadtest-50k' marker exclusively.

BEGIN;

DELETE FROM public.sync_ledger     WHERE source = 'loadtest-50k';
DELETE FROM public.sync_attempt    WHERE source = 'loadtest-50k';
DELETE FROM public.sync_cursor     WHERE source = 'loadtest-50k';
DELETE FROM public.sync_pipe_state WHERE source = 'loadtest-50k';

DELETE FROM public.incoming_documents
 WHERE "SYNC_NAME" = 'loadtest-50k'
    OR "CONNECTION" = 'loadtest-50k'
    OR "ID" LIKE 'lt50k_%';

COMMIT;

-- Verification (run after commit):
--   SELECT count(*) FROM public.incoming_documents WHERE "ID" LIKE 'lt50k_%' OR "SYNC_NAME" = 'loadtest-50k';  -- expect 0
--   SELECT count(*) FROM public.sync_ledger WHERE source = 'loadtest-50k';  -- expect 0
