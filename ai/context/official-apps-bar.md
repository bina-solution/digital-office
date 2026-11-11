# The bar for the office's official apps (DGO-1507)

The owner, 2026-11-09: «גם חייב להעלות רמה בכל האפלקציות הרשמיות שלנו שיהיה לפחות ברמה של גימייל או
המתחרות המקבילות לאותו פיתרון» and «אל תיקח שום דבר כמובן מאילו ותוודא שהכל מושלם».

Each official app is held against the product people already use for the same job. "At least as good"
is measured, not judged: the numbers below are taken from the app's own layout (headless Chromium, the
console mounted around it) at two profiles, and a change is done when it meets them on BOTH and on the
dark ground.

- **Phone**: 390 × 845 CSS px under the console shell (his own phone: Chrome's bar leaves 709, the
  console's bar 58 and tab bar 61, so the app has **590 px**). See `scripts/ui-coverage/view-profiles.yaml`.
- **Desktop**: 1300 × 800 inside the console's app frame.

## What every official app owes (the shell's rules, any app)

| # | Rule | How it is measured |
|---|---|---|
| S1 | **One header.** The console's bar is the app's bar; the app adds at most ONE row of its own (title, its menu, its one or two tools). No card inside the console's frame on a phone. | rows of chrome above the first item, px |
| S2 | **One search.** Inside an app the shell's search searches the app («חיפוש בדואר»); the app shows no second magnifier. | count of search controls on screen = 1 |
| S3 | **Content first.** The items fill the screen; counts, filters and settings live behind one tap. | items fully visible on the phone profile |
| S4 | **The common action in reach.** It is one tap or one gesture from the list, never behind a checkbox. | taps from the list |
| S5 | **States.** Loading (a skeleton, not «טוען…» alone), empty (a sentence and the next step), error (the cause, Hebrew, and «נסה שוב»). | forced in the sim: each renders |
| S6 | **Speed.** First content under the console within 1.5 s on the office's own network; a cached second open under 300 ms. | `performance` marks in the frame |
| S7 | **Touch.** Every target ≥ 30 px on a phone (44 for the primary), no hover-only action. | the coarse-pointer audit |
| S8 | **The palette.** Olive Grove tokens only (G27/G82), light and dark from one rule set. | the gates |

## Per app, against its leader

| App | Leader | Phone target (390 × 590 app area) | Desktop target | Common action |
|---|---|---|---|---|
| מייל `apps/mail` | Gmail | **≥ 6 conversations** visible (was 2.7); avatar, sender + date, subject + star, one preview line; unread bold; bounces bundled into one row | one-line rows with sender, subject — preview, date; ≥ 15 rows at 800 high | open = 1 tap; archive = 1 swipe (with undo); select = long-press or avatar tap |
| קבצים `apps/drive` | Google Drive | ≥ 8 files as rows (icon, name, owner/date, size) or 2-column grid; one search | list with columns name / owner / modified / size, sortable; ≥ 15 rows | open = 1 tap; share and download = the row's ⋮, 2 taps |
| פגישות `apps/meet` | Google Meet | the join screen: camera preview + «הצטרפות» above the fold; in a call, the controls bar always reachable | the grid fills the window; controls bar of ≤ 7 buttons | join = 1 tap from the link |
| צ'אט `apps/chat` | WhatsApp (and Slack on desktop) | ≥ 8 conversations with avatar, name, last line, time, unread count | two panes (list + thread); composer always visible | reply = 1 tap into the composer |
| משימות `apps/project-pln` (Plane) | Linear | ≥ 8 items with key, title, state, assignee; filters as one row of chips | list grouped by state, keyboard first (C to create, / to search) | create = 1 tap («+»); change state = 2 taps |
| הקונסול `platform-base/console` | the Google Workspace shell | one bar (app name, the app's search, account); a tab bar of 5 | the app frame takes everything but one bar | switch app = 1 tap |
| בינה `apps/bina-ds` | the ChatGPT / Claude apps | the composer always at the bottom; the conversation list one tap away | sidebar of conversations + thread | ask = type and send |
| INDOX `apps/indox` | Dext / Hubdoc | ≥ 6 documents with supplier, amount, date, state chip | table with the same columns + the document stage | approve = 1 tap |

What these leaders do that our screens did not, seen on the owner's own phone on 2026-11-09 (mail on
staging): two headers and two searches, a toolbar card inside the console's frame, a checkbox on every
row, no avatar, no preview, a label pill «+2» on every row, and two delivery-failure notices in the first
three rows. Each of those is a rule above.

## How each app is done

One app at a time, in this order: mail, drive (after DGO-1500's split lands; its screens are that
session's until then), chat, tasks, meet, the console shell, Bina, INDOX. For each:

1. Before/after shots at the phone and desktop profiles, light and dark, with the measured numbers.
2. The interactive mock built on the owner's own screenshot when he sent one (AGENTS.md rule 11).
3. Tests, the gates on a probe worktree (with G27/G82), a second reader, commit, report on DGO-1507.
