#!/usr/bin/env bash
# READ-ONLY progress watch for the read-only destination-folder backfill pipes.
set -u
D="docker -H unix:///run/bbox-docker.sock"
$D exec -i supabase-db-shlomo-laptop psql -U postgres -d postgres -c "
select replace(l.source,'incoming-documents-main/','') as pipe,
       count(*) filter (where l.status='delivered')    as delivered,
       count(*) filter (where l.status='claimed')      as claimed,
       count(*) filter (where l.status='needs_review') as needs_review,
       count(*)                                        as ledger_rows
  from public.sync_ledger l
 where l.source like '%drive-gdoc-scanned%' or l.source like '%drive-gdoc-chat-export%'
    or l.source like '%whatsapp-bot%'
 group by 1 order by 1;"
$D exec -i supabase-db-shlomo-laptop psql -U postgres -d postgres -c "
select \"SYNC_NAME\" as pipe, \"STATUS\", count(*)
  from public.incoming_documents
 where \"SYNC_NAME\" like 'drive-gdoc-scanned%' or \"SYNC_NAME\" like 'drive-gdoc-chat-export%'
 group by 1,2 order by 1,3 desc;"
$D exec -i supabase-db-shlomo-laptop psql -U postgres -d postgres -t -A -c \
  "select 'incoming_documents total = '||count(*) from public.incoming_documents;"
