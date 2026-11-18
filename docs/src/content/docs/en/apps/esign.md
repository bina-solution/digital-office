---
title: Signatures
description: "A document goes out for signature with one link, the signer signs, and the signed copy is kept in «Files». What the link opens, what the signature proves, and what it does not."
---

## What it is

«Signatures» (`esign`) sends a document for signature with one link. The signer signs in a minute, and the signed copy is kept in [Files](/en/apps/drive), under `/Signatures/<date>/`. It is off in a new install, and is in the «Signatures» tile in the «Business» group.

Turn it on from the apps screen, which goes all the way, or from the command line. There `apps enable` only writes the decision, and `./bbox run` brings it up:

```bash
./bbox apps enable esign
./bbox run
```

## Envelope, link, password

- **An envelope** is one document, one signer and one link, with a record and a log of its own.
- **The link** opens this envelope only, and nothing else in the office. It dies on its expiry date (14 days by default) or when it is cancelled.
- **A password** (if you want one) travels separately from the link: say it, do not write it next to the link. Until it is given, the document is not shown. Five mistakes lock the link for 15 minutes.
- **The log** is a hash-linked list of everything that happened. The last page of the signed PDF carries a summary of it: how many events, whether the chain is intact, and the last hash. The full log is kept next to it, in the file «<name> — signing log.pdf».

**Sending the link to a person outside the office is up to the owner.** The app produces the link, not the message.

## From the command line

| Command | What it does |
|---|---|
| `./bbox esign new "<file.pdf>" --to "<name>"` | A new envelope, and prints the link. `--password` adds a password, `--days N` sets the expiry, `--page` and `--box` the place of the signature |
| `./bbox esign list` | What went out for signature, and where it stands |
| `./bbox esign show <id>` | The state, the log, and whether the chain is still intact |
| `./bbox esign link <id>` | A new link. The previous one dies |
| `./bbox esign cancel <id>` | Closes the link. The envelope stays, signed or not |
| `./bbox esign flow` | The last ten events, then what happens now |

## What the signature proves

The office's signing certificate is created once by itself (a self-signature), or connected from a PKCS#12 file. A self-signature proves that the document did not change. It does not prove **who** signed: the log shows that.

**This is not an «approved electronic signature»** under the Electronic Signature Law. For that a registered certification authority must identify the signer themselves, and the app cannot do that, even with a connected certificate.

## What does not work yet today

- **An envelope is one signer.** Several signers are several envelopes.
- **If «Files» or «Notifications» are not available,** the signature is still kept, and the copy and the message wait. There is no command or button yet to try again: only through the app's internal API. Do not sign again.

## Going further

- [Files](/en/apps/drive)
- [Notifications](/en/apps/notifications)
- [API Tools](/en/apps/apitools)
