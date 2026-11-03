# Operating «אוטומציות» (the `n8n` app)

The office's automation engine, n8n in queue mode: `n8n` (the editor and API), `n8n-webhook` (the
webhook receiver), two workers with their runners, and its own `n8n-postgres`. Every app's workflows
run here. This app owns only the central ones in `blueprint/n8n/`. Each other app ships its own under
its `blueprints.n8n` folder, as `*.workflow.ts` code. **The code is the source; live n8n is a
rendering of it.**

## From the server's shell

```bash
./bbox n8n status [--brief]                   # the instance: workflows, activity, health
./bbox n8n pull <app> <wfId> [wfId …]         # live → just those .workflow.ts files (do this FIRST)
./bbox n8n push <app> <wfId> [wfId …]         # code → live: compile, update, re-activate, read back
./bbox n8n push <app> <wfId> --dry-run        # what a push would change
./bbox n8n plan|test <app> <wfId> [--prod]    # how to test it / trigger it for real, with a verdict
./bbox n8n exec list|get …                    # executions, for diagnosis
./bbox n8n code validate|info|search …        # the authoring toolchain
./bbox n8n execute -n node.json input.json [--ex-link]   # one node against items, in a throwaway workflow
./bbox n8n tags                               # every workflow's `app:<id>` owner tag
```

`push all` and `pull all` act on the whole instance, and `push all` also restarts n8n, the workers
and the runners. Both are the owner's to ask for. Deep reference: `ai/context/n8n-development.md`.

## From inside the office network

The API is `http://n8n:5678/api/v1/…`. Use the `bbox n8n` verbs, which read its key themselves. The
key is a full-access key to an instance whose host is on the edge, so never print it or pass it on.
`/webhook/`, `/webhook-waiting/` and `/form/` are answered by `n8n-webhook` and are public through
the edge with no SSO, so a webhook workflow guards itself.

## Rules

- **Pull exactly what you will edit (`pull <app> <wfId>`), edit the code, push exactly that.** A bare
  `pull <app>` rewrites every file of the app from live, drops their comments, and DELETES every
  local `.workflow.ts` whose id is not live, which loses an unpushed new workflow.
- **A CONFLICT on push means someone changed it live.** Find out what changed before anything else.
  A pull round-trips through n8n and drops the `.workflow.ts` comments, which once cost 151 lines of
  source notes. `--force` overwrites the live change.
- **`test` really triggers the workflow**, with real side effects. Run `plan` first.
- Give the owner the link of every execution you ran.
  - For a test it is `/workflow/<id>/executions/<execution id>` on the n8n host.
  - `execute` keeps its throwaway workflow and prints the link only with `--ex-link`. Without it,
    both are deleted.
- **Never without the owner's words:**
  - `bbox n8n <app> unpush` deletes ALL of that app's workflows from n8n's database, with no prompt
    and no dry run, then restarts n8n. `base unpush --retired` deletes the retired list, and restarts
    n8n only when one of them was active.
  - `clean-recreate` truncates the instance. bbox reads a global `--force` as its `--yes`.
  - `load-dump` drops the database.
  - `automations reset --force` clears the client's sheet rows, trashes Drive folder files, strips
    Gmail labels and clears Redis. Without `--force` it is a preview.

## Traps

- `pull <app>` (that app, through the API) is not `<app> pull` (a whole-instance export).
- A NEW workflow's schedule trigger registers only after the main process restarts.
- `apps/n8n/retired-workflows.txt` is read by `hooks/pull`, which serves `pull all` and `<app> pull`,
  so a retired workflow never comes back that way. `push <app>` does not read it, and gate G38 fails
  when a retired id has a blueprint file.
- There is no `hooks/test`: `bbox test n8n` fails. Test a workflow with `bbox n8n test`.
- The editor is n8n's own login on its own host (external tile), not the office's SSO.

Gates: G38 (no dangling or retired workflow reference), G42, G61 (published drift), G63, G86. Every
blueprint gate in `scripts/refactor/run-gates.py`'s n8n set reads every app's `*.workflow.ts`.
