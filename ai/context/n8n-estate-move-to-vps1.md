# Moving the n8n estate to vps1 — without losing credentials  (DGO-64 / DGO-65)

**Audience:** the session that places INDOX (supabase + indox + the n8n estate) on the remote office
(vps1, phase 2 of the dgo plan). **Owner's decision (2026-09-30):** the five supabase containers and
the n8n workers are **not** started on the Mac (memory), so the estate is imported **there**, and
this document is the part that has to be right before anyone runs it: the workflows are 92 files of
declarative blueprint, the *credentials* are not, and a wrong encryption key makes the import fail
in a way that looks like four unrelated red checks an hour later.

Everything below was measured on the Mac office, 2026-10-01.

---

## 1. What the estate actually is

| Thing | Where it lives | Moves by |
|---|---|---|
| 92 workflows | `platform-base/n8n/workflows/*.ts` + `apps/{indox,chat,drive,mail,google-workspace-agent}/blueprint/n8n/` (compiled from `.workflow.ts`) | git — `bbox n8n push all` imports them |
| 24 credentials — 20 `env-managed` | the blueprint's `credential_overrides` block: **data comes from `.env`**, re-PATCHed on every push | `.env` on the target |
| 24 credentials — 4 OAuth (Gmail, Google Drive, Google Sheets, Sheets Trigger) | nowhere: the committed manifests carry `"data": ""` | a human re-authorizes once, in the target's UI |
| n8n's own tables (users, projects, executions) | n8n's postgres | `bbox n8n pull all` + `bbox n8n load-dump`, or a fresh bootstrap |
| The **encryption key** | `.env` (`N8N_ENCRYPTION_KEY`) *and* `/home/node/.n8n/config` inside the n8n container | must be identical on both sides for any credential blob to decrypt |

A credential blob in n8n is AES-encrypted with the instance's key. There is no re-encryption on
import: `import:credentials` writes what it is given, and a PATCH/read of an existing row decrypts
the stored blob first. That single fact is what the rest of this document is about.

## 2. The drift that was fixed here, and why it mattered

`python3 scripts/env-consistency-check.py` failed:

```
✗ N8N_ENCRYPTION_KEY does not match the blueprint, and .env.ex has the one that does.
    blueprint expects fingerprint : 77aee1e843d268cd
    .env currently has            : bab9b99374559d79
```

Measured state before the fix: **0 workflows, 24 credentials** in `n8n-local` — 18 rows with an
encrypted blob (`U2FsdGVkX1…`, the OpenSSL `Salted__` envelope), 6 with empty data. `bbox n8n push`
refuses in exactly that situation (`platform-base/n8n/hooks/push`, the fingerprint block: a mismatch
on an instance that already holds credentials is FATAL, because step 1.5's PATCH would have to
decrypt a blob written under another key and the whole push — workflows included — dies with it).

The Mac's `.env` is minted by `scripts/ci-env.sh`, which generates a random key; `.env.ex` carries
the canonical one, and the blueprint's `encryption_key_fingerprint` pins it. For a **fresh** office
that mismatch is harmless (0 credential rows → the hook says so and imports normally, which is how
CI works). It is only fatal where credentials already exist — and it is exactly what a
`pg_dump`-restore or a `load-dump` from production needs to be right.

### What was done (Mac, 2026-10-01)

```bash
# 1) back up first — the 18 blobs become undecryptable, and this is the way back
docker exec n8n-postgres-local sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  | gzip > data/db-dumps/n8n-pre-keyfix-$(date +%Y%m%d-%H%M%S).sql.gz

# 2) the key: .env takes .env.ex's value (fingerprint 77aee1e843d268cd)
# 3) n8n reads its key from the settings file too, and REFUSES to start when the two differ:
#    "Mismatching encryption keys. The encryption key in the settings file /home/node/.n8n/config
#     does not match the N8N_ENCRYPTION_KEY env var."
docker exec n8n-local sh -c 'cp /home/node/.n8n/config /home/node/.n8n/config.bak &&
                             printf "{\n\t\"encryptionKey\": \"<the .env value>\"\n}" > /home/node/.n8n/config'

# 4) recreate what reads the key — main + webhook receiver; the workers stay DOWN here (owner's call)
./scripts/dc up -d --no-deps n8n n8n-webhook

# 5) proof
python3 scripts/env-consistency-check.py        # → env-consistency OK
```

`scripts/env-consistency-check.py` never looks at the container, so step 3 is the half it cannot
see — a green check with a stale settings file is a container that will not come back up.

