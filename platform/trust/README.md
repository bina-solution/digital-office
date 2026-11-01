# platform/trust — the keys this deployment will accept a catalog from

`keyring.json` is the **whole** trust root of the app store. An index signature is checked against
a public key **already in this file**; a key that is not here is refused, no matter what the index
claims about itself. That is the only reason the scheme is worth anything: an envelope that carries
its own key and is verified against it verifies every forgery ever made, so the key in the envelope
is ignored (see `platform/manager/signing.py`).

    bbox catalog keygen                     # this deployment's own signing key (public half lands here)
    bbox catalog trust <key-id> <hex>       # pin somebody else's key — the ONE trust decision
    bbox catalog keys                       # what is currently trusted

## What is in the file

| field | meaning |
|---|---|
| `key_id` (the map key) | `sha256(public_key)[:16]` — **self-certifying**: it names the key, never a person |
| `public_key` | 32-byte Ed25519 public key, hex |
| `label` | free text an operator wrote when pinning. Not verified by anything. |
| `added` | when it was pinned |

## What pinning a key does and does not mean

Pinning says: *"an index signed by the holder of this secret key may be installed here."* It says
nothing about who that holder is. There is no CA, no web of trust, no revocation list and no expiry.
If you fetched the key from the same URL as the index, you have proved the file was not corrupted or
altered **in storage or transit by someone who does not hold the key** — integrity. You have not
proved provenance. Provenance requires getting the key id from somewhere the publisher controls and
an attacker does not.

To distrust a key, delete its entry. Anything it signed stops verifying immediately.

**A signature never says an app is safe.** It says who published it. What the app will *do* is the
pre-install disclosure's job (`bbox catalog show <id>`), computed from the manifest and the compose
file rather than from anyone's promise.
