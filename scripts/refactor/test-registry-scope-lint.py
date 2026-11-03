#!/usr/bin/env python3
r"""test-registry-scope-lint — gate G64: a test may only ever drive its OWN registry, bound to a
LOCAL connection.

    python3 scripts/refactor/test-registry-scope-lint.py [--self-test]

WHY THIS GATE EXISTS

`data/registry/sync_registry.json` is the client's live pipe configuration. Four of its rows
(`gmail-doc`, `gmail-bs`, `gmail-link`, `mail-private`) name `mail_imap_app_password-51185288` —
person9@example.com, the client's real mailbox. Two fixture workflows read that registry and fanned
out over whatever they found:

  * `sv3Inject3x001`'s `Plan` looped EVERY row with no `enabled` filter, 3 documents each. Three of
    those rows are enabled and name the client's Gmail, so a run appended **9 fixture messages into
    the client's production mailbox** and applied each pipe's REAL `to_sync` label — which injected
    them into the live INDOX pipeline as genuine client documents. It was latent only by accident:
    `mail-private` carries `connection: null` AND `labels: null`, so `Plan` threw while building the
    array before returning any items. One malformed row was the entire thing standing between the
    injector and production, and "tidying" it would have started the bleeding.
  * `syncV3FullTest01`'s `RG Build` mirrored every live entry into `sv3f_rg_<name>`. Adding a
    production pipe therefore enlarged a test's blast radius with nobody deciding to:
    `sv3f_rg_drive-whatsapp-bot` delivered 3 rows into the real table that way.

**mailapi's explicit-connection guard cannot see any of this.** That guard (`_explicit_connection_
required`, live 2026-08-09) refuses an op that names NO connection. These ops named one — the
client's — so every check the service has says the op is legitimate. The only place it can be
refused is in the blueprint, before the op is built, which is what this gate makes mechanical.

THE RULES

  R1  A test blueprint may not read or write the live registry key `sync_registry`.
      It must declare its own entries under a test-prefixed settings key. Kind coverage — the one
      thing the live read bought — is proven by R5 instead, statically, without touching the
      client's data.

  R2  A test blueprint may not build a connection id conditionally. `...(x ? {connection_id: x}
      : {})` and `if (x) params.connection_id = x` both OMIT the key when the id is falsy, and an
      omitted `connection_id` used to resolve through mailapi's ambient `/data/active.json` — the
      client's Gmail. That is how 148 fixture messages addressed to @demo.indox ended up in
      person9@example.com between 2026-08-05 and 2026-08-09. Stamping the key unconditionally turns
      the same mistake into a loud 400.

  R3  A test blueprint that builds a mail op must carry the local-only guard — a
      `mail_imap_local-` prefix test. Precedent: `mailOrgTest00001`'s `Config` node, which had it
      before any of this was written and is the reason that suite was never implicated.

  R4  Every `settings` key a test blueprint writes must (a) begin with a registered fixture prefix
      and (b) be registered in `scripts/test-fixture-prefixes.yaml` under an `aux_tables` entry for
      `public.settings`. (a) makes it identifiable, (b) makes it CRASH-SWEPT — a suite that dies
      mid-run leaves a PIPE CONFIGURED, which is a worse leak than a stray document row because a
      document is inert and a registry entry is an instruction. This is not hypothetical:
      `syncV3FullTest01`'s `all`-lane teardown cleared `key like 'sv3f\_registry%'`, which does not
      match `sv3f_rg_registry`, so every full-battery run left its mirrored registry installed
      indefinitely.

  R5  Every source KIND in the live registry must be declared by at least one test registry entry.
      This is the lockstep guarantee `RG Build` used to get by mirroring production — "a registry
      entry added without suite coverage FAILS here" — kept, and moved somewhere it cannot reach
      the client's mailbox. A new kind in `sync_registry.json` fails the build until a test
      declares it.

  R7  (Phase 4, 2026-08-31) A prefix-owner suite runs against the dedicated tenant schema
      `indox_test`, and must SAY so in committed source: it must carry the literal
      `__instance:'test'` (either quote style) at least once, must carry NO `__instance` literal
      naming any OTHER instance (expressions and variables are outside this rule — a literal is
      what makes the binding legible before anything runs; one call pinned to 'test' and another
      pinned to 'hacohen' is worse than pinning nothing, because the first green covers for the
      second), and must not call drive DISCOVERY — `op:'connections'` in a driveApi01-calling
      blueprint, the raw `:8975/connections` endpoint, or `engine/profiles`. Test connections
      come from indox_test.settings key='test_connections'; discovery binds whatever identities
      the LIVE engine currently knows, which on this deployment includes the client's real
      Google account — R2's ambient-identity incident, respelled for drive.

WHICH BLUEPRINTS ARE TESTS — DERIVED, NOT LISTED

The set is the `owner` fields already in `scripts/test-fixture-prefixes.yaml`, which is the repo's
single source of truth for "what a fixture looks like". A suite must register a prefix to be swept
at all, so it cannot opt out of this gate without opting out of cleanup. `EXTRA` below carries the
fixture seeders that own no document prefix, each with a reason; an `EXTRA` entry matching nothing
FAILS, the same anti-rot rule G31/G34 use.

SCOPE OF THE GREEN — read before trusting it. Static, over committed blueprint JSON. It cannot see
what is ACTIVE in n8n (only `bbox n8n pull` reconciles that), it does not prove a declared test
entry is actually reachable, and R3 proves a guard is PRESENT, not that every op goes through it —
R2 is what covers the op sites.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("PyYAML required (scripts/test-fixture-prefixes.yaml is the source of truth)")

# Blueprints are code (.workflow.ts) since 52b32aa4. n8n_blueprint is the ONE reader — see its
# docstring for why this is not a per-gate parser.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from n8n_blueprint import load as load_blueprint, CompileError   # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
REGISTRY_YAML = ROOT / "scripts" / "test-fixture-prefixes.yaml"
LIVE_REGISTRY = ROOT / "data" / "registry" / "sync_registry.json"
LIVE_KEY = "sync_registry"

#: Fixture seeders that own no `incoming_documents` prefix and so are not reachable through the
#: registry's `owner` fields. Each needs a reason. An entry matching no file FAILS.
EXTRA: dict[str, str] = {
    "apps/indox/blueprint/n8n/IndoxInjectDemo01.workflow.ts":
        "The demo/E2E fixture injector. It owns no document prefix (its rows are written by the "
        "production processors it drives), but it seeds mail and drive from "
        "_active-blueprint.json and had six conditional connection sites — the exact R2 shape.",
}

#: The kinds the v3 engine can route. A live registry entry's kind is `v3_kind` if present, else
#: `gmail-link` when the name says so, else `source`. Mirrors syncV3Main0001/`Build Units`.
def entry_kind(e: dict) -> str:
    k = e.get("v3_kind")
    if k:
        return str(k)
    if "gmail-link" in str(e.get("name") or ""):
        return "gmail-link"
    return str(e.get("source") or "")


# ── the rules ────────────────────────────────────────────────────────────────────────────
COND_SPREAD = re.compile(r"\.\.\.\s*\(\s*[A-Za-z_$][\w.$]*\s*\?\s*\{\s*connection_id\s*:")
COND_ASSIGN = re.compile(r"\bif\s*\(\s*[A-Za-z_$][\w.$]*\s*\)\s*[\w.$]*\.?connection_id\s*=")
CONN_SITE = re.compile(r"connection_id\s*[:=]\s*")


def conditional_sites(code: str) -> list[re.Match]:
    return [m for rx in (COND_SPREAD, COND_ASSIGN) for m in rx.finditer(code)]


def names_alternative_identity(code: str, m: re.Match) -> bool:
    """True when the conditional's ELSE branch names another identity instead of dropping one.

    `...(p.connection_id ? {connection_id: p.connection_id} : (p.profile_id ? {profile_id:
    p.profile_id} : {}))` is the drive dispatch shape: it picks WHICH identity to send, and if it
    sends neither, apps/drive's `_explicit_connection_required` (gate G46) refuses the call loudly.
    That is a different rule with its own gate, and flagging it here would make this one noisy
    enough to be switched off — which is how a gate stops working.
    """
    return "profile_id" in code[m.end():m.end() + 200]


def stamps_unconditionally(code: str) -> bool:
    """True when some site assigns `connection_id` with no `?` and no `if` guarding it.

    This is what makes the `__conn_stamped` idiom pass: those nodes build ops with a conditional
    spread inside an IIFE and then overwrite every `params.connection_id` with
    `Object.assign(…, {connection_id: __cid})`. The conditional is dead code — the net effect is
    unconditional, which is the property the rule is about.

    DELIBERATELY LINE-LOCAL, and it is a false-NEGATIVE trade, stated rather than hidden: a
    conditional split across lines reads as unconditional here. Conditional connection shapes in
    this fleet are all single-expression; a multi-line one would need the parser this gate does
    not have, and guessing produces false positives on live suite code.
    """
    for m in CONN_SITE.finditer(code):
        line = code[:m.start()].rsplit("\n", 1)[-1]
        if "?" in line or "if(" in line.replace(" ", ""):
            continue
        return True
    return False
LOCAL_GUARD = "mail_imap_local-"
MAIL_OP_WORKFLOWS = ("gmailApiImap01",)
SETTINGS_KEY_WRITE = re.compile(
    r"table\s*:\s*['\"]settings['\"][^}]*?(?P<k>key)\s*:\s*['\"](?P<key>[A-Za-z0-9_\-]+)['\"]",
    re.S)
SETTINGS_KEY_WRITE_REV = re.compile(
    r"(?P<k>key)\s*:\s*['\"](?P<key>[A-Za-z0-9_\-]+)['\"][^}]*?table\s*:\s*['\"]settings['\"]",
    re.S)
#: A `key:'X'` sitting immediately inside `filter:{…}` is a READ, not a write. This matters
#: since Phase 4: the sanctioned way a suite gets its connections is
#: `TABLE_GET table:'settings' filter:{key:'test_connections'}`, and a gate that flags the exact
#: read the migration prescribes is a gate that gets switched off. Stated trade: a WRITE that
#: addressed its row through `filter:` would be exempted too — no settings write in this fleet
#: is spelled that way (writes carry the key at the top level of the op), and guessing at
#: parser-grade discrimination is how the false positives R2 documents were made.
SETTINGS_KEY_READ_CTX = re.compile(r"filter\s*:\s*\{\s*\Z", re.S)

#: [2026-08-31] The registry's settings entries moved with Phase 4: `table: public.settings`
#: became `table: indox_test.settings`. A gate that still filtered on the old name would build
#: an EMPTY registered-key set and report every registered key as unregistered — loud, but
#: false, at the exact moment everyone is watching the migration. Same census posture as G58's
#: schema alternation: accept `public` and ANY `indox_*` tenant spelling, so a registration
#: cannot fall out of the set by qualifying itself. `[.]` not `\.` — this block stays free of
#: backslashes for the reason stated above SQL_SETTINGS_HEADS.
SETTINGS_TABLE = re.compile("(public|indox_[a-z0-9_]+)[.]settings$")


def _is_settings_table(t) -> bool:
    return bool(SETTINGS_TABLE.match(str(t or "")))


# Deliberately regex-light: the heads are plain substrings and the two patterns carry NO
# backslash escapes. `\b` is a BACKSPACE inside a non-raw Python string, and an earlier version
# of this block shipped one -- so the pattern could never match, sql_settings_writes returned an
# empty set on every input, and R6 reported PASS having examined nothing. That is the exact
# defect this gate family exists to catch, produced by the gate itself; the fix is to leave
# nothing in the pattern that a copy, a heredoc, or a string layer can quietly eat.
SQL_SETTINGS_HEADS = (
    "insert into settings", "insert into public.settings",
    "update settings", "update public.settings",
    "delete from settings", "delete from public.settings",
)
SQL_SETTINGS_KEY_EQ = re.compile("key *= *'([A-Za-z0-9_.-]+)'", re.I)
SQL_SETTINGS_VALUES = re.compile("values *[(] *'[^']*' *, *'([A-Za-z0-9_.-]+)'", re.I)
SQL_WS = re.compile("[ \t\r\n]+")
# Phase 4 moves the suites' raw SQL onto the tenant schema. Rather than double the heads list,
# `indox_<anything>.settings` is normalised to `settings` before the substring test — so
# `update indox_test.settings …` hits the same head `update settings` does. `[.]`, no
# backslashes, per the discipline stated above.
SQL_TENANT_SETTINGS = re.compile("indox_[a-z0-9_]+[.]settings")

# R7 — the Phase-4 tenant move. `__instance` as a QUOTED literal, key optionally quoted (jsCode
# writes `__instance:'test'`, a compiled workflowInputs mapping is `"__instance": "test"`). The
# capture is the value; a value that is an n8n expression (`={{ … }}`) is not a literal and is
# filtered by the caller, not here. The lookbehind keeps `foo__instance` out.
R7_INSTANCE = re.compile(r"(?<![\w$])['\"]?__instance['\"]?\s*:\s*['\"]([^'\"]*)['\"]")
#: Drive discovery, in the three spellings the suites actually use today: the driveApi01
#: `op:'connections'` call (also matched in its compiled `"op": "connections"` form), the raw
#: engine endpoint, and the mail engine's profile enumeration. The `op:` form counts only in a
#: blueprint that calls driveApi01 — `op:` is a generic field and a non-drive op named
#: 'connections' elsewhere is not this rule's business.
R7_DRIVE_OP = re.compile(r"\bop['\"]?\s*:\s*['\"]connections['\"]")
R7_DRIVE_WF = "driveApi01"
R7_DISCOVERY_URLS = (":8975/connections", "engine/profiles")


def sql_settings_writes(code: str) -> set[str]:
    """Settings keys this node writes in RAW SQL.

    R4 only ever matched the object shape (`table:'settings' ... key:'X'`), so a write expressed
    as SQL was invisible to it -- and SQL is how the AI toggle writes. That is why a gate whose
    PASS line reads "every test registry key is crash-swept" reported PASS across every run in
    which `plt_prior_extraction_ai_enabled` was leaking.

    Scoped per STATEMENT, because `key='x'` appears in reads far more often than in writes and a
    read is not this gate's business. Only statements headed by insert/update/delete against
    `settings` contribute keys. Splitting on `;` is not a SQL parser and does not need to be: a
    semicolon inside a string literal would merely split a statement early, which can drop a key
    (a miss) but cannot invent one (a false positive, reported at a person).
    """
    out: set[str] = set()
    for stmt in code.split(";"):
        flat = SQL_TENANT_SETTINGS.sub("settings", SQL_WS.sub(" ", stmt).lower())
        if not any(h in flat for h in SQL_SETTINGS_HEADS):
            continue
        out |= set(SQL_SETTINGS_KEY_EQ.findall(stmt))
        out |= set(SQL_SETTINGS_VALUES.findall(stmt))
    return out


def node_code(n: dict) -> str:
    """Everything in a node a rule could match: Code bodies, SQL, and mapped expressions."""
    p = n.get("parameters") or {}
    return "\n".join(str(v) for v in (p.get("jsCode"), p.get("query"),
                                      json.dumps(p, ensure_ascii=False)) if v)


def check_blueprint(path: str, wf: dict, registered_prefixes: list[str],
                    registered_settings_keys: set[str],
                    saved: dict[str, dict[str, str]] | None = None,
                    prefix_owner: bool = False) -> list[str]:
    out: list[str] = []
    nodes = wf.get("nodes") or []
    whole = json.dumps(wf, ensure_ascii=False)

    for n in nodes:
        name = n.get("name", "?")
        code = node_code(n)

        # R1 — the live registry key, in any node, read or write.
        if re.search(r"['\"]%s['\"]" % LIVE_KEY, code):
            out.append("R1 %s / %s reads or writes the LIVE registry key %r — a test must declare "
                       "its own test-prefixed key" % (path, name, LIVE_KEY))

        # R2 — a connection id that can be OMITTED. A conditional shape is only a finding when
        # nothing else supplies the key: an else branch naming `profile_id` is an identity choice
        # (G46's rule, not this one), and an unconditional stamp later in the node makes the
        # conditional dead code.
        cond = [m for m in conditional_sites(code) if not names_alternative_identity(code, m)]
        if cond and not stamps_unconditionally(code):
            out.append("R2 %s / %s can emit a mail op with NO connection_id (%d conditional "
                       "site(s), no unconditional stamp) — an omitted id resolves through "
                       "mailapi's ambient /data/active.json, which on this deployment is the "
                       "client's real Gmail. Stamp it unconditionally."
                       % (path, name, len(cond)))

        # R4 — every settings key this blueprint writes.
        for rx in (SETTINGS_KEY_WRITE, SETTINGS_KEY_WRITE_REV):
            for m in rx.finditer(code):
                key = m.group("key")
                if SETTINGS_KEY_READ_CTX.search(code[:m.start("k")]):
                    continue                       # `filter:{key:…}` — a read, not a write
                if key == LIVE_KEY:
                    continue                       # already reported by R1
                if not any(key.startswith(p) for p in registered_prefixes):
                    out.append("R4 %s / %s writes settings key %r, which begins with no registered "
                               "fixture prefix — it cannot be identified as a test row"
                               % (path, name, key))
                elif key not in registered_settings_keys:
                    out.append("R4 %s / %s writes settings key %r, which is not registered in "
                               "scripts/test-fixture-prefixes.yaml under an aux_tables entry for "
                               "public.settings — a crash would leave that pipe installed"
                               % (path, name, key))

        # R6 — the same question as R4, asked of raw SQL, plus the one R4 cannot ask:
        # under what terms may a test write a LIVE client setting at all?
        #
        # The answer is: only by parking the original where a crash-safe sweep can find it. A
        # suite that overwrites `extraction_ai_enabled` and dies before its own restore leaves
        # the WHOLE deployment on the AI extraction path -- which on a box whose GEMINI_API_KEY
        # is a placeholder means real document processing fails, and means "no test requires
        # that key" quietly becomes a property of the last run's exit status.
        mine = (saved or {}).get(path, {})
        for key in sorted(sql_settings_writes(code)):
            if key == LIVE_KEY:
                continue                                   # R1 owns the live registry key
            if "_prior_" in key:
                want = key.split("_prior_", 1)[1]
                if key not in mine:
                    out.append("R6 %s / %s parks a client setting in %r but declares no "
                               "`saved_settings` entry for it in "
                               "scripts/test-fixture-prefixes.yaml — a crash leaves the TEST "
                               "value live and that row is the only copy of the real one"
                               % (path, name, key))
                elif mine[key] != want:
                    out.append("R6 %s / %s parks %r, whose name says it holds %r, but the "
                               "registry restores it to %r — one of the two is wrong and the "
                               "sweep believes the registry"
                               % (path, name, key, want, mine[key]))
            elif any(key.startswith(p) for p in registered_prefixes):
                if key not in registered_settings_keys:
                    out.append("R6 %s / %s writes settings key %r in SQL, which is not "
                               "registered under an aux_tables entry for public.settings — a "
                               "crash would leave it installed" % (path, name, key))
            elif key not in set(mine.values()):
                out.append("R6 %s / %s overwrites the LIVE client setting %r with no "
                           "`saved_settings` entry naming it as a target_key — a test may take "
                           "a client setting only if it has parked the original somewhere the "
                           "crash sweep can put back" % (path, name, key))

    # R3 — a blueprint that builds mail ops must carry the local-only guard.
    does_mail = any(w in whole for w in MAIL_OP_WORKFLOWS)
    if does_mail and LOCAL_GUARD not in whole:
        out.append("R3 %s builds mail ops (%s) but carries no `%s` local-only guard — nothing "
                   "stops it binding the client's mailbox"
                   % (path, "/".join(w for w in MAIL_OP_WORKFLOWS if w in whole), LOCAL_GUARD))

    # R7 — the Phase-4 tenant move: a prefix-owner suite is pinned to the 'test' instance and
    # discovers nothing. Only prefix owners: the injector and the aux-only owners have their own
    # rules above, and widening this one to them would flag driveApi01's own implementation of
    # the endpoint it serves.
    if prefix_owner:
        all_code = "\n".join(node_code(n) for n in nodes)
        # (a) at least one literal pin. An expression cannot satisfy this: the point is that the
        # instance binding is legible in committed source, not resolved at run time.
        if not any(v == "test" for v in R7_INSTANCE.findall(all_code)):
            out.append("R7 %s pins no `__instance:'test'` literal anywhere — after the Phase-4 "
                       "move a suite that does not pin the test instance runs against whatever "
                       "instance the router resolves, and 'whatever the router resolves' is how "
                       "both incidents in this file's docstring began" % path)
        for n in nodes:
            name = n.get("name", "?")
            code = node_code(n)
            # (b) no literal may name any OTHER instance. Deduplicated because node_code carries
            # jsCode both raw and inside the params dump; expressions (`={{ … }}`) are exempt.
            for v in sorted({v for v in R7_INSTANCE.findall(code)
                             if v != "test" and not v.startswith("=") and "{{" not in v}):
                out.append("R7 %s / %s carries the literal `__instance:'%s'` — a suite may pin "
                           "only the test instance; one call pinned elsewhere makes the "
                           "`__instance:'test'` green cover for it" % (path, name, v))
            # (c) no drive discovery — connections come from indox_test.settings
            # key='test_connections', never from enumerating what the live engine knows.
            if R7_DRIVE_OP.search(code) and R7_DRIVE_WF in whole:
                out.append("R7 %s / %s calls drive discovery (op:'connections' in a %s-calling "
                           "blueprint) — test connections come from indox_test.settings "
                           "key='test_connections', never from enumerating the live engine's "
                           "identities" % (path, name, R7_DRIVE_WF))
            for frag in R7_DISCOVERY_URLS:
                if frag in code:
                    out.append("R7 %s / %s reaches discovery via %r — test connections come "
                               "from indox_test.settings key='test_connections', never from "
                               "the engine's own enumeration" % (path, name, frag))
    return out


def declared_test_kinds(blueprints: dict[str, dict]) -> set[str]:
    """Kinds a test registry declares.

    A registry-entry literal is identified by `engine:'v3'` — the field that MAKES it a v3 registry
    entry. Keying on the settings upsert instead was wrong and the first run proved it: the entries
    are built in `RG Build` and upserted two nodes later in `RG Seed Registry Req`, so the kinds
    were invisible and R5 reported `gmail-link` uncovered when a test entry for it existed.
    """
    kinds: set[str] = set()
    for wf in blueprints.values():
        for n in (wf.get("nodes") or []):
            code = node_code(n)
            if "engine:'v3'" not in code.replace(" ", ""):
                continue
            kinds |= set(re.findall(r"v3_kind\s*:\s*'([a-z\-]+)'", code))
            kinds |= set(re.findall(r"source\s*:\s*'([a-z\-]+)'", code))
    return kinds


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()

    reg = yaml.safe_load(REGISTRY_YAML.read_text(encoding="utf-8")) or {}
    prefixes = sorted({str(p["prefix"]) for p in (reg.get("prefixes") or [])
                       if isinstance(p, dict) and p.get("prefix")})
    settings_keys = {str(k) for e in (reg.get("aux_tables") or [])
                     if isinstance(e, dict) and _is_settings_table(e.get("table"))
                     for k in (e.get("keys") or [])}

    saved: dict[str, dict[str, str]] = {}
    for e in (reg.get("saved_settings") or []):
        if not isinstance(e, dict) or not e.get("owner"):
            continue
        for s in (e.get("saves") or []):
            if isinstance(s, dict) and s.get("prior_key") and s.get("target_key"):
                saved.setdefault(str(e["owner"]), {})[str(s["prior_key"])] = str(s["target_key"])

    owners = {str(e["owner"]) for group in ("prefixes", "aux_tables", "saved_settings")
              for e in (reg.get(group) or [])
              if isinstance(e, dict) and e.get("owner")}
    # R7 applies to the suites that own a DOCUMENT prefix — the set the rule's wording names.
    doc_prefix_owners = {str(e["owner"]) for e in (reg.get("prefixes") or [])
                         if isinstance(e, dict) and e.get("owner")}
    fails: list[str] = []
    for extra, reason in EXTRA.items():
        if not (ROOT / extra).exists():
            fails.append("EXTRA entry %r matches no file — remove it or fix the path (%s)"
                         % (extra, reason))
        owners.add(extra)

    blueprints: dict[str, dict] = {}
    for rel in sorted(owners):
        p = ROOT / rel
        if not p.exists():
            fails.append("registered owner %r does not exist" % rel)
            continue
        try:
            blueprints[rel] = load_blueprint(p)
        except CompileError as ex:
            # A blueprint this gate cannot READ is not a pass. Saying so beats the old
            # json.loads, which raised a bare JSONDecodeError naming a line number in a
            # TypeScript file and told nobody which workflow it choked on.
            fails.append("cannot read blueprint %r: %s" % (rel, ex))

    for rel, wf in blueprints.items():
        fails += check_blueprint(rel, wf, prefixes, settings_keys, saved,
                                 prefix_owner=rel in doc_prefix_owners)

    # R5 — live kind coverage, the lockstep guarantee moved out of the client's data.
    declared = declared_test_kinds(blueprints)
    # The registry is the client's live pipe configuration: gitignored, present only on an office
    # that runs INDOX. Anywhere else (a fresh clone, CI, an office without the app) R5 has nothing
    # to compare and says so. It used to end the whole gate, static rules included, in a
    # FileNotFoundError traceback.
    live_kinds = None
    if LIVE_REGISTRY.is_file():
        live = json.loads(LIVE_REGISTRY.read_text(encoding="utf-8"))
        live_kinds = {entry_kind(e) for e in live if entry_kind(e)}
    missing = sorted((live_kinds or set()) - declared)
    for k in missing:
        fails.append("R5 live registry contains source kind %r that NO test registry declares — "
                     "add a test entry for it (this is the lockstep check syncV3FullTest01 used "
                     "to get by mirroring production)" % k)

    print("[test-registry-scope-lint] %d test blueprint(s); live kinds %s; declared %s"
          % (len(blueprints),
             "NOT CHECKED (no %s on this office)" % LIVE_REGISTRY.relative_to(ROOT).as_posix()
             if live_kinds is None else sorted(live_kinds), sorted(declared)))
    if fails:
        print("\n[test-registry-scope-lint] FAIL — %d finding(s):" % len(fails))
        for f in fails:
            print("  " + f)
        return 1
    print("[test-registry-scope-lint] PASS — no test blueprint touches the live registry, "
          "every connection is stamped unconditionally, every test registry key is crash-swept, "
          "every parked client setting is restorable, "
          + ("every live source kind has test coverage, " if live_kinds is not None else
             "live source kinds NOT CHECKED here, ") +
          "and every prefix-owner suite is pinned to __instance:'test' with no drive discovery")
    return 0


# ── self-test ────────────────────────────────────────────────────────────────────────────
def self_test() -> int:
    bad = 0

    def chk(label, ok):
        nonlocal bad
        bad += 0 if ok else 1
        print("  [%s] %s" % ("ok " if ok else "FAIL", label))

    # R1/R2/R3/R4 against synthetic blueprints, each carrying the REAL defect text.
    live_reader = {"nodes": [{"name": "Registry Req", "parameters": {"jsCode":
        "return [{json:{INLINE_ACTION:'TABLE_GET', table:'settings', instance:I, "
        "filter:{key:'sync_registry'}}}];"}}]}
    r = check_blueprint("x.json", live_reader, ["sv3i_"], set())
    chk("R1 catches a live-registry read (the sv3Inject3x001 defect, verbatim)",
        any(f.startswith("R1 ") for f in r))

    cond = {"nodes": [{"name": "Mail Req", "parameters": {"jsCode":
        "return [{json:{op:'append', params:{folder:'INBOX', "
        "...(p.connection_id?{connection_id:p.connection_id}:{})}}}];"}}]}
    chk("R2 catches the conditional spread (the shape that caused the incident)",
        any(f.startswith("R2 ") for f in check_blueprint("x.json", cond, [], set())))

    cond2 = {"nodes": [{"name": "Build e2e-mail", "parameters": {"jsCode":
        "const connId=bp.mail_connection_id||''; if(connId) params.connection_id=connId;"}}]}
    chk("R2 catches the conditional ASSIGN, not only the spread",
        any(f.startswith("R2 ") for f in check_blueprint("x.json", cond2, [], set())))

    good = {"nodes": [{"name": "Mail Req", "parameters": {"jsCode":
        "return [{json:{op:'append', params:{folder:'INBOX', "
        "connection_id: $('Config').first().json.connection_id}}}];"}}]}
    chk("R2 does NOT fire on an unconditional stamp",
        not any(f.startswith("R2 ") for f in check_blueprint("x.json", good, [], set())))

    # THE TWO FALSE POSITIVES THE FIRST RUN PRODUCED, kept as cases so they cannot come back.
    # 26 of that run's 29 findings were these; a gate this noisy gets switched off, and switching
    # it off is how the original defect survived.
    drive_alt = {"nodes": [{"name": "DG Seed", "parameters": {"workflowInputs": {"value": {
        "params": "={{ ({ ...$json.params, ...($json.params.connection_id ? "
                  "{ connection_id: $json.params.connection_id } : ($json.params.profile_id ? "
                  "{ profile_id: $json.params.profile_id } : {})) }) }}"}}}}]}
    chk("R2 does NOT fire on drive's identity CHOICE (else branch names profile_id — G46's rule)",
        not any(f.startswith("R2 ") for f in check_blueprint("x.json", drive_alt, [], set())))

    stamped = {"nodes": [{"name": "LE Pre Req", "parameters": {"jsCode":
        "const __conn_stamped = (function(){\n"
        "return [{json:{op:'search', params:{limit:5, "
        "...(cfg.connection_id?{connection_id:cfg.connection_id}:{})}}}];\n"
        "})();\nconst __cid = $('Config').first().json.connection_id;\n"
        "return (__conn_stamped||[]).map(function(it){\n"
        "  return Object.assign({}, it, {json: Object.assign({}, it.json,\n"
        "    {params: Object.assign({}, it.json.params, {connection_id: __cid})})});\n});"}}]}
    chk("R2 does NOT fire when a later unconditional stamp overwrites the conditional",
        not any(f.startswith("R2 ") for f in check_blueprint("x.json", stamped, [], set())))
    chk("…and the same node WITHOUT the stamper is still a finding",
        any(f.startswith("R2 ") for f in check_blueprint("x.json", {"nodes": [
            {"name": "LE Pre Req", "parameters": {"jsCode":
                "return [{json:{op:'search', params:{limit:5, "
                "...(cfg.connection_id?{connection_id:cfg.connection_id}:{})}}}];"}}]},
            [], set())))

    mail_no_guard = {"nodes": [{"name": "Mail Append", "parameters":
        {"workflowId": {"value": "gmailApiImap01"}}}]}
    chk("R3 catches a mail-op blueprint with no local-only guard",
        any(f.startswith("R3 ") for f in check_blueprint("x.json", mail_no_guard, [], set())))

    mail_guard = {"nodes": [
        {"name": "Mail Append", "parameters": {"workflowId": {"value": "gmailApiImap01"}}},
        {"name": "Config", "parameters": {"jsCode":
            "if(cid && !cid.startsWith('mail_imap_local-')) cid='';"}}]}
    chk("R3 passes once the guard is present",
        not any(f.startswith("R3 ") for f in check_blueprint("x.json", mail_guard, [], set())))

    unswept = {"nodes": [{"name": "Seed Registry Req", "parameters": {"jsCode":
        "return [{json:{INLINE_ACTION:'TABLE_UPSERT', table:'settings', instance:I, "
        "key:'sv3i_registry', value:v}}];"}}]}
    chk("R4 fires when a test settings key is not registered for crash-sweeping",
        any(f.startswith("R4 ") for f in check_blueprint("x.json", unswept, ["sv3i_"], set())))
    chk("R4 passes once the key is registered in aux_tables",
        not any(f.startswith("R4 ") for f in
                check_blueprint("x.json", unswept, ["sv3i_"], {"sv3i_registry"})))
    chk("R4 fires on an UNPREFIXED settings key even if somebody registered it",
        any("begins with no registered fixture prefix" in f for f in
            check_blueprint("x.json", {"nodes": [{"name": "N", "parameters": {"jsCode":
                "{INLINE_ACTION:'TABLE_UPSERT', table:'settings', key:'scratch', value:v}"}}]},
                ["sv3i_"], {"scratch"})))

    # R5's kind derivation, against the real shapes.
    chk("kind: v3_kind wins over source", entry_kind({"source": "gmail", "v3_kind": "gmail-link"})
        == "gmail-link")
    chk("kind: a gmail-link name is recognised without v3_kind",
        entry_kind({"source": "gmail", "name": "gmail-link"}) == "gmail-link")
    chk("kind: plain source otherwise", entry_kind({"source": "drive", "name": "drive-bs"})
        == "drive")
    # R5 keys on `engine:'v3'` — the field that MAKES something a registry entry — because the
    # entries are built in one node and upserted two nodes later. Keying on the upsert made R5
    # report `gmail-link` uncovered when a test entry for it existed, on this gate's first run.
    decl = declared_test_kinds({"t.json": {"nodes": [{"name": "RG Build", "parameters": {"jsCode":
        "mirror.push({name, source:'drive', engine:'v3'});\n"
        "mirror.push({name, source:'gmail', v3_kind:'gmail-link', engine:'v3'});"}}]}})
    chk("R5 reads declared kinds out of a registry BUILDER, not only an upsert node",
        decl >= {"drive", "gmail", "gmail-link"})
    chk("R5 ignores a node that declares no registry entry",
        declared_test_kinds({"t.json": {"nodes": [{"name": "N", "parameters":
            {"jsCode": "const x={source:'whatsapp'};"}}]}}) == set())

    # R7 — the Phase-4 tenant move: prefix-owner suites pin the test instance, literally, and
    # never discover connections. Scope first: R7 is a prefix-owner rule and the parameter
    # defaults to off, so the aux-only owners and the injector keep their existing verdicts.
    r7_ok = {"nodes": [{"name": "Build Req", "parameters": {"jsCode":
        "return [{json:{INLINE_ACTION:'TABLE_GET', __instance:'test', table:'settings', "
        "filter:{key:'test_connections'}}}];"}}]}
    chk("R7 passes a suite pinned to __instance:'test' that reads test_connections",
        not any(f.startswith("R7 ") for f in
                check_blueprint("x.json", r7_ok, [], set(), prefix_owner=True)))
    chk("R7(a) fires when a prefix-owner suite never pins __instance:'test'",
        any(f.startswith("R7 ") for f in check_blueprint("x.json", {"nodes": [{"name": "N",
            "parameters": {"jsCode": "return [{json:{op:'ping'}}];"}}]}, [], set(),
            prefix_owner=True)))
    chk("R7(a) accepts the double-quoted / compiled workflowInputs spelling",
        not any(f.startswith("R7 ") for f in check_blueprint("x.json", {"nodes": [
            {"name": "Call", "parameters": {"workflowInputs": {"value":
                {"__instance": "test"}}}}]}, [], set(), prefix_owner=True)))
    chk("R7(b) fires on a literal pinning a DIFFERENT instance next to the correct one",
        any("__instance:'hacohen'" in f for f in check_blueprint("x.json", {"nodes": [
            {"name": "N", "parameters": {"jsCode":
                "a={__instance:'test'}; b={__instance:'hacohen'};"}}]}, [], set(),
            prefix_owner=True)))
    chk("R7(b) ignores expression/variable-valued __instance — a variable is not a literal",
        not any(f.startswith("R7 ") for f in check_blueprint("x.json", {"nodes": [
            {"name": "N", "parameters": {"jsCode":
                "a={__instance:'test'}; b={__instance: inst};"}},
            {"name": "Call", "parameters": {"workflowInputs": {"value":
                {"__instance": "={{ $json.inst }}"}}}}]}, [], set(), prefix_owner=True)))
    r7_disc = {"nodes": [
        {"name": "List Conns", "parameters": {"jsCode":
            "return [{json:{__instance:'test', op:'connections'}}];"}},
        {"name": "Drive Req", "parameters": {"workflowId": {"value": "driveApi01"}}}]}
    chk("R7(c) fires on op:'connections' in a driveApi01-calling blueprint",
        any(f.startswith("R7 ") for f in
            check_blueprint("x.json", r7_disc, [], set(), prefix_owner=True)))
    chk("R7(c) needs the driveApi01 context — a lone op:'connections' is not drive discovery",
        not any(f.startswith("R7 ") for f in check_blueprint("x.json",
            {"nodes": [r7_disc["nodes"][0]]}, [], set(), prefix_owner=True)))
    chk("R7(c) fires on the raw :8975/connections endpoint",
        any(":8975/connections" in f for f in check_blueprint("x.json", {"nodes": [
            {"name": "HTTP", "parameters": {"jsCode": "x={__instance:'test'}; const r=await "
                "this.helpers.httpRequest({url:'http://drive:8975/connections'});"}}]},
            [], set(), prefix_owner=True)))
    chk("R7(c) fires on engine/profiles",
        any("engine/profiles" in f for f in check_blueprint("x.json", {"nodes": [
            {"name": "HTTP", "parameters": {"jsCode": "x={__instance:'test'}; "
                "const u='http://mailapi:8970/engine/profiles';"}}]}, [], set(),
            prefix_owner=True)))
    chk("R7 does not apply to a blueprint that owns no document prefix (default off)",
        not any(f.startswith("R7 ") for f in check_blueprint("x.json", r7_disc, [], set())))

    print("\ntest-registry-scope-lint self-test: %s" % ("FAILED" if bad else "all passed"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
