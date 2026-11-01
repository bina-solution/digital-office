#!/bin/bash
# What would flipping activePrioritySync actually dispatch? Measured, not guessed.
# Gate (indoxV2Actions{GDoc,Ship}01 'Decide'):
#   _priorityActive && (!PRIORITY_SYNC_COMPLETED || _sigChanged)
#   _sigChanged = stored signature present AND computed signature present AND they differ
DK="docker -H unix:///run/bbox-docker.sock"
$DK exec -i supabase-db-shlomo-laptop psql -U postgres -tAf - <<'SQL'
SET statement_timeout='180s';
SELECT '  COMPLETED documents                       = '||count(*)
FROM public.incoming_documents WHERE "STATUS"='COMPLETED';

SELECT '  ... PRIORITY_SYNC_COMPLETED true          = '||count(*)
FROM public.incoming_documents
WHERE "STATUS"='COMPLETED' AND lower(coalesce("PRIORITY_SYNC_COMPLETED",'')) = 'true';

SELECT '  ... NOT yet synced -> would SEND          = '||count(*)
FROM public.incoming_documents
WHERE "STATUS"='COMPLETED' AND lower(coalesce("PRIORITY_SYNC_COMPLETED",'')) <> 'true';

SELECT '  ... synced AND carrying a stored signature = '||count(*)
FROM public.incoming_documents
WHERE "STATUS"='COMPLETED' AND lower(coalesce("PRIORITY_SYNC_COMPLETED",'')) = 'true'
  AND coalesce(btrim("PRIORITY_SYNC_SIGNATURE"),'') <> '';

SELECT '  ... of those, signature CHANGED -> RE-SEND = '||count(*)||'   <- the blast radius of my signature fix'
FROM public.incoming_documents d
WHERE d."STATUS"='COMPLETED' AND lower(coalesce(d."PRIORITY_SYNC_COMPLETED",'')) = 'true'
  AND coalesce(btrim(d."PRIORITY_SYNC_SIGNATURE"),'') <> ''
  AND btrim(d."PRIORITY_SYNC_SIGNATURE") <> public.indox_priority_signature(d.*);

SELECT '  ... synced with NO stored signature -> SILENT (fail-safe) = '||count(*)
FROM public.incoming_documents
WHERE "STATUS"='COMPLETED' AND lower(coalesce("PRIORITY_SYNC_COMPLETED",'')) = 'true'
  AND coalesce(btrim("PRIORITY_SYNC_SIGNATURE"),'') = '';

SELECT '  rows already in the LOCAL mirror table     = '||count(*) FROM public.indox_priority_local;
SQL
