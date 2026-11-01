-- 2026-08-21 — SOURCE_LIST backfill: give every row a `self` provenance element.
--
-- WHY
-- ---
-- The flat SOURCE_* columns describe exactly ONE source. That stops being true the moment two
-- rows are merged: the loser's Drive file still exists and still needs filing, and after a merge
-- nothing on the surviving row can name it. SOURCE_LIST is the collection those columns are a
-- mirror of. Before this migration it was populated on 1,025 of 39,160 rows.
--
-- SCOPE: rows whose SOURCE_LIST is NULL/not-an-array/empty. The 1,025 rows that already carry an
-- array are LEFT ALONE — their elements were written by the double-group/merge tooling with a
-- different field vocabulary (`source_id` there is the FOLDER id on drive elements, while the
-- row's own SOURCE_ID is the FILE id), and reverse-engineering that writer's semantics inside a
-- migration that is otherwise a clean derivation is how you get a silent wrong answer. They get
-- their own explicit pass.
--
-- HOW THE PIPE IS RESOLVED — FOUR RULES, STRONGEST FIRST
--   1. drive folder id from SOURCE_LINK, against every pair folder AND `legacy_folders`
--   2. SYNC_NAME against `legacy_sync_names` (retired pipe names)
--   3. SYNC_NAME against live pipe names
--   4. the v1-mail rule below
-- Measured 2026-08-21: SYNC_NAME alone resolves 1,855 of 25,795 rows (7.2%) because pruned
-- entries and the v1 processors wrote names that no longer exist; the folder id resolves 20,441
-- of 23,518 drive rows (87%). Hence folder first, name second, and NULL rather than a guess when
-- none of the four apply — a null `required_feedback_type` means the state machine simply never
-- decides feedback for that source, which is the safe direction.
--
-- THE v1-MAIL RULE (rule 4), and why it is a one-time migration rule rather than config.
-- 2,154 rows carry SOURCE_TYPE='GMAIL' with a MAILBOX ADDRESS in SOURCE_ID, no SYNC_NAME, and no
-- message id — written by the v1 downloaders, which are dead, so no new such rows can appear.
-- Their message id is NOT lost: every one of the 2,154 carries it in SOURCE_LINK
-- ('https://mail.google.com/mail/u/0/#inbox/<msgid>'), recovered below. Ownership is settled by
-- document class, which is exactly what separates the three live mail pipes: BALANCE_SHEET ->
-- gmail-bs (SYNCED_BS/FAILED_BS), everything else -> gmail-doc (SYNCED_DOC/FAILED_DOC). The
-- distribution is 1,692 INVOICE / 380 SHIPMENT / 67 BALANCE_SHEET / 13 UNKNOWN / 2 ORDER, and
-- 582 of them share a message id with a mail-private row, confirming the mailbox.
--
-- updated_at IS DELIBERATELY NOT BUMPED.
-- `trg_incdoc_touch` stamps now() on every UPDATE, and `updated_at` is the pipeline's progress
-- signal ("progress is updated_at, NOT the STATUS histogram"). 38k backfilled rows would read as
-- a full-table drain in every monitor for the next cycle. `session_replication_role = replica`
-- suppresses user triggers FOR THIS SESSION ONLY — no DDL, no ACCESS EXCLUSIVE lock, and it
-- reverts when the session ends. The other two triggers are safe to skip: the warehouse mirror
-- is a no-op unless a FROM_* column changes (none do here) and doc_date_norm recomputes a value
-- that is already correct because DOC_DATE is untouched.
--
-- Idempotent: re-running is a no-op, since every row it touches stops matching the WHERE clause.

\set ON_ERROR_STOP on

SET session_replication_role = replica;
SET statement_timeout = '900s';

CREATE TEMP TABLE _reg AS
SELECT jsonb_array_elements(value::jsonb) AS e FROM public.settings WHERE key = 'sync_registry';

-- folder id -> pipe. A folder can be one pipe's `to_sync` and another's `synced`; the to_sync
-- role wins because that is where the pipe SCANS, i.e. whose document it is. `legacy_folders`
-- ranks last: it only answers for folders no live pair claims.
CREATE TEMP TABLE _fmap AS
SELECT fid, (array_agg(pipe ORDER BY prio))[1] AS pipe
FROM (
  SELECT e->>'name' AS pipe, p->>'to_sync' AS fid, 1 AS prio
    FROM _reg, LATERAL jsonb_array_elements(COALESCE(e->'pairs', '[]'::jsonb)) p
   WHERE p->>'to_sync' IS NOT NULL
  UNION ALL
  SELECT e->>'name', p->>'synced', 2
    FROM _reg, LATERAL jsonb_array_elements(COALESCE(e->'pairs', '[]'::jsonb)) p
   WHERE p->>'synced' IS NOT NULL
  UNION ALL
  SELECT e->>'name', p->>'failed', 3
    FROM _reg, LATERAL jsonb_array_elements(COALESCE(e->'pairs', '[]'::jsonb)) p
   WHERE p->>'failed' IS NOT NULL
  UNION ALL
  SELECT e->>'name', jsonb_array_elements_text(e->'legacy_folders'), 4
    FROM _reg WHERE jsonb_typeof(e->'legacy_folders') = 'array'
) x
GROUP BY fid;

-- retired pipe name -> the pipe that inherited its documents
CREATE TEMP TABLE _nmap AS
SELECT jsonb_array_elements_text(e->'legacy_sync_names') AS old_name, e->>'name' AS pipe
FROM _reg WHERE jsonb_typeof(e->'legacy_sync_names') = 'array';

CREATE TEMP TABLE _mode AS
SELECT e->>'name' AS pipe,
       COALESCE(e->'feedback'->>'mode', 'off')                 AS mode,
       COALESCE((e->'feedback'->>'on_success')::boolean, false) AS ok_s,
       COALESCE((e->'feedback'->>'on_failure')::boolean, false) AS ok_f,
       -- the pipe's own identity, used when the ROW carries none: 573 rows resolve a pipe but
       -- have a null SYNC_CONNECTION, and an op without a connection is refused by mailapi.
       COALESCE(e->>'connection', e->>'connection_id')          AS conn
FROM _reg WHERE e->>'name' IS NOT NULL;

CREATE INDEX ON _fmap (fid);
CREATE INDEX ON _nmap (old_name);
CREATE INDEX ON _mode (pipe);

CREATE TEMP VIEW _elem AS
SELECT d."ID",
       jsonb_build_array(jsonb_build_object(
         'origin',             'self',
         'doc_row_id',         d."ID",
         'first_seen',         to_char(COALESCE(d.created_at, now()) AT TIME ZONE 'UTC',
                                       'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
         'dup_cause',          NULL,
         'source_kind',        k.kind,
         'sync_registry_name', pipe.name,
         'source_folder_id',   k.folder_id,
         'file_id',            k.file_id,
         'message_id',         k.message_id,
         'mailbox',            k.mailbox,
         'link',               d."LINK",
         'hash',               d."HASH",
         'link_connection',    d."LINK_CONNECTION",
         'sync_connection',    COALESCE(NULLIF(d."SYNC_CONNECTION", ''), m.conn),
         -- feedback only when the pipe resolved AND its mode matches the source kind. A drive
         -- pipe cannot tag mail and a mail pipe cannot move files; a mismatch is a resolution
         -- error, so it is recorded as "no feedback" rather than acted on. A mail source with no
         -- recoverable message id is withheld for the same reason: there is nothing to tag.
         'required_feedback_type',
             CASE WHEN m.mode = 'drive_move' AND k.kind = 'drive' AND k.file_id    IS NOT NULL
                  THEN 'drive_move'
                  WHEN m.mode = 'mail_tag'   AND k.kind = 'mail'  AND k.message_id IS NOT NULL
                  THEN 'mail_tag'
                  ELSE NULL END,
         'feedback_on_success',
             CASE WHEN (m.mode = 'drive_move' AND k.kind = 'drive' AND k.file_id    IS NOT NULL)
                    OR (m.mode = 'mail_tag'   AND k.kind = 'mail'  AND k.message_id IS NOT NULL)
                  THEN m.ok_s ELSE false END,
         'feedback_on_failure',
             CASE WHEN (m.mode = 'drive_move' AND k.kind = 'drive' AND k.file_id    IS NOT NULL)
                    OR (m.mode = 'mail_tag'   AND k.kind = 'mail'  AND k.message_id IS NOT NULL)
                  THEN m.ok_f ELSE false END,
         'sync_feedback_completed', false,
         'sync_feedback_outcome',   NULL,
         'sync_feedback_dest',      NULL,
         -- Why this source can never be fed back, stated once at backfill time rather than
         -- rediscovered on every sweep. NULL when there is nothing wrong.
         'sync_feedback_error',
             CASE WHEN k.kind = 'other' THEN 'source kind ' || COALESCE(d."SOURCE_TYPE", '<null>')
                                             || ' has no source artifact to report back to'
                  WHEN pipe.name IS NULL THEN 'no sync_registry pipe owns this row'
                                             || ' (folder=' || COALESCE(k.folder_id, '-')
                                             || ', SYNC_NAME=' || COALESCE(d."SYNC_NAME", '-') || ')'
                  WHEN m.mode = 'off' THEN 'pipe ' || pipe.name || ' has feedback mode off'
                  WHEN k.kind = 'drive' AND k.file_id IS NULL
                       THEN 'no Drive file id in LINK'
                  WHEN k.kind = 'mail' AND k.message_id IS NULL
                       THEN 'no message id on the row and none recoverable from SOURCE_LINK'
                            || CASE WHEN k.mailbox IS NOT NULL
                                    THEN ' (SOURCE_ID is the mailbox address ' || k.mailbox || ')'
                                    ELSE '' END
                  ELSE NULL END,
         'sync_feedback_at', NULL
       )) AS src_list,
       k.kind, pipe.name AS pipe_name, m.mode
FROM public.incoming_documents d
CROSS JOIN LATERAL (
  SELECT CASE WHEN d."SOURCE_TYPE" IN ('GOOGLE_DRIVE_FOLDER', 'GOOGLE_DRIVE_FILE')  THEN 'drive'
              -- WHATSAPP arrives as a file the bot drops in a Drive folder: LINK is a Drive URL
              -- on all 43 rows and LINK_CONNECTION is set, so it is a drive source that happens
              -- to name its channel in SOURCE_TYPE.
              WHEN d."SOURCE_TYPE" = 'WHATSAPP'                                     THEN 'drive'
              WHEN upper(COALESCE(d."SOURCE_TYPE", '')) LIKE '%GMAIL%'
                OR d."SOURCE_TYPE" = 'MAIL_ATTACHMENT'                              THEN 'mail'
              ELSE 'other' END AS kind,
         substring(d."SOURCE_LINK" FROM '/folders/([A-Za-z0-9_-]+)') AS folder_id,
         -- The file id comes from LINK, never from a template applied to SOURCE_ID — the same
         -- derivation 'Build Drive Rename (update_name)' uses. On drive rows SOURCE_ID IS the
         -- file id, so it is a legitimate fallback there and only there.
         CASE WHEN d."SOURCE_TYPE" IN ('GOOGLE_DRIVE_FOLDER', 'GOOGLE_DRIVE_FILE')
              THEN COALESCE(
                     substring(d."LINK" FROM
                       'drive\.google\.com/(?:file/d/|open\?id=|uc\?id=)([A-Za-z0-9_-]{20,})'),
                     NULLIF(d."SOURCE_ID", ''))
              ELSE substring(d."LINK" FROM
                     'drive\.google\.com/(?:file/d/|open\?id=|uc\?id=)([A-Za-z0-9_-]{20,})')
         END AS file_id,
         -- A mailbox address is NOT a message id. On the 2,154 v1 rows that carry one in
         -- SOURCE_ID the real id is in SOURCE_LINK, and typing the handle is what makes posting
         -- the wrong one to Gmail unrepresentable rather than merely unlikely.
         CASE WHEN (upper(COALESCE(d."SOURCE_TYPE", '')) LIKE '%GMAIL%'
                    OR d."SOURCE_TYPE" = 'MAIL_ATTACHMENT')
              THEN COALESCE(
                     CASE WHEN COALESCE(d."SOURCE_ID", '') <> '' AND d."SOURCE_ID" NOT LIKE '%@%'
                          THEN d."SOURCE_ID" END,
                     substring(d."SOURCE_LINK" FROM '#[a-z]+/([A-Za-z0-9]+)'))
         END AS message_id,
         CASE WHEN d."SOURCE_ID" LIKE '%@%' THEN d."SOURCE_ID" END AS mailbox
) k
LEFT JOIN _fmap f ON f.fid = k.folder_id
LEFT JOIN _nmap n ON n.old_name = d."SYNC_NAME"
CROSS JOIN LATERAL (
  SELECT COALESCE(
    f.pipe,                                                        -- 1. folder (incl. legacy)
    n.pipe,                                                        -- 2. retired pipe name
    (SELECT pipe FROM _mode WHERE pipe = d."SYNC_NAME"),           -- 3. live pipe name
    -- 4. the v1-mail rule. Scoped to exactly the dead writer's fingerprint so it can never
    -- capture a live row: SOURCE_TYPE='GMAIL', a mailbox in SOURCE_ID, and no SYNC_NAME.
    CASE WHEN upper(COALESCE(d."SOURCE_TYPE", '')) = 'GMAIL'
              AND d."SOURCE_ID" LIKE '%@%'
              AND COALESCE(d."SYNC_NAME", '') = ''
         THEN CASE WHEN upper(COALESCE(d."TYPE", '')) = 'BALANCE_SHEET' THEN 'gmail-bs'
                   ELSE 'gmail-doc' END END
  ) AS name
) pipe
LEFT JOIN _mode m ON m.pipe = pipe.name
WHERE d."SOURCE_LIST" IS NULL
   OR jsonb_typeof(d."SOURCE_LIST") <> 'array'
   OR jsonb_array_length(d."SOURCE_LIST") = 0;

\echo '--- DRY RUN: what the backfill resolves to ---'
SELECT kind,
       COALESCE(pipe_name, '<unresolved>')                      AS pipe,
       COALESCE(mode, '-')                                      AS feedback_mode,
       count(*)                                                 AS rows,
       count(*) FILTER (WHERE src_list->0->>'required_feedback_type' IS NOT NULL)
                                                                AS will_get_feedback
FROM _elem GROUP BY 1, 2, 3 ORDER BY rows DESC;

\echo '--- DRY RUN: every row with NO feedback channel, and the stated reason ---'
SELECT COALESCE(src_list->0->>'sync_feedback_error', '(none — feedback will run)') AS reason,
       count(*) AS rows
FROM _elem GROUP BY 1 ORDER BY 2 DESC LIMIT 15;

\echo '--- WRITING ---'
UPDATE public.incoming_documents d
   SET "SOURCE_LIST" = e.src_list
  FROM _elem e
 WHERE e."ID" = d."ID";

\echo '--- VERIFY ---'
SELECT count(*) FILTER (WHERE jsonb_typeof("SOURCE_LIST") = 'array'
                          AND jsonb_array_length("SOURCE_LIST") > 0)         AS with_source_list,
       count(*) FILTER (WHERE "SOURCE_LIST" @> '[{"required_feedback_type":"drive_move"}]')
                                                                             AS drive_feedback,
       count(*) FILTER (WHERE "SOURCE_LIST" @> '[{"required_feedback_type":"mail_tag"}]')
                                                                             AS mail_feedback,
       count(*)                                                              AS total
  FROM public.incoming_documents;

RESET session_replication_role;
