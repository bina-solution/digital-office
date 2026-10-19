# Self-hosted mail that actually delivers

The platform runs its own MTA (Postfix + Dovecot, `apps/mail` → service `mailserver`). This is what it
took to make real mail flow **both ways** between that server and the outside world, verified against
Gmail on 2026-07-28. Every claim below was measured, not assumed — the failures are recorded with the
evidence, because each one looked like something else.

> **The values below are a historical record, not a template.** They are the identity that machine
> ran on 2026-07-28: one mailbox on the BARE base domain. The addressing model has since moved to a
> per-company subdomain (`admin@<slug>.digital-office.co.il`, MX on `<slug>.digital-office.co.il`)
> so that each company's mail touches only its own machine — see
> [mail-multi-tenant.md](mail-multi-tenant.md) for the decision and
> [GO-LIVE.md §8](../../GO-LIVE.md) for the current records. Copy the *diagnostics* from this page,
> which are timeless; do not copy the hostnames.

## The working configuration

Host `bina-devops-vps` (31.97.196.82), mailbox `person12@example.com`.

| Layer | Value | Why it matters |
|---|---|---|
| A | `mail.digital-office.co.il` → `31.97.196.82` | the MX target must resolve to the MTA |
| MX | `digital-office.co.il` → `mail.digital-office.co.il` | where the internet delivers |
| SPF | `v=spf1 a:mail.digital-office.co.il -all` | authorises the sender; without it → spam |
| DKIM | `mail._domainkey` TXT, key from the MTA | signature; without it → spam |
| DMARC | `_dmarc` TXT, `p=none` to start | policy + reporting |
| **PTR** | `31.97.196.82` → `mail.digital-office.co.il` | set at the **VPS provider**, not the registrar |
| HELO | `mail.digital-office.co.il` | must equal the PTR name |

**Forward-confirmed reverse DNS is the step most guides skim.** The PTR name has to resolve *back* to
the sending IP. It is one fact stated twice in opposite directions, in two different control panels,
and receivers check both.

## What actually blocked inbound (and what did not)

Inbound mail failed for hours. The cause was **not** any of the things it looked like.

**It was `/usr/local/sbin/docker-user-firewall.sh`** — a hardening script whose own header states the
thing that matters:

> Restrict externally-reachable Docker published ports to 80/443.
> **Docker bypasses ufw, so this chain is the actual enforcement point.**

It filled `DOCKER-USER` with `RETURN` for 80 and 443 and `DROP` for everything else on `eth0`. Port 25
was published by Docker, listening, and unreachable.

Three wrong conclusions on the way there, each of which cost time:

1. **"Hostinger blocks port 25."** They do not. Outbound reached `gmail-smtp-in.l.google.com:25`
   immediately, and inbound SYNs were arriving the whole time.
2. **"`ufw allow 25/tcp` will fix it."** It cannot. ufw's INPUT rules never see traffic destined for a
   published container port — that path goes through `nat`/PREROUTING then FORWARD → `DOCKER-USER`.
   The rule was added, showed up in `ufw status`, and changed nothing.
3. **"The panel firewall is the blocker."** The hPanel firewall existed (`Only80And433`) but its toggle
   was **off**. The real rule was in iptables, put there by the script above.

**The diagnostic that ended the guessing** — run it before theorising about any port:

```bash
tcpdump -n -i any 'tcp port 25 and not host 127.0.0.1' -c 20
```

* packets arrive, no SYN-ACK → something **local** is dropping them
* no packets at all → blocked **upstream**

SYNs were arriving and being retransmitted, which ruled out the entire "upstream block" theory in one
observation.

## Verifying from outside, not from here

A `Test-NetConnection` from one laptop is one vantage point and proves little; a VPS connecting to its
own public IP is a hairpin that may never traverse the edge. Use a third party:

```
https://mxtoolbox.com/SuperTool.aspx?action=smtp%3amail.digital-office.co.il
```

It connects from its own infrastructure, prints the full transcript, and checks **open relay** — the
thing you most need to be sure of after opening 25 to the internet. Ours answers
`554 5.7.1 Relay access denied` for foreign recipients, which is correct.

