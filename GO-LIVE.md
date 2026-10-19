# Go-Live Runbook — המרכז (the unified business system)

How to bring the whole platform up on your own machine or VPS and finish onboarding from the web.
No public HTTPS required — everything works locally or on a VPS with normal outbound access.

## 0. Prerequisites

- Docker + Docker Compose v2.
- A copy of `.env`: `cp .env.ex .env`. Set **one** value at the top:
  - `BUSINESS_NAME=` your business. Everything else derives from it — `COMPANY_SLUG`,
    `DEPLOYMENT_NAME`, `DEPLOYMENT_DOMAIN`, every `*_BASE_URL`, and the whole mail identity
    (`MAIL_DOMAIN`, `MAIL_FQDN`, `MAIL_DKIM_SELECTOR`). The slug is computed at render time by
    `reconcile.py :: sync_identity`, which runs before anything starts, so a fresh clone needs no
    manual step. For pure-local work the `*.localhost` hosts already work regardless.
  - For a company deployment that must send and receive real mail, §8 is the whole of it.
- You do **not** need to fill in secrets by hand. Machine secrets (Redis/Postgres/n8n keys, Portainer,
  Authentik admin) auto-generate on first boot; the rest you set from the web onboarding below.

## 1. One command — bring the stack up

```bash
docker compose up -d
```

This starts everything: Traefik edge, Authentik SSO, Supabase, n8n, the ledger (apitools), mail, drive,
homepage, alerts (GlitchTip), the **connections** credential plane, and the **console** shell (המרכז).

**Recommended — run off the credential plane** (connections becomes the single source of truth; secrets
never live in service envs):

```bash
docker compose -f compose.yml -f compose.connections.yml up -d
```

Consumers wait for `connections` to be healthy, then pull their secrets from it at boot. Fail-closed:
if connections is down, dependent services don't start.

## 2. First login (accounts are owned by Authentik)

The first admin is created automatically from `AUTHENTIK_BOOTSTRAP_*` (auto-minted if you left them
blank — view them any time in **connections**). Open `https://auth.<your-domain>` (or `auth.localhost`)
and sign in as `akadmin`. Account creation is Authentik's job — the app never builds its own login.

## 3. Web onboarding — open the console

Go to `https://console.<your-domain>` (or `console.localhost`). If the business isn't set up yet, you
land on **מסך התקנה** (the install screen). It leads with the keys/connections and frames the two goals:

### 3a. What needs YOU (everything else is automatic)

| Step | Where | Unlocks |
|---|---|---|
| **Scan WhatsApp QR** | סרוק QR button → modal | the WhatsApp bot |
| **Google consent** | Google row → התחבר | Drive + Sheets + Gmail for incoming documents |
| **Gemini API key** | הזן ערך | document extraction |
| *(optional)* Google OAuth client id/secret | connections | use your own GCP app for consent |
| *(optional)* Document-AI service-account key | connections | higher-accuracy OCR |

### 3b. Business identity (secondary)

Fill שם העסק / ח.פ / type at the bottom of the install screen. This is the ledger's business profile
(appears on invoices) — separate from `BUSINESS_NAME` branding.

## 4. What "working" looks like

- **מייל / drive / incoming documents**: once Google consent + Gemini are set, INDOX pulls mail,
  extracts documents, files them to Drive/Sheets, and records them in Supabase.
- **WhatsApp bot**: after you scan the QR, the install screen flips the WhatsApp row to *מחובר* and the
  bot starts handling messages/documents.
- **מסמכים שלי (my-docs)**: works immediately (business → customers → items → documents → PDF invoices).
- **תקלות / כל מקביל / מכונה**: live views of GlitchTip alerts, concurrency, and host/Docker metrics.

## 5. Managing connections (view / change / disconnect / disable)

- **View / change / add** any key: console → חיבורים ומפתחות (or the connections service directly).
  A user-set value is stored encrypted and overrides `.env`.
- **Disconnect**: the *נתק* button on a connected row — clears the override, revokes an OAuth grant, or
  logs the WhatsApp device out.
