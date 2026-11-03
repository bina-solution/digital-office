# Operating «בינה» (the `bina-ds` app)

The office's AI: a Hebrew agent harness where the office agents live. Azaria is the default agent
and acts; Raphael is the guardian and only proposes. People talk to them in the tile. Every other
caller (a script, another agent, a linked office) speaks agent.v1 to the agent door, for which the
CLI is `bbox agent`.

## From the server's shell (`bbox agent`, layer 0)

```bash
./bbox agent list                         # sessions: running / idle, title, goal
./bbox agent show|log|follow <id>         # one session: its state, its history, live
./bbox agent wait <id> [--for S]          # block until the turn ends (default 3600 s), print the answer
./bbox agent new -t "<title>" "<text>"    # a new session, first message sent (- reads stdin)
./bbox agent send <id> "<text>"           # queue a message; --steer into the running turn
./bbox agent do <DGO-12>                  # hand him a work item: «complete task @project-pln/DGO-12»
./bbox agent goal <id> get|set|pause|resume|clear|complete
./bbox agent tasks list|show …            # his work items (bbox project-pln tasks --as azaria)
./bbox agent doctor | whoami | models | presets
./bbox agent --office <office> …          # the same verbs, on a linked office's agent
```

`<id>` may be a unique prefix, and `--json` gives the contract's JSON. Exit codes: 3 unreachable,
4 not found, 5 auth, 6 ambiguous. The door is `http://bina-ds:3081` (agent.v1: `/v1/sessions…`
with the office's bearer token; `/v1/health` is open).

## Rules

- **A session costs money and acts.** `new`, `send`, `do`, `cmd` and `goal set` start LLM work, and
  the agent runs with full access to the office (the engine socket, a writable checkout).
  - A message to Azaria is an instruction to an operator with root.
  - Hand him only what the owner asked for, in the owner's words, with the work item's ref.
- Reading sessions is free. `cancel` drops the turn that is running.
- `model --set` also changes the office's default model, and `preset` changes how a session
  behaves. Both are the owner's to ask for.
- His work items are written as him (`tasks start|done|comment|take` are logged as azaria).

## Traps

- **Never recreate bina-ds from inside a session.** The compose guard hands it to
  `hooks/self-update`, which waits for quiet, forces after 3 h (5 min with `BBOX_UPDATE_NOW=1`), and
  rolls back if the new one is unhealthy.
- An office that runs bina-ds off (the MacBook does) reaches a linked office's agent with
  `--office <office>`.
- **`POST /v1/seder/{shacharit|mincha|arvit}` is the office clock's door (n8n), outside the token
  gate.** A real call (`{"by": "bina-seder"}`) starts a paid autonomous session.
  - Never send it yourself. `{"dry_run": true}` is the only call that is yours.
  - By the owner's design every call opens a new cycle, bounded by the day's budget
    (`data/bina-ds/sedarim/<day>/תקציב.json`), not by a count. Older docs that say a second start
    in a day is refused are wrong.

Gates: no registered gate names this app yet (the inventory's gate cell); its own tests.
