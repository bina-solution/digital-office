# operatives — the Operative Collective

Every action the office can do, kept as **one short plain-text recipe per action**: the shortest proven
way to do it through the office's CLI or API. A small local model is handed the one recipe a request
needs, never a list of everything the office can or cannot do (DGO-948, the owner's request DGO-952).

## Verbs

```bash
./bbox ops list [<group>]          # every operative, and where it runs: here, via a linked office, nowhere
./bbox ops find "<request>"        # the operatives a request needs, best first
./bbox ops find "<request>" --show # … and the best one whole, ready to follow
./bbox ops show <id>               # one operative
./bbox ops check                   # every operative is well formed (also test_ops.py)
```

## An operative

It lives with the app it belongs to, at `apps/<app>/operatives/<id>.md` (or under `platform-base/`).
The directory is the declaration, as `hooks/` is, and nothing else lists it. The front matter says when
the operative applies; the steps say how:

```markdown
---
id: tasks.comment                       # <group>.<action>, lower case; the file is <id>.md
title: Comment on a work item
title_he: הערה על פריט עבודה
when:                                   # how people ask for it, Hebrew first
  - הוסף הערה ל-DGO-123
  - comment on DGO-123
inputs: {ref: "the item, e.g. DGO-123", text: "the comment"}
reaches_people: false                   # true: it sends something a person receives
check: 'the command prints "commented on DGO-<n>"'
---
1. `./bbox project-pln tasks comment <ref> --comment "<text>" --as azaria`
2. Say it was added, with the item's ref — or the error exactly as printed.
```

Rules (`bbox ops check`):
- `id`, `title`, `when` and `check` are required.
- The file is named after its id.
- An id is unique across the office.
- The whole file stays under 3,000 bytes. It is a recipe, not a manual.
- It holds no secret. Credentials stay in the vault, and the steps name only the verb that leases them.
- `acts: true` when it changes something. `adds: true` (with `acts`) when all it does is add something
  new, such as a report: a misread request then costs one item too many, never a closed item or a sent
  mail. Such an operative may take a request with a negation in it (see the tiers below).

Write a `check` value that contains `: ` in quotes.

## Where it runs

Where it runs is computed, never written:
- **here:** its app is enabled in `platform.state.yaml`;
- **via `<office> (<alias>)`:** a linked office publishes the app, as named in
  `.generated/registry/remote.<office>.<alias>.json`. The steps then use
  `./bbox remote <office> <alias> <path>`, the way `mail.send` does for mail on vps1;
- **not reachable** otherwise. An operative whose steps work only where its app runs says `link: false`
  (`bbox b42` drives the local browser; a linked office that publishes browser42 serves its live view,
  not its CLI). It is then reachable only here.

## Matching a request

`find` compares the request's words with each operative's `when`, `title` and `title_he`:
- the measure is the cosine of the two word sets;
- Hebrew's one-letter prefixes are stripped, and niqqud is ignored; a word met with and without its
  prefix («הלשכה», «לשכה») is still one word;
- a phrase counts only when the request shares at least two of its words (one shared word is chance:
  "שלח לי את זה" is not a mail);
- a long request is also measured by its first six words, against a `when` phrase that is there whole
  and that the request opens with: a report says what to do first, and its own words would dilute the
  measure;
- below 0.45 it answers that no operative matches;
- when two operatives tie at the top it answers that the request fits both, so the agent asks rather
  than taking the first in file order.

What a request may get depends on its own words, in three tiers:
1. **It forbids or asks:** only operatives that read.
   - Forbidding is `אל …`, `אסור`, `don't`, `do not`, a `never` or `stop` that opens a clause, or
     `לא` / `בלי` / `not to` before an infinitive.
   - Asking is ending with `?`, or `did you …` / `have you …`.
2. **Any other negation or `?`:** operatives that read, or that only add (`adds: true`, such as a
   report). Examples: «הפריט DGO-950 לא בוצע», «סגרת את הפריט?!», «תדאג שלא תשלח», or a sentence opening
   with what you did («שלחת את המייל»).
   - A report says what does NOT work, so a `לא` that describes ("הקונסול לא נטען") must not hold it
     back.
   - «not done» is still no order to close, and «you sent it?!» none to send.
3. **Otherwise:** every operative.

Before the tiers: a request that carries WHOLE a `when` phrase of an operative that only adds («תפתח
באג», "report a bug") is that order, and only such operatives are ranked — a report names what does not
work, so it carries a status read's words too («יש הרצות תקועות ב-n8n, תפתח באג»). Not when the request
forbids it («אל תפתח באג»), asks "did you …", or ends asking («תפתח באג?»).

The first-six-words measure counts only for operatives that read or add, and only when the request
opens with the phrase's first word. Words alone cannot tell a short description that contains an
order's words ("to send an email to customers, n8n uses…") from the order itself. What stops the wrong
act there is the recipe's own rule: a mail goes only to an address the person wrote.

Before a change to matching goes in, it is run over the owner's real requests: 728 of them on
2026-10-21, where this one moved 22 from "no match" to the right operative (15 bug reports among them)
and none to a wrong one.

On the owner's real errands of 2026-10-21, each right operative ranked first, at 0.67–1.00. "1000 words
on love", "send it", "open DGO-950" and "close the browser" matched none (`test_ops.py`). A router that
picks by meaning (embeddings or a tiny model) is the next step (DGO-950).

## Free text in a recipe

A small model copies a recipe's command literally, and follows ONE command far better than a file step
then a command: given «write the text to a file, then run …», gemma4:e2b recited the steps and ran
neither (2026-10-21). So text the person dictated goes inside the command, quoted so that a `$`, a
backtick or a Hebrew `דו"ח` is only text:
- `report --said` carries no text at all: the verb reads the person's last message from the agent's
  session, which the harness names to every tool process (`DSH_SESSION_ID`). In five tries at quoting
  the owner's words into the command, gemma4:e2b failed five different ways:
  - it recited the steps;
  - it escaped a quote the wrong way for the shell;
  - it kept a placeholder's bracket;
  - it left a quote unescaped;
  - it wrote the call as text.
- `tasks comment <ref> --comment '<text>'` keeps plain single quotes, with `'` written as `׳`; it was
  proven on a geresh.

The verbs also take `@<file>` for a text too long for a command line.
A mail is JSON, so it is written to `/tmp/mail.json` with the file tool and sent from there. A file name
in a recipe is fixed: `<n>` copied literally is a shell redirection. A URL goes in single quotes.
A mail goes only to an address the person wrote; for a name with no address, the agent asks.

A step is ONE command, whole, with no pipe the model has to keep. Given `curl … | slots.py`,
gemma4:e2b ran only the second half and reported "no content". So the printer fetches by itself
(`slots.py content '<word>' --via <office> <alias>`).

What the relay (`apps/bina-ds/tools/llm-routes.mjs`) mends on the way, so a recipe need not:
- it hands each request its recipe;
- it labels and times bash calls;
- it cuts a tool's long answer to the model's window, never a file that was read;
- it sends with thinking on a model that drops its calls with thinking off;
- it turns a call written as the answer's text (`{"command": …}`) into that call. It never does so for
  a call this turn already made and that worked.

## The DGO benchmark

```bash
./bbox ops bench <provider> <model> [<case-id>…]     # e.g. dgo-ollama-portable-ubuntu gemma4:e2b
```

Each case in `bench/cases.json` runs as a new session of «עזריה · מקומי» on that model. The office's
relay hands the request its recipe, exactly as it does for the owner. A case passes when:
- its turn completed;
- every `ran` text is in some command the agent ran that worked: no tool error, exit 0, something
  printed (a command that failed is listed under `failed`);
- no `not_ran` text is in any command it ran, nor any of the file's `never` list (a mail sent, an item
  closed, commented, started or reported), unless the case itself asks for it;
