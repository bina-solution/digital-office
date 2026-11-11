# bina-claude — «בינה קלוד»: Claude inside the office

**Bina Claude is ONLY the official Claude Desktop app with ONE login; there is no terminal; never propose
/login or a terminal.** (The owner, 2026-11-09, DGO-1684: «Delete the terminal and make sure nobody gets
mixed up again». Gate G105 holds it.)

The app is streamed into the console tile «בינה קלוד» and signed in to the owner's Claude account. Every
channel runs on that one sign-in: the screen (UI), `./bbox …` (CLI), agent.v1 on :3091 (API) and the office
timeline's lane `bina_claude` (flow). Its sessions are office data on one volume.

- Every Claude session of the app: `./bbox bina-claude sessions`; one conversation: `./bbox bina-claude show
  <id>` (`--json` on both).
- Ask Claude and wait for the answer: `./bbox bina-claude ask "<text>"`
  (= `./bbox agent --app bina-claude new -F "<text>"`).
- Its sessions: `./bbox agent --app bina-claude list|show <id>|send <id> "<text>"|follow <id>|log <id>|cancel <id>`.
  Another office's: `./bbox agent --office <office> --app bina-claude …` (over its link, or over this office's
  Computers app while there is none).
- Is it signed in, and if not why: `./bbox bina-claude signed-in` (exit 3 = signed out, 1 = unknown).
  `./bbox bina-claude status` is the adapter's view. A lost sign-in rings a notice by itself (adapter/signin-watch.mjs).
- Signing in is the owner's step (a `בעלים` item), in the desktop tile only: «Continue with Google» (Google's
  page opens on the same screen, computer or phone) or «Continue with email» (the link opened on the phone
  shows a code to type in the app). Never type a password, a code or a consent for him.
- The app's sessions run with full access to the checkout and the engine, like Azaria, and reach Azaria with
  `./bbox agent …`.
- Never restart bina-claude-desktop from a session it is running, and back up its `/config` (the volume's
  `desktop` folder) before any recreate.
