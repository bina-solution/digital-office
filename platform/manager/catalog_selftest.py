#!/usr/bin/env python3
"""catalog-selftest — the gate for the signed catalog and install-by-reference.

    python3 platform/manager/catalog_selftest.py

The roadmap's own "known debt" list says the compiler has no unit tests. A signature
implementation with no tests is worse than no signature: it looks like a guarantee. So the
security-relevant behaviour is asserted here, and every assertion is a REFUSAL — the property that
matters is not "a good index verifies", it is "a bad one does not".

Runs entirely in a temp directory against a synthetic catalog. Touches no live state, needs no
docker, needs no network.
"""
import json
import pathlib
import shutil
import sys
import tempfile
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import catalog                                             # noqa: E402
import signing                                             # noqa: E402
import appinstall                                          # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))


def refuses(name, fn, needle=None):
    """The assertion this file exists for: the operation must FAIL, for the stated reason."""
    try:
        fn()
    except Exception as e:
        ok = (needle is None) or (needle.lower() in str(e).lower())
        check(name, ok, f"raised, but not about '{needle}': {e}")
        return
    check(name, False, "it was ACCEPTED")


def rejects(name, app_dir, needle):
    """inspect() REPORTS refusals rather than raising — a disclosure screen has to show every
    reason at once, not the first one. So assert on the list."""
    try:
        _, _, _, _, refusals = appinstall.inspect(app_dir)
    except Exception as e:
        check(name, needle.lower() in str(e).lower(), f"raised: {e}")
        return
    hit = [r for r in refusals if needle.lower() in r.lower()]
    check(name, bool(hit), f"refusals were: {refusals or '(none)'}")


def make_app(root, aid, host="demo", layer=3, extra=None):
    d = root / aid
    d.mkdir(parents=True, exist_ok=True)
    m = {"id": aid, "title": {"he": "בדיקה", "en": "Demo"}, "layer": layer, "kind": "service",
         "version": "1.0.0", "summary": {"en": "test app"}, "capabilities": [], "use": [],
         "connections": [], "compose": "docker-compose.yml",
         "routing": [{"host": host, "port": 80, "auth": "none"}]}
    m.update(extra or {})
    signing.write_lf(d / "app.json", json.dumps(m, indent=2, ensure_ascii=False) + "\n")
    signing.write_lf(d / "docker-compose.yml",
                     f"services:\n  {aid}:\n    image: alpine:3\nnetworks:\n"
                     f"  traefik-network:\n    external: true\n")
    return d