**Proof that the new key works end to end** (a credential written *after* the switch reads back):

```
$ docker exec n8n-local n8n import:credentials --input=/tmp/dgo65-testcred-arr.json
Successfully imported 1 credential.
$ docker exec n8n-local n8n export:credentials --id=dgo65keycheck0001 --decrypted --pretty
… "data": { "name": "Authorization", "value": "dgo65-roundtrip-ok" }   ← the exact value written
```

**State of the 24 legacy rows after the switch** (stated plainly, because it is a repair someone
will have to do): their blobs are encrypted under the *previous* key, so they are unreadable now.
Nothing is lost that is not reproducible — 20 of them are `env-managed` and are re-created from
`.env` by the next push's step 1.5, and the 4 OAuth ones were already empty. But `import:credentials`
is **create-if-missing**, so a push will not overwrite them; on a machine in that state, delete the
stale rows first and let the push recreate them:

```sql
-- the same rows the push would otherwise fail to reseed (they carry a pre-fix blob)
delete from credentials_entity where data <> '';
```

## 3. The runbook — importing the estate on vps1

Run this **on vps1**, from its own checkout, after `bbox run` there is green (dgo plan step
`converge` → `run` → `health`). Nothing here is Mac-specific except the note at the end.

```bash
# 0) preconditions — one commit, both sides (plan decision 11)
git -C <checkout> log -1 --format=%H          # the SAME commit the Mac is on, and PUSHED
python3 scripts/env-consistency-check.py      # must be OK (a fresh office mints its own keys: OK)

# 1) the whole estate in one command: owner → credentials → workflows → activation → restart
./bbox n8n push all

# 2) verify — three separate answers, because they fail independently
./bbox n8n status                             # drift, published/active, credential count
./bbox n8n verify                             # keys + credentials + instance readiness
docker exec n8n-postgres-local sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc \
  "select count(*) from workflow_entity;"'    # → 92
docker exec n8n-postgres-local sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc \
  "select count(*) from credentials_entity;"' # → 24
```

What to expect, and what each surprise means:

* **A key mismatch on a fresh instance is not a failure.** The push says so and imports anyway: the
  credentials are *created* from the manifest and then reseeded from `.env` under the instance's own
  key. It is fatal only when `credentials_entity` is non-empty (see §2).
* **4 credentials need a human.** Gmail, Google Drive, Google Sheets, Sheets Trigger have no secret
  in git; they must be authorized once in the target's own UI (the OAuth recipe is
  [incoming-documents-onboarding.md](incoming-documents-onboarding.md) §8c). Until then any workflow
  that uses them fails at its first Google call — which is most of INDOX.
* **Credentials come from the target's `.env`.** If a `${VAR}` is unset/empty there, step 1.5 SKIPS
  that credential on purpose (it never blanks a live secret) and says which variables were empty —
  read that line before concluding the import worked.
* **`EXECUTIONS_MODE=queue`:** the workers must be up for anything to *run*. `bbox run` starts them;
  a host that cannot afford them will import a complete estate and execute nothing.
* **Google Drive/Gmail triggers do not fire retroactively.** After the import, INDOX's backlog is
  whatever its own reset workflow is told to pull — check `bbox n8n test indox <wfId> --prod` rather
  than waiting for a poller.

### The higher-fidelity alternative (a dump, not an import)

If the target must inherit more than the blueprint describes (users, projects, execution history):

```bash
# on the SOURCE (Mac): full encrypted-credential cache + a dump
./bbox n8n pull all                                   # writes platform-base/n8n/.credentials-state
docker exec n8n-postgres-local sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' > n8n.sql
# on the TARGET: the SAME N8N_ENCRYPTION_KEY in .env, then
./bbox n8n load-dump n8n.sql
```

`load-dump` restores the dump and starts n8n (forward migrations run then). The credential blobs
come across as-is, so **the key has to match on both sides or every credential is unreadable** — the
whole reason `encryption_key_fingerprint` exists. Two shortcuts that do not work: a different key,
and "just re-run push afterwards" (create-if-missing will not replace the restored rows).

## 4. Acceptance for the remote session

* `./bbox n8n verify` green and `python3 scripts/env-consistency-check.py` OK on vps1;
* 92 workflows in `workflow_entity`, 24 credentials, the 20 env-managed ones resolvable;
* a document sent to the office mailbox is ingested, classified and visible in INDOX **within a
  minute** (DGO-64's own acceptance line);
* the Mac's office is untouched by it: no workers, no supabase, no workflows imported here.
