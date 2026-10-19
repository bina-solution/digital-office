# The engine/profile pattern — the template every app implements

**This is the architecture.** Every app that talks to a backend implements exactly this, the same
way. Adding an app is filling in five slots, not designing anything.

Current per-app gaps and the evidence behind the rules: [profiles-and-engines.md](profiles-and-engines.md).

---

## 1. Three nouns

```
ENGINE     a class of backend.
  private  we run the process     → profiles are CREATED here
  remote   someone else runs it   → profiles are CONNECTED to

PROFILE    an identity ON one engine, holding a CREDENTIAL.
           private → an API key we mint.   remote → an OAuth grant / password.

BINDING    which profile this app acts as. What the connection bar switches.
```

**An app acts as a *profile* on an *engine*; the *binding* says which.**

## 2. The unlock: a private profile has a credential, so it is a normal profile

Every private profile is issued an **API key** at creation. That key is its secret, stored in the
connections vault exactly like an OAuth token. Consequences:

- A private profile is a **real instance** — not a synthesised row. The `*_local-local` fake
  instance, and the ~6 special cases per app it forces, are **deleted**.
- `resolve()` treats private and remote identically: fetch secret → build adapter with it.
- `Backend(credential)` everywhere. Never `Backend()` reading env. This one line is what makes N
  profiles possible.
- **Every call into a private engine is authenticated as a profile.** There is no unauthenticated
  path and no ambient identity.

For mail this collapses completely: the mailbox password *is* the key, so the private profile's
secret is `{username, password}` — byte-identical in shape to the Gmail app-password profile.

**There is no "default profile".** There is a profile that happened to be created first, marked
admin. Nothing in the code may branch on "is default".

## 3. Four planes, one owner each

| Plane | Owner | Contains |
|---|---|---|
| **Catalogue** | the repo, compiled by `reconcile.py` | which engines exist, auth methods, form fields, **declared profiles** |
| **Credentials** | connections service | the secret for **every** profile, private and remote alike |
| **Profiles** | the app's own DB (private) · connections (remote) | identity, admin flag, key **hash** |
| **Binding** | the app, on its own volume | `{scope → profile_id}` |

The app stores the key's **hash** (to verify inbound calls); the vault stores the key itself (so
clients can fetch it). Never both in one place.

The binding stays app-local: a connections outage must degrade a *list*, not un-select every app.

## 4. Authorization — two rings, checked in the engine

Every request carries a profile credential. The engine resolves credential → profile, then:

| Ring | Who | May do |
|---|---|---|
| **data** | any profile | all engine ops (mail/drive/chat), scoped to **its own data** |
| **self** | any profile | read/update its own profile, rotate its own key |
| **admin** | `is_admin` profiles only | create, edit, suspend, delete **other** profiles; issue/rotate their keys |

Two hard rules:
- **Data scoping is enforced in the engine's queries, not in the UI.** A profile cannot see another
  profile's mail, files, or chats regardless of which endpoint is called.
- **The last admin cannot be removed or demoted.** Otherwise profile management becomes unreachable.

Bootstrap is exempt because it runs **in-process with direct DB access**, not over the API — which
resolves the chicken-and-egg (you need an admin key to manage profiles; you need bootstrap to get one).

## 5. Declarative profiles in `app.json`

```json
"engine": {
  "id": "drive_local",
  "profiles": [
    { "id": "admin", "display_name": "מנהל", "admin": true },
    { "id": "user2", "display_name": "משתמש 2" }
  ]
}
```

The first declared profile with `"admin": true` is the one a fresh deployment comes up with. Adding
a line here auto-creates the profile **and** its connection on the next `bbox run`.

## 6. Bootstrap reconcile — the same on a fresh or an existing machine

Runs at app start, in-process, idempotent. Per declared profile:

| State | Action |
|---|---|
| profile missing | create row → mint key → store hash → **create vault instance with the key** → record in ledger |
| profile + instance exist | leave alone. **Never re-mint a key** |
| profile exists, instance missing | re-create the instance from the stored key, or rotate if unrecoverable |
| we created it, no longer declared | remove profile **and** instance |
| exists, never ours (UI-created) | **leave alone** — a redeploy must never delete an operator's profile |

Ledger = the set of profiles this reconciler created, on the app's volume. This is the rule
`mailserver-init` already proves; it is what makes `bbox run` safe to re-run on a live company.

If connections is unreachable at bootstrap, the profile still exists locally and the instance is
created on a later pass — retry, never fail the boot, never mint a second key.

## 7. Creating a profile always creates its connection

In one operation, whether from `app.json` or from the UI's profile-management screen:

```
create profile row  →  mint key  →  store hash  →  create vault instance  →  appears in the bar
```

