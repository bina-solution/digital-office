# Definition of done — the loop, written down

Written 2026-10-07 after the owner, correctly, refused to keep testing my work for me: the first
overlay UI shipped broken to his phone, and the rebuild that fixed it shipped with a bug that made a
short recording produce *nothing*. Both had been "verified" — in the wrong conditions.

## The rule

**A change is done when the OWNER'S OWN ACTION, in the OWNER'S OWN CONDITIONS, has been observed to
work end to end — by a script, before I say a word.**

Not "the component works". Not "the endpoint returns 200". Not "it works in a lab container with a
35-second recording". The unit of done is a *person's gesture*: press the microphone, speak, stop,
see the words, send, watch the message arrive.

## Conditions that are part of the test (each one has already bitten)

| Condition | Why it is mandatory |
|---|---|
| **The console origin and its iframe** — `…:8080/a/bina/`, not the app's own host | The app is embedded; `getUserMedia` inside a cross-origin iframe is a permissions-policy question, and the identity header path differs |
| **390 × 844, dark theme** | The rejected UI was white-on-white *only* there |
| **A SHORT recording (≈5–8 s) stopped by hand** | The shipped bug: stopping before the first segment closed discarded the audio, so "nothing happened". Every test since records one short clip *first* |
| **A normal recording (≈40 s)** | The multi-segment path, queueing, mirroring into the composer |
| **The real send**: the harness's send button, and the audio-file send | "I couldn't send the recording" was the owner's complaint, not "the transcript looked wrong" |
| **Failure paths**: microphone denied, session not resolvable, relay 4xx/5xx | Each shows a line in the strip; none may fail silently |
| **No silent gap longer than ~2 s** | Feedback is the feature: idle → recording → uploading → transcribing → ready → sent, each visible |

## The loop, in order

1. **Read the acceptance list below and write the failing test first** (or extend the existing one).
2. Change code.
3. `node --check` / `python -m py_compile` — cheap, immediate.
4. **Run `tools/verify-voice.cjs` in the owner's conditions** (`MODE=short`, `ORIGIN=console`), against
   an image built from the change. Red → fix, do not proceed.
5. **Deploy** (`./scripts/dc up -d --build <svc>`) — and for bina-ds that means the hand-off helper,
   which now also proves the image actually changed (`self-update.sh`: "healthy ≠ updated").
6. **The same acceptance test runs again against the LIVE office**, automatically, and its verdict
   arrives as an office notification (`apps/bina-ds/tools/post-update-verify.sh`). No notification
   with a green verdict = not done.
7. Only then say it is done — and say what was observed, not what was intended.

## Observed, 2026-10-07 19:50 (the run that made this the standard)

Against a harness built from the committed image, driven by chromium at 390×844 in the dark theme
with a 16 kHz WAV of the office's own voice note as the "microphone", recording for **8 seconds** and
stopping by hand:

```
"short-recording": { "chars": 99, "hebrew": true },            ← the bug that shipped was here
"in-conversation": { "hasTranscript": true },                  ← the harness's own send button
"send-recording":  { "attachmentInConversation": true },       ← the audio itself, as a file
"errors": []
```

## Acceptance list (the script asserts these)

- [ ] A microphone button exists in the composer and is reachable at 390 px in the dark theme.
- [ ] Pressing it starts recording and the strip shows the elapsed time within 1 s.
- [ ] **Recording 5–8 s and stopping uploads that audio** (the segment is uploaded before the loop
      decides whether to continue) and the words appear in the composer within ~60 s.
- [ ] Recording ~40 s produces more text than the short clip, in the composer, in order.
- [ ] Text typed by the owner is never overwritten by the model.
- [ ] "שלח הקלטה" puts the audio into the conversation as a real attachment, with the transcript (or a
      placeholder) as its text.
- [ ] The harness's own send button sends the draft as a normal message.
- [ ] Nothing overlaps the conversation; no element is invisible against the background in either theme.
- [ ] Every failure leaves a visible line in the strip, never a silent no-op.
