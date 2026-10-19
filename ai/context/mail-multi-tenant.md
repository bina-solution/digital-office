# Many companies, each on its own VPS — how mail is addressed, and why

The product shape is **one deployment per company**. Each client runs their own stack, on their own
VPS, with their own database, their own mail server and their own mailboxes. There is no shared
instance and no tenant column anywhere: isolation comes from the deployments being genuinely
separate machines.

This document is the authoritative source for the mail identity and its DNS. `.env.ex` derives the
values, the mail UI checks them against live DNS, and `GO-LIVE.md §9` is the runbook — all three
point here for the reasoning.

Growth has to be boring, and this is the shape it takes:

| # | Onboarding a company | Cost |
|---|---|---|
| 1 | new VPS, `git clone`, set `BUSINESS_NAME`, `./bbox onboarding` | one line of config |
| 2 | publish **5 DNS records** + set the **PTR** at the VPS provider | one zone edit, once |
| 3 | add people from the mail UI | **zero DNS, zero config, zero restart** |

Step 3 is free *because* of the addressing decision in step 2. That is the whole point of the
design and the rest of this page.

## The addressing model

Each company gets a **subdomain of the shared base domain**, and both the web hosts and the mail
domain hang off the same slug:

```
BUSINESS_NAME = "Acme Ltd"
  └─ COMPANY_SLUG = acme-ltd                            (reconcile.py :: sync_identity)
     ├─ DEPLOYMENT_DOMAIN = acme-ltd.digital-office.co.il
     │    web    console.acme-ltd.digital-office.co.il, mail.acme-ltd…, n8n.acme-ltd…, auth.acme-ltd…
     ├─ MAIL_DOMAIN  = acme-ltd.digital-office.co.il    (= DEPLOYMENT_DOMAIN, deliberately)
     │    mail   person4@example.com, person6@example.com, …
     ├─ MAIL_FQDN    = mail.acme-ltd.digital-office.co.il   (Postfix HELO, the MX target, the PTR)
     └─ MAIL_DKIM_SELECTOR = acme-ltd
          record  acme-ltd._domainkey.acme-ltd.digital-office.co.il
```

The company is in the **domain**, so the local part is a plain human name: `admin@`, `user2@`,
`billing@`. That is what makes step 3 free.

### Why not `person18@example.com`

Putting the company in the LOCAL PART of one shared domain is the obvious first design, and it is
worth being precise about why it was rejected, because on the surface it looks *cheaper* — the base
domain's MX/SPF/DMARC and the mail host's PTR already exist, so a new company would inherit
deliverability instead of re-earning it.

It cannot work, for one structural reason and two consequences of it:

* **MX is per-DOMAIN, not per-address.** One MX for `digital-office.co.il` names exactly one host.
  Every company's inbound mail would land on that one machine, which would then have to relay to
  the right VPS. That reintroduces a shared component into a product whose entire isolation story
  is "separate machines" — a single point of failure that holds *every* client's mail in transit,
  can read all of it, and takes every company down when it is down. The one thing per-company VPSs
  are for is exactly the thing this gives back.
* **SPF is per-domain too.** Every company's VPS IP would have to appear in one SPF record for
  `digital-office.co.il`. That record authorises every listed host to send as *any* address at the
  domain, so company A could send as company B — and the record would be re-edited on every single
  onboarding, making step 2 permanently O(n) instead of O(1).
* **DMARC alignment** is evaluated against the domain. A subdomain gets its own policy and its own
  reports; a local part gets neither, so one company's spam problem becomes everyone's.

With a subdomain, each company's records are independent rows in one zone. Nothing about company
A's setup can affect company B, and a company that later wants its own domain changes one line.

The price is that a new company does publish its own MX/SPF/DMARC rather than inheriting them.
That price is paid **once per company, by us, at onboarding** — and it buys the property the
product is sold on: every company's mail touches only that company's machine.

