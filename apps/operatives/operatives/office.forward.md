---
id: office.forward
title: Forward - the round that starts every session (one picture first)
title_he: קדימה
when:
  - קדימה
  - יאללה קדימה
  - תתחיל בפקודת קדימה
  - תריץ קדימה
  - go forward
  - kadima
inputs: {}
reaches_people: false
acts: true
adds: true
command: true
check: 'a table of area | state | what is open, then each unanswered message with its item, then the first started item'
---
The owner's «קדימה» (DGO-1301, DGO-1339 step 5): ONE picture of the office first, gathered in PARALLEL, then the work.

1. Gather all five areas at once, each with its own timeout. One that does not answer is a row «unreachable: why» — never a stop:
   - meetings: where Meet runs (`./bbox remote` lists the linked offices and their apps), then `./bbox meet recordings 10`, `./bbox meet meetings 10`, or `./bbox via <office> meet …`.
   - the group: `./bbox telegram chat "Bina Solutions Main" history 40` — every message of the owner with no bot answer after it.
   - sessions: `./bbox agent list` — sessions idle with queued messages, and whether the official Claude app is signed in (`./bbox bina-claude status`, DGO-1336).
   - offices and links: `./bbox dgo link status`.
   - work: `./bbox project-pln tasks list --mine --state started` (200 s timeout: Plane is slow, a session owns it).
2. The answer OPENS with one table — area | state | what is open — and nothing before it.
3. Each unprocessed meeting (no meet-flow page, or its tasks read no «ב-Plane · KEY») → ONE item: `./bbox project-pln report "<room> <date>: לעבד את הפגישה לפי apps/meet/README.md «קדימה after a meeting»"`. Do not run the processing here: it is a session's work.
4. Each unanswered group message → its item, and a reply IN the group as the bot: `./bbox telegram say-group` (his language, quotes the message, names the item). Mark it as you go — `./bbox telegram chat -1001234567890 message <id> mark 👀` on receipt, `✍` when you start, `👌` in the answer, `🏆` when the item closes. The bot IS an admin (measured 2026-11-04): a message nobody marked is our silence, never the group's. The group never gets an internal address — a link for him is `https://console.staging.digital-office.co.il/#/m/plane.hp-laptop/bina/projects/<proj>/issues/<uuid>`, or just the item number. Never a secret, money, a signature, or an outside party. A photo he sent is brought in and READ, never guessed at: `./bbox telegram media <chat_id> <message_id>`.
5. Then the first unblocked started item from the work row.
