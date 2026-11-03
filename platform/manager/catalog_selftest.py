#!/usr/bin/env python3
"""catalog-selftest — the gate for the signed catalog and install-by-reference.

    python3 platform/manager/catalog_selftest.py

The roadmap's own "known debt" list says the compiler has no unit tests. A signature
implementation with no tests is worse than no signature: it looks like a guarantee. So the
security-relevant behaviour is asserted here, and every assertion is a REFUSAL — the property that
matters is not "a good index verifies", it is "a bad one does not".

Runs entirely in a temp directory against a synthetic catalog. Touches no live state, needs no
docker, needs no network — only git, since an artifact is git's tree.
"""
import contextlib
import io
import json
import os
import pathlib
import shutil
import subprocess
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


def cannot(name, why):
    """A check this machine cannot make — said, and never counted as a pass."""
    print(f"  ----  {name}  (not run here: {why})")


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


def git(repo, *args, stdin=None):
    """git in a fixture repository, its output stripped."""
    return subprocess.run(["git", "-C", str(repo), "-c", "core.autocrlf=false", *args], input=stdin,
                          capture_output=True, check=True).stdout.decode("utf-8").strip()


def members(zpath):
    """name -> (permission bits, create_system) of every member of an artifact."""
    with zipfile.ZipFile(zpath) as z:
        return {i.filename: (i.external_attr >> 16 & 0o777, i.create_system) for i in z.infolist()}


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
        # …and the same id with a line break after it is not a NEW id (DGO-615): `$` matched before
        # the break, so no conflict was found and the install went on to name a directory with it.
        broken = make_app(work / "broken", "demo-broken", host="demo-broken-xyz",
                          extra={"id": "indox\n"})
        rejects("an id that ends in a line break is refused", broken, "not a valid id")
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

        print("\n6. the artifact is git's tree, the same on every OS (DGO-609)")
        # An id and a version name the artifact's file: one that walks out of artifacts/ is refused
        # by name, and the refused build writes nothing — where it used to write <out>/../x.zip.
        around = work / "around"
        walks = make_app(work / "walks", "demo-walks", host="demo-walks",
                         extra={"version": "0/../../../x"})
        refuses("a version that walks out of artifacts/ is refused, naming the app and why",
                lambda: catalog.build(around / "cat", sign_it=False, source_dir=walks.parent),
                "demo-walks: version '0/../../../x' is not SemVer")
        walks_id = make_app(work / "walks-id", "demo-walks-id", host="demo-walks-id",
                            extra={"id": "../../x"})
        refuses("an id that walks out of artifacts/ is refused, naming the app and why",
                lambda: catalog.build(around / "cat", sign_it=False, source_dir=walks_id.parent),
                "demo-walks-id: id '../../x' is not an app id")
        written = sorted(p.relative_to(work).as_posix() for p in around.rglob("*") if p.is_file())
        check("…and a refused build writes no file, outside artifacts/ or in it", not written,
              f"written: {written}")
        semver = ["0.0.0", "1.2.3", "1.0.0-alpha.1", "1.0.0-0.3.7", "1.0.0-x-y.7", "1.0.0+20130313",
                  "1.0.0-beta+exp.sha.5114f85", "10.20.30"]
        not_semver = ["1.0", "01.0.0", "1.0.0-01", "1.0.0-", "1.0.0+", "v1.0.0", "1.0.0\n",
                      "1.0.0-a..b", chr(0xFF11) + ".0.0", "0/../../../x", "1.0.0/x"]  # FULLWIDTH 1
        check("SemVer is SemVer 2.0.0, ASCII digits, the whole string",
              all(catalog.SEMVER.fullmatch(v) for v in semver)
              and not any(catalog.SEMVER.fullmatch(v) for v in not_semver),
              f"accepted {[v for v in not_semver if catalog.SEMVER.fullmatch(v)]!r}, refused "
              f"{[v for v in semver if not catalog.SEMVER.fullmatch(v)]!r}")
        ids = ["a", "indox", "google-workspace-agent", "2fa"]
        not_ids = ["", "indox\n", "../x", "a/b", "a.b", "a\\b", "Indox", "-x", "a_b"]
        check("an app id is lower-case letters, digits and hyphens, the whole string",
              all(catalog.APP_ID.fullmatch(i) for i in ids)
              and not any(catalog.APP_ID.fullmatch(i) for i in not_ids),
              f"accepted {[i for i in not_ids if catalog.APP_ID.fullmatch(i)]!r}, refused "
              f"{[i for i in ids if not catalog.APP_ID.fullmatch(i)]!r}")
        # What git used to quote now reaches the packer: a name an unpacker reads otherwise is refused
        fine = ["app.json", "a b/c.txt", 'say "hi".txt', "שלום.txt"]
        odd = ["a\\b.txt", "a\nb.txt", "a\tb.txt", "a" + chr(0x7F), "x" + chr(0xDCFF) + ".txt"]
        check("a member name is UTF-8, with no control character and no backslash",
              all(catalog._portable(n) for n in fine) and not any(catalog._portable(n) for n in odd),
              ascii([n for n in fine if not catalog._portable(n)]
                    + [n for n in odd if catalog._portable(n)]))
        # …and the build refuses one by name. Outside git os.walk hands it over as git would: a lone
        # surrogate is a raw byte on POSIX and an unpaired UTF-16 unit on NTFS, so this runs anywhere.
        bad = make_app(work / "bad", "demo-bad", host="demo-bad")
        signing.write_lf(bad / ("x" + chr(0xDCFF) + ".txt"), "x")
        refuses("a file name that is not UTF-8 is refused, naming the app and the file",
                lambda: catalog.build(work / "cat4", sign_it=False, source_dir=bad.parent),
                "demo-bad: " + repr("x" + chr(0xDCFF) + ".txt") + " cannot be named in an artifact")

        if not shutil.which("git"):
            check("git is on PATH (the artifact is git's tree)", False, "no git")
        else:
            repo, hebrew = work / "repo", "שלום.txt"    # a name git's core.quotepath quotes
            app = make_app(repo / "apps", "demo-git", host="demo-git",
                           extra={"blueprints": {"n8n": "blueprint/n8n"}})
            for rel, body in {"tool.sh": "echo", "notes.txt": "n", hebrew: "x", "linked.txt": "x",
                              "data": "../../.env", "blueprint/n8n/a.workflow.ts": "export {}",
                              "blueprint/n8n/b.workflow.ts": "export {}",
                              "blueprint/n8n/b.json": "{}", "blueprint/n8n/c.json": "{}",
                              "blueprint/n8n/README.md": "x"}.items():
                (app / rel).parent.mkdir(parents=True, exist_ok=True)
                signing.write_lf(app / rel, body)
            git(repo, "init", "-q")
            git(repo, "config", "core.quotepath", "true")   # the default, whatever ~/.gitconfig says
            git(repo, "add", "--", *(f"apps/demo-git/{r}" for r in (
                "app.json", "docker-compose.yml", "tool.sh", "notes.txt", hebrew, "linked.txt",
                "blueprint")))
            git(repo, "update-index", "--chmod=+x", "apps/demo-git/tool.sh")
            os.chmod(app / "notes.txt", 0o755)    # the disk says executable; git keeps 100644
            # a link as git tracks it (mode 120000), and as a checkout without symlinks leaves it
            blob = git(repo, "hash-object", "-w", "--stdin", stdin=b"../../.env")
            git(repo, "update-index", "--add", "--cacheinfo", f"120000,{blob},apps/demo-git/data")
            # a file git tracks that the working tree has since replaced by a link (git still says
            # 100644) — where a link can be made: Windows asks a privilege for one
            signing.write_lf(work / "outside.txt", "TOKEN=1\n")
            (app / "linked.txt").unlink()
            try:
                os.symlink(work / "outside.txt", app / "linked.txt")
                no_link = None
            except OSError as e:
                no_link = f"no symlink without a privilege ({e.__class__.__name__})"
                signing.write_lf(app / "linked.txt", "x")
            said = io.StringIO()
            with contextlib.redirect_stderr(said):
                out3, index3 = catalog.build(work / "cat3", sign_it=False, source_dir=repo / "apps")
            e3 = index3["entries"][0]
            got = members(out3 / "artifacts" / e3["artifact"]["name"])
            check("a name git quotes (Hebrew) is packed, exactly as git names it",
                  f"demo-git/{hebrew}" in got, ascii(sorted(got)))
            check("each mode is git's, not the disk's (100755 -> 0755, 100644 -> 0644)",
                  got.get("demo-git/tool.sh", (0,))[0] == 0o755
                  and got.get("demo-git/notes.txt", (0,))[0] == 0o644, ascii(got))
            check("every member is made by Unix (create_system 3), whichever OS packs it",
                  {s for _, s in got.values()} == {3}, ascii(got))
            check("a link git tracks is never packed", "demo-git/data" not in got, ascii(sorted(got)))
            check("…and the build names it",
                  "left out, links are never followed: demo-git/data" in said.getvalue(),
                  ascii(said.getvalue()))
            if no_link is None:
                check("a link on disk where git has a file is not followed either, and is named",
                      "demo-git/linked.txt" not in got and "demo-git/linked.txt" in said.getvalue(),
                      ascii([sorted(got), said.getvalue()]))
            else:
                cannot("a link on disk where git has a file is not followed either", no_link)
            check("workflows are the blueprint's ids: *.workflow.ts and *.json, one per stem",
                  e3["automations"]["workflows"] == 3, ascii(e3["automations"]))
            check("…and the disclosure says how many it imports",
                  any("Imports 3 workflow(s)" in p["text"] for p in catalog.disclose(e3)["powers"]))
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