## What is shared and what is not

| Thing | Shared | Why |
|---|---|---|
| Base domain `digital-office.co.il` | ✅ one zone, one owner | so a company can start today with no registrar account |
| A company's subdomain records | ❌ per company | independent rows; one company cannot break another |
| Inbound mail path | ❌ per company | the MX names that company's own VPS — no relay, no shared box |
| DKIM key | ❌ never | a shared private key would let any company sign as any other |
| Mail server, maildirs, mailboxes | ❌ per VPS | each company runs its own Postfix + Dovecot |
| Public IP / PTR | ❌ per VPS | belongs to whoever rents the machine |

## Step 2 in full — the exact records for one company

Substitute the slug. `<IP>` is the VPS's public address; `MAIL_PUBLIC_IP` in `.env` must equal it.

| # | Type | Name | Value |
|---|---|---|---|
| 1 | A | `*.<slug>.digital-office.co.il` | `<IP>` |
| 2 | MX | `<slug>.digital-office.co.il` | `10 mail.<slug>.digital-office.co.il.` |
| 3 | TXT | `<slug>.digital-office.co.il` | `v=spf1 mx ~all` |
| 4 | TXT | `<slug>._domainkey.<slug>.digital-office.co.il` | the generated `v=DKIM1; h=sha256; k=rsa; p=…` |
| 5 | TXT | `_dmarc.<slug>.digital-office.co.il` | `v=DMARC1; p=none; rua=mailto:postmaster@<slug>.digital-office.co.il` |

**Plus, at the VPS provider and not the registrar:**

| — | PTR (reverse DNS) for `<IP>` | → | `mail.<slug>.digital-office.co.il` |
|---|---|---|---|

Notes that each cost an afternoon to learn:

* **Record 1 is doing two jobs.** It puts every web host online *and* it resolves the MX target —
  `mail.<slug>.…` is one label under the slug, so the same wildcard answers for it. There is no
  separate A record for the mail host, and adding one is harmless but unnecessary.
  It is a **one-label** wildcard: it matches `console.<slug>.…` and does **not** match
  `x.y.<slug>.…`, which is why no host in this platform may go a level deeper.
* **Record 3 says `mx`, not an IP.** `v=spf1 mx ~all` authorises whatever the domain's own MX
  resolves to, so it never needs editing again — not when the VPS is rebuilt, not when the IP
  changes. The setup checker also accepts a stricter hand-written record such as
  `v=spf1 a:mail.<slug>.digital-office.co.il -all`; it resolves `a:` mechanisms rather than
  pattern-matching, so it will not tell you to *weaken* a correct record.
* **Record 4's value is generated, not chosen.** `mailserver-init` mints a 2048-bit keypair on
  first boot and never overwrites one that exists. Read the public half back with:
  ```bash
  docker exec mailserver-<slug> \
    cat /tmp/docker-mailserver/opendkim/keys/<slug>.digital-office.co.il/<slug>.txt
  ```
  A 2048-bit key is over 255 bytes, so DNS stores it as several quoted chunks. Most registrars
  accept the whole `"…" "…"` value pasted as-is.
* **PTR is the one record a registrar cannot set.** It belongs to whoever rents you the IP
  (Hostinger/Hetzner/etc., in the rDNS settings of the address). Gmail weighs it heavily:
  forward-confirmed reverse DNS — the A record and the PTR agreeing — is a large part of why mail
  is accepted rather than spam-filed. `MAIL_FQDN` must equal it exactly.

Everything else is generated by the deployment with nothing to do: the mailbox and its password
hash, the DKIM keypair, and the OpenDKIM `KeyTable` / `SigningTable` / `TrustedHosts`.

### One trap that is already fixed, and must stay fixed

