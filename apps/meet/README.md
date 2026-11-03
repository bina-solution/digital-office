# meet — the office's video meetings (Jitsi Meet)

Work item: DGO-824. The owner, 2026-10-20: «adding an app for jitsi meet to enable video calling
online from the staging dgo … fully declarative and rtl and out of the box like we do for plane n8n
deepseek harness … deeply investigate on other fully open source alternatives and rate».

## The choice, measured (2026-10-20)

Stars and releases from GitHub; the Hebrew share is each project's Hebrew catalogue measured against
its own English one.

| App | Stars | Release | License | Hebrew / RTL | What it takes to run |
|---|---|---|---|---|---|
| **Jitsi Meet** | 30,111 (+3,619 docker) | stable-11248, 2026-09-14 | Apache-2.0 | 39% (631/1,598), no RTL | 4 containers, UDP 10000 |
| plugNmeet | 576 | v2.5.3, 2026-10-12 | MIT | 100%, real RTL | LiveKit + Redis + MariaDB; one maintainer |
| BigBlueButton | 9,247 | v4.0.0, 2026-10-14 | LGPL-3.0 | 52%, RTL | a whole server: 16 GB / 8 cores |
| LiveKit + Meet | 21,685 | v1.13.10 | Apache-2.0 | Meet: English only | light, but Meet is a demo |
| OpenVidu v3 | 2,137 | v3.9.0 | Apache-2.0 (+PRO) | — | 8+ containers, 4 GB |
| Element Call | 1,015 | v0.28.0 | AGPL-3.0 | none | needs Matrix |
| Nextcloud Talk | 2,217 | v25.0.6 | AGPL-3.0 | ~25% | needs Nextcloud |
| MiroTalk SFU / P2P | 3,131 / 4,800 | v2.6.54 / v2.1.78 | AGPL-3.0 | none | one container |
| Galene | 1,420 | 1.2.1 | MIT | English | no official image |

Jitsi Meet, as asked: the largest community, mobile apps, four containers, every setting an
environment variable, recording and transcription from the same project. Its gap is Hebrew, and the
gap is closed here, in the wrapping, the way Plane's is:

- **The catalogue.** `lang/main-he.json` = upstream's 631 strings + the 967 it lacked (and the 8 it
  left empty), translated against upstream's own Hebrew as the glossary, placeholders checked
  mechanically (`{{x}}`, `$t(…)`, tags: equal in every new string). Terms unified across the file:
  חדר המתנה (lobby), חדרי קבוצות (breakout rooms).
- **The direction.** Jitsi sets no `dir`. `web/plugin.head.html` — Jitsi's own include point, after
  config.js — sets `dir`/`lang` on `<html>` from Jitsi's own language choice, and follows a change.
- **The default.** `DEFAULT_LANGUAGE=he` and `LANG_DETECTION=false`: a browser set to English still
  opens in Hebrew; a person who picks another language keeps it.

No image is rebuilt: the four images are upstream's, pinned; everything of ours is a read-only file
mounted at an include point the image already reads.

## Who may open a meeting

Jitsi's JWT mode. A room is opened only with a token, so the meeting host cannot be used by the
internet at large; guests join an open room by its link (`ENABLE_GUESTS`) and wait for a host if
they are early. The token is minted by `meet-start`, which stands behind the office sign-in and so
knows who is asking — the same identity every office app reads (`use: identity`). P2P is off and
STUN is not used: every call's media goes through the office's own bridge, nothing to jitsi.net.

## Recording, by default (the owner: «by default the videos to be saved … in the VPS»)

The official recorder, Jibri (`ghcr.io/jitsi/jibri:stable-11248`: Chrome + ffmpeg, a 2 GB shm, no
kernel module in this release), writes each meeting into this app's volume `meet_recordings` on the
office's own server.

**The server starts it** (DGO-831, the owner: «שזה יקליט לי את המסך גם כשאני לבד וישמור הכל»).
`prosody/mod_meet_auto_record.lua`, a module in the prosody image's own plugin folder, sends the
request Jitsi's record button sends, from a host's own session, once per room. So Jitsi's own
checks and its recording metadata apply as for the button. It works from every client: the web page,
and the Jitsi Meet phone apps, which run no page script. It also works when the host is alone: the
recorder becomes the room's second participant, and jicofo starts a meeting's media only at two.
`MEET_AUTO_RECORD=0` in `.env` leaves recording to the button. A start that fails, such as when the
one recorder is busy, is logged by prosody and shows nothing on screen.

