---
title: Video meetings
description: "The office's meetings on Jitsi Meet, on its own server: a new meeting and a link for guests, recording, transcription, captions — and what does not happen yet after a meeting."
---

## What it is

«Video meetings» (`meet`) is the office's meeting service: Jitsi Meet running on the office's server, in Hebrew and right to left. It is off in a new install, and is in the «Video meetings» tile in the «Business» group.

Turn it on from the apps screen, which goes all the way, or from the command line. There `apps enable` only writes the decision, and `./bbox run` brings the app up:

```bash
./bbox apps enable meet
./bbox run
```

## Room, host and guest

- **A room** is a name in the address: `meet.<domain>/<room>`. The same name is the same meeting.
- **A host** is a person from the office who signed in. The host's link is good for one room and for four hours.
- **A guest** is anyone who has the link. They wait until a host comes in.

Open a new meeting from the tile, or from the terminal:

```bash
./bbox meet new
```

The command returns the room, the host's link and the link for guests.

## Recording

- Recording starts by itself when the first host comes in.
- **One recording at a time.** A second meeting at the same time is not recorded.
- When the recording loses sound or picture, the room sees «⚠️ The recording is losing sound/picture», and a [notification](/en/apps/notifications) is sent.
- Whoever's microphone does not work, or who was not heard, knows it within 10 to 20 seconds.

After the recording, a flow in n8n transcribes the sound twice, with two engines of `apitools`. The transcripts arrive as an item per recording in the [Projects](/en/apps/project-pln) app (Plane). See also «What does not work yet today».

## Captions

- **Live captions** are off by default. When they are turned on, each participant's browser transcribes their own voice. In Chrome that is Google's speech service, that is, a service outside the office.
- **The server's own captions** turn on by themselves only on a computer with at least 4 cores, when the recording is healthy. On a computer with 2 cores they are off. Whoever forces them on there (`MEET_LIVE_CAPTIONS=on`) gets them more than two minutes late, and some of them drop.

## The network

All the video passes through the office's bridge, not directly between the participants. The bridge uses UDP on port 10000. In an office with a public domain, the app's preparation publishes this port on every interface, and tells the browsers what the public address is. It does not touch any firewall: if the server's provider has a firewall, UDP 10000 must be let through it. Whoever's network blocks UDP goes through TURN, on port 443.

When you see names and chat but no video, the problem is on the video's path: the bridge's port or address.

## From the command line

| Command | What it does |
|---|---|
| `./bbox meet new` | A new room, a link for the host and a link for guests |
| `./bbox meet recordings` | The latest recordings: when, which room, who, and whether they finished |
| `./bbox meet meetings` | The latest meetings that have a flow page |
| `./bbox meet flow` | The events: a meeting opened, a recording created |
| `./bbox meet verify` | Every meetings service answers, and the recorder is ready. `--call` holds a simulated meeting and checks it end to end |

## What does not work yet today

- **The recording misses the first 11 to 13 seconds** of every meeting, because the recorder comes in after the host. A very short call comes out almost empty.
- **The transcripts in the office's own Plane.** Until 10 November 2026, the flow found Plane only through a link to another office. The fix is in the code, but has not been measured on a live office yet.
- **The MEET project is not created by the install.** Open it in Plane by hand.
- **A meeting's flow page is not built by itself.** Every meeting gets a page, but it stays «first processing». No automatic process writes the flow page. Build it by hand, with the tools in `apps/meet/tools/flow`.
- **After the XMPP service restarts,** the coordination service may not see the recorder, and the recording does not start. Restart the coordination service too, then `./bbox meet verify`.
- **One recording at a time,** as written above.

## Going further

- [Notifications](/en/apps/notifications)
- [Files](/en/apps/drive)
- [Sites](/en/apps/sites)