Switching the bar to that connection shows **that profile's** data. Create-then-separately-connect is
a step with no decision in it, and it is exactly what made "add a mail user" undiscoverable.

## 8. The five slots

**1 — Declare engines and profiles** in `app.json`. The **only** place. No hardcoded provider list in
a UI, a service, or the console.

**2 — One adapter per engine.** `CANONICAL_OPS` (mandatory) + `PROTOCOL_OPS` (optional). **Absence of
a method is how an engine says "unsupported"** — never a stub that fails at call time. Capability is
derived by introspection so `/manifest` cannot drift from the implementation.

**3 — One resolution choke point.**
```
resolve(profile_id=None) -> (profile_id, adapter)
  precedence: explicit argument > binding > (error — there is no implicit fallback)
  cache key:  (profile_id, credential fingerprint)   ← rotation rebuilds without a restart
```
The only way to obtain an adapter. `/readyz` uses it too, so health and ops agree **by construction**.

**4 — The standard HTTP surface**, identical in every app:

| Method | Path | Ring |
|---|---|---|
| GET | `/manifest` | — |
| GET | `/readyz` | — |
| GET | `/engines` | — |
| GET | `/profiles` · POST `/profiles` · DELETE `/profiles/<id>` | remote profiles |
| GET | `/profiles/<id>/probe` | verify **without** binding |
| POST | `/profiles/bind` | set the binding |
| GET | `/engine/profiles` | admin |
| POST | `/engine/profiles` | **admin** — create on the private engine |
| PATCH | `/engine/profiles/<id>` | self (own) / admin (others) |
| POST | `/engine/profiles/<id>/key` | rotate. self (own) / admin (others) |
| DELETE | `/engine/profiles/<id>` | admin. Removes access, **never data** |

Every op route accepts an optional `profile_id` override so one request can address a non-bound
profile — this is what makes automation multi-profile without touching the binding.

**5 — UI in three parts.** Connection bar (dot from `/readyz`, a real probe). Connect wizard
(engine → auth → credentials → **verify** → activate; activation is a separate explicit step).
**Profile-management screen**, shown when a private engine is bound and the acting profile is admin —
create, rotate keys, suspend. Deliberately *not* the connect wizard: creating an identity and
connecting to one are different acts.

## 9. The laws

1. **Unset binding = "use the default engine". Broken binding = "not ready".** Never fall back to the
   private engine because a remote profile went missing. The opposite once wrote a business's real
   documents to a local disk, green the whole way.
2. **One choke point.** If health and ops can resolve differently, they eventually will.
3. **A profile is verified, never merely added.**
4. **Absence of a method is "unsupported".** A stub that fails at call time is a lie the UI can't see.
5. **A write that did not happen never reports success.**
6. **A profile carries its identity in its credential, not in the environment.**
7. **Creating a profile creates its connection in the same operation.**
8. **Deleting a profile removes access, never data.**
9. **Data scoping is enforced in the engine's queries.** Never in the UI, never by convention.
10. **Never re-mint a key on boot.** Idempotence is what makes the reconciler safe.

## 10. Scope — build the shape now, the feature later

The binding is `{scope → profile_id}`, with exactly one scope today: `"deployment"`. **Store it as a
map from day one, never a scalar.** When per-user selection arrives the scope key becomes the user
id and nothing else moves. Platform users and permissions are a separate concern; the shape must not
need migrating twice.

## 11. Per-engine work to reach this

| | Has | Needs |
|---|---|---|
| **chat** | `chat_local-<userId>` → `LocalChatBackend({selfId})` — N profiles already work; engine-admin routes already separate | API key + real vault instance instead of the synthetic id; admin ring; drop `is_self`-as-identity |
| **mail** | mailboxes via `mailboxd`, each with a password | `LocalBackend(user, pw)` from the instance instead of `LOCALMAIL_*` env; `POST /mailboxes` mints the instance; **this is the smallest change of the three** |
| **drive** | one global `drive_files` table | a `profile` discriminator column, defaulting to the admin profile so rollout is a **no-op** (INDOX's proven pattern + `tenancy-lint.py`); drop the `POST /connections` refusal of `drive_local` |

## 12. Checklist for a new app

- [ ] engines **and** profiles declared in `app.json`
- [ ] one adapter per engine; optional ops omitted, not stubbed
- [ ] `resolve()` the only path to an adapter; `/readyz` uses it
- [ ] the standard routes, `profile_id` accepted on every op
- [ ] private profiles: row in the app DB (identity + admin flag + key hash), key in the vault
- [ ] data scoped by profile **in the queries**
- [ ] bootstrap reconciler: idempotent, ledger-backed, never re-mints
- [ ] creating a profile creates its connection
- [ ] connection bar + wizard + profile-management screen
- [ ] binding stored as a scope map on the app's volume