**The sharer is told** (DGO-832, the owner: «when I click share screen, I get no feedback … It must
be clear that it's working»). A phone app shows no preview of its own shared screen, and Android's
picker says nothing once it closes. `prosody/mod_meet_share_notice.lua` watches each participant's
presence: when it first announces a live desktop source, the server sends that participant, and only
them, a chat message from the room, which the web page and the phone apps pop up, with the message
sound, and keep in the chat: «✅ המסך שלך משותף עכשיו» (with «ומוקלט» while the meeting is recorded),
and «שיתוף המסך שלך הופסק» when it ends. Jitsi's own "system" chat message would not do: the client
shows it as a chat line with no pop-up (it carries a timestamp, and only a message without one is
popped up).

`recordings.showPrejoinWarning` tells everyone before they join, and Jitsi shows the recording label
to all. `/a/meet/recordings` lists the files with who was there (Jibri's `metadata.json`).
Browser-side "local recording" is switched off: a record on one laptop is not the office's record.

## Every recording, transcribed, in Plane (DGO-834)

The owner, 2026-10-21: «every time something it saved, so it would create a plain ticket with video
… and then also give the full transcription there … everything ready on our plane».

1. **The sound.** Jitsi's own hook for a finished recording, Jibri's finalize script
   (`jibri/finalize.sh`, `JIBRI_FINALIZE_RECORDING_SCRIPT_PATH`), writes the meeting's audio beside
   the video: `<room>_<time>.ogg`, 16 kHz mono Opus, about 15 MB an hour. Jitsi itself transcribes
   only live meetings (Jigasi), never a finished file.
2. **The door.** `meet-start` lists the finished recordings as data on a second port (8001), which
   the edge routes nothing to and which answers only n8n's containers (`MEET_MACHINE_PEERS`):
   `GET /api/recordings` and `GET /api/recordings/<session>/<file>.ogg|.mp4`.
3. **The workflow** (`blueprint/n8n/meetRecordings01.workflow.ts`, declared in `app.json` like
   INDOX's), run by meet-start the moment a recording ends and every five minutes besides (see
   «Where it runs»):
   - sends each new recording's audio to the office's `speech` capability (`apitools-asr`) TWICE
     (DGO-955, the owner: «פשוט צריך לתמלל בשתי השפות … בשפה שהדברים נאמרו»; nothing is
     translated): ivrit.ai's Hebrew Whisper (`model=ivrit`, `language=he`, compared on the office's
     recordings in DGO-833), and OpenAI's own Whisper (`model=whisper`, `language=auto`: each stretch
     in the language it was spoken). Two jobs there at most, and nothing while it is down or its
     queue is full;
   - collects finished transcripts. A one-hour meeting takes over an hour on vps1, so nothing
     waits: the jobs in between live in the workflow's static data. Plane is the record: a
     recording that already has its item is never sent again, even if that data is lost;
   - writes one item per recording in Plane project **MEET** «פגישות»
     (`apps/project-pln/plans/meetings.yaml`) as soon as its Hebrew transcript is there (a Hebrew
     pass with no words waits for the Whisper one: it may have been an English meeting): the room,
     the time, who opened it, the link to the recording, the models (name, revision, compute and
     speed, as the transcriber reports them), the Hebrew transcript and the Whisper one, with time
     marks. A Whisper transcript still being made is said, and put in its place when it comes. A
     pass that fails three times is given up, and the item says so — and that it is tried again:
     six hours later the recording goes round once more (eight rounds in all). One pass given up
     is sent again alone, and its transcript put in place of the line that said it failed (the
     other pass, and anything the owner added, stay as they are); a recording with neither is sent
     again from the start, and its item written over whole. A long recording is transcribed in
     ten-minute pieces, so its length never takes the transcriber past its memory. An item written before there
     were two (it had a translation, or «ממתין לתרגום») gets the Whisper transcript in place of its
     English section, and loses that label: only the paragraphs the writers wrote are replaced.
     A transcriber that does not list the `whisper` model is sent no Whisper pass (the owner is
     told daily). Labels: הקלטה, and תומלל or אין דיבור. The item is keyed by the recording
     (`external_source: meet-recording`), so a repeated run edits it instead of opening a second;
   - tells the owner (the notice centre), with the item's link.

   Plane is reached at `MEET_PLANE_API_URL`, which `hooks/prepare` derives the way
   `bbox project-pln` finds Plane: through the link to the office that runs it, no key in n8n.
4. **The list.** `/a/meet/recordings` links each recording to its item (`MEET-10`, opened in the
   console), and says «בתמלול…» while a recent one has none yet. meet-start reads the items from
   Plane (project MEET, `external_source: meet-recording`) once a minute.

### Where it runs, and what starts it (DGO-907)

