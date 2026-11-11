# Operating «Google Drive» (the `drive-google` engine)

Google Drive, an EXTERNAL engine of «קבצים» (the generic `drive` app; apps/drive/ENGINES.md). Nothing of
Google runs in the office: this engine bridges the Drive API v3 for each Google account the office
connects. It has no screen of its own: you never call it directly — work through «קבצים».

## Two kinds of account (each a vault instance)

- **A person's account, signed in with Google** (`drive_google_oauth`): «קבצים» › «חיבור Google Drive» ›
  «התחברות עם Google». One consent connects the account's Drive and Gmail; it returns through the herd's
  one redirect address (connections `OAUTH_RELAY_URL/oauth/relay`). Sees and changes everything in that
  Drive. Needs the herd's Google OAuth client (DGO-1392) — when Google answers `invalid_client`, the
  dialog says so and offers the second way.
- **A service account** (`drive_google_service_account`): the office's own address at Google
  (`…@….iam.gserviceaccount.com`). A person shares folders with that address in Google Drive (Share ›
  Editor), and they appear in «קבצים». It reads, downloads, moves, renames and trashes what was shared;
  it cannot CREATE files (a service account has no storage of its own).

## The four channels

- **ui** — inside «קבצים»: each account is a drive under «כוננים»; «חיבור Google Drive» connects one.
- **cli** — `./bbox drive -p <address> ls /…` (a Google account is named by its address);
  `./bbox drive-google status` says whether the engine answers and lists its accounts.
- **api** — `drive-engine.v1` at `http://drive-google:8989`: «קבצים»'s, not yours. Use «קבצים»'s routes
  with `connection_id=<the account's id>`.
- **flow** — none of its own.

## Rules

- A Google account's files are its owner's: read them for the task you were given; never copy them out
  of the office or between drives unless asked.
- Never delete; trash only with the owner's words. A Google Doc/Sheet/Slides file has no bytes of its
  own: «קבצים» exports it (PDF to view, the Office file with `dl=1`).
- Never print a grant, a token or a service account's key.
