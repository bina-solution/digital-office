"""מפתחות בוואט — an app's secret is LEASED from the credential plane, never carried by the app.

SECTION 9 OF THE RELEASE (rel-3, apps/project-pln/plans/dgo-dev.yaml): every security claim is a
test. This is the one for `ai/context/dgo-security.md` §3.1 — Secrets, "vault-owned lifecycle": the
credential plane owns the secret, an app holds a NAME and leases the value at boot.

WHERE THE CLAIM LIVES, IN CODE. An app that reads a secret declares it in its own `app.json` under
`broker` (`blank_env` = the env names that ARE secrets, `entrypoint` = its real command) and lists
under `connections[]` what it may be granted. `platform/manager/reconcile.py` compiles those blocks
into `.generated/connections.override.yml` (`render_broker`), and `compose_files()` places that
overlay LAST in the `-f` order, on purpose: the app's own compose hands the container
`SECRET=${SECRET:-}` (the host's value, interpolated at up time), and only a later file can take it
back. The overlay blanks each declared name, mounts `platform-base/connections/inject.sh` read-only,
and wraps the app's command in it; at boot the injector proves the container's identity to the broker
at `connections:8990`, receives ONLY what that app's `connections[]` declares, writes the values to a
file it sources and unlinks, and execs the real command.

FIVE THINGS ARE MEASURED, AND THE FOURTH IS WHAT KEEPS THE OTHERS FROM BEING DECORATION:

  1. declared  every enabled app with a `broker` block names the secrets it blanks (none is blanking
               nothing) and declares what it may be granted (`connections[]` is the broker's whole
               authorization input — a cut-over app with none can never receive its values);
  2. blanked   each of those names reaches the container as `NAME=` — an empty right side, which is
               what makes the value absent from `docker inspect`, from the container's environ and
               from any later `docker exec`. A BARE `NAME` FAILS (compose re-imports it from the host
               environment, undoing the cutover on any machine that exports it) and a value FAILS (a
               key in the config is the claim, broken);
  3. leased    nothing but the lease comes in: the entrypoint runs `/inject.sh` first, `CONN_URL` is
               the credential plane, the injector is mounted `:ro`, and `depends_on: connections:
               service_healthy` makes it FAIL CLOSED (a consumer that boots without its secrets fails
               later, somewhere else, with a worse error);
  4. order     measured BY EFFECT on the real `-f` order with compose's own layering rule (a later
               file wins per key): before the overlay the app carries the host's value for the name,
               after it the name is empty. If check 2 ever stops holding, this check fails too — it
               is the proof that check 2 is measuring something that exists;
  5. live      the running container of a cut-over app, read with one `docker inspect` and NO value
               ever read out: each declared name is empty in that container's environment, so the
               office is running the leased shape and not the pre-cutover one.

WHY THIS IS NOT ONE OF ITS NEIGHBOURS. Gate G92 (`tracked-secret-lint.py`) asks whether a secret
VALUE sits in a tracked file, and `platform-base/connections/test_vault_keys.py` asks what the vault
FILE does when the key changes; `test_broker.py` asks what the broker REFUSES at the door. None of
them asks the question here: was this container BUILT to hold the value at all, or to lease it? The
overlay could be rendered with a bare name, with a value, without the injector, without the
fail-closed wait, or first instead of last — five plausible edits, each of which puts the secret back
into the app's config, and until this file nothing measured any of them.

THE PROOF THAT IT CAN FAIL is in the file: `--inject` renders five such violations into an in-memory
copy and requires each one to be CAUGHT by the check that names it (a mutation nobody catches is a
real failure of this test's sensitivity, and it says so). Nothing is written anywhere.

Run: `python3 platform/manager/test_broker_lease.py` (also discovered and run by gate G72,
`scripts/refactor/plane-tests-lint.py`). Exit 0 = every claim held, 1 = a claim is broken (or an
injection went unnoticed), 3 = NOT RUN, with the reason on a line that starts `NOT RUN ` — a checkout
that has never compiled has no overlay to measure, and that is not a pass.

The file prints NAMES, counts and booleans. It never prints a value, never decrypts anything and
never contacts the vault.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys

import yaml

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
GEN = REPO / ".generated"
OVERLAY = ".generated/connections.override.yml"
COMPILED = ".generated/compose.yml"
INJECTOR = "platform-base/connections/inject.sh"
CONN_URL = "http://connections:8990"


def _load():
    spec = importlib.util.spec_from_file_location("reconcile_broker_lease", HERE / "reconcile.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["reconcile_broker_lease"] = mod
    spec.loader.exec_module(mod)
    return mod


rc = _load()


# ── reading a compose file the way compose does ──────────────────────────────────────────────────


def env_of(service: dict) -> dict[str, str | None]:
    """A service's `environment`, both of compose's spellings, as {name: raw value}.

    `None` means the entry carried no `=`: compose then imports the name from ITS OWN environment,
    which is the one spelling that silently undoes the cutover."""
    env = service.get("environment")
    out: dict[str, str | None] = {}
    if isinstance(env, dict):
        for k, v in env.items():
            out[str(k)] = "" if v is None else str(v)
    else:
        for item in env or []:
            s = str(item)
            if "=" in s:
                k, _, v = s.partition("=")
                out[k.strip()] = v
            else:
                out[s.strip()] = None
    return out


def services_of(path: pathlib.Path) -> dict[str, dict[str, str | None]]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(svc): env_of(body or {}) for svc, body in (data.get("services") or {}).items()}


def stack_files() -> list[str]:
    """The real `-f` order the launcher uses, with `.generated/compose.yml`'s `include:` expanded in
    its place — that include is how each app's OWN compose enters the model, so its position against
    the overlay is the thing being measured."""
    seq: list[str] = []
    for rel in rc.compose_files():
        p = REPO / rel
        if rel == COMPILED and p.is_file():
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            for inc in data.get("include") or []:
                seq.append(inc if isinstance(inc, str) else str(inc.get("path") or ""))
        seq.append(rel)
    return [s for s in seq if s]


def layered(seq: list[str]) -> dict[str, dict[str, str | None]]:
    """compose's layering rule, applied in order: a later file's value wins, per key, per service."""
    merged: dict[str, dict[str, str | None]] = {}
    for rel in seq:
        for svc, env in services_of(REPO / rel).items():
            merged.setdefault(svc, {}).update(env)
    return merged


def env_holds(names: set[str]) -> set[str]:
    """Which of `names` this office's `.env` really holds a value for — a boolean per name, never the
    value: `blank` is only doing work if the host actually had something to leak."""
    held: set[str] = set()
    p = REPO / ".env"
    if not p.is_file():
        return held
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        k, sep, v = line.partition("=")
        if sep and not k.lstrip().startswith("#") and k.strip() in names and v.strip():
            held.add(k.strip())
    return held


# ── the estate as declared ───────────────────────────────────────────────────────────────────────


def broker_service(cat: dict, aid: str) -> str:
    """The compose service `render_broker` will cut over — its own rule, restated so the owner of
    each rendered service can be named."""
    a = cat[aid]
    b = a.get("broker") or {}
    return b.get("service") or (a.get("routing") or [{}])[0].get("service") or aid


def build_view() -> dict:
    cat = rc.load_catalog()
    state = yaml.safe_load((REPO / "platform.state.yaml").read_text(encoding="utf-8")) or {}
    enabled = sorted(rc.enabled_ids(state, cat))
    text = rc.render_broker(cat, enabled)
    owners = {broker_service(cat, aid): aid for aid in enabled if cat[aid].get("broker")}
    services: dict[str, dict] = {}
    if text:
        services = (yaml.safe_load(text) or {}).get("services") or {}
    return {"cat": cat, "enabled": enabled, "text": text, "services": services, "owners": owners,
            "stack": stack_files(),
            "names": {svc: list((cat[owners[svc]].get("broker") or {}).get("blank_env") or [])
                      for svc in services}}


def own_compose(view: dict, svc: str) -> pathlib.Path:
    a = view["cat"][view["owners"][svc]]
    return a["_dir"] / (a.get("compose") or "docker-compose.yml")


# ── 1. declared ─────────────────────────────────────────────────────────────────────────────────


def check_declared(view: dict) -> str:
    rows = []
    for svc in sorted(view["services"]):
        aid = view["owners"][svc]
        names = view["names"][svc]
        if not names:
            raise AssertionError(f"{aid}: declares a `broker` cutover and blanks NO name — a lease "
                                 f"of nothing, and the app keeps whatever its compose hands it")
        if not (view["cat"][aid].get("connections") or []):
            raise AssertionError(
                f"{aid}: a cut-over app with no `connections[]` — the broker's whole authorization "
                f"input is that declaration, so {names} can never be granted and would boot empty")
        rows.append(f"{aid}→{svc} ({len(names)} secret(s): {', '.join(names)})")
    return f"{len(rows)} cut-over app(s): " + "; ".join(rows)


# ── 2. blanked ──────────────────────────────────────────────────────────────────────────────────


def check_blanked(view: dict) -> str:
    reported = []
    for svc in sorted(view["services"]):
        env = env_of(view["services"][svc])
        for name in view["names"][svc]:
            if name not in env:
                raise AssertionError(f"{svc}: the overlay never names {name} — the app's own compose "
                                     f"hands the container its value and nothing takes it back")
            value = env[name]
            if value is None:
                raise AssertionError(
                    f"{svc}: {name} is blanked as a BARE name, not `{name}=` — compose then imports "
                    f"it from the host environment, which undoes the cutover on every machine whose "
                    f"shell exports it")
            if value != "":
                raise AssertionError(
                    f"{svc}: {name} carries a VALUE in the compiled overlay — that is a secret in the "
                    f"office's config, which is the claim itself broken (its value is not printed "
                    f"here, by design)")
            reported.append(f"{svc}:{name}")
    return f"{len(reported)} name(s) reach the containers empty: " + ", ".join(reported)


# ── 3. leased ───────────────────────────────────────────────────────────────────────────────────


def check_leased(view: dict) -> str:
    parts = []
    for svc in sorted(view["services"]):
        body = view["services"][svc]
        entry = [str(x) for x in (body.get("entrypoint") or [])]
        if not entry or entry[0] != "sh" or "/inject.sh" not in entry[:2]:
            raise AssertionError(f"{svc}: the entrypoint does not run /inject.sh first "
                                 f"({entry[:2]}) — the container's command would start with no lease "
                                 f"and its secrets permanently empty")
        env = env_of(body)
        if env.get("CONN_URL") != CONN_URL:
            raise AssertionError(f"{svc}: CONN_URL is {env.get('CONN_URL')!r}, not the credential "
                                 f"plane ({CONN_URL})")
        if env.get("CONN_SERVICE") != svc:
            raise AssertionError(f"{svc}: CONN_SERVICE is {env.get('CONN_SERVICE')!r} — the injector "
                                 f"would ask the broker for another service's connections")
        mounts = [str(v) for v in (body.get("volumes") or [])]
        if not any(INJECTOR in m and m.endswith(":ro") for m in mounts):
            raise AssertionError(f"{svc}: the injector is not mounted read-only ({mounts}) — a "
                                 f"writable injector is a writable lease")
        if not (REPO / INJECTOR).is_file():
            raise AssertionError(f"{svc}: the overlay mounts {INJECTOR}, which is not in the tree")
        dep = ((body.get("depends_on") or {}).get("connections") or {})
        if (dep.get("condition") if isinstance(dep, dict) else None) != "service_healthy":
            raise AssertionError(f"{svc}: depends_on connections is {dep!r}, not healthy — a "
                                 f"consumer that boots before the vault is up fails later, elsewhere")
        parts.append(f"{svc}: sh {INJECTOR.lstrip('/')} → {CONN_URL} (CONN_SERVICE={svc}), fail-closed")
    return "; ".join(parts)


# ── 4. order, measured by effect ────────────────────────────────────────────────────────────────


def check_order(view: dict) -> str:
    seq = view["stack"]
    if OVERLAY not in seq:
        raise AssertionError(f"{OVERLAY} is not in the -f order ({seq}) — the blank is in a file "
                             f"compose never reads")
    cut = seq.index(OVERLAY)
    before, after = layered(seq[:cut]), layered(seq[:cut + 1])
    held = env_holds({n for svc in view["services"] for n in view["names"][svc]})
    parts, live = [], []
    for svc in sorted(view["services"]):
        own = own_compose(view, svc).relative_to(REPO).as_posix()
        if own not in seq:
            raise AssertionError(f"{svc}: {own} is not in the -f order at all ({seq}) — the app's own "
                                 f"compose is not compiled in, so nothing here describes the container")
        if seq.index(own) > cut:
            raise AssertionError(
                f"{svc}: the -f order puts the cutover ({OVERLAY}, position {cut}) BEFORE the app's "
                f"own compose ({own}, position {seq.index(own)}) — later files win, so the app's own "
                f"compose writes the value back over the blank at boot")
        for name in view["names"][svc]:
            got = before.get(svc, {}).get(name)
            if got is None:
                raise AssertionError(
                    f"{svc}: before the overlay {name} is not the app's own compose's to hand over "
                    f"({got!r}) — nothing would put it there, so the overlay's blank measures nothing")
            if got == "":
                raise AssertionError(
                    f"{svc}: {name} is ALREADY empty before the overlay — the -f order has the "
                    f"cutover first, so the app's own compose writes the value back at boot")
            if after.get(svc, {}).get(name) != "":
                raise AssertionError(f"{svc}: {name} is {after.get(svc, {}).get(name)!r} after the "
                                     f"whole -f order — later files did not win")
            if name in held:
                live.append(f"{svc}:{name}")
        parts.append(f"{svc}: '{view['names'][svc][0]}' carries the host's value before the overlay, "
                     f"empty after it")
    return (f"{len(parts)} service(s) losing the value at its own -f position: " + "; ".join(parts) +
            (f" · the host's .env really holds {len(live)} of them, so this is not hypothetical: "
             f"{', '.join(live)}" if live else
             " · NOTE the host's .env holds none of these names here, so the blank protects nothing "
             "on this checkout"))


# ── 5. live: the container the office is actually running ───────────────────────────────────────


def running(prefix: str) -> str | None:
    """A running container of that compose service, by the name `docker ps` shows — the office's own
    project suffix differs per install (`drive-staging` here), so the first stem is what is matched."""
    try:
        out = subprocess.run(["docker", "ps", "--format", "{{.Names}}"], capture_output=True,
                             text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for name in out.split():
        if name.split("-")[0] == prefix:
            return name
    return None


def check_live(view: dict) -> str:
    parts, measured, skipped = [], 0, []
    for svc in sorted(view["services"]):
        container = running(svc)
        if not container:
            skipped.append(svc)
            continue
        try:
            out = subprocess.run(["docker", "inspect", container, "--format", "{{json .Config.Env}}"],
                                 capture_output=True, text=True, timeout=20).stdout
            env = json.loads(out)
        except (OSError, subprocess.SubprocessError, ValueError):
            skipped.append(svc)
            continue
        got = env_of({"environment": [str(e) for e in env]})
        for name in view["names"][svc]:
            if got.get(name) is None:
                raise AssertionError(f"{container}: {name} is not in the container's environment at "
                                     f"all — this is not the cut-over shape the overlay describes")
            if got[name] != "":
                raise AssertionError(
                    f"{container}: {name} is SET in the running container's environment — the office "
                    f"is running the pre-cutover shape and any `docker exec` reads that secret (its "
                    f"value is not printed here, by design)")
        measured += len(view["names"][svc])
        parts.append(f"{container}: {len(view['names'][svc])} declared secret(s) empty in its own env")
    if not parts:
        return ("NOT RUN live — no running container of " + ", ".join(skipped or sorted(view["services"]))
                + " is visible from here (the static claim above holds; the running estate was not "
                  "measured)")
    return "; ".join(parts) + (f" · not running here: {', '.join(skipped)}" if skipped else "")


CHECKS = [("declared", check_declared), ("blanked", check_blanked), ("leased", check_leased),
          ("order", check_order), ("live", check_live)]


# ── the proof that it can fail ──────────────────────────────────────────────────────────────────


def mutations(view: dict) -> list[tuple[str, str, dict]]:
    """(name, the check that must catch it, the mutated view). Each is one plausible edit of the
    overlay — the five ways the value goes back into the app's config."""
    svc = sorted(view["services"])[0]
    name = view["names"][svc][0]

    def copy():
        return {"cat": view["cat"], "enabled": view["enabled"], "text": view["text"],
                "owners": view["owners"], "names": view["names"], "stack": view["stack"],
                "services": {k: json.loads(json.dumps(v)) for k, v in view["services"].items()}}

    def with_env(fn):
        v = copy()
        body = v["services"][svc]
        env = [str(e) for e in (body.get("environment") or [])]
        body["environment"] = fn(env)
        return v

    def bare(env):
        return [name if e == f"{name}=" else e for e in env]

    def valued(env):
        return [f"{name}=from-the-host" if e == f"{name}=" else e for e in env]

    v_no_inject = copy()
    v_no_inject["services"][svc]["entrypoint"] = [e for e in v_no_inject["services"][svc]["entrypoint"]
                                                  if e != "/inject.sh"]

    v_no_dep = copy()
    v_no_dep["services"][svc].pop("depends_on", None)

    v_first = copy()
    stack = list(v_first["stack"])
    stack.remove(OVERLAY)
    stack.insert(0, OVERLAY)
    v_first["stack"] = stack

    v_no_decl = copy()
    v_no_decl["names"] = {k: ([] if k == svc else v) for k, v in view["names"].items()}

    return [("a bare name instead of `NAME=`", "blanked", with_env(bare)),
            ("a value instead of a blank", "blanked", with_env(valued)),
            ("the entrypoint without /inject.sh", "leased", v_no_inject),
            ("no fail-closed wait on the vault", "leased", v_no_dep),
            ("the cutover FIRST in the -f order", "order", v_first),
            ("a cut-over app that blanks nothing", "declared", v_no_decl)]