- **Disable a feature**: `POST /api/features/<service> {enabled:false}` (per-service switch).

## 6. Environment notes

- **WhatsApp pairing needs a normal (residential/VPS) IP.** WhatsApp's anti-abuse rejects the pairing
  WebSocket from many cloud/datacenter IP ranges (you'll see the bot hang at "connecting" with no QR).
  Everything else — Google, Gemini, Supabase — is plain HTTPS and works anywhere.
- **No public HTTPS required.** The OAuth broker uses connections' own redirect URI; as long as your
  browser can reach `connections.<host>`, consent completes on local or VPS.
- **Secrets are never committed.** `.env` is git-ignored; user-set values live in the encrypted vault.

## 7. Regenerate / rotate

Machine secrets can be rotated from connections (`/api/regenerate/<id>`). Rotating
`N8N_ENCRYPTION_KEY` re-encrypts n8n credentials — the one to treat carefully (OAuth grants re-consent).

## 8. Onboarding a company — public web + fully working inbound and outbound mail

This is the growth path the product is built around: **lots of VPSs, each running one company's
digital office, and adding another one is three steps.** They are listed here verbatim, with the
exact commands and the exact DNS records, because "onboarding is easy" is only true if it can be
read off a page and executed without asking anyone.

> **1.** new vps, git clone, minimal config, `bbox run`
> **2.** domain management, multiple actions to get the new platform publicly accessible and mail
>        fully working inbound outbound
> **3.** adding more private mail account (e.g. `user2@<company>.digital-office.co.il`) easy and
>        fully from mail ui, no domain management work needed

The reasoning behind the addressing that makes step 3 free is in
[ai/context/mail-multi-tenant.md](ai/context/mail-multi-tenant.md). This section is the runbook.

### 8.1 Step 1 — new VPS, clone, minimal config, run

`debian-install.sh` provisions Docker on a fresh Debian/Ubuntu host. Then:

```bash
git clone <this repo> /root/deployment-hacohen && cd /root/deployment-hacohen
cp .env.ex .env
```

**The minimal config is four lines.** One is the company; the other three are the facts only this
machine knows — that it is a real server, at a real address, that should accept mail from the
internet:

```dotenv
BUSINESS_NAME=Acme Ltd            # the ONLY identity line; the slug and every host derive from it
MAIL_PUBLIC_IP=203.0.113.10       # this VPS's public address (blank => the checker guesses, badly)
MAIL_BIND=0.0.0.0                 # publish port 25 to the internet. 127.0.0.1 = no mail ever arrives
TRAEFIK_ACME_EMAIL=ops@example.com
```

Production hardening, worth setting at the same time:

```dotenv
MAIL_ENABLE_SPAM=1
MAIL_ENABLE_FAIL2BAN=1
MAIL_SPOOF_PROTECTION=1
GMAIL_IMAP_MODE=local             # the built-in mailbox is the active account, not a Gmail import
```

Then bring it up. **`./bbox run` brings up infrastructure only — it does not import automations or
apply the app schema**, so use `onboarding`, which is `run` + `n8n push` + `seed`:

```bash
./bbox onboarding
```

Nothing else is edited. `COMPANY_SLUG`, `DEPLOYMENT_NAME`, `DEPLOYMENT_DOMAIN`, every `*_BASE_URL`,
`MAIL_DOMAIN`, `MAIL_FQDN`, `MAIL_DKIM_SELECTOR` and the mailbox address all derive from
`BUSINESS_NAME` at render time (`reconcile.py :: sync_identity`). For `Acme Ltd` that is:

```
slug   acme-ltd
web    console.acme-ltd.digital-office.co.il   (n8n., auth., mail., drive., … all one label deep)
mail   person4@example.com
MX     acme-ltd.digital-office.co.il  ->  mail.acme-ltd.digital-office.co.il
DKIM   acme-ltd._domainkey.acme-ltd.digital-office.co.il
```

The mailbox, its password hash, the 2048-bit DKIM keypair and the OpenDKIM tables are all generated
by `mailserver-init` on this first boot. There is nothing to create by hand.

### 8.2 Step 2 — domain management: **5 records**, published once

Read the generated DKIM public key off the machine first — it is the only value that is not known
in advance:

```bash
docker exec mailserver-acme-ltd \
  cat /tmp/docker-mailserver/opendkim/keys/acme-ltd.digital-office.co.il/acme-ltd.txt
```

Then publish these five rows in the `digital-office.co.il` zone. Substitute the slug and the IP:

| # | Type | Name | Value |
|---|---|---|---|
| 1 | A | `*.acme-ltd.digital-office.co.il` | `203.0.113.10` |
| 2 | MX | `acme-ltd.digital-office.co.il` | `10 mail.acme-ltd.digital-office.co.il.` |
| 3 | TXT | `acme-ltd.digital-office.co.il` | `v=spf1 mx ~all` |
| 4 | TXT | `acme-ltd._domainkey.acme-ltd.digital-office.co.il` | `v=DKIM1; h=sha256; k=rsa; p=…` (from the command above) |
| 5 | TXT | `_dmarc.acme-ltd.digital-office.co.il` | `v=DMARC1; p=none; rua=mailto:person5@example.com` |

**And one record that is not in the zone at all:**

* **PTR (reverse DNS)** for `203.0.113.10` → `mail.acme-ltd.digital-office.co.il`, set at the **VPS
  provider** (Hostinger/Hetzner rDNS settings), not at the registrar. No amount of registrar access
  can produce it, and Gmail weighs it heavily.

Why it is only five:

* **Record 1 does two jobs.** It puts every web host online *and* resolves the MX target, because
  `mail.acme-ltd.…` is one label under the slug like every other host. It also covers TLS: traefik's
  HTTP-01 challenge runs per host and every host resolves through this one row, so certificates
  issue with no further DNS.
* **Record 3 says `mx`, not an IP,** so it never needs editing again — not when the VPS is rebuilt,
  not when the address changes.
* **Nothing on the base domain is touched.** No shared MX, no shared SPF, no coordination with any
  other company. That is the property that makes this O(1) per company instead of O(n).

Verify without leaving the product — the mail UI does exactly these checks against live public DNS:

```bash
curl -s http://<mailapi-ip>:8970/setup/status | python3 -m json.tool
# ready: true, remaining: 0
```

or in the browser: **מייל → the account menu → דואר פרטי — בדיקת הגדרות**. Every row shows what was
expected beside what was found, with a copy button on the record to publish.

Prove real mail actually arrives, with the RECEIVER's own evidence rather than the sender's:

```bash
# send a message from a normal Gmail account to person4@example.com, then:
docker exec mailserver-acme-ltd sh -c \
  'grep -aiE "policyd-spf|opendkim|opendmarc|stored mail into mailbox" /var/log/mail/mail.log | tail -20'
# want: SPF Pass · "DKIM verification successful" · opendmarc pass · stored mail into mailbox
```

### 8.3 Step 3 — more private mail accounts, from the mail UI, with zero domain work

**מייל → the account menu → תיבות דואר בדומיין.** List, create, delete. Creating
`person6@example.com` needs **no DNS record, no certificate and no restart**,
because step 2's records already cover every address at the domain: the MX points here, SPF
authorises this host, the DKIM `SigningTable` signs for `*@acme-ltd.digital-office.co.il`, and
DMARC covers the domain. A new person is one line in `postfix-accounts.cf`, and docker-mailserver
picks it up within seconds.

The same three operations over HTTP, if you need them from a script:

```bash
curl -s        http://<mailapi>:8970/mailboxes
curl -s -XPOST http://<mailapi>:8970/mailboxes -H 'content-type: application/json' \
     -d '{"local":"user2","password":"<at least 8 chars>"}'
curl -s -XDELETE http://<mailapi>:8970/mailboxes/user2%40acme-ltd.digital-office.co.il
```

Two behaviours that are decisions, not omissions:

* **Deleting a mailbox does not delete the mail.** The account is removed (delivery stops, login
  stops); the maildir stays at `/var/mail/<domain>/<local>/` and the response says so.
* **The primary mailbox (`LOCALMAIL_USER`) cannot be deleted** — it is the account the mail
  application itself logs in as.

Use `LOCALMAIL_EXTRA_USERS` in `.env` instead for mailboxes that must exist on *any* machine that
stages this repo (a role address an automation sends to, a postmaster alias): a UI-created mailbox
lives in the `mail_config` volume and does not survive it being wiped. People go in the UI;
infrastructure goes in the env. Appending to `postfix-accounts.cf` over ssh is supported by neither
and needed by neither.

### 8.4 Carrying the DKIM private key across a volume wipe

`mailserver-init` generates a 2048-bit key on first boot and **never overwrites one that exists**
(`apps/mail/docker-compose.yml`, the `[ -s "$kd/$sel.private" ]` guard) — so the key survives
restarts and re-deploys. It does **not** survive `docker volume rm`, and record 4 of §8.2 belongs to
the key that exists today. Destroy the `mail_config` volume and the next boot mints a *different*
key, after which every signature fails verification against the published record until DNS is
re-published.

This is the one step of §8.2 that has to be redone, and only in this case. Records 1, 2, 3 and 5
are derived from the slug and the IP, so they are correct forever.

So a wipe that includes volumes has exactly two acceptable endings: re-publish the new public key
from `opendkim/keys/<domain>/<selector>.txt`, **or** restore the old key before the first bring-up.
Back it up before destroying anything:

```bash
docker run --rm -v deployment-hacohen_mail_config:/c:ro -v "$PWD":/b alpine \
  tar czf /b/mailserver-config.tar.gz -C /c .
```

and restore it into the empty volume **before** `./bbox run` (order matters — restore first and
`mailserver-init` leaves the key alone; boot first and you have already minted a new one):

```bash
docker volume create deployment-hacohen_mail_config
docker run --rm -v deployment-hacohen_mail_config:/c -v "$PWD":/b alpine \
  tar xzf /b/mailserver-config.tar.gz -C /c
```

Verify the restored key is the published one — this must print the same `p=` as the DNS record:

```bash
docker run --rm -v deployment-hacohen_mail_config:/c alpine \
  cat /c/opendkim/keys/acme-ltd.digital-office.co.il/acme-ltd.txt
dig +short acme-ltd._domainkey.acme-ltd.digital-office.co.il TXT
```

### 8.5 Certificates

Nothing manual. `platform-base/traefik/config/acme.json` is **gitignored** — it holds the ACME
account key and every issued TLS private key — and traefik's own bring-up hook
(`platform-base/traefik/hooks/prepare`, run for every enabled app by `bbox run`) creates it at mode
0600. That mode is the whole point: traefik refuses an ACME account whose store is group-readable,
and it does not fail loudly — it *skips the resolver* and serves its self-signed default cert. The
same hook warns about a contact address Let's Encrypt refuses, which produces an identical symptom
by a quieter route. Confirm a real certificate after bring-up:

```bash
echo | openssl s_client -connect 203.0.113.10:443 -servername console.acme-ltd.digital-office.co.il \
  2>/dev/null | openssl x509 -noout -issuer      # must say Let's Encrypt
```

Record 1 of §8.2 is what makes this automatic: the HTTP-01 challenge runs per host and every host
resolves through that one wildcard, so no certificate needs a DNS action of its own.

### 8.6 Order of a from-scratch re-stage

`./bbox run` brings up infrastructure only — it does not import automations or apply the app schema.

```bash
git pull                                  # the repo is the source of truth; never patch the VPS
cp .env.ex .env && $EDITOR .env           # set the four lines from §8.1
# restore the DKIM key per §8.4 if the volumes were wiped
./bbox onboarding                         # = run + n8n push + seed
```

`git status --porcelain` on the VPS must end **empty**: the repo is the source of truth, and a fix
that exists only on a server is a fix that no other company's deployment will ever have.
