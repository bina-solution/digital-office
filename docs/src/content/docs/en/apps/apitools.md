---
title: API Tools
description: "apitools: reading documents (OCR), Hebrew transcription on the office's computer, and the business documents ledger — the measured speed, and what is not legal by default yet."
---

## What it is

«API Tools» (`apitools`) gives the office three tools: reading documents (OCR), transcribing Hebrew speech, and a ledger of business documents. It is on in a new install. It has no tile: other apps use it, for example [INDOX](/en/apps/indox), [Video meetings](/en/apps/meet) and «Bina»'s microphone.

## Reading documents (OCR)

By default, every document is read on the office's computer (`OCR_ENGINE=local`). A file can be up to 50 MB. Google Vision is used only if `OCR_ENGINE=google` is set, or if a single request asks for `?ocr_engine=google`.

## Hebrew transcription

Transcription runs on the office's computer, with no account and no key. The first transcription downloads the model once from Hugging Face, so it needs the internet. After that the voice does not leave the computer. The model takes about 1 GB of memory.

| Model | When |
|---|---|
| `ivrit` (the default) | Hebrew: ivrit.ai's Hebrew Whisper model |
| `whisper` | English, or when the language is not known |

- **A short recording** (up to 120 seconds) gets its transcript in the same request, once it finishes. **A long recording** becomes a job, and the transcript arrives when it finishes.
- **Who said what:** in a recording of two minutes or more, each segment gets a speaker label, by voice. A person gives the speakers names. A shorter recording gets no labels. The model for this is already inside the app, and needs no internet.
- **The result is kept,** and you can get it as VTT, SRT, TXT or DOCX without transcribing again. Jobs are deleted after 30 days. Uploaded files are deleted after 7 days.
- **The measured speed** on a computer with 2 cores and no graphics card: dense speech took about a third of its length (0.29 to 0.35). A 30-second voice note took 20 to 40 seconds. The measurement was taken before the service was limited to one core, so today it may be slower.
- **One job at a time,** and a queue of 8. When the queue is full, the answer is «try again later».
- **The model leaves memory** after 5 minutes with no work. The next job waits 10 to 16 seconds while it loads.
- **Dictation:** the microphone button in «Bina» sends 30-second segments. The text grows every 30 to 60 seconds, not at once.

## The documents ledger

Business, customers, items and documents, in the office's database. The screen on top of it is «My Docs» (`my-docs`), and it is off in a new install.

Three final actions, and there is no interface that undoes them. An office agent performs them only in the owner's own words:

- **Issuing a document** takes the next number, with no gaps, and freezes it.
- **Cancelling** issues a credit document.
- **Deleting** a customer or an item is a full deletion.

A first download of a document is a change too: the ledger records it as «original», and every download after it as «copy».

## From the command line

| Command | What it does |
|---|---|
| `./bbox apitools speech-health` | The model's state, the queue's length and the limits |
| `./bbox apitools speech-jobs` | The transcription jobs |
| `./bbox apitools speech-models` | The models |
| `./bbox apitools ocr-health` | Whether document reading answers |
| `./bbox apitools test` | The app's tests |

## What does not work yet today

- **A document the ledger issues is not legal by default yet.** The allocation number for Israeli invoices comes from a test implementation (`ALLOCATION_BACKEND=stub`), not from the Tax Authority. The digital signature is a development environment's self-signature, not an approved signature. For a document to be a legal original you need to connect the Tax Authority (`live`) and a signing certificate from an approved authority.
- **There is no transcription from an address.** You send a file, not a link, and that is on purpose.

## Going further

- [INDOX](/en/apps/indox)
- [Video meetings](/en/apps/meet)
- [The apps](/en/apps)