- it gave an answer (its `text` parts; a thinking model's `reasoning` is not the answer).

Each case prints one JSON line: the commands, the time to the first command, the total time and the
answer. A summary line follows (passed / of, the median first command, the timeouts). A turn still
running at `BENCH_TURN_S` (900 s) is cancelled, and its end waited for, so the next case does not queue
behind it.

The runner, `bench/agent.mjs`, runs inside the office's bina-ds container. Choosing a session's model
also rewrites the office's default model, so the runner reads the default just before and puts it back
just after. A default someone chose in the meantime is left alone. When the default cannot be put back,
the run stops and says what it was.

v1 holds cases that only read, or that change nothing of anyone's. The cases that act (a comment, a mail,
a WhatsApp message) wait for test targets (DGO-957).

The cases are real sessions on the office's model, so a case beside a person's own session competes
with them for it. Before each case the runner reads the agent's sessions:
- one that is not the benchmark's, running or touched in the last `BENCH_IDLE_S` (600 s), makes it
  wait, looking again every 30 s. A session on another provider does not count, since it does not
  compete for this model. Neither does the session the benchmark is run from (`BENCH_IGNORE`, by
  default `DSH_SESSION_ID`), nor any session the run made;
- after `BENCH_WAIT_S` (1800 s) it stops, names the session it waited for, prints the summary of what
  ran (with `stopped`), and exits 3.

`BENCH_TIMES=k` runs each case k times. Each line then carries its `try`, and the summary carries
`pass_k`: the cases that passed every try (τ²-bench's pass^k; `bench/MAPPING.md`).

## Adding one

1. Run the command it will contain, for real, on the office (and over a link if it can run there).
2. Write the file next to its app, with the requests people really make in `when`.
3. Run `./bbox ops check` and `python3 apps/operatives/test_ops.py`. Add the request to the test's
   cases when it is one people make.