## Outbound TLS: one optional letter in someone else's `sed`

Mail reached Gmail's **inbox** with SPF, DKIM and DMARC all passing — and Gmail showed
**"digital-office.co.il did not encrypt this message"**. The hop to Gmail was plaintext.

The cause is not a setting anyone chose. With `SSL_TYPE` empty, docker-mailserver's `ssl.sh` takes
its `( '' )` branch and runs one substitution over `main.cf`:

```
s|^#?(smtpd?_tls_security_level).*|\1 = none|
```

The `d?` is optional, so the one edit that means *"we have no server certificate, do not offer TLS
to clients"* also sets **`smtp_tls_security_level = none`** — the **client** side, i.e. how this
server talks to every other server on the internet. Sending over STARTTLS needs no certificate of
our own at all. Outbound encryption was switched off as collateral damage of a decision about
inbound.

The diagnostic is one command, and it is the only one that settles it:

```bash
docker exec mailserver-<name> postconf | grep -E '^smtp_(tls_security_level|use_tls)'
# broken:  smtp_tls_security_level = none / smtp_use_tls = no
# correct: smtp_tls_security_level = may  / smtp_use_tls = yes
```

The fix is declarative and lives in `apps/mail/docker-compose.yml` — `mailserver-init` writes a
managed block into `postfix-main.cf`, docker-mailserver's supported override file, which is applied
in `_setup_postfix_late`, **after** `_setup_ssl`, and therefore wins:

```
smtp_tls_security_level = may      # opportunistic: encrypt when offered, still deliver when not
smtp_tls_loglevel = 1              # so "TLS connection established" appears in mail.log
```

`may`, not `encrypt`: opportunistic. `encrypt` would turn every MTA that does not offer STARTTLS
into a permanent bounce, which is a worse failure than one unencrypted hop. Skipped entirely when
`RELAY_HOST` is set, because docker-mailserver deliberately raises that hop to `encrypt` and this
file is appended after it.

### `docker restart mailserver` applies NOTHING — the container must be recreated

This cost an hour and looks exactly like "the fix did not work". `start-mailserver.sh` ends with:

```bash
if [[ -f /CONTAINER_START ]]; then
  _log 'info' 'Container was restarted. Skipping most setup routines.'
  ...
else
  _setup
fi
date >/CONTAINER_START
```

`/CONTAINER_START` lives in the container's own filesystem, so a **restart** keeps it and every
setup routine — including the one that reads `postfix-main.cf` — is skipped. `main.cf` still has the
mtime of the first boot. A **new container** has no marker, so a fresh deployment is always correct;
it is only an existing one that silently ignores config changes.

So after changing anything `mailserver-init` writes:

```bash
docker rm -f mailserver-<name> && ./bbox run mailserver     # recreate, do not restart
docker exec mailserver-<name> postconf | grep '^smtp_tls_security_level'
```

(`postfix-accounts.cf` is the exception — `check-for-changes.sh` watches the config directory and
regenerates the Postfix/Dovecot maps live, which is what makes adding a mailbox restart-free.)

**Proof is a log line, never the config.** On the sending side:

```
postfix/smtp[…]: Trusted TLS connection established to gmail-smtp-in.l.google.com…:25:
  TLSv1.3 with cipher TLS_AES_256_GCM_SHA384
```

and on the receiving side, in the message's own `Received:` header, `with ESMTPS … (TLS1_3 …)`.
`ESMTP` without the S is the failure this section is about.

**How to read the receiving side when you cannot log into the receiving mailbox.** Send to a
Google-hosted address that will reject — `person13@example.com` is one — and Google's DSN
comes back to the sending mailbox carrying a `text/rfc822-headers` part: the original message's
headers **including the `Received:` line Google's own MTA wrote**. Same recipient, ten minutes
apart, on 2026-07-29:

```
by mx.google.com with ESMTP  id …                                                  ← before
by mx.google.com with ESMTPS id … (version=TLS1_3 cipher=TLS_AES_256_GCM_SHA384 bits=256/256)  ← after
```

