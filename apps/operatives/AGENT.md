# Operating the Operative Collective (the `operatives` app, `bbox ops`)

Every action the office can do, as one short, proven recipe per action: the exact CLI or API call,
and how to tell that it worked. Before you act on a request, find the operative that does it and
follow its steps exactly. Each lives with its app, at `apps/<app>/operatives/<id>.md`; the directory
is the declaration. This app has no service, port or screen: it is the index and the matcher.

## From the server's shell

```bash
./bbox ops find "<the request, in its own words>"         # the operatives it needs, best first
./bbox ops find "<request>" --show                        # …and the best one whole, ready to follow
./bbox ops show <id>                                      # one operative
./bbox ops list [<group>]                                 # every operative, and where it runs
./bbox ops check                                          # all well formed (also test_ops.py)
```

**Where it runs is computed:**

- here, when its app is enabled;
- `via <office> (<alias>)`, when a linked office publishes the app;
- not reachable, otherwise.

An operative marked `link: false` (the browser's `page` and `shot`, `n8n.status`) works only where
its app runs.

## Rules

- **Match first, act second.** `find` compares the request's words with each operative's `when`,
  `title` and `title_he`.
  - Below the match threshold (0.45), or on a tie at the top, it answers with no operative. Then ask
    the owner instead of picking one.
- **A request that forbids or asks gets only operatives that read.** That is a request with «אל», «לא
  ל…», "don't", "do not" or a question in it.
- Follow the steps exactly. Free text goes in ONE command, in single quotes, with `'` written as `׳`.
- An operative with `reaches_people: true` (such as `mail.send`) sends something a person receives.
  `acts: true` changes something, and `adds: true` only adds (a report).
- `bench <provider> <model>` runs real sessions on a local model and changes the default model for
  the run. It waits up to 30 minutes for a quiet agent. Run it only when asked.

## Writing one

The file is `<id>.md`, named after its id (`<group>.<action>`), under 3,000 bytes, with front matter
`id`, `title`, `when` (Hebrew first), `check`, and `acts`/`adds`/`reaches_people` as they apply. It
holds no secret: the steps name the verb that leases a credential, never the credential. `./bbox ops
check` must pass. The full contract is in `apps/operatives/README.md`.

## Traps

- bina-ds injects recipes only on its local-model (Ollama) routes, not on DeepSeek.
- `ops.py match` (a JSON list on stdin) is the relay's door and has no `bbox` verb.

Gates: its own tests (`test_ops.py`, `bbox ops check`).
