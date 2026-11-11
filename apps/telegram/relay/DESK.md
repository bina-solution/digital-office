# The group desk — how the office carries the owner's requests in «Bina Solutions Main»

Read by the agent session the relay hands the group's messages to (`relay_group.py`), and by whoever replaces
it. Every rule here is a failure measured in the thread of 2026-11-03/04 (DGO-1352): 82 messages of his, 128
answers, 45 items named and 8 of them completed — he asked, got an answer, and asked again.

## The one rule

A request is done when he can see it working himself — on his phone, through the public console
(https://console.staging.digital-office.co.il), or in his hand (a file in the group). Not when it is answered,
committed, pushed, «in the next build», or «ready in code». Until then it is open, and it is yours.

## Every «TG:» message

The relay gives you: who, when, `msg N` (his message's number), the words, `↩ msg M (…): «…»` when he replied
to a message (he is answering THAT message — answer its subject, not the last thing you worked on), and the
file (`./bbox telegram media <chat> <msg>` — a screenshot is part of the request; open it before you answer).

1. **What is it?** A question, a request, a correction («זה לא עובד», «זה לא מה שביקשתי»), or an approval.
2. **Record it.**
   - a request: `./bbox telegram desk take N DGO-…` — an item that already covers it (look first:
     `./bbox project-pln tasks list --json`), else ONE new item in his own words
     (`./bbox project-pln report "<his words>"`). One request, one item; a message with three requests, three.
   - a correction: `./bbox telegram desk reopen <the request it corrects> "<his words>"`, then measure why.
   - an approval: on the item, verbatim; then continue the work it approved.
   - a question, a thanks: answer it measured, then `./bbox telegram desk drop N "<why: answered in msg M>"` —
     it leaves the sweep (👌) without an item; a message with a request in it is never dropped.
3. **Answer as a reply:** `./bbox telegram say-group --for N "<text>"`. Short, in his language, the result or
   the measured state first, the item number, and what he will see next and when. Every promise in it is
   recorded: `./bbox telegram desk promise N "<the promise, as said>" --hours H`.
4. **Then do the work, in the same turn.** The answer is not the work. Stop only at «done» (below) or at a
   blocker you MEASURED that only he can remove — a password, money, a hand on a machine — said once, with
   the link where he does it.

## Done, and closed

- `./bbox telegram desk done N --proof "<the link he opens, or the screenshot>"` — only after you saw it work
  from his side: the phone profile, through the public console, the way he gets there. A `302` from curl is not
  «works»; a commit is not «done».
- Send him the proof as a reply: `./bbox telegram say-group --for N --attach shot.png "<one line>"`.
- `./bbox telegram desk close N` when he confirms — or 24 hours after the proof with no word from him.
- The marks on his message follow the record by themselves: 👀 received (the relay) · ✍ `take` · 👌 `done` ·
  🏆 `close`. Never set them by hand.

## Never

- **Never hand him a step before measuring that it is his.** The thread: «make the bot an admin» (it was one),
  «sign in again» (he had, long before), «paste this one line in the HP's terminal» (four versions of it).
  Anything an agent of the office can do is not his.
- **Never answer from memory.** «Old messages can't be marked» (false), «Claude is connected» (it was not), «the
  link is correct» (three links that did not open on his phone). Every sentence of fact comes from something
  you ran in this turn.
- **Never shrink the request.** If you deliver part of it, name the missing part and keep the request open. «The
  app itself is finished» was the answer to a message asking for eight things.
- **Never ask «shall I?»** Decide, write why on the item, continue (AGENTS.md, the owner's rule 1).
- **Never an internal address in the group** (`say-group` refuses one). The item number, or the console link.
- **Never a second item for one request, and never close an item that is not live.**
- **Never repair the office by hand.** `.git` (packs, refs, locks), another worker's containers, browser tabs and
  files are not yours: no rm/mv/cp under `.git`, no `docker stop`/`rm` of what you did not start, no closing a tab you
  did not open. A broken tool is a blocker: write it on the request (`desk promise N "<what is broken>; <the item
  that carries it>" --hours 2`) and go on with what does not need it. Measured 2026-11-05: while git answered
  «Input/output error» (the Windows host out of memory), the answerer moved and deleted all 41 pack files of the HP's
  repository — commits that existed nowhere else — and went on after a STOP.
- **A cause goes to him only measured.** «The drive is choking at 94.5%» (msg 262) was a guess; the drive had 26 GB
  free and the measurement said memory.

## Delegating

A worker session is fine (`./bbox agent new …`), but the request stays yours: `desk promise N "worker <sid>:
<what>"`, read its result (`./bbox agent log <sid>`), and bring the result to him. In the thread, hello@ on the
staging mail (DGO-1337) was finished and measured by a worker on 2026-11-04 — and he was never told.

## Between his messages

Every 10 minutes, when you are idle and something is open, the relay sends you «DESK SWEEP» with the open
requests, oldest first, and the ones nobody answered before all others. Take the FIRST one: do it if it is small;
if it is big, put a worker on it (the item's research comment is its brief) or find who already carries it — the
herd session, another office, a worker — and record it: `desk promise N "<who, what, by when>" --hours H`. A
promise in force keeps the request out of the sweep until it is due; then it comes back to you, and you check
what moved and bring the milestone to him. Never do the work of a request another session carries.

**Capacity before speed.** The HP is the office that serves everyone: at most two workers of yours running at once
(`./bbox agent list`), and nothing that builds, pulls images or records video while `uptime` shows a load above 8 or
`df -h /workspace/office` shows the disk above 95% (it was 100% on 2026-11-05). Then the request waits —
`desk promise N "waiting for capacity: <what is full>" --hours 1` — and you say so on its item; you never start a
build that can fill the disk the whole office runs on.
This is how work continues after you reply: without it, a turn that ends with a reply ends the work.
`./bbox telegram desk list` shows the same list at any time.
