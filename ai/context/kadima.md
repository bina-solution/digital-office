# «קדימה» — the procedure

When the owner says «קדימה» (or asks for a «קבץ קדמה», a version, a distribution) the herd stops being seven
lanes with their own lists and becomes one line with six stages. This file is that line. It exists because of one
night (2026-11-10 → 11, DGO-1820): eight sessions had a tool call in 38% of their minutes, wrote «waiting» or
«blocked» 280 times, and in ten hours one office of six ran the new version. His words: «איך כששאני אומר קדימה
זה לא קורה יותר לעולם הנמנמת הזאת והדחיינות».

The word: never «אצווה». A gathering is a «קבץ קדמה»; what goes out to the offices is a «גרסה».

## The six stages, each with its owner and its clock

| # | Stage | Who | Done when | Clock |
|---|---|---|---|---|
| 1 | **Gather** — every lane lands what is whole and parks what is not; what sits uncommitted on each machine is listed | every lane, 30 minutes; the release lane keeps the list | one list on the item: in / stays out, with the reason | 30 min |
| 2 | **Sweep** — the seconds-long gates on the exact head, before any cut | release | every gate green on the head named on the item | 10 min |
| 3 | **Cut** — one version from the swept head | release | `dgo-stable` at that head | 5 min |
| 4 | **Prove** — one proof, nothing else on the runner ahead of it | release; the coordinator clears the runner | the proof's verdict on the item; green moves | 40 min |
| 5 | **Distribute** — every office takes it by its own follow: ours, then the clients by a public release that counts zero client names | release leads; herd (links, EXF, the HP), the client's lane (its office), security (the count) | per office: from → to, healthy, its link answers | 60 min |
| 6 | **Show** — one screenshot per office of what changed, and anything built is run on a device | ui-bugs; the lane that built it | the pictures are with the owner | 20 min |

A stage that passes its clock is not «late»: the same minute it gets another way, or one line to the owner with
its link — never a second report that says «not yet».

## The rules that hold from the first minute

1. **Four lanes at full pace** — release, the lane that owns the red or the app in question, herd, security. The
   others land, park and stop spending the shared usage window; eight sessions empty a five-hour window in two
   hours and twenty minutes, and then all eight stand for the rest of it.
2. **«Waiting for X» is not an end state.** A turn that closes on a wait is refused by the stop check
   (`.claude/hooks/work-left.py`, check 6). The answer is the way that does not need X — one app installed with
   `bbox app install` instead of a whole take; a proof's runner cleared instead of queued behind; a screenshot from
   the office that has the code instead of the one that has not.
3. **Nobody idles.** The coordinator's idle sweep runs every ten minutes: a lane that is not running and has work
   is woken with its next step — two at a time, never all at once (seven wakes in five minutes put the desk at
   load 50), and it stops sending only when the application refuses. **The coordinator ends its own turn every
   ten minutes or less**: the sweep's timer and a message the owner sends are both read only when the turn ends
   (2026-11-11: one lane stood 50 minutes, and the owner's order to run a command half an hour, behind a
   coordinator's turn of 68). Work that runs longer goes detached, with a log the next turn reads.
4. **Built is not done.** A report line about a build names the device that opened it, or says «not opened».
5. **One machine, one heavy thing — and the release line first.** The Dell cannot hold a device emulator and a CI
   job together; whoever takes it says so on the item, with the minute it gives it back. Between the cut and the
   verdict (each measured on 2026-11-11):
   - no agent turn on the proof's machine — one turn loaded a 5 GB model under the proof, and the next job stood
     34 minutes at its memory gate;
   - no heavy slot on a shared machine for a lane that is not one of the four — the release's own check stood
     third on vps1's heavy lock, behind two probes;
   - a take on the desk the owner sits at builds one image at a time and starts nothing that was off — the
     MacBook's console answered 404 for 17 minutes under a take that baked two images and started n8n.
6. **Measure it.** `ci-artifacts/king-2026-11-10/k3/night-audit.py <since> <until> <transcripts…>` prints, per
   session, the minutes it worked, the gaps it stood and the last words before each. The coordinator runs it
   whenever progress feels thin, and says the percentages to the owner as they are.

## The board

One comment on the item, replaced at every stage: the stage, who holds it, when it began, when it is due, and for
stage 5 the six rows — MacBook, HP, vps1, Dell, EXF, Exampleu — each with its commit before and after, its health,
its link, its picture. An office that cannot be reached is a row that says exactly what is missing and who alone
can give it, with the link — once.
