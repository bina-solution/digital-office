-- Per-action router batch caps (owner design 2026-08-21).
--
-- `Group By ACTION` splits each action's lines into groups of at most
--   indox.statemachine.action_router.<action>.max   (per-action override)
--   indox.statemachine.action_router.max            (default)
-- so no single router call can exceed the router's 3600 s executionTimeout.
--
-- SIZED FROM A REGRESSION OF DISPATCH DURATION AGAINST WIDTH, not from p95 seconds-per-line.
-- The naive per-line figure is dominated by fixed overhead at narrow widths and is wildly wrong:
-- it made update_status_garbage look like 6.6 s/line when its raw dispatches show width 23 in 2 s
-- and width 12 in anything from 2 s to 1580 s -- i.e. duration is uncorrelated with width there,
-- and the variance is queue contention. Every update_status_* action is a batched upsert that
-- collapses to ONE call, so they stay at the default.
--
-- Fitted marginal cost (reap-spike excluded), and time at 2,000 lines:
--   extract_base_doc      149s + 42.455s/line  ->  85,059s  (23.6 h)   <- the only real offender
--   find_link               6s +  1.831s/line  ->   3,668s  (61 min)   <- marginal, trim it
--   apply_gmail_labels     59s +  1.081s/line  ->   2,221s  (37 min)   ok
--   restart_base           -8s +  0.492s/line  ->     975s  (16 min)   ok
--   update_status_old_doc -16s +  0.249s/line  ->     482s  ( 8 min)   ok, already ran 2,638 wide
--
-- extract_base_doc corroborates independently: exec 3455459 extracted 51 documents before the
-- 3600 s wall, i.e. ~70 s/document. Its max observed width is 71 against a computed cap of 74 --
-- it has been running at its limit all along, and the batch that died was 142, almost exactly 2x.

BEGIN;

INSERT INTO public.settings (instance, key, value, updated_at) VALUES
    ('incoming-documents-main', 'indox.statemachine.action_router.max',                      '2000', now()),
    -- 42.455 s/line: (3300-149)/42.455 = 74. Held at 60 for margin, since the fit is
    -- extrapolated from a max observed width of 71.
    ('incoming-documents-main', 'indox.statemachine.action_router.extract_base_doc.max',       '60', now()),
    -- 1.831 s/line: 2,000 lines is 61 min, just over the wall. 1,500 lands at ~46 min.
    ('incoming-documents-main', 'indox.statemachine.action_router.find_link.max',            '1500', now()),
    -- link_documents_r1 is the BS-link action added 2026-08-21. It did not exist when the table
    -- above was measured, so it fell through to the 2000 default -- and was caught LIVE during the
    -- first wet full-table drain: exec 3460585 dispatched it 434 wide, all 434 open. Fitted from
    -- its own closed dispatches: 11s + 12.16s/line, i.e. 5,290s at 434 wide against a 3600 s
    -- executionTimeout. (3300-11)/12.16 = 270; held at 250.
    -- LESSON: a NEW action defaults to 2000 and is therefore unbounded until someone measures it.
    -- Any action added later needs its own row, or the default needs to be conservative instead.
    ('incoming-documents-main', 'indox.statemachine.action_router.link_documents_r1.max', '250', now())
ON CONFLICT (instance, key) DO NOTHING;

COMMIT;

SELECT key, value FROM public.settings
WHERE instance = 'incoming-documents-main'
  AND key LIKE 'indox.statemachine.action_router.%'
ORDER BY key;