The `KeyTable` must name `/etc/opendkim/keys/<domain>/<selector>.private`, **not** the
`/tmp/docker-mailserver/...` path the key is written to. docker-mailserver copies that directory to
`/etc/opendkim` at startup, and OpenDKIM walks the key's path and refuses any key reachable through
a world-writable directory (`/tmp` is 1777):

```
key data is not secure: /tmp can be read or written by other users
error loading key 'sel._domainkey.domain'
```

That does not degrade to unsigned mail. OpenDKIM fails the milter, Postfix answers **451 on every
send**, and the deployment cannot send at all. It is correct in `apps/mail/docker-compose.yml`
today; it is only discoverable by actually sending a message.

## Step 3 — adding a person, with zero DNS

Once step 2 is done, `<slug>.digital-office.co.il` accepts mail for **every** address at it. The MX
points here, SPF authorises this host, the DKIM key signs for `*@<slug>.digital-office.co.il` (the
`SigningTable` is a `refile:` regex, not an exact-address lookup — see below), and DMARC covers the
domain. A new person is therefore one line in one file:

```
person6@example.com|{SHA512-CRYPT}$6$…
```

That is done from **מייל → the account menu → תיבות דואר בדומיין**: list, create, delete. No DNS,
no certificate, no restart — docker-mailserver watches its config directory and regenerates the
Postfix and Dovecot maps within seconds of the file changing.

### Who is allowed to write that line

The interesting question is not how to append it. `mailapi` already mounts the mail server's config
volume, and flipping that mount to read-write would have been one character of diff. It is the
wrong character, because the volume is not "the accounts file" — it is the mail server's entire
configuration: the **DKIM private key**, `postfix-main.cf` (arbitrary Postfix configuration, i.e.
arbitrary commands via a transport), and the routing of every incoming message.

`mailapi` is the wrong process to hold that. It is browser-facing on an authentik-gated host of its
own, and it parses untrusted input from three directions — RFC822 from the internet, IMAP from
remote providers, OAuth callbacks. A traversal or SSRF bug anywhere in it becomes "read the signing
key" the moment it can write there.

So the privilege is separated by **mount**, not by discipline:

| Service | Mount | Can do |
|---|---|---|
| `mailapi` | `mail_config:/mailconfig:ro` | read one file: `<selector>.txt`, the PUBLIC half of the key |
| `mailboxd` | `mail_config:/cfg` | write one file: `postfix-accounts.cf` |
| `mailboxd` | `mail_data:/var/mail:ro` | report whether a mailbox has mail, and how much |

`mailboxd` (`apps/mail/mailboxd/mailboxd.py`) has **no traefik labels and no published port**: it
is addressable only from inside the compose network, so `mailapi` — behind authentik — is the only
route to it and there is no second, unauthenticated door to the same capability. It never accepts a
path or a filename from its caller; the only file it can open is composed from a constant. Its
whole vocabulary is list / create / delete, and every mutation is validated against the one domain
this deployment serves before it touches disk.

It runs the **mailserver image**, not a python one, for the reason `mailserver-init` already
learned: the password hash must come from the very Dovecot that will verify it, so it shells out to
that image's own `doveadm pw -s SHA512-CRYPT`. The image ships python 3.11, so the server is
stdlib-only — no build, no requirements file, no image beyond the one this app already pulls. (The
alternative, python's `crypt.crypt(pw, mksalt(METHOD_SHA512))`, is byte-compatible today and was
**removed from the standard library in 3.13** — a dependency on a deleted module, to reimplement a
binary sitting in the same image.)

Two behaviours worth stating because they are decisions, not omissions:

* **Deleting a mailbox does not delete the mail.** The account line is removed — delivery stops,
  login stops — and the maildir stays at `/var/mail/<domain>/<local>/`. The API response and the UI
  both say exactly where it is. A button that silently destroys years of a company's correspondence
  with no way back is not a feature anyone asked for.
* **The primary mailbox cannot be deleted.** `LOCALMAIL_USER` is the account `mailapi` itself
  authenticates as; removing it does not remove a person, it disconnects the mail application from
  its own server. The UI does not render the button and the service refuses the call.

