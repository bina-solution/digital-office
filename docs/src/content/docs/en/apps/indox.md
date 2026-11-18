---
title: INDOX
description: "INDOX, the intake of the business's financial documents: where documents come from, how to set up a sync, what the screen shows, and what does not work yet in a new office."
---

## What it is

«INDOX» (`indox`) takes in the financial documents that reach the business, reads them, and files each one. It is on in a new install, open to everyone in the office, and is in the «Documents» tile in the «Business» group.

A document's path:

1. **A sync** in n8n brings files from a folder in [Files](/en/apps/drive) or from a label in [Mail](/en/apps/mail).
2. **Reading:** `apitools` reads the document (OCR) on the office's computer.
3. **Filing:** a state machine files each document. Only it changes a document.
4. **The screen** shows the result.

## Instances

Each client is an **instance**, and its documents are kept separately. A new office starts with two instances: `main`, the main one, and `test`, the permanent test instance.

## Set up a sync

A new office has no sync yet. Set it up in the instance's «Sync» tab:

| Source | What you choose |
|---|---|
| «Drive — folder» | A folder in «Files». The office's own storage works with no outside account at all |
| «Gmail — label» | A label in a «Mail» mailbox. A local mailbox of the office needs no permission at all |

A local mailbox has two conditions. It exists only after a mail domain is set in `MAIL_DOMAINS`, and in a new install that is empty. It receives mail from outside only with `MAIL_BIND=0.0.0.0`, and by default no mail from the internet reaches it. See [Mail](/en/apps/mail).

A mail sync can also download a document that arrives as a link: it downloads the first link in the body of the mail. The sync reads documents from the last six months.

**There is no direct upload of a document.** To put a document in by hand, put it in the folder «INDOX» follows in «Files». The upload in the «Document extraction» tab is a test tool only: it shows what was read from the document, and does not put it into the documents table.

## The screen

| Tab | What it holds |
|---|---|
| Dashboard | How many documents, how many were completed, how many need handling, and how many failed, by type, source and company |
| Documents | The instance's documents table, with a picture, filtering and re-running a document |
| Sync | A card per sync: the connection, the folders or labels, and a comparison with the source |
| Activity log | Everything the system did to documents, newest first |
| Settings | The main switches, the extraction queries, and the companies |
| Tests | Running INDOX's tests, with the progress in real time |
| Document extraction | A test bench for reading documents, with a score against known answers |

## From the command line

| Command | What it does |
|---|---|
| `./bbox indox sync state --instance=<id>` | An instance's syncs: what they hold |
| `./bbox indox doc-trace <id>` | The full path of one document |
| `./bbox indox test` | The tests, always on the `test` instance |

Always give an instance. Without `--instance`, some commands choose the client's instance by themselves.

## What only the owner does

- **The intake is not turned off.** The main switches are on, and the owner is the only one who changes them.
- **Actions that leave the office are off:** moving files at the source, labelling mails and sending to the client's accounting system. Only the owner turns them on.
- **Deleting and clearing an instance** are done only in the owner's own words, and only for the instance they named.
- **Reading with an outside AI** is off by default. The reading runs on the office's OCR.

## What does not work yet today

- **Sign in with Google does not work** on any office, so Google Drive or Gmail cannot be connected with the «Sign in with Google» button. What does work: Google Drive through a service account (share the folder with its address), a Gmail app password, and the office's own storage and mail.
- **Folders inside folders are not read.** The sync sees only what is directly inside the chosen folder. A subfolder is skipped without a message.
- **Documents from WhatsApp do not arrive.** The chat app sends them to an address «INDOX» does not have. In a new install the chat is off anyway.

## Going further

- [Files](/en/apps/drive)
- [Mail](/en/apps/mail)
- [Notifications](/en/apps/notifications)