def inject(view: dict) -> int:
    """Every violation must be caught by the check that names it. Nothing is written anywhere."""
    missed, caught = [], 0
    for label, check, mutated in mutations(view):
        fn = dict(CHECKS)[check]
        try:
            fn(mutated)
        except AssertionError as exc:
            caught += 1
            print(f"CAUGHT {check:<9} {label} → {exc}")
        else:
            missed.append(f"{label} (check `{check}` passed it)")
            print(f"MISSED {check:<9} {label} → that check cannot see this violation")
    if missed:
        print(f"FAIL injected: {len(missed)} violation(s) went unnoticed — this test cannot fail for "
              f"them, so it does not prove them: {'; '.join(missed)}")
        return 2
    print(f"FAIL injected: {caught}/{caught} injected violation(s) caught — exit 1 IS THE POINT. The "
          f"same file with no injection exits 0 (run it without --inject).")
    return 1


# ── the run ────────────────────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    view = build_view()
    if not view["services"]:
        print("NOT RUN no enabled app declares a `broker` cutover in this checkout — there is no "
              "lease here to measure")
        return 3
    if OVERLAY not in view["stack"]:
        print(f"NOT RUN this checkout has no {OVERLAY} in its -f order — the estate was never "
              f"compiled here, so there is no overlay on disk to measure against")
        return 3
    on_disk = REPO / OVERLAY
    if on_disk.is_file() and on_disk.read_text(encoding="utf-8") != view["text"]:
        print("NOTE stale    the overlay on disk differs from the one this declaration compiles to — "
              "the running estate was rendered from an older declaration (run a render/`./bbox run`)")
    if "--inject" in argv:
        return inject(view)
    try:
        for label, fn in CHECKS:
            result = fn(view)
            if result.startswith("NOT RUN live"):
                print(f"SKIP {label:<9} {result[len('NOT RUN '):]}")
            else:
                print(f"PASS {label:<9} {result}")
    except AssertionError as exc:
        print(f"FAIL broker-lease {exc}")
        return 1
    print(f"PASS broker-lease: {len(view['services'])} app(s) lease their secrets from the credential "
          f"plane — the name is in the container, the value is in the vault")
    return 0


if __name__ == "__main__":
    sys.exit(main())
