-- Drain pool settings (phase 1 of apps/indox/issues/drain-pool-consolidation-plan.md)
--
-- Three settings that bound the drain, replacing the single `indoxScalingFactor`:
--   drain.parallel  P — how many driver lanes may be in flight at once
--   driver.batch    B — how many documents one driver execution ever receives
--   driver.max          circuit-breaker at the driver entry; must never fire normally
--
-- `indoxScalingFactor` is deliberately LEFT IN PLACE: the current drainer still reads it,
-- and it is only removed when the drainer is rewritten onto the pool (phase 3).
--
-- Why B matters: n8n retains every node's output for the whole execution, so heap grows
-- with lane WIDTH. Measured 2026-08-21 — a 9,790-document lane serialises to 266 MB
-- (~9.5 retained copies of the row set) and costs ~1,060 MB of heap; two on one worker hit
-- V8's 2,600 MB ceiling and aborted the process. At B=2000 one lane is ~220 MB.

BEGIN;

INSERT INTO public.settings (instance, key, value, updated_at) VALUES
    ('incoming-documents-main', 'indox.statemachine.drain.parallel', '4',    now()),
    ('incoming-documents-main', 'indox.statemachine.driver.batch',   '2000', now()),
    ('incoming-documents-main', 'indox.statemachine.driver.max',     '2000', now())
ON CONFLICT (instance, key) DO NOTHING;

COMMIT;

-- Verification: all three present, and the drainer's one-query read resolves with defaults
-- even if a row were missing (a missing row must never be able to dark-stop a lane).
SELECT
    coalesce((SELECT value FROM public.settings
              WHERE instance = 'incoming-documents-main' AND key = 'indoxDrainOn'), 'true')
        AS drain_on,
    coalesce((SELECT value FROM public.settings
              WHERE instance = 'incoming-documents-main' AND key = 'indox.statemachine.drain.parallel'), '4')
        AS parallel,
    coalesce((SELECT value FROM public.settings
              WHERE instance = 'incoming-documents-main' AND key = 'indox.statemachine.driver.batch'), '2000')
        AS batch,
    coalesce((SELECT value FROM public.settings
              WHERE instance = 'incoming-documents-main' AND key = 'indox.statemachine.driver.max'), '2000')
        AS max_lane;
