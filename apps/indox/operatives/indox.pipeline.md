---
id: indox.pipeline
title: How INDOX's document pipeline is doing — the drain, what waits, the errors
title_he: מצב צינור המסמכים הנכנסים
when:
  - מצב המסמכים הנכנסים
  - כמה מסמכים ממתינים באינדוקס
  - האם הדריין של אינדוקס רץ
  - מה מצב הצינור של אינדוקס
  - indox pipeline status
inputs: {instance: "the INDOX instance id the person named, e.g. hacohen; none for every enabled instance"}
reaches_people: false
check: 'per instance: whether a drain runs now and whether its gate is open, documents not done, restarts asked, dispatched in 5 min; n8n errors in an hour once — or which source did not answer'
---
1. Without a named instance, the instances first; then step 2 for each `enabled` one but `test`:
   - here: `curl -sS --max-time 60 http://incoming-documents:8080/incomingDocuments/instances`
   - linked: `./bbox remote <office> <alias> /incomingDocuments/instances --timeout 60`
   An empty `instances` with a `reason` means the list could not be read: say so, never "no clients".
2. One instance's pipeline — ALWAYS with `?instance=` (without it the call reads the first production instance):
   - here: `curl -sS --max-time 60 'http://incoming-documents:8080/incomingDocuments/pipeline/status?instance=<instance>'`
   - linked: `./bbox remote <office> <alias> '/incomingDocuments/pipeline/status?instance=<instance>' --timeout 60`
3. An answer with no `db_available` field (a curl error, an empty or an HTML answer, or over a link an HTTP status of 400 or more) is "did not answer". Otherwise one line per instance:
   - from n8n — only when `n8n_available` is true, else "unknown": a drain runs now when `drain` is not null (its `started_at`), none when it is null;
   - from INDOX's database — only when `db_available` is true, else "unknown", never 0: `drain_on` is the GATE (whether a drain may run, not whether one does), `non_terminal` documents not done, `action_restart`, `dispatch_5m`, `parallel`.
   `errors_1h` counts every n8n workflow's errors, not INDOX's: say it once, not per instance.
4. This only reads. Starting a drain (one drainer only), restarting, resetting a sync and any document's state are not part of it: those stay on the screen and the owner's words.
