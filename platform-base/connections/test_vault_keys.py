#!/usr/bin/env python3
"""test_vault_keys — the vault's key can be replaced without losing a byte, and a wrong key never wipes it (hos-002).

    python3 platform-base/connections/test_vault_keys.py

Before: one key, CONNECTIONS_ROOT_KEY, falling back to a constant written in app.py; and a vault the key could not
open read as `{}`, which the next write persisted over every secret. Now:

  · a vault the configured keys cannot open RAISES VaultUnreadable — it is never read as empty, and so never
    overwritten by a read-modify-write;
  · CONNECTIONS_ROOT_KEY_OLD keeps an old key able to decrypt while CONNECTIONS_ROOT_KEY encrypts;
  · rekey() re-encrypts the vault under the new key, after which the old key alone no longer opens it;
  · an office still on the constant keeps working (it is warned, not broken).

Hermetic: its own vault file in a temporary directory.
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ["CONN_DATA_DIR"] = tempfile.mkdtemp(prefix="vaultkeys-")
os.environ.pop("CONNECTIONS_ROOT_KEY", None)
os.environ.pop("CONNECTIONS_ROOT_KEY_OLD", None)
import app  # noqa: E402

FAILS = []


def check(cond, what):
    print(("PASS  " if cond else "FAIL  ") + what)
    if not cond:
        FAILS.append(what)


def keys(new=None, old=None):
    for name, value in (("CONNECTIONS_ROOT_KEY", new), ("CONNECTIONS_ROOT_KEY_OLD", old)):
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def main() -> int:
    app.VAULT_PATH = os.path.join(tempfile.mkdtemp(prefix="vaultkeys-vault-"), "vault.enc")
    keys()                                                     # an office on the constant
    app.vault_write({"probe": "v1", "other": "v2"})
    check(app.vault_read().get("probe") == "v1", "an office on the constant still reads its vault")

    keys(new="new-key-" + "x" * 24)                            # the key changed, the old one forgotten
    try:
        app.vault_read()
        check(False, "a vault no configured key opens raises instead of reading as empty")
    except app.VaultUnreadable:
        check(True, "a vault no configured key opens raises instead of reading as empty")
    before = open(app.VAULT_PATH, "rb").read()
    try:
        app.create_instance("google-oauth", "probe", {"t": "1"}, "x@example.com", iid="probe-1")
    except app.VaultUnreadable:
        pass
    check(open(app.VAULT_PATH, "rb").read() == before, "a write through a read it could not do leaves the vault untouched")

    keys(new="new-key-" + "x" * 24, old=app.DEV_ROOT_KEY)      # the replacement: new key, old beside it
    check(app.vault_read().get("other") == "v2", "with the old key beside the new one the vault opens")
    n = app.rekey()
    check(n >= 2, f"rekey carried every entry over ({n})")

    keys(new="new-key-" + "x" * 24)                            # the old key dropped
    check(app.vault_read().get("probe") == "v1", "after rekey the new key alone opens the vault")
    keys(new=app.DEV_ROOT_KEY)
    try:
        app.vault_read()
        check(False, "after rekey the old key alone no longer opens it")
    except app.VaultUnreadable:
        check(True, "after rekey the old key alone no longer opens it")
    # the vault is now under the new key and the configured key is the constant: it cannot be opened
    c = app.app.test_client()
    check(c.get("/healthz").get_json().get("vault") == "unreadable", "/healthz says the vault is unreadable")
    r = c.get("/api/connections")
    check(r.status_code == 503 and "no configured key" in (r.get_json() or {}).get("error", ""),
          "a route that reads the vault answers 503 with the reason, not a bare 500")
    r = c.post("/api/vault/wipe", json={"confirm": "wipe"})
    aside = [f for f in os.listdir(os.path.dirname(app.VAULT_PATH)) if ".unreadable-" in f]
    check(r.status_code == 200 and aside, "the wipe button still works: the unreadable file is set aside, not deleted")
    check(app.vault_read() is not None and c.get("/healthz").get_json().get("vault") == "readable",
          "after the wipe the vault is fresh and readable")
    keys()
    print(f"{'OK' if not FAILS else 'FAILED'}: {len(FAILS)} failure(s)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