The owner asked (2026-10-21) where the automations run, believing it was on the HP. They run
**in the office that runs the app**, because that is where the app's data is:

| What | Where | Why there |
|---|---|---|
| Jitsi, the recorder, the recordings | vps1 (`meet`, `meet-jibri`, volume `meet_recordings`) | a public office: phones and guests reach it |
| The transcriber (`apitools-asr`, ivrit.ai + Whisper) | vps1 | beside the audio; nothing leaves the office |
| The workflow `meetRecordings01` | **vps1's own n8n** (`n8n-staging`), imported by `bbox n8n push meet` | an app's blueprints go into the n8n of the office that runs the app (app-management `_blueprint_apply`); one n8n per office, never federated |
| Plane, project MEET | the HP (`project-pln`), reached from vps1 through the link | the office's one Plane |

**What starts a run:** meet-start runs the workflow through its webhook (`MEET_WORKFLOW_HOOK`,
n8n's webhook service):
- the moment a recording ends (meet-start sees Jibri's `metadata.json` and its sound);
- then once a minute, for the quarter hour after it ended, while it has no item yet. A short
  meeting's item then lands a minute after its transcript;
- and every five minutes, for everything else: a long meeting's transcripts, a retry.

The runs come one at a time. The webhook answers when its run ends, and meet-start waits for that
answer before its next call; a reason that comes meanwhile becomes one run after it. Two runs at
once would upload and write the same recording twice.

The workflow's own clock, every 15 minutes, is the safety net. It does nothing while meet-start's
call is going (for twenty minutes at most: a longer one hangs) or its last one worked within ten
minutes; meet-start's door says both. When the webhook does not answer (n8n's webhook service
down), the clock does the work. Two runs can still meet, seldom: a clock run that began just before
meet-start's call, or meet-start restarted while its run went on. Plane refuses a second item for
one recording, so even then there is one item. Only the office's
own network may call the webhook: the edge publishes `/webhook/*`, and a caller from outside is
answered 403.

The first call, on 2026-10-21, waited for the clock: the call ended at 12:48:57, the 12:50 run sent
it to the transcriber, and the 12:55 run wrote MEET-10. That is five to ten minutes. With the
webhook it is the transcription time plus at most a minute.

**Where to see it:**
- n8n's own tile in this office's console, «n8n» (the editor, with its own sign-in: every run,
  every node). It is framed on `n8n.console.<domain>`, which n8n's own routers answer
  (`apps/n8n/docker-compose.yml`). Each office's console shows its own n8n, so these automations
  are in **vps1's** console;
- **any-concurrency**, every run as a bar labelled by what it did («2 לתמלול · 1 לכתיבה»). From a
  linked office (the HP), the same view comes through the link as «any-concurrency · vps1».
- vps1's n8n is not yet framed inside another office's console. Through the link, n8n refuses
  the frame and its live updates, and the fix is the link's: DGO-912.

### The target: the transcriber on the Dell, the workflow in the HP's n8n (DGO-945)

The owner, 2026-10-21: «transcription and LLMs and heavy stuff like that should work always on the
portable machine … meet stays on the VPS, plane … and n8n … on the HP». So:

| What | Where |
|---|---|
| Jitsi, the recorder, the recordings, meet-start | vps1 |
| The transcriber (`apitools-asr`) and the local LLMs (Ollama) | the Dell |
| n8n, with this workflow, and Plane | the HP |

Nothing in the workflow names an office. Each office declares its own half, and the platform
does the rest:
- **A door with no tile.** The office that runs an app offers a capability to its links with
  `link: true` (`apps/apitools/app.json` `speech`, this app's `recordings` on meet-start:8001,
  `apps/n8n/app.json` `workflow-hooks`), and gives it BY NAME, to the offices it names, in its own
  `serve:` (`serve.services`; a door is never given under `*`). A linked office reaches it at
  `http://<name>.<office>:<door>`; no tile, edge route or sign-in is drawn for it
  (`ai/context/dgo-remote-apps.md` § 8). The three offices' declarations:
  - the Dell: `"services": {"speech": {"to": ["hp-laptop"]}}`;
  - the HP: `"services": {"workflow-hooks": {"to": ["vps1"], "paths": ["/webhook/meet-recordings"]}}`
    — vps1 can start this one workflow and reach no other webhook, and the peer's forwarding headers
    never reach n8n's IP allow-list;
  - vps1: `"services": {"recordings": {"to": ["hp-laptop"]}}`. meet-start lets the link in only for
    the office Meet's workflows run in (`MEET_WORKFLOWS_OFFICE`, from `workflows:`), and relays to
    Plane only the workspace's project list (read) and project MEET.
- **Where the workflows run** is the app's entry in `platform.state.yaml`:
  - on the HP, `meet: { state: disabled, workflows: here }`: the HP's n8n imports Meet's workflows
    although Meet runs elsewhere;
  - on vps1, `meet: { state: enabled, workflows: hp-laptop }`: vps1 runs Meet and imports none of
    its workflows.
  An app without the field keeps the old rule, so a switched-off app is never imported
  (`reconcile.py` `workflows_here`).
- **Push points the workflow at the doors.** On an office that does not run an app, `bbox n8n push`
  rewrites that app's addresses in the compiled workflow to the linked office's door. On the HP,
  `http://meet-start:8001` becomes `http://recordings.vps1:<door>`, and
  `http://apitools-asr:8987` becomes `http://speech.dell:<door>`. Every rewrite is printed
  (`scripts/link-endpoints-apply`, map: `reconcile.py link-endpoints`), and `bbox n8n pull` turns
  them back, so the shared blueprint never carries an office's door. An HP that runs apitools itself
  (INDOX's OCR) would keep its own transcriber; `apitools: { state: enabled, by: user, linked: dell }`
  sends its transcription to the Dell and leaves the OCR home (`reconcile.py` `linked_from`).
- **Plane through meet-start.** The workflow's Plane calls go to meet-start's `/api/plane/…`.
  meet-start relays them to `MEET_PLANE_API_URL`, the link door that signs the call in. So the
  workflow holds no key, in whichever office's n8n it runs. Only what the workflow writes is relayed:
  the workspace's projects (read) and everything under project MEET.
- **meet-start calls the HP's webhook.** With `workflows: hp-laptop`, `hooks/prepare` reads the HP's
  `workflow-hooks` door from the compiler's `remote:` block (`reconcile.py remote-get`) and writes
  `MEET_WORKFLOW_HOOK` = `http://workflow-hooks.hp-laptop:<door>/webhook/meet-recordings` and
  `MEET_WORKFLOWS_OFFICE=hp-laptop`. The run still comes one at a time; the link door holds a
  connection for as long as the run takes. With no such door, meet-start calls nothing and the HP's
  own clock (every 15 minutes) runs the workflow.
- **The move, in order** (so no recording is written twice): on vps1, `bbox n8n unpush --app meet`
  first (its own copy of the workflow stops), then `workflows: hp-laptop`; on the HP, `workflows: here`
  and `bbox n8n push meet`.

**The model, measured on the owner's own call** (2026-10-21: he read Psalm 1 in the call
ahrarey-haish and asked for the transcript to be compared with the text). The psalm's 67 words
were transcribed by each candidate, with the transcriber's own options (Hebrew, beam 5, VAD), and
scored by word error rate. Two scores are given:
- strict;
- lenient: the Name read «אדוני», and full and defective spelling counted as one word, since
  neither is a mistake of hearing.

| Model | Strict | Lenient | Speed (4 cores) | Weights |
|---|---|---|---|---|
| **ivrit-ai whisper-large-v3-turbo, int8** (the office's) | 19.4% | **7.5%** (5 words) | 4.4× real time | 0.8 GB |
| the same, float32 | 17.9% | 6.0% (4 words) | 2.7× | 3.2 GB |
| the same, newest revision / beam 8 | 19.4% / 20.9% | 7.5% | — | — |
| ivrit-ai whisper-large-v3, int8 | 16.4% | 9.0% (6 words) | 0.96× | 1.6 GB |

The office's model stays. Full precision gets one word more right in 67, and needs four times the
memory, which vps1 does not have free (under 1 GB available). The large model is 4.6 times slower,
and is no better on the mistakes of hearing. (Weights are the models' parameters times their
precision; the newest revision gave the pinned one's words exactly.)

The mistakes that remain are words a listener could also mishear:
- בעתו → ביתו;
- תדפנו → תדבנו;
- the psalm's last word, «תאבד», heard as «טובים».

The recording itself is attached to its item («upload the file to Plain»): the video when Plane takes
its size (its `FILE_SIZE_LIMIT`, 50 MB on this office's Plane: about ten minutes of meeting), else its
sound (about 15 MB an hour), and the item then says the video is at its link. Plane signs an upload
form; `meet-start`, the one container that holds the file, posts it to Plane's store through that
form (`POST /api/recordings/<session>/<file>/to-plane` on the machines' door, only ever to
`MEET_PLANE_API_URL`'s `/uploads`); the workflow tells Plane the file arrived. A store that does not
answer leaves the recording for the next run, which attaches it to the same item.

## Never again betrayed by a silent recording (fireplace, 2026-10-26)

Two failures in one day, both silent: the owner joined from a Mac Chrome that had never been allowed
the microphone (the permission was "prompt"), Jitsi made no audio track, the bridge got 0 kbps and
the recording is mute; and the recorder had been throttled to 0.48 of a core, ffmpeg ran at
0.93–0.97× and 40 % of every second of audio became zeros. Nothing on screen said either. Three
safeguards now speak during the meeting, in the chat (the page and the phone apps pop a room message
up) and, for the recorder, in the notice centre. Everything below was measured with the harness in
`qa/` (`micA.sh`, `throttleB.sh`, `captionsC.sh`: synthetic Chromes joining the live office with a
`qa-host` token, the chat read through CDP).

**The microphone, from the first seconds** (`prosody/mod_meet_silent_mic.lua`, `web/plugin.head.html`).
The server reads each person's SourceInfo and asks the bridge every 5 s what it hears:
- no audio track at all (no browser permission, no device) → `MEET_NO_MIC_SECONDS` (10) after the
  bridge has the person's media connected (ICE), a private message with the fix (lock icon →
  Microphone → Allow), and the room is told whose voice is missing. Measured: the warning 10 s after
  the person was first seen, the room note at the same moment, «✅» to all within 10 s of the
  microphone appearing. Not counted from the join (2026-11-01, `verify-261101-1448` on vps1): a
  client lists its sources only once jicofo has invited it to the bridge, and jicofo invites nobody
  while they are alone in the room — the host, its microphone on 1 s after joining, was told «no
  microphone» 12 s in, before its invitation, and its audio arrived 10 s later;
- unmuted, but the bridge has heard nothing since the join → the same, 10 s after the bridge lists
  them (a track's first packets at unmute do not count as "heard": speech-rate packets, or two
  rounds, do);
- heard, then silent for `MEET_SILENT_MIC_SECONDS` (20) → the Android advice, as before.
A microphone muted on purpose is a muted source in SourceInfo (`{"<id>-a0": {"muted": true}}`,
measured) and is never a failure. The page adds a red banner at the top once joined without a local
audio track — the wording follows `navigator.permissions` (denied / prompt / no device) — with an
«Enable microphone» button that asks the browser again; it goes when a track appears. Never on the
recorder's own page.

**The recorder's watchdog** (`jibri/watch.py`, an s6 longrun inside meet-jibri; `prosody/mod_meet_recorder_watch.lua`
and meet-start's `/api/recorder/*` are its two doors, behind `MEET_RECORDER_WATCH_SECRET`). While Jibri
is BUSY it measures every 5 s the pace of ffmpeg between two of its progress lines, the lag behind
the clock, the share of scheduling periods the kernel throttled this container, ffmpeg/pulse errors
and Jibri's health; three bad ticks → «⚠️ ההקלטה מאבדת קול/תמונה — המקליט לא עומד בקצב (…)» to the
room and a warning notification; three good ticks → «✅ ההקלטה חזרה לקצב מלא». Measured on a test
call: `docker update --cpus 0.4` at 21:11:32Z → the warning at 21:11:47Z ("88 % of the time"); the
cap restored at 21:12:37Z → «✅ (after 71 s)» at 21:12:58Z; one notification row per recording,
warning then info; `cpu.max 200000 100000`, weight 942, `memory.low` 1.25 G after. Each recording
gets `<room>_<time>.capture.json` beside its video (wall vs recorded seconds, lost seconds, min
pace, throttled periods, the events). `./bbox meet verify` now fails when the recorder's cap is
under 1.5 CPUs, when the watchdog is not running, or when jicofo counts no recorder.

### Live captions, measured

`MEET_LIVE_CAPTIONS` (`on` | `off` | `auto`, default `auto`): the same watchdog reads PulseAudio's
`jibri-loop.monitor` — the mix Jibri records — into 30-s, 16 kHz mono WAVs (30 s is the
transcriber's measured sweet spot), sends each finished one through meet-start to the office's
transcriber (`/transcribe`, synchronous; `MEET_LIVE_CAPTIONS_LANGUAGE` `auto` = the whisper model,
each stretch as spoken, `he` = ivrit), posts the text as a quiet chat line from «כתוביות» (a delay
stamp: no pop-up, no sound; the page shows the newest line over the video for 25 s) and appends it
to `<room>_<time>.live.txt` beside the recording. Silent segments are not sent, and «Thank you.»
on near-silence is dropped. A backlog over three segments is dropped oldest-first and the room is
told once that the transcriber is behind. `auto` turns captions on only when the machine has at
least `MEET_LIVE_CAPTIONS_MIN_CORES` (4) cores AND the recorder is healthy; a file
`/run/meet-watch/captions` inside meet-jibri (`on`/`off`/`auto`) overrides it at runtime.

Measured on this 2-core box, forced on for a 4-minute test call (host and guest speaking English
TTS, the recorder recording, two synthetic Chromes on the same machine; `qa/captionsC.sh`, room
fpgwatchd):

| What | Measured |
|---|---|
| Captions posted | 4 lines, text correct («This is the fireplace office recording check…», the counting, the alphabet) |
| Transcription time per 30-s segment | 125 s (first: the whisper model had to load), then 82, 49, 31, 34 s |
| Lag behind the meeting | 78–137 s, median 126 s; 4 of 12 segments dropped as backlog |
| The recorder meanwhile | 0.31–0.49 cores, **0 of 3634 periods throttled**, pace never under 0.98, no «⚠️» |
| The transcriber | 0.42–0.82 cores (`SPEECH_CPU_THREADS=1`, weight 1 under the recorder), 11 periods throttled |
| The machine | load1 up to 12 (the test's own Chromes included), 1.5 GB available at the least |

So on 2 cores captions **do not starve the recorder** — the weights do their job — but they are not
live: one thread of the transcriber is slower than real time once anything else runs, the lag grows
past two minutes and segments are dropped. That is why `auto` is off here and the switch is not set.
On a KVM 4 (4 cores / 16 GB): the recorder keeps its two cores and the transcriber gets two of its
own; one segment at the measured idle speed (~1.4× real time) takes ~21 s, so the text would trail
the meeting by 30–60 s, which is what this design promises. Two things to set with it:
`SPEECH_CPU_THREADS=2` for the transcriber (it is pinned to one thread today), and
`MEET_LIVE_CAPTIONS_LANGUAGE=he` for Hebrew meetings, so the live pass uses the ivrit model the
recordings' workflow keeps warm instead of paying a model switch for the first segment. Sub-second
captions remain a GPU feature.

## Load, measured on the 2-core office (fireplace, 2026-10-27)

The owner: «שיחות עם ווידאו חי, קול דיבור, שיתוף מסך ומספר הולך וגדל של משתתפים … לדעת בדיוק מתי מגיעים לקצה».
Ramps against the live office from a laptop (`%TEMP%\fpgsr` on the owner's machine: `ramp.py`, `light.js`,
`lightctl.py`, `analyze.py`; the server side `/root/sampler.sh` → `/root/meet-load/<tag>.csv`): one full Jitsi
page as host (its real microphone track captioned by the browser) plus lightweight participants — lib-jitsi-meet
tabs on the meeting's own origin, each with a moving camera, ITS OWN Hebrew speech (FLEURS sentences taking turns,
known text) and live captions of it; one of them shares a full-HD screen at Jitsi's 5 fps. Recording on (auto),
two minutes per step, 5-s samples of every meeting container's cgroup, the bridge's colibri stats, the machine.

**Where a recorded meeting's CPU goes.** The recorder, not the bridge: Jibri's Chrome draws the meeting in software
and ffmpeg encodes it. With a shared screen it took 1.25 cores of the box's 2, flat from 3 to 10 people; inside it
Chrome's GPU process (software GL) 0.73, the renderer 0.25, ffmpeg 0.18. VP8 instead of AV1, 15 fps instead of 30
and `--disable-gpu` each changed nothing (1.25–1.26). The cost was Jitsi's blurred copy of the large video behind
it, redrawn every frame: `interfaceConfig.DISABLE_VIDEO_BACKGROUND` on the recorder's page only
(`web/custom-interface_config.js`) → **0.57 cores** (0.58 with Jibri's default Chrome flags, so those stay).

| participants (screen share from 3) | recorder cores before → after | machine CPU pressure before → after | bridge cores |
|---:|---|---|---:|
| 2 | 0.48 → 0.55 (one camera more in the later run) | 32 % → 32 % | 0.09 |
| 3 | 1.25 → 0.56 | 50 % → 33 % | 0.13 |
| 4 | 1.28 → 0.60 | 54 % → 36 % | 0.15 |
| 6 | 1.22 → 0.64 | 57 % → 41 % | 0.22 |
| 8 | (1.02) → (0.54) | 55 % → 46 % | 0.26 |
| 10 | (0.62) → (0.39) | 52 % → 43 % | 0.20–0.35 |

From 6 people on, the LAPTOP generating the load ran out (100 % CPU, received video at 0–6 fps; two Windows
processes there burn ~2 cores permanently), so it sent less than real people would: those rows understate the
server. In every run the recorder was never throttled, the watchdog stayed «ok», and the recordings came out whole
(`holes.json`: 0 % in 20- and 19-minute recordings of up to 10 people with a shared screen). prosody, jicofo and
nginx stayed near 0.01 core each (signalling and the captions relay are not a limit). The bridge costs ~0.035 core
per participant at these rates, and its stress level is its own CPU over its 1-core cap.

**The limits, as measured and as estimated.**
- One recorded meeting at a time (one Jibri). A second meeting at the same time runs, unrecorded: the owner is
  warned, the room is told, and its live transcript becomes its record (start/server.py).
- Measured healthy: 10 people with cameras, speech and a shared screen, recorded, captioned.
- Estimated, not measured (the generator could not go further): the recorder stays ~0.6–0.8 core at any size
  (it receives at most 6 videos: `channelLastN` on its page); the bridge reaches its 1-core cap near ~25
  participants at these rates — the watch warns at stress 0.9 («⚠️ גשר הווידאו בעומס»).
- What a full meeting costs everyone else: 33–46 % CPU pressure on the box — the office's other apps answer
  slower during a large recorded meeting; nothing in the meeting is at risk while the recorder keeps its weight.

**Kept from the ramps:** the blur off on the recorder's page; the recorder receives at most 6 videos; Jibri at
15 fps (half of ffmpeg's work; files only ~12 % smaller); VP8 first for cameras (`web/custom-config.js`: the test
laptop needed 90–99 % CPU for AV1 at 3–4 people, 51–62 % for VP8 — participants' own machines, not the server).

## Operating notes moved from AGENT.md (2026-10-27)

AGENT.md is injected into every agent session and the render refuses it over
6000 bytes, so the operating detail lives here.

### The media path — the one thing that is not HTTP
Two ways in, and a browser takes the first that works:
- **UDP to the bridge** (`MEET_JVB_PORT`, 10000), published on the machine, not routed by the edge.
  `hooks/prepare` publishes it on every interface on a public office and advertises the meet host's
  public DNS address (re-derived each run, marked `MEET_JVB_ADVERTISE_AUTO=1`); on a `.localhost`
  office it advertises 127.0.0.1. vps1's Docker firewall admits it from `.env`
  (`scripts/ops/docker-user-firewall.sh`, the boot script).
- **TURN over TLS on 443** (`meet-turn`, coturn) for a network that lets no UDP out: the edge ends
  TLS for `meet-turn.<domain>` (a TCP router by SNI, hand-written in the compose); coturn relays to
  the bridge's private address only (refusals for its public one are expected). prosody hands out
  expiring credentials.
P2P is off: every call's media goes through this bridge, nothing through jitsi.net. Names and chat
but no video = the media path: `./bbox meet verify` prints what the bridge advertises and publishes.

### Hebrew and right-to-left
`lang/main-he.json` is the full catalogue (its terms: README). `web/plugin.head.html` sets
`dir`/`lang` from Jitsi's language (localStorage `language`), plus two start/end fixes by stable
class labels. The image appends `web/custom-*.js` to its generated config. `?lang=` is ignored
(`defaultLanguage`); a language picked in settings lasts that visit. A new image: re-merge its
`main.json`, re-check the screens.

### Phones
A phone browser cannot share a screen (Android Chrome, iOS Safari; DGO-829), so Jitsi's
deep-linking page stays on: a phone first gets «הצטרף ביישום»
(the Jitsi Meet app, given the whole link with `?jwt=`; it shares) or «הצטרף בדפדפן». The app
reads `config.js` with no `location`, and its own catalogue. On Android 13+ it keeps the mic in
the background only if notifications are allowed (DGO-959): that page and the share notice say so.

### Recording — the office's record of its meetings
`meet-jibri` (Chrome in a virtual screen + ffmpeg, 1280×720) writes
`recordings/<session>/<room>_<time>.mp4` and, at the end, `metadata.json` into `meet_recordings`;
`jibri/finalize.sh` adds `<room>_<time>.ogg`, the sound, for the transcript.
`prosody/mod_meet_auto_record.lua` starts it once per room when the first host is in, from any
client, alone too (`MEET_AUTO_RECORD`, default 1): the button's request, from the host's session.
The recorder is the second participant, so jicofo (media at two) starts a lone host's. A failed
start is only in prosody's log. One recording at a time. `/a/meet/recordings` lists and plays them.
`prosody/mod_meet_share_notice.lua` (DGO-832) tells the sharer, in a chat message only they get,
that the screen is shared (and recorded), and when it stops. `mod_meet_silent_mic.lua` (DGO-959,
and fireplace 2026-10-26) reads the bridge's `/debug` every 5 s and each person's SourceInfo: (1) no
audio track at all (no browser permission, no device) → told `MEET_NO_MIC_SECONDS` (10) after the
bridge has their media connected, with the fix (lock icon → Microphone → Allow), and the room is told
whose voice is missing; (2) unmuted
but the bridge never heard them → the same, 10 s after the bridge lists them; (3) heard, then
nothing for `MEET_SILENT_MIC_SECONDS` (20; 0 = all off) → the Android advice. Once per state, «✅»
when audio arrives. `web/plugin.head.html` shows the same as a red banner on the page (never on the
recorder's page) with an «Enable microphone» button that asks the browser again.

**The recorder's watchdog** (`jibri/watch.py`, an s6 longrun inside meet-jibri, `jibri/s6/`; fireplace
2026-10-26: a recorder starved to 0.48 core lost 40 % of every second and told nobody). While Jibri
is BUSY it measures every 5 s: ffmpeg's pace between two progress lines (Δtime/Δwall; ffmpeg's own
`speed=` is an average since the start), the lag behind the clock, the share of cgroup periods the
kernel throttled (`/sys/fs/cgroup/cpu.stat`, no docker socket), ffmpeg/pulse errors, Jibri's health.
Three bad ticks → «⚠️ ההקלטה מאבדת קול/תמונה…» to the room and a warning in the notice centre;
three good ticks → «✅ …». It speaks through two doors: prosody's `mod_meet_recorder_watch.lua`
(HTTP 5280 on meet-net, `Host: muc.meet.jitsi`, bearer `MEET_RECORDER_WATCH_SECRET` minted by
hooks/prepare) and meet-start's `/api/recorder/*` (the machines' port; meet-start is on meet-net too
for this) → notifications and the transcriber. Measured: `docker update --cpus 0.4` → the warning in
15 s; cap restored → «✅» in 21 s. That prosody module also writes «⚠️ ההקלטה נפלה» when jicofo
reports a recording failure.

**Live captions** (`MEET_LIVE_CAPTIONS`: `on` | `off` | `auto`, default auto = on only with
`MEET_LIVE_CAPTIONS_MIN_CORES` (4) cores AND a healthy recorder; `/run/meet-watch/captions` inside
meet-jibri overrides at runtime). The same watchdog reads PulseAudio's `jibri-loop.monitor` (what
Jibri records) into 30-s 16 kHz WAVs, sends each through meet-start to the transcriber
(`/transcribe`, `MEET_LIVE_CAPTIONS_LANGUAGE` auto = whisper as spoken, he = ivrit), posts the text
as a quiet chat line from «כתוביות» (a delay stamp: no pop-up, no sound; the page shows the newest
over the video) and appends it to `<room>_<time>.live.txt`. Silent segments are not sent. On this
2-core box auto = off: see README «Live captions, measured».

## «קדימה» after a meeting — its full processing, one path (MEET-48, DGO-1134, 2026-11-02)

The owner: process it so the meeting page is complete and tasks live only in Plane. The page
(`/a/meet/flow/<room>/`) stays «עיבוד ראשון» until the meeting has a flow folder; nothing else
fills it. So, every time:

1. The recording and its two transcripts (the MEET item's, or `speech` on the `.ogg`). A recording
   with no index is rebuilt first (`tools/restore/rebuild_moov.py`; finalize.sh does it by itself).
2. An analysis JSON from the transcript: title, who, summary, topics (s/e), decisions, tasks,
   questions, each on the recording's clock — format in `tools/flow/build_flow.py`. A clear statement is
   a decision or a task, never a question: a question is only what was left open and blocks work, says
   what it blocks, at most 5 a meeting (DGO-1183; the builder refuses more).
3. Each task → ONE Plane item in the owner's project (a plan file, `./bbox project-pln plan`), its
   key and console URL put on the task as `plane`. Never a second list anywhere else.
4. `build_flow.py REC.mp4 analysis.json --he he.json --whisper en.json` in meet-jibri (the volume is
   writable there only; pipe the inputs onto the volume — its rootfs is read-only) → `<session>/flow`.
5. `link_tasks.py ROOM '<json>'` in meet-start (`python - … < link_tasks.py`): the tasks stored
   approved with their Plane link; the page shows «ב-Plane · KEY» and approving files nothing twice.
   Its own process, not the server's lock: run it right after step 4, while nobody edits the meeting.
6. Proof: `server.flow_meeting(room, "")` in meet-start says `ready`, best/speakers/summary done, and the
   counts; a comment on the MEET item links the page. The review step stays the owner's.

Closing a meeting's decisions/questions in bulk: `tools/flow/close_items.py` (meet-start's own
change_item; not while the page is in use).
