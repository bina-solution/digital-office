-- e2e-loadtest-cleanup.sql
-- Removes every DB trace of the E2E load-test document corpus injected via the real pipeline
-- (LOCAL MAIL engine -> "e2e-mail", LOCAL DRIVE engine -> "e2e-drive-gdoc" / "e2e-drive-bs").
--
-- Marker used by the fixture:
--   "SYNC_NAME" IN ('e2e-mail','e2e-drive-gdoc','e2e-drive-bs')  -- the pipe every injected row is stamped with
--   "ID" carrying 'E2ELT-' (doc_id we set) or filenames prefixed 'E2ELT_'
--   sync_ledger/sync_attempt/sync_cursor/sync_pipe_state "source" matching the same three names,
--     PLAIN or NAMESPACED as "<instance>/<pipe>" (sync-v3 multi-tenancy — schema.sql)
--
-- Does NOT touch: the pre-existing gmail-doc/gmail-bs/gmail-link/drive-gdoc/drive-bs/mail-private
-- pipes, any row without one of the three e2e-lt SYNC_NAME values, or anything client-real.
--
-- Usage:
--   docker cp e2e-loadtest-cleanup.sql supabase-db-shlomo-laptop:/tmp/e2e-loadtest-cleanup.sql
--   docker exec supabase-db-shlomo-laptop psql -U postgres -d postgres -f /tmp/e2e-loadtest-cleanup.sql
--
-- This is the DB-side half only. Also run (in order, BEFORE this script, so the ledger rows this
-- script deletes still line up with what's being removed source-side):
--   1. scripts/ops/e2e-loadtest/teardown.py   (removes the 3 sync_registry entries, restores the
--      pre-provision registry snapshot, deletes the local drive folders/files, deletes the injected
--      local-mailbox messages)
--   2. this script
--
-- Verification (run after commit):
--   SELECT count(*) FROM public.incoming_documents
--    WHERE "SYNC_NAME" IN ('e2e-mail','e2e-drive-gdoc','e2e-drive-bs') OR "ID" LIKE '%E2ELT-%';  -- expect 0
--   SELECT count(*) FROM public.sync_ledger WHERE source LIKE '%e2e-mail'
--      OR source LIKE '%e2e-drive-gdoc' OR source LIKE '%e2e-drive-bs';                            -- expect 0

BEGIN;

DELETE FROM public.sync_ledger
 WHERE source IN ('e2e-mail','e2e-drive-gdoc','e2e-drive-bs')
    OR source LIKE '%/e2e-mail' OR source LIKE '%/e2e-drive-gdoc' OR source LIKE '%/e2e-drive-bs';

DELETE FROM public.sync_attempt
 WHERE source IN ('e2e-mail','e2e-drive-gdoc','e2e-drive-bs')
    OR source LIKE '%/e2e-mail' OR source LIKE '%/e2e-drive-gdoc' OR source LIKE '%/e2e-drive-bs';

DELETE FROM public.sync_cursor
 WHERE source IN ('e2e-mail','e2e-drive-gdoc','e2e-drive-bs')
    OR source LIKE '%/e2e-mail' OR source LIKE '%/e2e-drive-gdoc' OR source LIKE '%/e2e-drive-bs';

DELETE FROM public.sync_pipe_state
 WHERE source IN ('e2e-mail','e2e-drive-gdoc','e2e-drive-bs')
    OR source LIKE '%/e2e-mail' OR source LIKE '%/e2e-drive-gdoc' OR source LIKE '%/e2e-drive-bs';

DELETE FROM public.incoming_documents
 WHERE "SYNC_NAME" IN ('e2e-mail','e2e-drive-gdoc','e2e-drive-bs')
    OR "ID" LIKE '%E2ELT-%'
    OR "NAME" LIKE 'E2ELT_%'
    OR "COMPANY_DOC_ID" LIKE 'E2ELT-%';

-- companies seeded/looked-up for the run are REAL rows from public.companies (not created by this
-- fixture) and are left untouched deliberately — deleting them could break attribution for the
-- real historical documents that already reference those company ids.

COMMIT;
