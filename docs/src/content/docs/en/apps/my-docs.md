---
title: My Docs
description: "The business's documents: quotes, invoices, receipts and credits, numbered as the Tax Authority expects — what is final, and what is not legal by default yet."
---

## What it is

«My Docs» (`my-docs`) is the screen of the business documents: quotes, invoices, receipts and credit documents, with their customers and items. It is off in a new install, and is in the «My Docs» tile in the «Business» group.

Turn it on from the apps screen, which goes all the way, or from the command line. There `apps enable` only writes the decision, and `./bbox run` brings the app up:

```bash
./bbox apps enable my-docs
./bbox run
```

The documents themselves are kept in the ledger of [API Tools](/en/apps/apitools): it numbers them, produces the file and keeps a log of every change. «My Docs» is the screen on top of it.

## What is final

- **Issuing is final.** An issued document gets the next number in the series, and a number never comes back. To undo an issued document you cancel it, which issues a credit invoice next to it, for every kind of document.
- **The first download is the «original».** The ledger records the first download as «original» and every one after it as «copy», the owner's too. The mark is printed on the file only on a download as an image (PNG). A PDF file comes out the same on every download.
- **«Sent» does not send mail.** It only marks the document as sent and records the address in the log. Sending the file to the customer is a separate action.

A draft can be prepared and changed freely.

## From the command line

The commands here only read:

| Command | What it does |
|---|---|
| `./bbox my-docs documents` | The documents |
| `./bbox my-docs show <id>` | One document |
| `./bbox my-docs events <id>` | A document's log |
| `./bbox my-docs customers` | The customers |
| `./bbox my-docs items` | The items |
| `./bbox my-docs integrity` | Checks that the numbering is continuous and that the log was not changed. In an office without a signing certificate, the first check creates the development certificate. It changes no document |

## What does not work yet today

- **A document issued here is not legal by default yet.** The allocation number for Israeli invoices comes from a test implementation, and the digital signature is a self-signature. See [API Tools](/en/apps/apitools).
- **The ledger has no sign-in of its own.** The office's sign-in at the edge router is the only gate, so the `apitools` port is not exposed.

## Going further

- [API Tools](/en/apps/apitools)
- [INDOX](/en/apps/indox): the intake of documents that reach the business
- [Edge router](/en/apps/traefik)
