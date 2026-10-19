-- 2026-08-06 — revert THUMBNAIL_COMPLETED on 13 rows where it was stamped after a TRANSIENT
-- failure. This corrects a mistake made by the first run of
-- scripts/ops/indox-thumbnail-backfill.py --run 20 --commit.
--
-- WHAT HAPPENED. THUMBNAIL_COMPLETED is TERMINAL by design: apps/indox/app/incoming_documents/
-- api/__init__.py:3931 records that the live action "stamps THUMBNAIL_COMPLETED either way, so a
-- single failed attempt terminates rather than retrying forever". That is the right rule for a
-- PERMANENT failure (unsupported mime, empty file, unrenderable bytes).
--
-- It is the WRONG rule for a timeout. 13 of the 20 documents in that batch failed with
--     render_failed: ReadTimeout: timed out
-- after the full 90s httpx timeout on apitools /pdfToJpeg — i.e. apitools was saturated, which is
-- a statement about CAPACITY at 17:0x on 2026-08-06, not about the document. Stamping them
-- terminal would have permanently excluded 13 perfectly renderable documents from both this tool
-- and the live pipeline, which is a worse outcome than never having run the batch.
--
-- The 7 rows that succeeded keep their THUMBNAIL and their flag — nothing here touches them.
-- The guard `coalesce("THUMBNAIL",'') = ''` makes that explicit and makes this file re-runnable.
--
-- scripts/ops/indox-thumbnail-backfill.py has been changed so it can no longer do this: it now
-- stamps THUMBNAIL_COMPLETED only for failures it classifies as permanent.
--
-- Backup covering these rows:
--   data/_registry_backup/incoming_documents.pre-shortdocid.20260806T150000Z.sql

\set ON_ERROR_STOP on

BEGIN;
update public.incoming_documents
   set "THUMBNAIL_COMPLETED" = null
 where "ID" in ('doc_mshfn3docszg7y','doc_mshfln6f4q97jp','doc_mshflkyizat0te','doc_mshflkl3pwv0mb',
                'doc_mshflkjqf97aso','doc_mshflhgskcu97p','doc_mshflhfp9h2e9q','doc_mshfleppswi982',
                'doc_mshfj0fo248mpi','doc_mshfirzaktugex','doc_mshffuge26js4z','doc_mshffub3eg36bh',
                'doc_mshcwwzwbt9eat')
   and coalesce("THUMBNAIL",'') = '';
-- expect: UPDATE 13
COMMIT;

\echo '--- POST-CHECK: the 13 are eligible again (expect 13 clear, 0 still stamped) ---'
select count(*) filter (where coalesce("THUMBNAIL_COMPLETED",'') = '') as eligible_again,
       count(*) filter (where coalesce("THUMBNAIL_COMPLETED",'') <> '') as still_stamped
  from public.incoming_documents
 where "ID" in ('doc_mshfn3docszg7y','doc_mshfln6f4q97jp','doc_mshflkyizat0te','doc_mshflkl3pwv0mb',
                'doc_mshflkjqf97aso','doc_mshflhgskcu97p','doc_mshflhfp9h2e9q','doc_mshfleppswi982',
                'doc_mshfj0fo248mpi','doc_mshfirzaktugex','doc_mshffuge26js4z','doc_mshffub3eg36bh',
                'doc_mshcwwzwbt9eat');

\echo '--- POST-CHECK: the 7 successes are untouched (expect 7 with a THUMBNAIL) ---'
select count(*) as still_have_thumbnail
  from public.incoming_documents
 where "ID" in ('doc_mshfohebfumft6','doc_mshfn33rpoa76c','doc_mshfiyxbt5qckt','doc_mshcx4cvk4oamk',
                'doc_mshcx24xmgyfmk','doc_mshcx1yul1md22','doc_mshcwqpu51sx0w')
   and coalesce("THUMBNAIL",'') <> '';