### `LOCALMAIL_EXTRA_USERS` still exists, and is for something else

A UI-created mailbox lives in the `mail_config` **volume**, so it is gone the moment the volume is.
`LOCALMAIL_EXTRA_USERS` in `.env` is the declarative list that `mailserver-init` re-provisions
(create-only) on every bring-up — it is for mailboxes that must exist on *any* machine that stages
this repo: a role address an automation sends to, a postmaster alias, anything a workflow
hard-codes. People go in the UI; infrastructure goes in the env.

What is not supported either way is appending to `postfix-accounts.cf` over ssh. That account is
invisible to the repo, invisible to the UI's list, and cannot be reproduced on a second deployment.
Both paths above exist so that nobody ever needs to.

### A previous tenant must not survive into the next company

`mail_config` is a **volume**, and a volume outlives `.env`. Re-point a machine at another company —
new `COMPANY_SLUG`, therefore new `MAIL_DOMAIN` — without wiping volumes, and `postfix-accounts.cf`
still holds the previous company's addresses. Provisioning was append-only, so nothing ever removed
them. Measured on staging on 2026-07-29: five accounts, **one** of which belonged to the deployment
that was running. Three were at domains this machine no longer serves, so they could not receive a
message; they were purely one customer's names left visible on the next customer's mailbox screen.

`mailserver-init` now **reconciles** rather than only appending. It owns what it declares, and only
that:

| account in `postfix-accounts.cf` | outcome |
|---|---|
| declared (`LOCALMAIL_USER` / `LOCALMAIL_EXTRA_USERS`) | kept |
| undeclared, at a domain this deployment does not serve | **removed** — a black hole by construction; the MX for it points elsewhere |
| undeclared, but a previous run of init created it (ledger `.mailserver-init-declared` in the volume) | **removed** — taking the name out of `LOCALMAIL_EXTRA_USERS` is how you delete a declared mailbox |
| anything else at **this** domain | **kept** — that is a mailbox someone created in the UI through `mailboxd`; it is declared nowhere and a restart that deleted it would be a catastrophe |

The mail is never touched — same decision as `mailboxd`'s delete: the account stops resolving, every
message stays in `/var/mail`. The accounts file is copied to `postfix-accounts.cf.bak-<timestamp>`
in the same volume before it is rewritten, and only when something is actually being removed.

The ledger is why a mailbox created in the UI is safe: init has no record of creating it, and it is
at the served domain, so it falls into the last row. Without the ledger the two are
indistinguishable, which is exactly why `LOCALMAIL_EXTRA_USERS` alone could not be used as the
answer to "what should exist".

## Bringing your own domain

Nothing structural changes. Set `COMPANY_BASE_DOMAIN` to the company's own domain (at which point
`DEPLOYMENT_DOMAIN` and `MAIL_DOMAIN` become the bare domain rather than a subdomain), publish the
same five records in their own zone, update the PTR at the provider, and restart. The DKIM key
regenerates for the new domain on first start because keys are stored per-domain; the old one stays
in place and simply stops being referenced. The selector still carries the company's name, so the
record is readable in a zone that is now theirs.

## What the mail UI does about all of this

`GET /setup/status` checks every row above against **live public DNS** — never the container's own
resolver, which answers for container hostnames and once reported a perfectly correct A record as
wrong — and reports each as `ok` / `propagating` / `missing` / `bad` / `unknown` with the expected
value beside the observed one. It also reports the mailbox list, so the two halves of "is this company's mail set
up" are one answer. The UI renders it under **חשבונות → דואר פרטי — בדיקת הגדרות** as a checklist,
with the exact record to publish and a copy button on each, and a button through to the mailbox
screen.

### The account menu says what each entry does, because it did not

