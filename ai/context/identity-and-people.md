# People and private-engine users — the shared pattern

**Status:** design contract. Any agent adding user management to an app engine (mail, chat, drive,
or a new one) builds against *this*, not its own model. If something here is wrong, change this file
first and say so — do not diverge silently.

## The problem

Today there are four unrelated notions of "user" and no notion of a *person*:

| Plane | Where it lives | Creatable from UI |
|---|---|---|
| Console SSO | authentik | yes, login only |
| Mail | dovecot accounts file, owned by `mailboxd` | yes, buried in the setup flow |
| Chat | `chat_users` / `chat_members` (Postgres) | no |
| Drive | *nothing* — `drive_files` has no owner column | no |

So "add Dana to the company" is not expressible. Each engine invented its own user, so onboarding is
four screens and offboarding is four screens you must remember. That is the actual defect; a nicer
"add mailbox" button does not fix it.

## The one constraint that shapes the design

**Mail needs a real password. The others do not.**

IMAP and SMTP authenticate with a secret. Thunderbird, Apple Mail and Outlook cannot do OIDC against
our authentik. So the mail engine must hold a per-user credential in dovecot — that is a protocol
fact, not a shortcut. Chat and drive sit behind traefik forward-auth and can trust the identity
header instead.

Any design that unifies all three onto one credential store is wrong. What unifies them is not the
credential — it is the **person**.

## The model

```
Person  (who) ── grants ──> Engine principal (what each engine actually creates)
                              ├─ mail   → dovecot account (+ password)      → mail connection
                              ├─ chat   → chat_users row                    → chat connection
                              └─ drive  → owner principal                   → drive scope
```

- **Person** — a human. Stable id, display name, one **local-part** (`dana`), status
  (`active` / `suspended` / `removed`), roles.
- **Grant** — "this person has mail", "this person has chat". Carries engine-specific attributes
  (mail quota, drive quota, chat display name). A grant is a *decision*; a principal is its effect.
- **Principal** — what the engine materialises. Engine-owned, engine-shaped, never shared.

### One local-part, everywhere

A person's local-part is allocated once and reused by every engine:

```
dana → dana@<MAIL_DOMAIN>   (mail)
     → @dana                (chat)
     → owner "dana"         (drive)
```

This is the consistency the platform is missing today, and it is cheap: the domain is already
derived (`BUSINESS_NAME → COMPANY_SLUG → DEPLOYMENT_DOMAIN → MAIL_DOMAIN`), so a person's addresses
in all three engines follow from one field the operator types.

## Source of truth: declared + reconciled, not one or the other

Do **not** pick "the repo declares users" or "the UI creates users". Both are needed, and the
platform already has the proven answer — `mailserver-init`'s ledger. Generalise that rule to every
engine:

| Case | Action |
|---|---|
| Granted, principal missing | create it |
| Granted, principal exists | leave it alone (idempotent) |
| **We** created it before, grant withdrawn | remove the principal |
| Exists, never ours | **leave it alone** — an operator or UI made it, and a redeploy must never delete it |

Track the third case with a per-engine ledger of what this engine provisioned, stored beside the
engine's own state. This is what makes `bbox run` safe to re-run on a live company: the reconciler
can tell "no longer wanted" from "not mine".

## Removal never destroys data

`mailboxd` already made this call and it is correct — elevate it to a platform invariant:

> Removing a principal stops access. **It does not delete the person's data.**

Mail stays in the maildir, files stay in drive, messages stay in chat history. Deletion of content
is a separate, explicit, audited action. Offboarding must be safe to do in a hurry.

## Provisioning registers the connection

When an engine materialises a principal it **also registers the connection** for that app. Creating
a mailbox and then separately "connecting" it is a step with no decision in it — the operator is
never going to answer "no" there. Proven feasible: `user2` was created and receiving public mail
60 seconds later with no further action.

## Credentials

- Engines behind forward-auth (chat, drive): **no password**. Trust the identity header.
- Mail: generate a strong password at provisioning, **show it once**, store only what dovecot needs.
  Support rotation without recreating the mailbox. Never store or log plaintext, never echo it back
  in a listing endpoint.
- Suspension must be enforced by the engine (dovecot refuses auth), not merely hidden in the UI.

## Surfaces

**The console is the master interface.** `הלשכה הדיגיטלית` → **אנשים**: every person, which engines
they hold, status, and the lifecycle actions. This is where you onboard and offboard, once.

**Each app keeps its own users tab**, because per-engine enablement is a real decision — not everyone
needs a mailbox. That tab lists *people* and toggles this engine's grant, and it is a filtered view
of the same grants the console writes. It is **not** a second source of truth, and it must never grow
its own create-a-user-from-nothing path.

Naming: the tab manages *people in this engine*. The existing "connect an account" wizard is a
different thing — it attaches an external mail source (Gmail, IMAP) — and the two must read as
clearly different, because conflating them is exactly what confused the operator who went looking
for user creation and found a dialog that never asked for a username.

## For the agent building chat multi-user

Build the **grant + principal + ledger reconcile** shape above. Do not build a chat-only user
manager on `chat_users`; make `chat_users` the *principal* projection of a person, keyed by the
person id, with the local-part as the handle. If the Person registry does not exist yet, define the
person id and local-part contract now and read it from a single module so it can be swapped for the
real registry without touching chat logic.

## Open decisions (do not settle these unilaterally)

1. **Where Person lives** — authentik (already the SSO truth, but heavy for engines to query) versus
   a `people` table with authentik as an upstream projection. Whichever wins, there must be exactly
   one, and the console must not quietly become a second one.
2. **Quotas** — no engine enforces any today; one user can fill the disk for the whole company.
   Quota belongs on the grant.
3. **Audit** — who granted what, when. Needed before this is credible for real companies.
