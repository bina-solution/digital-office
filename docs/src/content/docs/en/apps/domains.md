---
title: Domains
description: "The business's domains: accounts at registrars and DNS providers, expiry against the registry, and records — with an API or through the office's browser, and what needs a person watching."
---

## What it is

«Domains» (`domains`) holds the business's domains: the expiry against the registry, the DNS providers and the registrars behind one interface, and the records. It is for administrators only, off in a new install, and is in the «Domains» tile in the «Business» group.

Turn it on from the apps screen, which goes all the way, or from the command line. There `apps enable` only writes the decision, and `./bbox run` brings it up:

```bash
./bbox apps enable domains
./bbox run
```

## An account, its domains, and one domain

- **An account** is a [connection](/en/concepts/connection): an API account (for example GoDaddy, Cloudflare, Plesk, Porkbun, DigitalOcean, Gandi or Hetzner), or a **browser account**, at a registrar that has no API. Such a registrar is an app of its own: InterNIC is `domain-internic`. A browser account needs both that app and the [office's browser](/en/apps/browser42) turned on.
- **Registry watch** always works, with no password: it asks the public registry (WHOIS) about every domain the office knows.
- **A browser account** connects when the owner signs in to the panel once, in the [office's browser](/en/apps/browser42). The connection is kept only after the office has read the account's list of domains, as proof.
- **One domain** shows an overview, records, health, actions, and a log of every change with the state before and after, and the option to undo.

## From the command line

| Command | What it does |
|---|---|
| `./bbox domains accounts` | The accounts, without calling them |
| `./bbox domains ls` | An account's domains, or every domain the office knows |
| `./bbox domains show <domain>` | One domain: registrar, expiry, name servers and state |
| `./bbox domains records <domain>` | The DNS records, as the provider reports them |
| `./bbox domains whois <domain>` | One live query to the public registry. Not in a loop |

On a browser account, `ls`, `show` and `records` read the panel in the office's browser.

## What needs a person

- **A write in a panel runs the first time while a person watches.** Until then it is refused.
- **An action that costs money or cannot be undone** needs an exact approval: the domain's name and the action, not «yes».
- **A read that failed is not kept as truth.** The screen keeps the last list that succeeded and marks it as stale. An empty DNS zone that looks normal is the one wrong answer that must not be shown.
- **A record the panel does not show** but the world does answer is marked «exists in the world; this panel does not show this kind», not as a missing record.

## What does not work yet today

- **A fault or a delay of the office's browser** is shown as «the browser is not available», and never as a failed sign-in. The browser starts again by itself.
- **On InterNIC** you can only create a record today. Update and delete are not written yet.

## Going further

- [The office's browser](/en/apps/browser42)
- [Sites](/en/apps/sites)
- [Connections](/en/apps/connections)