The three entries in the account menu do three different things and their titles alone were not
telling them apart. An operator went looking for "add a mail user for user2", opened the obvious
one — **חיבור חשבון** — and found a wizard that never asks for a username, because *connecting* is
not *creating*: it attaches a mailbox that already exists somewhere as a source to read. Creating an
address was one entry further down, named **תיבות דואר בדומיין**, which reads like a list rather
than an action. Nothing was missing. The labels were:

| entry | second line | what it does |
|---|---|---|
| **הוספת כתובת דואר בחברה** (first) | יצירת תיבה חדשה, למשל user2 — ללא כל שינוי בדומיין | `POST /mailboxes` → `mailboxd` |
| **חיבור חשבון דואר קיים** | Gmail או תיבה קיימת — מחבר מקור לקריאה, אינו יוצר כתובת | the guided connect flow |
| **דואר פרטי — בדיקת הגדרות** | הדומיין, רשומות ה-DNS וחתימת השולח | `GET /setup/status` |

The connect wizard now carries the same disambiguation on its first step and on the local-mailbox
step — the exact screen that read as "add a user, and it forgot to ask me for one" — each with a
button straight through to the create screen. And the create screen states the property that is the
whole point and was one subordinate clause before: MX, SPF, DKIM and DMARC are published for the
**domain**, they cover **every** local-part at it, so a new address needs no DNS record, no
certificate and no restart. The example address is `user2@<slug>.digital-office.co.il` — plain
local-part on the company subdomain, which is the current model; the older
`user2.<slug>@digital-office.co.il` shape is gone.

Deliberate limits, so the checklist never claims more than it knows:

* Every check reports what it **observed** next to what was **expected**. A check that says
  "probably fine" is how the DKIM `SigningTable` bug survived: it matched envelope addresses
  exactly, so mail from any other address went out unsigned and the server looked healthy.
* It proves Postfix answers on 25 **inside** the deployment, and that this host can **reach** the
  internet on 25. It cannot prove the internet reaches *in* — that needs a prober outside the box —
  so those are two separate facts rather than one confident green.
* A deployment still on a `.test` / `.local` domain is reported as `local`, not as a pile of
  failures: a laptop is not a broken mail server, it is a correctly-working local one.
* The mailbox count is `unknown`, never `bad`, when `mailboxd` cannot be reached. Not being able to
  *list* the mailboxes says nothing about whether they receive mail.
* **One resolver is one opinion.** Every DNS check asks all of `MAIL_DNS_RESOLVERS` in parallel and
  treats *agreement* as part of the answer. When they disagree and at least one already has the
  expected value, the row is `propagating` — the record is right, some caches have not expired yet,
  and it does **not** count toward `remaining` or block `ready`. The alternative is what actually
  happened: the PTR for `31.97.196.82` was corrected at the provider, `1.1.1.1` and `9.9.9.9` still
  served the old name from a 23-hour cache entry, and the checklist went green → red → green
  depending only on which resolver answered first.
* **The zone's own nameservers are an upgrade-only tiebreaker.** When *nobody* matches, all of the
  zone's nameservers are asked directly; if any of them has the expected value the row is
  `propagating` rather than `bad` — the operator published it and no cache has it yet. It never
  works the other way. The symmetric version (a mismatching authoritative answer *downgrading* a
  `propagating`, on the argument that a stale cache which happens to match is a value on its way
  out) was written, deployed and measured here, and real infrastructure will not support it: the
  provider's two "authoritative" reverse-zone servers are anycast, and mid-edit the *same* address
  answered `mail.staging.digital-office.co.il` and `mail.digital-office.co.il` on consecutive
  queries. A downgrade rule on top of that samples a coin and calls a correct, already-published
  record broken — so a check only goes red when nothing, anywhere, has the expected value. An
  authoritative query that cannot be made changes nothing: the public verdict stands.
  `MAIL_DNS_AUTHORITATIVE=0` skips it where direct port-53 egress is not allowed.