That is the receiver describing the session it just had with us, which is the only evidence that is
not our own opinion of our own configuration. `person14@example.com` is the companion for
SPF/DKIM/iprev — it replies to the envelope sender, so the report lands in the mailbox under test
and doubles as proof that a brand-new address can receive mail from the public internet.

## The header nobody wrote: `message-id=<>`

Every outgoing message this platform composed left without a `Message-ID`. The tell is one field in
the postfix cleanup line, and it is easy to read past because the line otherwise looks healthy:

```
postfix/cleanup[3704]: 4C9B0ABD74: message-id=<>          ← ours, composed by mailapi
postfix/cleanup[1957]: EF48BAB5C7: message-id=<person15@example.com>   ← inbound, normal
```

Google states the consequence plainly:

```
550 5.7.1 Messages missing a valid Message-ID header are not accepted
```

RFC 5322 calls `Message-ID` a SHOULD; the receivers that matter treat it as a MUST, and it is also
what threading, deduplication and any "did my message arrive" correlation are keyed on. A message
without one is unreferenceable as well as refusable.

**Two things had to both be true for this to go unnoticed.** The composing code never wrote the
header — `EmailMessage()` invents nothing, so `From`/`To`/`Subject`/`Date` were set and `Message-ID`
simply was not. And Postfix did not cover for it: `always_add_missing_headers` defaults to **no**, so
cleanup synthesises `From:`/`Date:`/`Message-ID:` only when header *address rewriting* needs them,
which a fully-qualified `From` never triggers. Neither layer was obviously wrong on its own.

The fix is in the composer, where the sender knows its own identity:

```python
m["Message-ID"] = make_msgid(domain=_domain)   # _domain = MAIL_DOMAIN, same var the mailbox uses
```

`make_msgid` supplies the uniqueness (time + pid + randomness); the only decision is the right-hand
side, and it must be the deployment's own mail domain from the existing
`BUSINESS_NAME → COMPANY_SLUG → DEPLOYMENT_DOMAIN → MAIL_DOMAIN` chain. A literal (the old
`make_msgid(domain="local.test")` in `/append`) is useless for correlation and looks forged.

`always_add_missing_headers = yes` is set as well, in the same `postfix-main.cf` managed block as the
TLS settings — **as a net under the fix, not as the fix.** The argument for it: this MTA accepts
submissions from every container on the compose network, so a future app forgetting the header should
degrade into "Postfix filled it in" rather than "Gmail refused the mail". The argument against
relying on it: a Postfix-generated Message-ID is opaque to the sender, so anything that wants to
correlate what it sent still has to write its own — which is why the composer fix is the primary one.
It is also correctly scoped: header synthesis happens in the local rewriting context, so relayed
inbound mail from the internet is untouched. **Verify it empirically rather than trusting the
parameter name** — whether it applies to a given submission depends on `local_header_rewrite_clients`
(default `permit_inet_interfaces`), and a container on the bridge network is not an inet interface of
the mailserver.

Proof is the same log line, with the field populated, plus the receiver's own copy of the headers
from a `person14@example.com` report.

## Deliberately still closed

**587 (submission) and 993 (IMAPS) are NOT published to the internet.** `SSL_TYPE` is empty on this
MTA, so opening them would put plaintext AUTH on the public network. Get a certificate
(`SSL_TYPE=letsencrypt`) before opening either.

## What "sent" means

`/send` reports `delivered: "queued"` — a real MTA has accepted responsibility, which is the strongest
promise SMTP allows. Final delivery is asynchronous and lands in `/var/log/mail/mail.log`. This
replaced GreenMail, which accepted every recipient and filed unknown addresses into freshly-created
local mailboxes, so `{"ok":true,"via":"smtp"}` was returned for mail that never left the machine.

## Reputation is the part that is not configuration

The first messages landed in Gmail's **spam** folder even with SPF and DKIM passing, because the
domain had never sent mail and the IP had no sending history. That improves with volume and age. It is
not a bug and there is no setting for it.
