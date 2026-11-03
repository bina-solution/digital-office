# The DGO benchmark beside the public ones (DGO-949)

The owner asked for "our own DGO/Azaria benchmark", mapped to the online benchmarks (DGO-952).

The two kinds measure different things:
- **Ours** measures the errands people ask local Azaria for. Each runs through the real harness, relay and office.
- **The public ones** measure a model's tool calling in isolation.

So a public score says whether a model is worth a run of ours. Ours says whether it does the office's errands.

## How each judges

- **DGO** (`cases.json`, `bbox ops bench`). One request goes to a new session of «עזריה · מקומי». It passes when all of these hold:
  - the turn completed;
  - every `ran` text is in a command that worked;
  - no `not_ran` or `never` text is in any command;
  - the answer is text, and it holds `answer_has` when a case gives one.

  That judges the outcome and the end state, like τ²-bench, not the shape of a call. The time to the first command and to the answer is recorded too.
- **BFCL v4** ([leaderboard](https://gorilla.cs.berkeley.edu/leaderboard.html)). Its categories:
  - single and parallel calls checked against the expected call, both non-live and "live" (phrasings people contributed);
  - relevance and irrelevance (whether to call at all);
  - multi-turn, in four sets of 200: base, missing function, missing parameter, long context;
  - agentic: web search, memory, and format sensitivity.

  The overall score is 40% agentic, 30% multi-turn, and 10% each for live, non-live and irrelevance.
- **τ²-bench** ([arXiv 2506.07982](https://arxiv.org/abs/2506.07982), ICML 2026). Conversations in the airline, retail and telecom domains, where telecom is dual-control: the user acts as well.
  - It judges the final database state and what the agent told the user.
  - Reliability is pass^k: all k tries pass.
- **When2Call** ([arXiv 2504.18851](https://arxiv.org/abs/2504.18851), NAACL 2025). Whether to make a call at all, to ask a follow-up question, or to say it cannot.

## Case by case

| DGO case | What it asks of the model | Nearest public measure |
|---|---|---|
| mail-new, office-status, office-reach, tasks-show | the recipe's one command, whole | BFCL live simple |
| mail-find, mail-find-2, drive-find | one argument from the request, never the example | BFCL live simple (the argument) |
| assets-show | the argument and the linked office; the answer quotes the result | BFCL live multiple; τ² information given |
| assets-show-2 | the website's own page goes to its texts, not to the browser: two near tools | BFCL live multiple (the right one of similar functions) |
| browser-page, browser-page-2 | the address from the request; the answer from the page's quoted text | BFCL live simple; τ² information given |
| mail-read | the newest id, then that mail: a chain | BFCL multi-turn base, in one turn |
| tasks-open | two calls, their answers combined | BFCL parallel multiple |
| dont-close | the request forbids the acting step | τ² policy; When2Call (no call) |
| ops-list, ops-list-2, ops-list-3 | one intent, three phrasings | BFCL live; v4 format sensitivity |
| just-write, just-hello, just-translate | no tool at all | BFCL irrelevance; When2Call direct answer |
| browser-shot | a side effect in the office browser | BFCL live simple; τ² end state |
| `never` (every case) | no mail sent, no item closed or touched | τ²: the state must not change |

## What is missing, and what it costs

The Dell runs gemma4:e2b at about 1.8 minutes a case: 29 minutes for 16 cases on 2026-10-22. All 21 cases
take about 40 minutes.

1. **Reliability (τ² pass^k).** Run each case three times and report pass^3 next to pass@1: about 2 hours.
   The runner does it (`BENCH_TIMES=3`).
   - The first run (2026-10-22): of 15 cases measured, 14 passed all three tries (pass^3 93%), and 43
     of 45 tries passed (96%).
   - The one that did not: mail-new, 1 of 3. Its recipe's "unread" variant was an instruction to edit
     a command, and the model pasted the recipe's lines into bash.
   - The other 6 cases were not measured: the Dell left the network halfway (DGO-990).
2. **Missing parameter** (BFCL, When2Call "ask"). «תשלח מייל לשלמה», a name with no address, must be asked about, never invented.
   `not_ran` only fails a case after it ran; it stops nothing. A model that guessed an address would
   send first and fail after. So this case waits for the test mailbox (DGO-957), like the acting ones.
3. **Missing function** (BFCL, When2Call "cannot"). For an errand no operative serves («תזמין לי פיצה»), the agent says so, and nothing that acts runs.
4. **More irrelevance.** Begun: a greeting and a translation (just-hello, just-translate). A sum is left out
   on purpose: working it out in bash is a fair use of a tool, not a wrong call.
5. **Multi-turn.** A follow-up in the same session («ומה עם השני?»). The runner takes one request per session today; a case would take a list of turns. About half a day.
6. **State, not commands (τ²).** The acting cases (a comment, a mail, a WhatsApp message) are judged by what exists afterwards. They wait for the owner's test targets (DGO-957).
7. **A candidate's public score before a run of ours.** BFCL's `bfcl-eval` package scores a model against an API.
   - Whether it runs against Ollama's OpenAI-compatible `/v1` as it is still has to be checked.
   - The full set is about 5,100 cases, some 30–40 hours on the Dell. A stratified 200 instead takes about 2 hours a model.
