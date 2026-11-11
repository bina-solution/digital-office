# Operating «סלאק» (the `slack` app)

Slack's own Linux client inside the office (ai/context/wrapped-official-app.md, DGO-1264):
- its screen is the console's tile (Slack under Selkies, behind the front door). amd64 only: Slack ships no
  arm64 build for Linux, so it runs on the HP and vps1, not on the MacBook's engine;
- its headless side is the adapter at `http://slack:3094` (`chat.v1`: probe, listConversations,
  getConversation, sendMessage, markRead), over Slack's official Web API;
- both live in the volume `slack_home`: the screen's sign-in in `desktop/`, the adapter's token in
  `adapter/` (the only folder the adapter mounts).

The adapter uses the owner's USER token (`xoxp-…`, or a rotating `xoxe.xoxp-…`) of a Slack app installed in
his workspace. A bot token would not act as him, and is refused. The app's user scopes:
- `channels:read groups:read im:read mpim:read` (the list);
- `channels:history groups:history im:history mpim:history` (reading);
- `chat:write` (sending);
- `channels:write groups:write im:write mpim:write` (marking read).

Keep it an INTERNAL app of his own workspace. Since 2025-05-29, a non-Marketplace app that is distributed
commercially reads history at 1 request a minute. Installing it and copying the token are the owner's steps.

## What you can do from here

```bash
./bbox slack status [--json]
./bbox slack login --token-stdin < token-file        # never on the command line
./bbox slack rooms [N]                               # id · name · channel|private|dm|group-dm, in Slack's order
./bbox slack read <channel id> [N]
./bbox slack send <channel id> <text…>
./bbox slack mark-read <channel id> <ts>
./bbox slack logout
```

## Rules

- `send` is a message to people, as the owner: it runs only on the owner's word.
- The sign-in and the token are the owner's. Never sign out the screen. `logout` only forgets the token;
  revoking it is done in his Slack app.
- Act through the adapter (`chat.v1`), never through Slack's files.

## Traps

- The screen's sign-in goes out to a BROWSER and comes back on a `slack://` link. The desktop image has no
  browser yet, so signing in on the screen is DGO-1264's next slice (bina-claude's sign-in browser,
  DGO-1506, is the pattern, and Element needs the same). The adapter works without it, on the token.
- Slack answers HTTP 200 with `{"ok": false, "error": …}`. The adapter passes the name on with 403
  (`invalid_auth`, `missing_scope`, `not_in_channel`…; 401 is the adapter's own token gate), and the scope
  it needs is in `detail`. A revoked token signs the adapter out: `status` asks Slack.
- A rate limit is 429 with how long to wait (`Retry-After`, and `retry_after` in the body).
- The client's version is pinned with its sha256 (Dockerfile.desktop). A new Slack is a deliberate bump.
- No flow yet: the adapter does not listen to Slack's events, so nothing is published on `dgo:flow:slack`
  (G108 KNOWN).