def main():
    work = pathlib.Path(tempfile.mkdtemp(prefix="catalog-selftest-"))
    try:
        print("1. signature primitive")
        ok, detail = signing.selftest()
        check("RFC 8032 vectors", ok, detail)

        print("\n2. keys + envelope")
        kr = work / "keyring.json"
        sk = work / "secret.json"
        kid, pub = signing.keygen("selftest", sk, kr)
        check("key id is sha256(pubkey)[:16]", kid == signing.key_id(bytes.fromhex(pub)))

        src = work / "apps"
        make_app(src, "demo-one", host="demo-one")
        out, index = catalog.build(work / "cat", base_url=None, secret_path=sk, keyring_path=kr,
                                   source_dir=src)
        check("index has the app", len(index["entries"]) == 1 and index["entries"][0]["id"] == "demo-one")

        idx_path = out / catalog.INDEX_NAME
        env = json.loads((out / catalog.SIG_NAME).read_text(encoding="utf-8"))
        good, why = signing.verify_envelope(env, idx_path.read_bytes(), kr)
        check("a good index verifies", good, why)

        print("\n3. refusals — the whole point")
        tampered = idx_path.read_bytes().replace(b'"demo-one"', b'"demo-0ne"')
        bad, why = signing.verify_envelope(env, tampered, kr)
        check("a tampered index of the SAME LENGTH is refused on its hash",
              not bad and "sha256" in why, why)
        longer = idx_path.read_bytes().replace(b'"demo-one"', b'"demo-evill"')
        bad2, why2 = signing.verify_envelope(env, longer, kr)
        check("a tampered index of a different length is refused on its size",
              not bad2 and "size" in why2, why2)

        env2 = dict(env)
        env2["index"] = dict(env["index"])
        env2["index"]["sha256"] = signing.sha256_bytes(tampered)
        bad, why = signing.verify_envelope(env2, tampered, kr)
        check("re-hashing the tampered index does not help (signature covers the hash)",
              not bad and "SIGNATURE DOES NOT VERIFY" in why, why)

        # An attacker who signs with their OWN key and ships the public key inside the envelope.
        # This is the failure mode of every "self-describing" signature scheme.
        sk2, kr2 = work / "evil.json", work / "evil-keyring.json"
        signing.keygen("attacker", sk2, kr2)
        evil = signing.sign_envelope(idx_path, sk2, kr2)
        bad, why = signing.verify_envelope(evil, idx_path.read_bytes(), kr)
        check("an index signed by an UNTRUSTED key is refused, even though the envelope carries "
              "that key", not bad and "not trusted" in why, why)

        empty_kr = work / "empty-keyring.json"
        signing.save_keyring({"format": "bina.catalog.keyring/v1", "keys": {}}, empty_kr)
        bad, why = signing.verify_envelope(env, idx_path.read_bytes(), empty_kr)
        check("a deployment that trusts nothing accepts nothing", not bad)

        print("\n4. artifacts")
        e = index["entries"][0]
        art = out / "artifacts" / e["artifact"]["name"]
        check("artifact hash in the index matches the file",
              signing.sha256_file(art) == e["artifact"]["sha256"])
        out2, index2 = catalog.build(work / "cat2", secret_path=sk, keyring_path=kr, source_dir=src)
        check("packing is REPRODUCIBLE (same tree -> same sha256)",
              index2["entries"][0]["artifact"]["sha256"] == e["artifact"]["sha256"])

        slip = work / "slip.zip"
        with zipfile.ZipFile(slip, "w") as z:
            z.writestr("../../../evil.txt", "pwned")
        refuses("zip-slip archive is refused", lambda: catalog.unpack(slip, work / "slipout"),
                "unsafe path")

        noapp = work / "noapp.zip"
        with zipfile.ZipFile(noapp, "w") as z:
            z.writestr("readme.txt", "hello")
        refuses("an archive with no app.json is refused",
                lambda: catalog.unpack(noapp, work / "noappout"), "no app.json")

        print("\n5. install-by-ref refusals (against the LIVE catalog)")
        refuses("a bare file with no hash and no signed index entry is refused",
                lambda: appinstall.stage(str(art), index_ref=str(work / "nope.json")),
                "nothing proves these bytes")
        refuses("a wrong --sha256 is refused",
                lambda: appinstall.stage(str(art), index_ref=str(work / "nope.json"),
                                         expect_sha="00" * 32), "hash mismatch")

        # id / layer / route-host conflicts, checked by the compiler's own validate()
        dup = make_app(work / "dup", "indox", host="indox-x")
        rejects("an id already in the catalog is refused", dup, "id conflict")
        base = make_app(work / "base", "demo-base", host="demo-base", layer=1)
        rejects("a layer-1 app is refused (chassis is not installable)", base, "only layer-3")
        clash = make_app(work / "clash", "demo-clash", host="incoming-documents")
        rejects("an app claiming a route host another app owns is refused", clash,
                "route conflict")

        good_app = make_app(work / "good", "demo-good", host="demo-good-xyz")
        manifest, cat, state, dis, refusals_ = appinstall.inspect(good_app)
        check("a clean app passes validation", not refusals_, "; ".join(refusals_))
        check("disclosure is computed, not written", dis["id"] == "demo-good"
              and "credentials" in dis and "powers" in dis)
        check("a route with auth:none is disclosed as such",
              any(p["id"] == "no-auth" for p in dis["powers"]))

        socketed = make_app(work / "sock", "demo-sock", host="demo-sock-xyz")
        signing.write_lf(socketed / "docker-compose.yml",
                         "services:\n  demo-sock:\n    image: alpine:3\n    volumes:\n"
                         "      - /var/run/docker.sock:/var/run/docker.sock\n")
        _, _, _, dis2, _ = appinstall.inspect(socketed)
        check("mounting the docker socket is disclosed as CRITICAL",
              any(p["id"] == "docker-socket" and p["level"] == "critical" for p in dis2["powers"]))

        # A credential an app declares for ITSELF (contributes.connection_providers) is named to
        # its installer like any other. Read from the tree: the claim is about the catalog shipped.
        own = next((p for f in sorted(catalog.APPS.glob("*/app.json"))
                    for p in (json.loads(f.read_text(encoding="utf-8")).get("contributes") or {})
                    .get("connection_providers") or [] if p.get("title")), None)
        told = catalog._providers_catalog().get((own or {}).get("id"), {})
        check("a credential an app declares for itself is disclosed by its title and kind",
              own is not None and told.get("title") == own["title"] and told.get("kind") == own["kind"],
              f"{(own or {}).get('id')}: {told}")
    finally:
        shutil.rmtree(work, ignore_errors=True)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("CATALOG SELFTEST FAILED: " + "; ".join(FAIL))
        return 1
    print("CATALOG SELFTEST OK — signatures, hashes and every refusal path hold.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
