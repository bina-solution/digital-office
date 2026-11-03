# Operating `meet`

The office's video meetings: **Jitsi Meet** (docker-jitsi-meet `stable-11248`), self-hosted, Hebrew
and right-to-left. A **room** is a name in a URL (`meet.<domain>/<room>`); the same name is the same
meeting. A **host** is someone from the office, signed in; a **guest** is anyone with the link and
waits until a host is in. The detail behind every line here: README.md.

## How a meeting opens — every screen is Jitsi's own
The tile (`meet-start` at `/a/meet/`) lands on Jitsi's welcome page; its card offers a new meeting as
host (`/a/meet/new`) and the recordings (`/a/meet/recordings`). "I am the host" goes to
`TOKEN_AUTH_URL` = `console.<domain>/a/meet/r/{room}`. `new` and `r/<room>` mint a JWT (HS256,
`MEET_JWT_SECRET`, iss `dgo`, aud `jitsi`, one room, 4 h) and redirect to `meet.<domain>/<room>?jwt=…`,
Jitsi's pre-join page as moderator. The console frames apps with `allow="camera; microphone; …"`.

## Services
`meet` (web), `meet-prosody` (XMPP), `meet-jicofo` (focus), `meet-jvb` (bridge, UDP `MEET_JVB_PORT`,
10000), `meet-turn` (TURN/TLS on 443 through the edge, for networks without UDP), `meet-jibri` (the
recorder, its watchdog `jibri/watch.py` beside it), `meet-start` (the host's door; its machines' port
answers n8n and the watchdog). Private network `meet-net`; meet-start is on the shared one too. P2P
is off: all media goes through this bridge. Names and chat but no video = the media path.

## Recording, safeguards, live captions
- `meet-jibri` (Chrome + ffmpeg, 1280×720) writes `recordings/<session>/<room>_<time>.mp4`;
  `jibri/finalize.sh` adds the `.ogg`. `mod_meet_auto_record.lua` starts it once per room when the
  first host is in (`MEET_AUTO_RECORD`, default 1). ONE recording at a time: a second meeting at the
  same time is not recorded.
- The watchdog measures ffmpeg's pace, its lag and the cgroup's throttling every 5 s while recording:
  three bad ticks → «⚠️ ההקלטה מאבדת קול/תמונה» in the room and a warning notification;
  `<room>_<time>.capture.json` beside each video. `mod_meet_silent_mic.lua` and the page's red banner:
  no microphone, never heard, or gone silent → told within 10–20 s. `mod_meet_share_notice.lua` tells
  the sharer.
- Live captions: each person's own browser captions that person's voice (Web Speech API on Jitsi's
  microphone track; in Chrome that is Google's speech service), shows it to the room over the video,
  and `mod_meet_captions.lua` writes it down per meeting (`/var/lib/prosody/meet-captions`, door
  `/meet-captions` on 5280). Office switch: `config.dgoCaptions.mode` in `web/custom-config.js`. The
  server's own near-live captions (`MEET_LIVE_CAPTIONS`, auto = only with ≥4 cores) trail ~2 min on 2.

## Transcripts → Plane (DGO-834)
`blueprint/n8n/meetRecordings01`, run one at a time by meet-start (`MEET_WORKFLOW_HOOK`): audio →
`speech` twice (ivrit/he and whisper/auto, untranslated, DGO-955) → one MEET item per recording.

## «קדימה» after a meeting
The meeting's page stays «עיבוד ראשון» until `tools/flow/` writes its flow folder; tasks live only in
Plane, questions only what blocks work. The six steps: README «קדימה after a meeting».

## Doors
- `./bbox meet new` — a room, the host's link (a signed-in person opening it is the host) and the
  guests' link; give the owner both. `./bbox meet recordings [N]`, `./bbox meet meetings [N]` — the
  newest recordings and meet-flow meetings, read from the volume.
- `./bbox meet verify` — health, the recorder's CPU cap and weight, its watchdog, jicofo's recorder,
  the bridge's address, conferences now.
- `docker logs meet-jibri-<name> | grep meet-watch` — the watchdog's trail.
- `GET http://notifications:8977/api/notifications?source=meet-recorder` — what it had to say.
- `docker exec meet-jvb-<name> curl -s localhost:8080/colibri/stats` — the bridge's own counters.

## Traps
- Empty `MEET_JWT_SECRET`: prosody refuses to start. Empty `MEET_RECORDER_WATCH_SECRET`: nobody is
  told and the captions door answers 503. `hooks/prepare` mints both.
- `prosody/*.lua`, `jibri/watch.py`, `web/plugin.head.html` are bind-mounted FILES: write them in
  place, never by a rename. The page is served at once; prosody and the watchdog read theirs at start:
  restart only with `colibri/stats` conferences == 0 and Jibri IDLE.
- `web/custom-config.js` is read when `meet` (web) STARTS (appended into its config.js): restart `meet` after
  editing it (conferences == 0 — its nginx carries every meeting's websockets). plugin.head.html is live.
- After a prosody restart, restart jicofo too (it may never register a Jibri that joins later), then
  `./bbox meet verify` (issues/meet-jicofo-loses-the-recorder-after-prosody-and-jibri-restart-in-a-row.yaml).
- Changing `MEET_JWT_SECRET` invalidates the tokens already handed out (4 h at most).
- Host-door room names: what Jitsi accepts (Hebrew too), ≤200 characters, none of `/?&:"'%#`.
- This file is injected into every agent session: the render refuses it over 6000 bytes.
