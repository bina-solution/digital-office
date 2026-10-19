#!/usr/bin/env python3
"""platform manager — the reconciler/compiler behind `bbox reconcile`.

    apps/*/app.json  +  platform.state.yaml   ->   .generated/   ->   docker compose

Pure function of (catalog, state). Produces the compose include chain today; the
authentik blueprint, console modules and connections consumers are added as apps migrate.

The LEGACY LANE is what makes an incremental refactor safe: services not yet migrated are
still included from production/compose.yml, so the rendered system stays byte-identical
(gate G1) at every step. When apps/ owns everything, the legacy include disappears.

Verbs:
    plan           resolve + print the dependency graph and what would change (no writes)
    render         write .generated/ only
    up             render, then docker compose up -d --remove-orphans
    validate       structural-validate every manifest against platform/schema/app.schema.json
    compose-files  print the canonical -f list (the one answer to "which files are the stack?")
    services       print the compose SERVICE names a lane must start, DERIVED from the graph
"""
import argparse, hashlib, shutil, json, pathlib, re, sys, subprocess

try:
    import yaml
except ImportError:
    sys.exit("PyYAML required: pip install pyyaml")

REPO = pathlib.Path(__file__).resolve().parents[2]
# The reverse plane (apps of ANOTHER office, shown here) lives in its own module beside this one:
# its rules are pure functions of a declaration, and keeping them out of this file is what lets the
# phase-3 gate exercise them without the compiler, the catalogue or a machine.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import serve  # noqa: E402  (must come after REPO/sys.path, and it imports nothing from here)

# Where a manifest lives is not cosmetic — it IS its layer, and the loader enforces it.
#   platform/       layer 1 mechanism: the schema + this compiler. No app manifests.
#   platform-base/  layers 1-2: the base every deployment needs (edge, identity, state,
#                   automation, the shell). Not things a user chooses to install.
#   apps/           layer 3 ONLY: the installable surface — what a user adds or removes.
# Splitting the tree this way means "what can I uninstall?" is answered by `ls apps/`
# rather than by reading 25 manifests.
BASE = REPO / "platform-base"
APPS = REPO / "apps"
CATALOG_ROOTS = {BASE: (1, 2), APPS: (3,)}
STATE = REPO / "platform.state.yaml"
# What a fresh install starts from. The office's own file is written at runtime and belongs to the
# deployment (like `.env` beside `.env.ex`); this one is tracked and never written by anything but a
# person. ensure_state() below is the one place the two meet, and it only ever CREATES the office's
# file — it never replaces one. See platform.state.default.yaml's header for the whole argument.
DEFAULT_STATE = REPO / "platform.state.default.yaml"
SCHEMA = REPO / "platform/schema/app.schema.json"
GEN = REPO / ".generated"

STRENGTHS = {"requires", "wants", "requisite", "binds_to", "conflicts"}
HARD = {"requires", "requisite", "binds_to"}

# A brief is injected into every agent session, so its size is taken from every other app's brief.
# This is a REFUSAL, not a warning: an unenforced budget is discovered as "the agent got dumber",
# which names no file and no author.
MAX_BRIEF_BYTES = 6000


# ── company identity: BUSINESS_NAME -> COMPANY_SLUG -> every host and the mail address ─────────
# A deployment has exactly ONE company identity, and the operator states it once, as a human name:
#
#   BUSINESS_NAME=Hacohen
#     -> COMPANY_SLUG          hacohen
#        -> DEPLOYMENT_NAME    hacohen                        -> n8n-hacohen, mailserver-hacohen, …
#        -> DEPLOYMENT_DOMAIN  hacohen.digital-office.co.il   -> console.hacohen…, n8n.hacohen…, …
#        -> MAIL_DOMAIN        = DEPLOYMENT_DOMAIN            -> person1@example.com
#        -> MAIL_DKIM_SELECTOR hacohen
#        -> GLITCHTIP_ORG_SLUG hacohen
#
# Everything after the slug is ordinary `${VAR}` interpolation, which compose already does inside
# .env. The slug itself is the one step compose CANNOT do: there is no lowercase and no substitution
# in its interpolation grammar. So it is computed here, at render time, and written back into .env
# as a literal — which is also what makes it readable by the shell/python helpers that parse .env
# line-by-line (scripts/lib.sh `read_env` builds every `<svc>-<DEPLOYMENT_NAME>` container name).
#
# Render time is the right moment because it is the ONLY moment guaranteed to precede every use:
# `bbox run` calls ensure_rendered() before compose, and compose_files() renders a missing
# .generated/. A fresh clone thus needs no manual step and no bootstrap script.
#
# Scope is deliberately narrow: it rewrites ONLY an assignment sitting directly under a
# `#@derived slug` marker line. Anything else in .env — secrets, operator overrides, CI's own
# DEPLOYMENT_NAME — is out of reach by construction.
DERIVED_MARKER = "#@derived slug"
ENVFILE = REPO / ".env"


def slugify(name):
    """"Hacohen" -> "hacohen"; "Bina Solutions Ltd." -> "bina-solutions-ltd"."""
    return re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")


def _env_assign(line):
    """('KEY', 'value') for an assignment line, else None. Comments/blanks/`export` are not ours."""
    m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
    return (m.group(1), m.group(2)) if m else None


_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _envfile_value(var):
    """This machine's .env value of `var` (last assignment wins, quotes and CR stripped), else None.

    WITH ITS `${NAME}` / `${NAME:-default}` REFERENCES RESOLVED, from the same file — the way compose
    reads it, and `scripts/lib.sh read_env`, and the archiver's reader. This one returned the raw
    text, so on an office whose .env says `CONSOLE_BASE_URL=console.${DEPLOYMENT_DOMAIN}` (the
    template's own spelling) every host DERIVED from it carried the reference along. Measured
    2026-10-05 on hp-laptop, the first time a framed app was switched on there: the sign-in blueprint
    got `external_host: http://plane.console.${DEPLOYMENT_DOMAIN}`, authentik refused it ("Enter a
    valid URL"), the sentinel that applies blueprints exited and was restarted for ever, and no host
    declared after that moment was ever served. Every caller here wants the VALUE on this machine.
    """
    if not ENVFILE.is_file():
        return None
    raw = {}
    for ln in ENVFILE.read_text(encoding="utf-8", errors="replace").split("\n"):
        kv = _env_assign(ln[:-1] if ln.endswith("\r") else ln)
        if kv:
            raw[kv[0]] = kv[1].strip().strip('"').strip("'")
    val = raw.get(var)
    for _ in range(20):                                  # bounded: a reference to itself ends here
        m = _ENV_REF.search(val or "")
        if not m:
            break
        val = val[:m.start()] + (raw.get(m.group(1)) or m.group(2) or "") + val[m.end():]
    # ...and what is still a reference after that (a line that names itself) is nothing: a caller
    # builds a host or a port from this, and must never be handed the text of a reference.
    return _ENV_REF.sub(lambda m: m.group(2) or "", val) if val else val


def traefik_host(var, fallback):
    """The value inside Host(`…`): `${var:-fallback}` — unless THIS machine's .env gives `var` a
    value with a port, in which case the host part is rendered as a literal.

    traefik v3 matches Host() against the request host WITHOUT its port, so a rule that contains a
    port never matches anything — measured 2026-09-30 with Host headers against the running edge
    (issue traefik-v3-ignores-the-request-port…). On the Mac, scripts/ci-env.sh writes
    `<host>.localhost:8080` into every <APP>_BASE_URL, so every -http/-https router rendered from it
    was dead code and every app lived on its -local twin — until the first nested host
    (plane.console.localhost, framed inside the console for same-site cookies) had no twin and 404'd.
    Compose interpolation cannot split a string, so the split happens here, and only when there is
    something to split: a port-less value, or no .env, keeps the interpolation and renders
    byte-identically to before. The port is not lost — it lives in the app's own URLs, never in a
    traefik rule.
    """
    val = _envfile_value(var)
    if val and re.fullmatch(r"[A-Za-z0-9.-]+:\d+", val):
        return val.rsplit(":", 1)[0]
    return "${" + var + ":-" + fallback + "}"


def sync_identity():
    """Keep every `#@derived slug` line in .env equal to slugify(BUSINESS_NAME). Returns the slug.

    No-ops (silently, returning None) when there is no .env yet, no BUSINESS_NAME in it, or the
    name slugifies to nothing — a render must stay usable while the deployment is half-configured.
    Writes only when a value actually changes, so it does not churn .env's mtime on every render.
    """
    if not ENVFILE.is_file():
        return None
    raw = ENVFILE.read_text(encoding="utf-8", errors="replace")
    # Keep the file's own line endings: .env is edited on Windows and on the VPS, and rewriting
    # LF as CRLF puts a trailing \r INSIDE every value docker then reads.
    nl = "\r\n" if "\r\n" in raw else "\n"
    lines = raw.split("\n")
    lines = [ln[:-1] if ln.endswith("\r") else ln for ln in lines]

    business = None
    for ln in lines:
        kv = _env_assign(ln)
        if kv and kv[0] == "BUSINESS_NAME":
            business = kv[1].strip().strip('"').strip("'")
    slug = slugify(business)
    if not slug:
        return None

    changed, have_slug_var = [], False
    for i, ln in enumerate(lines):
        if ln.strip() != DERIVED_MARKER or i + 1 >= len(lines):
            continue
        kv = _env_assign(lines[i + 1])
        if not kv:                      # dangling marker (CI strips the line under it) — leave it
            continue
        key, val = kv
        if key == "COMPANY_SLUG":
            have_slug_var = True
        if val != slug:
            lines[i + 1] = f"{key}={slug}"
            changed.append(f"{key}: {val or '(empty)'} -> {slug}")

    # An .env written before this existed has no marker at all. Plant the one variable everything
    # else interpolates from, right under BUSINESS_NAME — compose's .env interpolation is
    # ORDER-SENSITIVE, so it must precede DEPLOYMENT_DOMAIN and the MAIL_* lines that reference it.
    if not have_slug_var:
        for i, ln in enumerate(lines):
            kv = _env_assign(ln)
            if kv and kv[0] == "BUSINESS_NAME":
                lines[i + 1:i + 1] = [DERIVED_MARKER, f"COMPANY_SLUG={slug}"]
                changed.append(f"COMPANY_SLUG: (absent) -> {slug}   [inserted under BUSINESS_NAME]")
                break

    if changed:
        # newline="" so `nl` (the file's OWN ending) is what lands on disk, not python's translation.
        # Path.write_text() only grew a newline= kwarg in 3.10; open() has had it forever.
        with ENVFILE.open("w", encoding="utf-8", newline="") as fh:
            fh.write(nl.join(lines))
        print(f"  identity  BUSINESS_NAME={business!r} -> slug {slug!r}", file=sys.stderr)
        for c in changed:
            print(f"  identity  .env {c}", file=sys.stderr)
    return slug


# ── disposition: what the operator wants an app to BE ──────────────────────────
# `enabled: bool` could not express the states a real app engine needs. Android carries eight;
# the three that earn their keep here are:
#   enabled   — running
#   disabled  — switched off, containers kept (stopped), data kept
#   archived  — images and containers removed to reclaim disk, DATA AND THE TILE KEPT.
#               Android 15 added exactly this because "uninstall to free space" loses the data
#               people actually care about. Unarchive = re-pull + up.
# Provenance travels with it: `by: user` must never be silently undone by the system.
# The legacy `{enabled: true|false}` form still parses, so no state file has to be rewritten.
DISPOSITIONS = ("enabled", "disabled", "archived")


def disposition(entry):
    """The declared disposition of one platform.state.yaml app entry."""
    if not entry:
        return "disabled"
    st = (entry.get("state") or "").strip().lower() if isinstance(entry, dict) else ""
    if st in DISPOSITIONS:
        return st
    if isinstance(entry, dict) and "enabled" in entry:
        return "enabled" if entry.get("enabled") else "disabled"
    return "disabled"


def current_disposition(aid):
    """The disposition WRITTEN in platform.state.yaml for one app, or None when it has no entry.

    set_disposition() answers "did the file change?", which is False BOTH when the app is absent and
    when it is already in the requested state — and the caller reported that single False as "not
    found in platform.state.yaml". So the second `bbox apps enable <app>` of any app exited 1 with
    advice ("use --create to add it") that was already satisfied, and the idempotent case looked
    exactly like a typo. Asking the reader instead of inferring from a no-op separates them.
    """
    try:
        txt = STATE.read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(rf"^\s+{re.escape(aid)}:\s*\{{([^}}]*)\}}", txt, flags=re.M)
    if not m:
        return None
    body = m.group(1)
    st = re.search(r"state:\s*([A-Za-z_]+)", body)
    if st and st.group(1).lower() in DISPOSITIONS:
        return st.group(1).lower()
    en = re.search(r"enabled:\s*(true|false)", body)
    if en:
        return "enabled" if en.group(1) == "true" else "disabled"
    return "disabled"


def enabled_ids(state, cat):
    """Apps the platform should actually RUN. Archived is deliberately not running."""
    return {aid for aid, e in (state.get("apps") or {}).items()
            if aid in cat and disposition(e) == "enabled"}


def set_disposition(aid, dispo, by="user", create=False):
    """THE writer for apps.<id> in platform.state.yaml. One implementation, beside the reader.

    Until this existed the desired-state file had FOUR independent regex writers — bbox's inline
    python, app-management's _set_disposition, appinstall's state_upsert and packaging/qa-fix-loop.sh
    — each doing its own text surgery on the same brace block, in TWO incompatible shapes, with no
    schema and no validation anywhere. `disposition()` above is why that never exploded: one shared
    READER parses both shapes. The write side had no such mercy, and whichever surface acted last
    silently rewrote the form the other had written.

    Text surgery, not a YAML round-trip: the file is ~80% comments explaining the model and a
    round-trip deletes every one of them. That constraint is real and is why this is regex — but it
    belongs in ONE function, not four.

    Writes the explicit `{ state: <dispo>, by: <who> }` form. The legacy `{ enabled: bool }` form
    still parses (see disposition()), so nothing has to be rewritten to adopt this. Replaces the
    WHOLE brace block, so it transitions out of `archived` correctly — the bug that made
    `bbox apps enable <archived-app>` report success and change nothing.

    Returns True if the file changed. `create=True` appends a new entry (install path) instead of
    failing when the app has no entry yet.
    """
    if dispo not in DISPOSITIONS:
        raise ValueError(f"unknown disposition {dispo!r}; expected one of {DISPOSITIONS}")
    txt = STATE.read_text(encoding="utf-8")
    repl = f"{{ state: {dispo}, by: {by} }}"
    new, n = re.subn(rf"^(\s+{re.escape(aid)}:\s*)\{{[^}}]*\}}",
                     lambda m: m.group(1) + repl, txt, count=1, flags=re.M)
    if n:
        if new != txt:
            STATE.write_text(new, encoding="utf-8", newline="\n")
            return True
        return False
    if not create:
        return False
    # Append inside the apps: block, after the last app entry.
    lines = txt.splitlines()
    in_apps, last = False, None
    for i, ln in enumerate(lines):
        if ln.startswith("apps:"):
            in_apps = True
            continue
        if in_apps:
            if ln.strip() and not ln.startswith((" ", "\t", "#")):
                break
            if re.match(r"^  [a-z][\w-]*:", ln):
                last = i
    if last is None:
        raise ValueError("platform.state.yaml has no apps: block to extend")
    lines.insert(last + 1, f"  {aid}:".ljust(20) + repl + f"   # added by {by}")
    STATE.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return True


# ── the office's own record — `office:` ─────────────────────────────────────────────────────────
#: The facts the install wizard writes about THIS office, and nothing else: what it is called, the
#: animal and hue that mark its apps wherever a linked office shows them (the owner's fleet,
#: 2026-10-09: hp = elephant/grey, macbook = deer/yellow, vps = eagle/sky), the terms it accepted and
#: when its wizard finished. `installed_at` is what the console reads as "this office has been set
#: up": an office without it is served the wizard instead of the shell.
OFFICE_FIELDS = ("name", "animal", "hue", "terms_version", "terms_accepted_at", "installed_at")
#: A COLOUR is never written here. A hue is one of the palette's families, by NAME — the file that
#: owns colour (platform-base/bina-ui/theme-tokens.css) must still declare `--<hue>:`, and a screen
#: resolves `var(--<hue>)`. `muted` is the palette's grey (the elephant's); the rest are the hues a
#: fill may take. The set is the palette's vocabulary, not a design decision made here.
OFFICE_HUES = ("olive", "lime", "sky", "plum", "violet", "muted")
OFFICE_NAME_MAX = 60
_OFFICE_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_OFFICE_WORD = re.compile(r"^[a-z][a-z0-9-]{0,30}$")
_OFFICE_HEADER = ("# ── this office's own record: written by the install wizard through the control plane's "
                  "/api/office; read by the console, the link's catalog and `bbox dgo identity` ──\n")


def office_block():
    """The `office:` block as the FILE has it — this office's own record. {} before the wizard ran."""
    try:
        doc = yaml.safe_load(STATE.read_text(encoding="utf-8")) or {}
    except OSError:
        return {}
    block = doc.get("office")
    if not isinstance(block, dict):
        return {}
    return {k: str(v) for k, v in block.items() if k in OFFICE_FIELDS and v is not None}


def _glyph_names():
    """Every glyph the ONE icon set draws. An office's animal must be one of them, or it is a box on
    every screen that names the office — the set is read, not remembered, so a glyph added there is
    an animal here the same day."""
    try:
        js = (REPO / "platform-base/bina-ui/bina-icons.js").read_text(encoding="utf-8")
    except OSError:
        return set()
    return set(re.findall(r"^\s+'?([a-z][a-z0-9-]*)'?:\s*'<", js, flags=re.M))


def set_office(fields, by="wizard"):
    """THE writer for `office:` in platform.state.yaml. Returns (changed, errors).

    Beside set_disposition and set_remote for their reason — the compiler owns this file's format —
    and shaped like set_remote: VALIDATED before anything is written, then text surgery that cuts the
    old block out whole and re-appends the new one, every other byte (the comments that explain the
    model) kept. A field not given keeps its value: the wizard writes the record once, and a later
    screen may change the animal without knowing when the terms were accepted. `by` is recorded in
    the block's header for the same reason set_disposition records it.
    """
    if not isinstance(fields, dict):
        return False, ["office: a JSON object of fields"]
    cur = office_block()
    new, errs = dict(cur), []
    for k, v in fields.items():
        if k not in OFFICE_FIELDS:
            errs.append(f"office: unknown field {k!r} (the fields are {', '.join(OFFICE_FIELDS)})")
            continue
        if v is None or not str(v).strip():
            continue
        new[k] = " ".join(str(v).split())
    if len(new.get("name", "")) > OFFICE_NAME_MAX:
        errs.append(f"office: name is one line of at most {OFFICE_NAME_MAX} characters")
    animal = new.get("animal")
    if animal and (not _OFFICE_WORD.match(animal) or animal not in _glyph_names()):
        errs.append(f"office: animal {animal!r} is not a glyph of platform-base/bina-ui/bina-icons.js")
    hue = new.get("hue")
    if hue:
        try:
            css = (REPO / "platform-base/bina-ui/theme-tokens.css").read_text(encoding="utf-8")
        except OSError:
            css = ""
        if hue not in OFFICE_HUES or f"--{hue}:" not in css:
            errs.append(f"office: hue {hue!r} is not one of the palette's families "
                        f"({', '.join(OFFICE_HUES)}) declared in theme-tokens.css")
    for k in ("terms_accepted_at", "installed_at"):
        if new.get(k) and not _OFFICE_TIME.match(new[k]):
            errs.append(f"office: {k} is a UTC time written YYYY-MM-DDTHH:MM:SSZ")
    # `installed_at` stands on its own: an office installed before the wizard existed (every office
    # of 2026-10-09) has no terms record, and writing one it never clicked would be a lie. The wizard
    # itself always writes both.
    if new.get("terms_accepted_at") and not new.get("terms_version"):
        errs.append("office: terms_accepted_at names no terms_version — which terms were accepted?")
    if errs:
        return False, errs
    if new == cur:
        return False, []
    out, skipping = [], False
    for ln in STATE.read_text(encoding="utf-8").splitlines(keepends=True):
        if re.match(r"^office:\s*$", ln) or ln.startswith(_OFFICE_HEADER.rstrip("\n")):
            skipping = True
            continue
        if skipping:
            if ln.strip() and not ln[0].isspace():
                skipping = False
            else:
                continue
        out.append(ln)
    text = ("".join(out).rstrip("\n") + "\n\n" + _OFFICE_HEADER.rstrip("\n") + f"  (by {by})\n"
            + yaml.safe_dump({"office": new}, allow_unicode=True, sort_keys=False,
                             default_flow_style=False, width=1000))
    STATE.write_text(text, encoding="utf-8", newline="\n")
    return True, []


def remote_block():
    """The `remote:` block as the FILE has it — what linked offices give this one, declared."""
    block = (yaml.safe_load(STATE.read_text(encoding="utf-8")) or {}).get("remote")
    return block if isinstance(block, list) else []


def set_remote(block):
    """THE writer for `remote:` in platform.state.yaml. Returns (changed, errors).

    The block is what a LINKED OFFICE's catalog becomes here (dgo-extend's projection builds it), and
    it used to be written by a script that app carried and ran on "the machine that runs this
    office" over SSH — a second writer of this file, outside the compiler, and no writer at all on
    an office with no such door (measured 2026-10-05: hp-laptop has no sshd by its owner's decision,
    so every new app of a linked office waited for somebody to run `bbox dgo project` by hand).

    Beside `set_disposition` for the reason that one gives — the compiler owns this file's format —
    and one more: THE BLOCK IS VALIDATED BEFORE IT IS WRITTEN. `render` refuses the whole office on
    a remote block it cannot plan ("SERVE PLAN REFUSED"), and this block arrives from another
    office: unvalidated, one bad catalog over there is every lifecycle change over here failing to
    compile until somebody edits the file. A refused block changes nothing and says why.

    Text surgery, like the rest of this file's writers: the block is cut out and re-appended, and
    every other byte — the comments that explain the model — is left alone. A legacy top-level
    `serve:` block is removed with it, as the writer this replaces did.
    """
    if not isinstance(block, list):
        return False, ["remote must be a list of offices"]
    _entries, errs = serve.plan({"remote": block}, load_catalog())
    if errs:
        return False, list(errs)
    # `fetched` is the moment a catalog was read — new on every pass, and a READING, not a
    # declaration. Comparing it made every pass "a change" and rewrote the file once a minute.
    def declared(b):
        return json.dumps([{k: v for k, v in e.items() if k != "fetched"} for e in b],
                          sort_keys=True, ensure_ascii=False)

    if declared(remote_block()) == declared(block):
        return False, []
    out, skipping = [], False
    for ln in STATE.read_text(encoding="utf-8").splitlines(keepends=True):
        if re.match(r"^(remote|serve):\s*$", ln):
            skipping = True
            continue
        if skipping:
            # The entries sit at column 0 (`remote:\n- office: …`), so a list item does NOT end the
            # block — otherwise every rewrite would leave the old list behind, keyless.
            if ln.strip() and not ln[0].isspace() and not ln.startswith("-"):
                skipping = False
            else:
                continue
        out.append(ln)
    text = "".join(out).rstrip("\n") + "\n"
    if block:
        text += "\n" + yaml.safe_dump({"remote": block}, allow_unicode=True, sort_keys=False,
                                      default_flow_style=False, width=1000)
    STATE.write_text(text, encoding="utf-8", newline="\n")
    return True, []


# ── load ──────────────────────────────────────────────────────────────────────
def load_catalog():
    cat = {}
    for root, layers in CATALOG_ROOTS.items():
        if not root.exists():
            continue
        for m in sorted(root.glob("*/app.json")):
            try:
                a = json.loads(m.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                sys.exit(f"FATAL {m.relative_to(REPO)}: invalid JSON: {e}")
            a["_dir"] = m.parent
            if a.get("id") != m.parent.name:
                sys.exit(f"FATAL {m.relative_to(REPO)}: id '{a.get('id')}' != directory '{m.parent.name}'")
            if a.get("layer") not in layers:
                want = "apps/" if a.get("layer") == 3 else "platform-base/"
                sys.exit(f"FATAL {m.relative_to(REPO)}: layer {a.get('layer')} manifest is in "
                         f"{root.name}/, which holds layer(s) {', '.join(map(str, layers))} — move it to {want}")
            if a["id"] in cat:
                sys.exit(f"FATAL duplicate app id '{a['id']}' in both platform-base/ and apps/")
            cat[a["id"]] = a
    return cat


#: App ids that were RENAMED. `offices` → `dgo-extend` (2026-09-30) is a live migration rather than
#: history: an office that already ran the old name has `offices: {state: enabled}` written in its
#: state file, and without this it would come up with an app that no longer exists and none of its own
#: — and because `run_app_hooks` only visits ENABLED apps, the rename's own migration hook could
#: never run to fix it. The read is normalized here; apps/dgo-extend/hooks/migrate rewrites the file.
LEGACY_APP_IDS = {"offices": "dgo-extend"}


def ensure_state():
    """The office has a platform.state.yaml, or it gets one. Never replaces an existing file.

    THREE ANSWERS, IN THIS ORDER, and the order is the point:

      1. the file is there — nothing happens. This is every ordinary run.
      2. it is missing and this checkout was ON a commit a moment ago (`ORIG_HEAD`, which a pull
         leaves behind): put back the copy THAT commit carried. This is the office whose file was
         tracked until the pull that untracked it — its own app set comes back, not the product's.
      3. it is missing and there is nothing to put back: a real first run → the tracked default.

    3 IS REFUSED ON A CHECKOUT THAT HAS COMPILED BEFORE (it has .generated/, or its own flag). "The
    desired state disappeared and we started the office from the product default" is a silent reset
    of somebody's deployment — the failure this whole split exists to make impossible — so it stops
    with what to do about it instead of doing something plausible.
    """
    if STATE.exists():
        return
    restored = None
    try:
        ref = subprocess.run(["git", "rev-parse", "--verify", "--quiet", "ORIG_HEAD"],
                             cwd=REPO, capture_output=True, text=True, timeout=10)
        if ref.returncode == 0 and ref.stdout.strip():
            show = subprocess.run(["git", "show", f"{ref.stdout.strip()}:{STATE.name}"],
                                  cwd=REPO, capture_output=True, text=True, timeout=10)
            if show.returncode == 0 and show.stdout.strip():
                restored = show.stdout
    except (OSError, subprocess.SubprocessError):
        restored = None
    if restored is None:
        if GEN.exists():
            sys.exit(f"FATAL {STATE.name} is missing on a checkout that has compiled before "
                     f"({GEN.name}/ is here) — refusing to start it from {DEFAULT_STATE.name}. "
                     f"Restore this office's own {STATE.name}, or remove {GEN.name}/ to install the "
                     f"product default on purpose.")
        if not DEFAULT_STATE.exists():
            sys.exit(f"FATAL {STATE.name} is missing and there is no {DEFAULT_STATE.name} to create "
                     f"it from")
        restored = DEFAULT_STATE.read_text(encoding="utf-8")
        print(f"  info  {STATE.name}: created from {DEFAULT_STATE.name} (this checkout's first run)")
    else:
        print(f"  info  {STATE.name}: restored from the commit this checkout was on (ORIG_HEAD)")
    STATE.write_text(restored, encoding="utf-8", newline="\n")


def load_state():
    ensure_state()
    st = yaml.safe_load(STATE.read_text(encoding="utf-8")) or {}
    if st.get("schema_version") != 1:
        sys.exit(f"FATAL platform.state.yaml schema_version {st.get('schema_version')} unsupported (expected 1)")
    apps = st.get("apps") or {}
    for old_id, new_id in LEGACY_APP_IDS.items():
        if old_id in apps and new_id not in apps:
            apps[new_id] = apps.pop(old_id)
            print(f"  info  platform.state.yaml: legacy app id '{old_id}' is '{new_id}' now — "
                  f"run apps/dgo-extend/hooks/migrate to rewrite the file", file=sys.stderr)
    return st


# ── validate ──────────────────────────────────────────────────────────────────
def _check_enums(aid, val, spec, path, errs):
    """Recursively enforce every `enum` the schema declares — including inside array items.

    validate() used to hardcode two enum checks (`kind`, `use[].strength`) and no others, so every
    enum nested under an array or a sub-object was decorative. `routing[].auth` is the one that
    matters: the schema says sso|none|basic, and the label emitter attaches the authentik
    forwardAuth middleware only on an exact `auth == "sso"`. So `auth: "SSO"`, `auth: "ssoo"`, or a
    stray trailing space passed validation, compiled cleanly, and published the app with **no
    authentication at all** — no error, no warning, and a healthy-looking stack.

    Checking enums generically rather than adding a third hardcoded case is the point: `module.group`
    had exactly the same hole, and so will the next enum somebody adds.
    """
    if spec.get("enum") is not None:
        # An explicit null is NOT a free pass. `auth: null` makes `r.get("auth", "sso")` return
        # None — the default never applies, because the key is present — so it failed the
        # `== "sso"` test and published an open route, exactly like a typo. Only accept None when
        # the schema actually declares null as a type.
        types = spec.get("type")
        types = [types] if isinstance(types, str) else list(types or [])
        if val is None and "null" in types:
            return
        if val not in spec["enum"]:
            errs.append(f"{aid}: {path} must be one of "
                        f"{'|'.join(map(str, spec['enum']))}, got {val!r}")
        return
    props = spec.get("properties")
    if props and isinstance(val, dict):
        for k, sub in props.items():
            if k in val:
                _check_enums(aid, val[k], sub, f"{path}.{k}", errs)
    items = spec.get("items")
    if items and isinstance(val, list):
        for i, el in enumerate(val):
            _check_enums(aid, el, items, f"{path}[{i}]", errs)


JS = {"object": dict, "array": list, "string": str, "boolean": bool,
      "integer": int, "number": (int, float)}


def _check_types(aid, val, spec, path, errs):
    """Declared types at EVERY depth, mirroring _check_enums directly above.

    2026-08-24: the type check ran isinstance() against each TOP-LEVEL key and stopped, so a nested
    value of the wrong type was never examined. Enums recursed; types did not, and nothing said why.

    That shipped a visible bug. platform-os-net/apps/network/app.json declares
    routing[0].module.name and .desc as {en,he} OBJECTS, while the schema declares both
    type=string. Nothing rejected it, the console sidebar stringified the object, and the entry
    rendered as "[object Object]share-2" with the icon id appended. The same file's TOP-LEVEL
    title/summary are objects and are correct - the schema declares those as objects - which is
    exactly why the mistake is easy to make and worth catching mechanically rather than in review.

    A value of the wrong type is NOT descended into: reporting "field 'x' must be string" and then
    a cascade of complaints about the keys inside it buries the one line that matters.
    """
    types = spec.get("type")
    if types:
        types = [types] if isinstance(types, str) else list(types)
        if not (val is None and "null" in types):
            want = tuple(t for t in (JS.get(x) for x in types) if t)
            if want and not isinstance(val, want):
                errs.append(f"{aid}: {path} must be {'|'.join(types)}, got {type(val).__name__}")
                return
    props = spec.get("properties")
    if props and isinstance(val, dict):
        for k, sub in props.items():
            if k in val:
                _check_types(aid, val[k], sub, f"{path}.{k}", errs)
    items = spec.get("items")
    if items and isinstance(val, list):
        for i, el in enumerate(val):
            _check_types(aid, el, items, f"{path}[{i}]", errs)


def validate(cat):
    """Structural validation without a jsonschema dependency (it isn't installed here)."""
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    allowed, required = set(schema["properties"]), set(schema["required"])
    errs = []
    provided = {}
    claimed_hosts, claimed_modules = {}, {}
    for aid, a in cat.items():
        keys = {k for k in a if not k.startswith("_")}
        for miss in required - keys:
            errs.append(f"{aid}: missing required field '{miss}'")
        for extra in keys - allowed:
            errs.append(f"{aid}: unknown field '{extra}'")
        # TYPE checking, not just presence. `title` and `summary` are {he,en} objects; writing
        # them as plain strings passed this validator (the key was present) and then blew up in
        # the console at runtime with "'str' object has no attribute 'get'" — the apps screen
        # showed an error instead of the catalog. Validate what the schema actually declares.
        for k, v in ((k, a[k]) for k in keys & allowed):
            spec = schema["properties"][k]
            types = spec.get("type")
            if not types:
                continue
            types = [types] if isinstance(types, str) else list(types)
            if "null" in types and v is None:
                continue
            want = tuple(t for t in (JS.get(x) for x in types) if t)
            if want and not isinstance(v, want):
                errs.append(f"{aid}: field '{k}' must be {'|'.join(types)}, got "
                            f"{type(v).__name__}")
                continue
            if isinstance(v, dict):
                for sub in spec.get("required", []):
                    if sub not in v:
                        errs.append(f"{aid}: field '{k}' is missing required key '{sub}'")
            _check_enums(aid, v, spec, f"field '{k}'", errs)
            _check_types(aid, v, spec, f"field '{k}'", errs)
        if a.get("layer") not in (1, 2, 3):
            errs.append(f"{aid}: layer must be 1|2|3")
        if a.get("kind") not in set(schema["properties"]["kind"]["enum"]):
            errs.append(f"{aid}: invalid kind '{a.get('kind')}'")
        for c in a.get("capabilities", []):
            provided.setdefault(c["name"], []).append(aid)
        for u in a.get("use", []):
            s = u.get("strength", "requires")
            if s not in STRENGTHS:
                errs.append(f"{aid}: use[{u.get('capability')}] bad strength '{s}'")
        # CONFLICTS. The loader already rejects a duplicate app id (and id != dirname), but two
        # DIFFERENT apps could still claim the same edge route or the same console tile. Whichever
        # compiled last would silently win: one app becomes unreachable, or its tile opens the
        # other. Debian calls this Conflicts/Replaces and refuses to co-install; Android enforces a
        # unique package name. Same idea — detect it at compile time, not in production.
        for r in (a.get("routing") or []):
            if r.get("host"):
                claimed_hosts.setdefault(r["host"], []).append(aid)
            mid = (r.get("module") or {}).get("id")
            if mid:
                claimed_modules.setdefault(mid, []).append(aid)

        # ── the app's brief for the office agent ────────────────────────────────
        # A pointer to a file that is not there is the worst kind of manifest error: the app installs,
        # the platform is green, and the agent simply never learns how to operate it — a silence with
        # no owner. So the compiler refuses it here, at the same place compose paths are checked.
        ag = a.get("agent")
        if ag is not None:
            rel = (ag.get("context") or "").strip()
            if not rel:
                errs.append(f"{aid}: agent.context must name the brief file (convention: AGENT.md)")
            elif rel.startswith("/") or ".." in pathlib.PurePosixPath(rel).parts:
                errs.append(f"{aid}: agent.context must be a path INSIDE apps/{aid}/, got {rel!r}")
            elif not (a["_dir"] / rel).is_file():
                errs.append(f"{aid}: agent.context '{rel}' does not exist — the agent would never "
                            f"learn how to operate this app")
            else:
                size = (a["_dir"] / rel).stat().st_size
                if size > MAX_BRIEF_BYTES:
                    errs.append(
                        f"{aid}: agent.context '{rel}' is {size} bytes, over the {MAX_BRIEF_BYTES} "
                        f"budget — this file is injected into EVERY agent session, so it buys its "
                        f"size from every other app's brief. Cut it to what a caller cannot read "
                        f"off the manifest (what the app is FOR, its vocabulary, its traps).")

        comp = a.get("compose")
        if comp and not (a["_dir"] / comp).exists():
            errs.append(f"{aid}: compose '{comp}' not found")
        if a.get("kind") in ("blueprint", "library") and comp:
            errs.append(f"{aid}: kind={a['kind']} must not declare compose")
    for host, owners in sorted(claimed_hosts.items()):
        if len(owners) > 1:
            errs.append(f"route conflict: host '{host}' claimed by {', '.join(sorted(owners))} "
                        f"— only one app can own an edge route")
    for mid, owners in sorted(claimed_modules.items()):
        if len(owners) > 1:
            errs.append(f"tile conflict: console module '{mid}' claimed by {', '.join(sorted(owners))} "
                        f"— the shell would route one app's tile to the other")
    return errs, provided


# ── resolve ───────────────────────────────────────────────────────────────────
def resolve(cat, state, roots=None):
    """Return (ordered_enabled_ids, diagnostics). Enforces strength, ordering, cycles.

    roots: start the closure at these app ids instead of "every enabled app in the state".
    A lane (a CI job, a partial bring-up) wants "indox and whatever indox needs", which is a
    question about the GRAPH, not about the persisted disposition — so it must not be answered
    by editing platform.state.yaml. Everything downstream (strength, ops negotiation, ordering,
    cycles) is identical; only the seed set differs.
    """
    diags = []
    if roots:
        unknown = [r for r in roots if r not in cat]
        if unknown:
            sys.exit("FATAL unknown app id(s): " + ", ".join(sorted(unknown))
                     + " — not a manifest in platform-base/ or apps/")
        enabled = set(roots)
    else:
        enabled = enabled_ids(state, cat)
        for aid in (state.get("apps") or {}):
            if aid not in cat:
                diags.append(("info", f"{aid}: in state but not yet migrated to apps/ (legacy lane)"))

    provider = {}
    for aid, a in cat.items():
        for c in a.get("capabilities", []):
            provider.setdefault(c["name"], []).append(aid)

    # Bridge: capabilities still served by un-migrated services. Satisfies `use` without adding a
    # node to the graph (the legacy lane already starts them). Shrinks to empty as apps migrate.
    legacy_caps = {}
    lc = REPO / "platform/legacy-capabilities.yaml"
    if lc.exists():
        legacy_caps = yaml.safe_load(lc.read_text(encoding="utf-8")) or {}

    # transitively pull in providers of hard-used capabilities (ref-counted implicitly)
    # Admin-chosen capability -> provider bindings (the durable half of the decision).
    bindings = {k: v.get("provider") if isinstance(v, dict) else v
                for k, v in (state.get("bindings") or {}).items()}
    want, frontier = set(enabled), list(enabled)
    while frontier:
        aid = frontier.pop()
        for u in cat[aid].get("use", []):
            if u.get("strength", "requires") not in HARD:
                continue
            cap = u["capability"]
            provs = provider.get(cap, [])
            if not provs:
                if cap in legacy_caps:
                    diags.append(("info", f"{aid}: '{cap}' served by legacy '{legacy_caps[cap]}' (not yet migrated)"))
                else:
                    diags.append(("error", f"{aid}: requires capability '{cap}' — no provider in catalog "
                                           f"and not declared in platform/legacy-capabilities.yaml"))
                continue
            # ops negotiation: refuse a provider missing a required op
            need = set(u.get("ops") or [])
            ok = []
            for p in provs:
                # NB: do not rebind `cap` here — it holds the capability NAME and is used below for
                # binding lookup and diagnostics. This loop needs the provider's capability DICT.
                pcap = next(c for c in cat[p]["capabilities"] if c["name"] == cap)
                have = set(pcap.get("required_ops", [])) | set(pcap.get("optional_ops", []))
                if need and not need <= have:
                    diags.append(("error", f"{aid}: provider '{p}' lacks ops {sorted(need - have)} for '{cap}'"))
                else:
                    ok.append(p)
            # PROVIDER SELECTION. `ok[:1]` picked whichever provider the catalog dict happened to
            # yield first — silent, non-deterministic, and unauditable the moment two apps provide
            # the same capability. Selection is now an explicit, reviewable decision, in the order
            # every mature package manager uses:
            #   1. a binding recorded in platform.state.yaml   (the admin's choice — Android's
            #      remembered "preferred activity" / Debian's update-alternatives manual mode)
            #   2. the consumer's declared `default_provider`  (Snap's default-provider)
            #   3. the only candidate
            # Ambiguity with no rule is NOT resolved by guessing: it fails the plan and names every
            # candidate, so the operator picks instead of finding out in production.
            chosen = None
            if len(ok) == 1:
                chosen = ok[0]
            elif len(ok) > 1:
                bound = bindings.get(cap)
                pref = u.get("default_provider")
                if bound and bound in ok:
                    chosen = bound
                    diags.append(("info", f"{cap}: bound to '{chosen}' by platform.state.yaml"))
                elif bound:
                    diags.append(("error", f"{cap}: platform.state.yaml binds '{bound}', which is not "
                                           f"an eligible provider ({', '.join(sorted(ok))})"))
                elif pref and pref in ok:
                    chosen = pref
                    diags.append(("info", f"{cap}: '{chosen}' selected via {aid}'s default_provider"))
                else:
                    diags.append(("error",
                        f"{aid}: capability '{cap}' has {len(ok)} eligible providers "
                        f"({', '.join(sorted(ok))}) and no rule to choose — set "
                        f"`bindings.{cap}` in platform.state.yaml or `default_provider` on the use[] entry"))
            if chosen and chosen not in want:
                want.add(chosen); frontier.append(chosen)
                diags.append(("info", f"{chosen}: pulled in as provider of '{cap}' for {aid}"))

    # CONFLICTS. `conflicts` was in STRENGTHS but nothing ever read it, so declaring one did
    # nothing. Debian splits this in two and the distinction is the useful part:
    #   Breaks    -> the other must be DECONFIGURED (here: disabled; data kept)
    #   Conflicts -> the other must be REMOVED      (here: uninstalled)
    # Policy's own guidance is to prefer the softer form, so `conflicts` means "these two cannot
    # both be enabled" and is reported as a plan failure naming BOTH apps — never resolved by
    # silently dropping one, which is the failure mode Gateway API explicitly forbids.
    for aid in sorted(want):
        for u in cat[aid].get("use", []):
            if u.get("strength") != "conflicts":
                continue
            target = u.get("capability")
            # a conflict may name a capability (every provider of it) or a specific app id
            hits = [p for p in provider.get(target, []) if p in want] if target in provider else []
            if target in want:
                hits.append(target)
            for other in sorted(set(hits)):
                if other == aid:
                    continue
                diags.append(("error",
                    f"conflict: '{aid}' and '{other}' cannot both be enabled "
                    f"({aid} declares conflicts with '{target}') — disable one in "
                    f"platform.state.yaml"))

    # ordering graph: only `after` edges, and never through weak links (Fuchsia)
    edges = {aid: set() for aid in want}
    for aid in want:
        for u in cat[aid].get("use", []):
            if not u.get("after", True) or u.get("dependency", "strong") == "weak":
                continue
            for p in provider.get(u["capability"], []):
                if p in want and p != aid:
                    edges[aid].add(p)

    order, seen, stack = [], {}, []

    def visit(n):
        st = seen.get(n)
        if st == 2:
            return
        if st == 1:
            cyc = " -> ".join(stack[stack.index(n):] + [n])
            diags.append(("error", f"dependency CYCLE: {cyc} (break it with dependency:'weak')"))
            return
        seen[n] = 1; stack.append(n)
        for d in sorted(edges.get(n, ())):
            visit(d)
        stack.pop(); seen[n] = 2; order.append(n)

    for n in sorted(want):
        visit(n)
    return order, diags


def write(path, text):
    r"""Write one generated file with LF endings, on every platform.

    `write_text(..., encoding="utf-8")` uses the PLATFORM newline. So running `bbox reconcile` on
    Windows — which CLAUDE.md lists as one of the three supported environments — emitted CRLF into
    every file under .generated/. Those files are staged into the shipped artifact by
    packaging/stage-control.py, so a Windows-built artifact and a Linux-built one differ
    byte-for-byte from identical source, and the manifest hash the release signs depends on who
    built it. (This was one of the reasons the old G1 "rendering is byte-identical" gate was DELETED
    on 2026-07-30 rather than re-goldened — it could not hold across platforms, and nothing asserts
    byte-equivalence of the render today. See scripts/refactor/GATES.md, "Why G1 was deleted".
    Emitting LF everywhere still matters: the shipped ARTIFACT must be reproducible.)

    Found by rendering twice on the same commit and diffing: all 26 lines "changed" and every
    include was identical.

    appinstall.py and signing.py already pass newline="\n" for exactly this reason. This is the same
    fix for the writers in this file, in one place so the next one cannot forget it.

    A FILE THAT ALREADY SAYS THIS IS LEFT ALONE. Everything written here is watched by something —
    the sign-in worker watches its blueprints, the edge its dynamic config, the console its tiles —
    and a watcher cannot tell a rewrite from a change. Every render runs on every `bbox` verb and
    every control-plane job, and each one made the sign-in worker re-apply its whole generated
    blueprint (forty providers, twice: a truncate and a write are two events), with nothing in it
    different. Measured on hp-laptop, 2026-10-05: eight renders in an hour, sixteen full applies.
    """
    path, data = pathlib.Path(path), text.encode("utf-8")
    try:
        if path.read_bytes() == data:
            return
    except OSError:
        pass                            # not there yet (or unreadable): writing it is the answer
    path.write_bytes(data)


def compose_files():
    """Canonical -f order for every consumer (bbox, G1 gate, CI). Overlays come last."""
    files = [(GEN / "compose.yml").relative_to(REPO).as_posix()]
    if (GEN / "routing.override.yml").exists():
        files.append((GEN / "routing.override.yml").relative_to(REPO).as_posix())
    # The reverse plane's network aliases: one `<alias>.<office>` per remote app on the link proxy's
    # namespace. Present only when some office is shown here, so an office with no linked peer keeps
    # a byte-identical -f list.
    if (GEN / "remote.override.yml").exists():
        files.append((GEN / "remote.override.yml").relative_to(REPO).as_posix())
    # Credential-broker cutovers LAST: this overlay blanks env vars the app's own compose sets, and
    # compose merges later files over earlier ones, so its position is load-bearing rather than
    # cosmetic. Emitted only when some app declares `broker` — an estate with none renders no file
    # and the -f list is byte-identical to before.
    if (GEN / "connections.override.yml").exists():
        files.append((GEN / "connections.override.yml").relative_to(REPO).as_posix())
    # The SSO bootstrap follows its inputs: a label that changes with the blueprints it applies, so
    # `dc up` recreates the container when they change (see _bootstrap_inputs_overlay).
    bootstrap = _bootstrap_inputs_overlay()
    if bootstrap is not None:
        files.append(bootstrap.relative_to(REPO).as_posix())
    # The CPU plan (gate G65), rendered by scripts/perf-profile-apply. What compose is given of it
    # is only its `services:` — a cap this machine has too few cores to create, lowered to the
    # machine's — LAST, because a later file wins. The budget's SCALE is not here: it moves with
    # every app switched on or off, so it is told to the running containers (`docker update`,
    # lib.sh cpu_caps_apply) and is no container's identity.
    if (GEN / "cpu-budget.yml").exists():
        files.append(_effective_cpu_budget().relative_to(REPO).as_posix())
    return files


def _compiled_services():
    """Every service name the compiled set declares: the `include:` list of .generated/compose.yml
    plus the routing/connections overlays. Raises on an unreadable file — callers decide what a
    missing answer means for them (both today fail open: no overlay rather than a broken project)."""
    compiled = yaml.safe_load((GEN / "compose.yml").read_text(encoding="utf-8")) or {}
    have = set((compiled.get("services") or {}).keys())
    # The compiled file is an `include:` list; the services live in the included files.
    for inc in compiled.get("include") or []:
        p = REPO / (inc if isinstance(inc, str) else inc.get("path", ""))
        if p.is_file():
            have |= set(((yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("services") or {}).keys())
    for extra in ("routing.override.yml", "connections.override.yml"):
        p = GEN / extra
        if p.exists():
            have |= set(((yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("services") or {}).keys())
    return have


# Everything authentik-bootstrap runs, and every blueprint that only IT can be trusted to apply. A
# change in any of these must recreate the container; nothing else about it should.
BOOTSTRAP_INPUTS_DIR = "platform-base/authentik"
BOOTSTRAP_INPUTS = ("bootstrap.sh", "outpost-ready.py")          # + the committed blueprints/*.yaml, sorted
# The compiled blueprint — written by render_authentik, and deliberately NOT one of those inputs.
GENERATED_BLUEPRINT = "zz-generated-apps.yaml"


def _bootstrap_inputs_overlay():
    """A label on authentik-bootstrap carrying the digest of everything it applies — so compose's
    own config hash follows the inputs and `dc up -d` recreates the container exactly when they
    changed. Returns the overlay path, or None when the compiled set has no bootstrap (an overlay
    naming a service that does not exist makes the WHOLE project invalid — the cpu-budget lesson).

    WHY (2026-09-30). The bootstrap applies its blueprints ONCE at start, then serves the readiness
    healthcheck for ever. Its environment carries the host variables the committed blueprint
    resolves (routing.override.yml), so a changed .env does recreate it — but nothing in its
    compose config moves when the blueprint
    CONTENT moves: a new `sso` slug in an app.json, a renamed display name, a fix in bootstrap.sh or
    outpost-ready.py, an edit to deployment-apps.yaml / zzz-migrations.yaml. `dc up` then reports
    the container up-to-date and the estate keeps running on providers compiled from an older
    render, while the generated blueprint on disk says otherwise. Measured: a container from 09-22
    that was `docker start`ed instead of recreated served no plane/git/forge providers for fifteen
    hours (issue authentik-bootstrap-unhealthy-for-fifteen-hours-two-sso-hosts-unserved). This
    label is the recreate trigger the container was missing; the first `dc up` after it lands
    recreates the bootstrap once, and after that only a real input change does.

    THE COMPILED BLUEPRINT IS NOT AN INPUT (2026-10-06). It was, and so every app switched on or
    off re-created this container, which then re-applied EVERY custom blueprint — each one a full
    authentik boot in a small container: four of the 4 min 22 s of an app's bring-up measured on
    hp-laptop, spent after the worker had applied the file and the outpost had been serving the new
    host for minutes. What made that trigger look necessary in the 09-22 measurement above was not
    that nobody applied the file — the worker applies it within seconds of every change (4–5 s,
    each time it was measured) — but that the outpost never loaded what was applied
    (render_authentik, ONE PROVIDER PER HOST). That is fixed at its cause; and whether the hosts of
    a render are in fact served is now ASKED (`hooks/refresh` → outpost-ready.py, which reads them
    from that very file), with a re-apply by this container as the remedy when they are not,
    instead of as the routine. Same install after: 30 s, and no sign-in container touched.
    """
    out = GEN / "authentik-bootstrap.override.yml"
    try:
        if "authentik-bootstrap" not in _compiled_services():
            out.unlink(missing_ok=True)
            return None
        adir = REPO / BOOTSTRAP_INPUTS_DIR
        files = [adir / f for f in BOOTSTRAP_INPUTS] + sorted(
            f for f in (adir / "blueprints").glob("*.yaml") if f.name != GENERATED_BLUEPRINT)
        h = hashlib.sha256()
        for f in files:
            if f.is_file():
                h.update(f.relative_to(REPO).as_posix().encode("utf-8") + b"\0")
                h.update(f.read_bytes().replace(b"\r\n", b"\n") + b"\0")   # CRLF checkouts hash alike
        body = ("# GENERATED by reconcile.compose_files() — do not edit.\n"
                "# The digest of what authentik-bootstrap runs and of the committed blueprints it applies\n"
                "# (bootstrap.sh, outpost-ready.py, blueprints/*.yaml but the compiled one). It only exists\n"
                "# so compose recreates the container when they change.\n"
                "services:\n"
                "  authentik-bootstrap:\n"
                "    labels:\n"
                f"      bbox.bootstrap-inputs: {h.hexdigest()[:16]}\n")
        # Written only on change: this runs on every dc call, and a rewrite each time would churn mtimes.
        if not out.exists() or out.read_text(encoding="utf-8") != body:
            out.write_text(body, encoding="utf-8", newline="\n")
        return out
    except Exception:
        return out if out.exists() else None       # unreadable inputs / read-only .generated: the last good overlay


def _effective_cpu_budget():
    """The CPU overlay restricted to services the compiled set still declares.

    The overlay is rendered at bring-up (scripts/perf-profile-apply) from the apps' compose files,
    and an app's compose can change afterwards. 2026-09-30 16:33: the Plane session removed its
    `plane-mq` service; the overlay still carried `plane-mq: {deploy: …}`, and because compose
    merges this file LAST, a service with a `deploy` and no image made the WHOLE project invalid
    ("service plane-mq has neither an image nor a build context") — every dc command, for every
    session, until somebody re-rendered. The join between "what the profile budgeted" and "what
    exists now" belongs here, where the -f list is assembled: drop the blocks that name no service
    and hand compose the result, written beside the overlay. The rendered overlay itself stays as
    perf-profile-apply wrote it, so gate G65's header check keeps reading the real thing.
    """
    src = GEN / "cpu-budget.yml"
    out = GEN / "cpu-budget.effective.yml"
    try:
        overlay = yaml.safe_load(src.read_text(encoding="utf-8")) or {}
        have = _compiled_services()
        services = overlay.get("services") or {}
        kept = {k: v for k, v in services.items() if k in have}
        dropped = sorted(set(services) - set(kept))
    except Exception:
        return src                                  # unreadable: the overlay as rendered, as before
    if not dropped:
        return src
    body = ("# GENERATED by reconcile.compose_files() from cpu-budget.yml — do not edit.\n"
            "# Dropped — no such service in the compiled set any more: " + ", ".join(dropped) + "\n"
            + yaml.safe_dump({"services": kept}, sort_keys=True, allow_unicode=True))
    # Written only on change: this runs on every dc call, and a rewrite each time would churn mtimes.
    # newline="\n" for the same reason as every other writer in this file (CRLF-hosted checkouts).
    try:
        if not out.exists() or out.read_text(encoding="utf-8") != body:
            out.write_text(body, encoding="utf-8", newline="\n")
    except OSError:
        return src                                  # cannot write .generated: the overlay as rendered
    return out


def required_by(app_id, cat, state):
    """The ENABLED apps that cannot run without `app_id` — directly, or through a provider of theirs.

    Asked of the resolver itself: `resolve(roots=[one app])` is "that app and whatever it needs",
    so "required" here is exactly the rule that keeps an app's services compiled while its own line
    says disabled. A second reading of `use:` written for this question would be a second rule.
    """
    out = []
    for aid in sorted(enabled_ids(state, cat)):
        if aid == app_id or aid not in cat:
            continue
        order, _diags = resolve(cat, state, roots=[aid])
        if app_id in order:
            out.append(aid)
    return out


def compose_services(app, mounting=None):
    """The compose SERVICE names an app's own compose file declares (services: keys only) — all of
    them, or with `mounting` only the ones that mount something at that path in the container.

    Volumes and networks are top-level siblings of `services:` in the same file, so this parses
    the YAML rather than grepping — a grep for '^  name:' also returns `traefik-network` and
    `n8n_storage`, which are not startable services.
    """
    comp = app.get("compose")
    if not comp:
        return []                      # kind: blueprint/library — declares no containers
    p = app["_dir"] / comp
    try:
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        sys.exit(f"FATAL {p.relative_to(REPO)}: {e}")
    services = doc.get("services") or {}
    if mounting is None:
        return list(services.keys())
    return [name for name, svc in services.items()
            if any(mounting in str(v) for v in ((svc or {}).get("volumes") or []))]


def lane_services(cat, order, exclude=()):
    """Compose services for a resolved closure, in dependency order, minus an explicit trim.

    This exists so a CI lane stops hand-maintaining `SERVICES:`. A hand-written list is a SECOND
    source of truth for "what does this lane need", and it drifts the moment an app gains a
    service: indox has required the `drive` capability all along, but the workflow's hand-written
    list never gained `drive`, so the lane started without it and every suite died on the first
    drive call. Deriving inverts the failure mode — you can still trim deliberately (--exclude,
    which is reviewable in the diff), but you can no longer FORGET to add.

    An exclude naming a service that does not exist is reported on stderr rather than ignored.
    The whole point of --exclude is that a trim stays VISIBLE, and a silently-dropped entry is
    the opposite: a typo, or a service that has since been renamed or removed, leaves the lane
    quietly running something the author believed it had excluded. This is not fatal — a stale
    entry is harmless in itself, and failing the build over one would make removing a service a
    two-repo dance — but it must not be silent.
    """
    drop, out = set(exclude), []
    known = set()
    for aid in order:
        for s in compose_services(cat[aid]):
            known.add(s)
            if s not in drop and s not in out:
                out.append(s)
    stale = sorted(drop - known)
    if stale:
        print(f"warning: --exclude names {len(stale)} service(s) that do not exist: "
              f"{', '.join(stale)}", file=sys.stderr)
    return out


# ── routing -> traefik/homepage labels ────────────────────────────────────────
def base_url_env(app_id):
    """machine -> MACHINE_BASE_URL ; any-concurrency -> ANY_CONCURRENCY_BASE_URL."""
    return app_id.upper().replace("-", "_") + "_BASE_URL"


def en_name(v, fallback):
    """A manifest's `title` is `{he, en}`; a layer-3 `sso.display_name` is one string. One name out."""
    if isinstance(v, dict):
        return v.get("en") or v.get("he") or fallback
    return v or fallback


COMMITTED_AUTHENTIK_BP = REPO / "platform-base/authentik/blueprints/deployment-apps.yaml"


def committed_sso_estate():
    """(host variables, provider slugs) the COMMITTED authentik blueprint already owns.

    Two facts, both READ from that file instead of restated here:
      * `!Env [<NAME>_BASE_URL, <default>]` — a host variable that blueprint hands to one of its own
        providers, i.e. a host whose identity record is the base estate's to keep;
      * `id: provider-<slug>` — a provider id that is already taken, so emitting a second entry with
        that id would make the generated blueprint collide instead of extend it.
    """
    try:
        txt = COMMITTED_AUTHENTIK_BP.read_text(encoding="utf-8")
    except OSError:
        return {}, set()
    vars_ = {m.group(1): m.group(2).strip()
             for m in re.finditer(r"!Env \[([A-Z0-9_]+_BASE_URL),\s*([^\]]+)\]", txt)}
    return vars_, set(re.findall(r"^  - id: provider-(\S+)", txt, re.M))


def published_hosts(cat, order):
    """{host variable: routed host} for every ENABLED app that publishes a host behind SSO.

    Separate from `sso_providers` because the question is different: that one asks "which provider
    must this compiler emit" (skipping hosts the committed blueprint owns), while the authentik
    container needs the variable of EVERY host here — including the ones the base blueprint resolves
    itself, because its own default is the `.localhost` twin and this is the host traefik routes.
    """
    hosts = {}
    for aid in order:
        a = cat[aid]
        for r in (a.get("routing") or []):
            if r.get("auth") != "sso":
                continue
            s = dict(r.get("sso") or {})
            if a.get("layer") == 3 and not s:
                continue
            var = s.get("base_url_env") or r.get("url_env") or base_url_env(aid)
            hosts[var] = f"{r.get('host') or aid}.${{DEPLOYMENT_DOMAIN:-localhost}}"
    return hosts


def sso_host_env(cat, order):
    """{host variable: what it falls back to when this office's .env does not set it}.

    (a) the COMMITTED blueprint's own — the base estate it owns (console, connections, machine,
    traefik, apps, any-concurrency), each with the default that file states. (b) every host an
    ENABLED app publishes behind SSO — from published_hosts(), which is the same rule the routers
    are labelled from, so the host a provider is given and the host traefik routes cannot drift
    apart. The routing-derived host wins over the blueprint's `.localhost` default: the host that is
    actually routed is the one an identity must know.

    Two renders ask. The sign-in containers' environment takes the variables of (a) from here —
    the committed file resolves them with `!Env`, so they have to exist in the container that
    applies it. And every provider's host on this machine is resolved from here (`_env_here`).
    """
    pairs = dict(committed_sso_estate()[0])
    pairs.update(published_hosts(cat, order))
    return pairs


def _here(text):
    """`text` with every `${NAME}` / `${NAME:-default}` in it resolved from this machine's .env."""
    text = text or ""
    for _ in range(20):                                  # bounded, like _envfile_value's own loop
        m = _ENV_REF.search(text)
        if not m:
            break
        text = text[:m.start()] + (_envfile_value(m.group(1)) or m.group(2) or "") + text[m.end():]
    return text


def _env_here(name, default, host_env):
    """What a blueprint's `!Env [name, default]` IS in the container that applies it, on this machine:
    this office's `.env`, else the fallback the compiler compiles onto that container
    (`sso_host_env`), else the blueprint's own default — compose's `NAME=${NAME:-fallback}`."""
    return _here(_envfile_value(name) or host_env.get(name) or default or "")


def _host_of(url):
    """`host[:port]` of a URL or of a bare host — the key authentik's outpost files a provider under."""
    return str(url or "").split("//", 1)[-1].split("/", 1)[0].strip().lower()


def sso_host_here(expr, host_env):
    """The `host[:port]` a provider's `external_host` IS on this machine — "" when it cannot be told.

    `expr` is the blueprint's own spelling with its tags stripped: a literal URL, or the
    `[format, argument…]` of a `!Format` whose arguments are literals and the `[NAME, default]` of
    an `!Env`. The scheme plays no part: the outpost files a provider under its host alone.
    """
    if isinstance(expr, list):
        args = [_env_here(str(a[0]), str(a[1]) if len(a) > 1 else "", host_env)
                if isinstance(a, list) and a else _here(str(a)) for a in expr[1:]]
        try:
            expr = str(expr[0]) % tuple(args) if expr else ""
        except (TypeError, ValueError):       # a format this compiler does not know how to fill
            return ""
    return _host_of(expr) if "//" in str(expr or "") else ""


def console_framed_host(cat, host):
    """`<host>.<console host>` — the address the shell DERIVES for an app it frames on its own host.

    The console's `externalUrl()` builds `<host>.<location.hostname>`, and that nesting is a
    `.localhost` rule: on an unregistered TLD the site is the LAST TWO LABELS, so `plane.localhost`
    is a different site from `console.localhost` and only `plane.console.localhost` is same-site with
    the console's session cookie. The console's own host is read from its manifest and the domain
    from this machine's `CONSOLE_BASE_URL` — the same value the console's own routers are rendered
    from, so the frame and the console stand or fall together.
    """
    routes = (cat.get("console") or {}).get("routing") or []
    console_host = (routes[0].get("host") if routes else "") or "console"
    origin = (_envfile_value("CONSOLE_BASE_URL") or "").split("//", 1)[-1].split("/", 1)[0]
    if not origin:
        origin = f"{console_host}.{_envfile_value('DEPLOYMENT_DOMAIN') or 'localhost'}"
    return f"{host}.{origin.split(':', 1)[0]}"


def _console_port() -> str:
    """The port a browser on the HOST reaches this office's edge on, or "" when it is the scheme's own.

    Read from `CONSOLE_BASE_URL`, and asked in one place because two renders must agree on it: the
    host a remote app's provider is registered under (`serve.sso_hosts`) and the `Origin` its router
    recognises as that app's own page (`serve.render`).
    """
    tail = (_envfile_value("CONSOLE_BASE_URL") or "").split("//")[-1]
    return tail.rsplit(":", 1)[1] if ":" in tail else ""


def _own_route_hosts(app_id, r):
    """The hosts one routing entry's own routers already match on THIS machine.

    traefik strips the request's port before comparing, so `<APP>_BASE_URL=plane.localhost:8080`
    matches `Host(plane.localhost)`; the `-local` twin always matches `<host>.localhost`.
    """
    val = (_envfile_value(r.get("url_env") or base_url_env(app_id)) or "").strip()
    hosts = {f"{r.get('host') or app_id}.localhost"}
    if val:
        hosts.add(val.split("//", 1)[-1].split("/", 1)[0].split(":", 1)[0])
    return hosts


def external_modules(cat, order):
    """[(app_id, routing entry, module)] for every app the shell FRAMES on its own host."""
    out = []
    for aid in order:
        for r in (cat[aid].get("routing") or []):
            m = r.get("module") or {}
            if m.get("external") and r.get("host"):
                out.append((aid, r, m))
    return out


def framed_sso_entries(cat, order):
    """Identity records for the host the shell frames an `external` app on — `(aid, sso block, host)`.

    A framed app has exactly ONE address, the one `externalUrl()` derives, and a host the outpost was
    never registered with answers 404 while the router looks healthy — measured 2026-09-30, the frame
    came up empty and nothing in the access log said why.

    Only the `.localhost` engine needs this. On a real domain every app already sits BESIDE the
    console (`plane.<domain>` / `console.<domain>`) — that IS one site — so the app's own `<BASE_URL>`
    is the framed address verbatim, and the provider emitted for its declared host already covers it.

    Two forms on `.localhost`, because the browser's own origin decides which one it derives:
      * `<host>.<console host>`          — a browser that reaches this edge PORT-LESS, which is the
        office browser: browser42's `localhost-forward.py` serves loopback :80 and nothing else;
      * the same host WITH the console's port — a browser on the host, where the edge is on :8080.
    The ported form is emitted only when the app's own `<BASE_URL>` does not already resolve to that
    host, because one host with two proxy providers leaves the outpost unable to pick between them.
    """
    if (_envfile_value("DEPLOYMENT_DOMAIN") or "localhost") != "localhost":
        return []
    console_origin = (_envfile_value("CONSOLE_BASE_URL") or "")
    port = console_origin.split("//")[-1].rsplit(":", 1)[1] if ":" in console_origin.split("//")[-1] else ""
    out = []
    for aid, r, m in external_modules(cat, order):
        if r.get("auth", "sso") != "sso":
            continue
        s = dict(r.get("sso") or {})
        slug = s.get("slug") or aid
        name = s.get("display_name") or en_name(cat[aid].get("title"), aid)
        framed = console_framed_host(cat, r["host"])
        # THE NAME IS THE PROVIDER'S IDENTITY, so a framed host needs a name of its own. The renderer
        # writes `<display_name> Provider` into `identifiers.name`, and authentik resolves an entry by
        # that name: two entries sharing it collapse into ONE provider row, and the second application
        # is then refused ("Application with this provider already exists") because a proxy provider
        # belongs to exactly one application. `ak apply_blueprint` fails, and bootstrap.sh treats that
        # as fatal (`|| exit 1`) — so the sentinel container crash-looped (measured 2026-10-05 on the
        # MacBook office: 262 restarts), never minted the probe token /tmp/outpost-token, and every
        # `bbox run` then read "the host list cannot be determined" as "the outpost is stale",
        # restarted authentik-server, waited four minutes and printed "EVERY gated surface is down"
        # over a working SSO. The local twin is disambiguated the same way, at the point it is
        # rendered (`display_name + " Local"`); this is that rule for the frame.
        if port:
            own = external_origin(aid, r, m) or ""
            if own.split("//", 1)[-1].split(":", 1)[0] != framed:
                out.append((aid, {"slug": f"{slug}-frame-port", "display_name": f"{name} Frame Port",
                                  "host_expr": frame_host_expr(f"{framed}:{port}")}, framed))
        out.append((aid, {"slug": f"{slug}-frame", "display_name": f"{name} Frame",
                          "host_expr": frame_host_expr(framed)}, framed))
    return out


def framed_hosts(cat, order):
    """{app id: the host the shell frames it on} — framed_sso_entries(), asked per app."""
    return {aid: host for aid, _sso, host in framed_sso_entries(cat, order)}


def frame_host_expr(host):
    """The `external_host` a framed host's provider carries — a literal, not an `!Env` lookup.

    No variable in this office's `.env` carries the framed host on a machine that does not already
    name it, and inventing one would put the host in two places. The scheme still follows
    AUTH_PROTOCOL, so the same blueprint is right on an http laptop and on an https office.
    """
    return f'!Format ["%s://%s", !Env [AUTH_PROTOCOL, http], "{host}"]'


def sso_providers(cat, order):
    """[(app_id, sso block, routed host)] — every SSO provider THIS compiler has to emit.

    A layer-3 app declares its provider in its own manifest (`routing[].sso`). A layer 1-2 app has no
    such block, and its provider is normally committed in the base blueprint — but when the committed
    file does not own that host, publishing it with `auth: sso` and no provider is precisely the
    "traefik routes it, the identity layer 404s it" defect (measured on vps1, 2026-09-30: notifications'
    `alerts-svc`, apitools' public host). So the compiler emits the same provider pair the blueprint
    would have hand-written, and ownership is decided by reading that file — never by naming apps here.
    """
    owned_vars, owned_slugs = committed_sso_estate()
    out = []
    for aid in order:
        a = cat[aid]
        for r in (a.get("routing") or []):
            if r.get("auth") != "sso":
                continue
            s = dict(r.get("sso") or {})
            layer3 = a.get("layer") == 3
            if layer3 and not s:
                continue            # a layer-3 host declared without a provider block: not ours to invent
            host = r.get("host") or aid
            var = s.get("base_url_env") or r.get("url_env") or base_url_env(aid)
            slug = s.get("slug") or aid
            if not layer3:
                if var in owned_vars or slug in owned_slugs:
                    continue        # the committed blueprint already registers this host
                # A base app titles itself `{he, en}` (a layer-3 app's `sso.display_name` is one
                # string), so normalize — the other providers here are English, and a name is not
                # worth a branch in the emitter.
                s = {"slug": slug,
                     "display_name": s.get("display_name") or en_name(a.get("title"), slug),
                     "base_url_env": var,
                     "default_host": f"{host}.localhost",
                     "local_twin": True, **s}
            out.append((aid, s, host))
    # …and the host an `external` app is FRAMED at, which is a host of its own (see the function).
    out += framed_sso_entries(cat, order)
    return out


def routing_labels(app_id, r, framed=""):
    """Emit the exact label set the platform's edge convention requires.

    Three routers per host (Runtipi's 'declare intent, platform emits labels'):
      <name>-local  : Host(<host>.localhost) on :web        — the dev/local entrypoint
      <name>-http   : Host(${<APP>_BASE_URL}) on :web
      <name>-https  : same host on :websecure + TLS via myresolver
    auth:sso attaches the authentik forwardAuth middleware to the browser-facing routers
    (local + https), matching the established convention.
    """
    svc = r.get("service") or app_id
    name = r.get("name") or app_id            # traefik router/service base name
    host, port = r["host"], r["port"]
    # Fall back to <host>.<DEPLOYMENT_DOMAIN> when <APP>_BASE_URL is unset, so a NEW app routes
    # without also needing a matching line in .env.ex. An explicit var still wins, so every app
    # that already has one renders byte-identically. Without the fallback an unset var rendered
    # Host() empty, which traefik treats as malformed and drops the WHOLE container's routers —
    # the app 404s even though its -local rule is correct.
    # `url_env` is per-ROUTING-ENTRY, because one app may publish more than one host (git publishes
    # its own panel AND the local forge's UI). Falling back to the app-level <APP>_BASE_URL keeps
    # every single-host app byte-identical: this is an addition to the convention, not a change of it.
    env = traefik_host(r.get("url_env") or base_url_env(app_id), host + ".${DEPLOYMENT_DOMAIN:-localhost}")
    auth = r.get("auth", "sso")
    # `basic` is in the schema's enum but no basic-auth middleware exists anywhere in this platform,
    # so it fell through the `auth == "sso"` test below and published an app with NO authentication.
    # A gap between what the schema permits and what the emitter implements must fail loudly here,
    # not resolve to "open" — that is the same failure mode as an unvalidated typo, just spelled
    # legally. Implement the middleware or drop it from the enum; do not let it compile.
    if auth not in ("sso", "none"):
        raise SystemExit(
            f"{app_id}: routing auth '{auth}' is declared in the schema but not implemented by the "
            f"label emitter — it would publish an UNAUTHENTICATED route. Use 'sso' or 'none'.")
    L = ["traefik.enable=true"]

    def router(suffix, rule, entry, tls=False, mw=False):
        p = f"traefik.http.routers.{name}-{suffix}"
        L.append(f"{p}.rule={rule}")
        L.append(f"{p}.entrypoints={entry}")
        if tls:
            L.append(f"{p}.tls=true")
            L.append(f"{p}.tls.certresolver=myresolver")
        L.append(f"{p}.service={svc}")
        if mw and auth == "sso":
            # authentik@file, NOT a bare `authentik`. The middleware is defined in traefik's FILE
            # provider (platform-base/traefik/config/authentik-forwardauth.yaml), and a bare name on
            # a docker-provider router resolves to `authentik@docker` — which is exactly the bug:
            # label-defined middlewares only exist while authentik-server is in traefik's snapshot,
            # and traefik DISCARDS any router whose middleware it cannot resolve. Every SSO-gated
            # host then serves a bare 404 while the stack reports healthy.
            L.append(f"{p}.middlewares=authentik@file")

    router("local", f"Host(`{host}.localhost`)", "web", mw=True)
    # SECURITY: the -http router historically carried no auth middleware, on the assumption that
    # ${APP}_BASE_URL is a public domain distinct from <host>.localhost. On a *.localhost
    # deployment (DEPLOYMENT_DOMAIN=localhost) it resolves to the SAME host as -local, and traefik
    # may serve the UNPROTECTED one — silently bypassing SSO. Auth must never depend on which of
    # two identical rules traefik happens to pick, so the plain-http router is gated too.
    router("http", f"Host(`{env}`)", "web", mw=True)
    router("https", f"Host(`{env}`)", "websecure", tls=True, mw=True)
    # The host the shell FRAMES this app at (`module.external`) is a host of its own — the nested one
    # on a `.localhost` edge — and a framed host that no router matches is a 404 nobody can explain.
    # Emitted only when this app's own host variable does not already route it (a laptop `.env` that
    # names the nested host itself), so one host never gets two identical rules.
    if framed and framed not in _own_route_hosts(app_id, r):
        router("frame", f"Host(`{framed}`)", "web", mw=True)
    L.append(f"traefik.http.services.{svc}.loadbalancer.server.port={port}")

    return L


def console_passthrough_labels(app_id, r, console_r, console_app=None):
    """Compile direct edge routes for embedded transports the console's WSGI proxy cannot carry.

    The app declares only its relative endpoint. The platform owns the console hosts, Authentik
    boundary, mount prefix and Traefik mechanics, so adding another websocket app never requires
    app-specific code in the console or handwritten edge labels in the app's compose file.
    """
    module = r.get("module") or {}
    passthroughs = module.get("passthrough") or []
    if not passthroughs:
        return []
    if not module.get("embed", True):
        raise SystemExit(f"{app_id}: module.passthrough requires module.embed=true")
    if r.get("auth", "sso") != "sso":
        raise SystemExit(f"{app_id}: console passthrough must inherit auth:sso")

    alias = module.get("alias")
    if not alias:
        raise SystemExit(f"{app_id}: module.passthrough requires module.alias")
    svc = r.get("service") or app_id
    port = r["port"]
    console_host = console_r["host"]
    console_env = traefik_host(base_url_env("console"), console_host + ".${DEPLOYMENT_DOMAIN:-localhost}")
    labels = ["traefik.enable=true"]

    # A ROOT mount (module.passthrough[].mount = root, owner-approved 2026-09-17 for bina-ds) claims
    # part of the console's own URL space: a third-party client that addresses /api and /plugins at
    # the origin root cannot live behind the /a/<alias> rewriting proxy. The shell's own routes are
    # carved out mechanically from the console's declared `reserved_paths`, so an app taking over
    # /api/<x> can never shadow /api/modules — and never has to know the shell's route table.
    reserved = [rp for rp in ((console_app or {}).get("reserved_paths") or []) if rp != "/a"]
    reserved_rule = ""
    if reserved:
        alternatives = "|".join(re.escape(rp.lstrip("/")) for rp in reserved)
        reserved_rule = f" && !PathRegexp(`^/({alternatives})(/|$)`)"

    for index, spec in enumerate(passthroughs):
        route_name = f"{app_id}-console-{spec['transport']}-{index}"
        root_mount = spec.get("mount", "alias") == "root"
        mount = spec["path"] if root_mount else f"/a/{alias}{spec['path']}"
        matcher = "PathPrefix" if spec.get("match", "exact") == "prefix" else "Path"
        rule_path = f"{matcher}(`{mount}`)" + (reserved_rule if root_mount else "")
        middlewares = []
        if not root_mount and spec.get("strip_mount_prefix", True):
            strip_name = f"{route_name}-strip"
            labels.append(f"traefik.http.middlewares.{strip_name}.stripprefix.prefixes=/a/{alias}")
            middlewares.append(strip_name)
        middlewares.append("authentik@file")

        def router(suffix, host, entrypoint, tls=False):
            key = f"traefik.http.routers.{route_name}-{suffix}"
            labels.append(f"{key}.rule=Host(`{host}`) && {rule_path}")
            labels.append(f"{key}.entrypoints={entrypoint}")
            labels.append(f"{key}.priority=100")
            if tls:
                labels.append(f"{key}.tls=true")
                labels.append(f"{key}.tls.certresolver=myresolver")
            labels.append(f"{key}.service={svc}")
            labels.append(f"{key}.middlewares={','.join(middlewares)}")

        router("local", f"{console_host}.localhost", "web")
        router("http", console_env, "web")
        router("https", console_env, "websecure", tls=True)

    labels.append(f"traefik.http.services.{svc}.loadbalancer.server.port={port}")
    return labels


def render_broker(cat, order):
    """Compile every app's `broker` block into ONE overlay that cuts those apps over to the
    credential broker.

    What the overlay does per app, and why each line is there:

      entrypoint  wrap the app's command in platform-base/connections/inject.sh, which proves the
                  container's identity to the broker, receives ONLY the connections this app's
                  `connections[]` declares, exports them and execs the original command.
      environment blank the named secrets. This is the entire point: after this render the value is
                  absent from `docker inspect`, absent from the container's environ, and cannot be
                  read by anything that gets a shell in the container after boot. Before it, one
                  `docker exec` yielded every credential the app held, permanently and silently.
      depends_on  connections must be HEALTHY first. Fail-closed is correct here — a consumer that
                  boots without its secrets fails later, somewhere else, with a worse error.
      volumes     the injector itself, read-only.

    Written as an overlay rather than into each app's compose because the declaration belongs to the
    app (app.json) while the mechanism belongs to the platform: an app author says "these two env
    vars are secrets and here is my command", and never has to know the injector's path, the broker's
    URL or the identity header."""
    svcs = {}
    for aid in order:
        b = cat[aid].get("broker")
        if not b:
            continue
        svc = b.get("service") or (cat[aid].get("routing") or [{}])[0].get("service") or aid
        env = [f"{b.get('url_env', 'CONN_URL')}=http://connections:8990",
               f"CONN_SERVICE={svc}"]
        # `KEY=` (empty) beats `KEY` (inherit): an entry without `=` re-imports the value from the
        # host environment, which would silently undo the whole cutover on a machine whose shell
        # happens to export it.
        env += [f"{k}=" for k in sorted(b.get("blank_env") or [])]
        svcs[svc] = {
            "depends_on": {"connections": {"condition": "service_healthy"}},
            "volumes": ["./platform-base/connections/inject.sh:/inject.sh:ro"],
            "environment": env,
            "entrypoint": list(b["entrypoint"]),
        }
    if not svcs:
        return None
    body = yaml.safe_dump({"services": svcs}, sort_keys=True, allow_unicode=True,
                          default_flow_style=False)
    return ("# GENERATED by platform/manager/reconcile.py — DO NOT EDIT.\n"
            "# Credential-broker cutovers, compiled from each app.json's `broker` block. Each app\n"
            "# below runs with its secrets BLANK in the environment; they are leased at boot from\n"
            "# connections, which identifies the container over the docker socket and grants only\n"
            "# what that app's own connections[] declares. Every grant is logged\n"
            "# (GET /api/broker/audit). Apps without a `broker` block are untouched.\n"
            "#\n"
            "# Host paths are repo-root-relative: every consumer invokes compose with\n"
            "# --project-directory <repo> (scripts/dc / dcx), so relative binds resolve there.\n"
            + body)


def render_routing(cat, order):
    """Generated compose override: routing labels, plus env each app contributes to a base app.

    The `contributes.env` half exists because of the layering rule. `any-concurrency` needs
    APITOOLS_CONTAINER to tail apitools' logs, and `console` needs APITOOLS_URL to proxy it — but
    a layer-2 base app may not name a layer-3 app, so those lines cannot live in the base app's
    compose. The consuming app declares them instead and they are merged onto the base service
    here. The RENDERED config is identical either way; only the source of the declaration moves,
    which is why this costs nothing at G1."""
    svcs = {}
    console_routes = (cat.get("console") or {}).get("routing") or []
    console_r = console_routes[0] if console_routes else None
    for aid in order:
        a = cat[aid]
        for r in a.get("routing", []):
            passthroughs = (r.get("module") or {}).get("passthrough") or []
            if passthroughs:
                if not console_r:
                    raise SystemExit(f"{aid}: module.passthrough requires the console app")
                svc = r.get("service") or aid
                svcs.setdefault(svc, {}).setdefault("labels", []).extend(
                    console_passthrough_labels(aid, r, console_r, cat.get("console")))
            if not r.get("emit_labels", True):
                continue  # app carries its own labels in its own compose — nothing to emit
            svc = r.get("service") or aid
            framed = (console_framed_host(cat, r["host"])
                      if (r.get("module") or {}).get("external") and r.get("host")
                      and (_envfile_value("DEPLOYMENT_DOMAIN") or "localhost") == "localhost"
                      and r.get("auth", "sso") == "sso" else "")
            svcs.setdefault(svc, {}).setdefault("labels", []).extend(
                routing_labels(aid, r, framed))

    # A contribution lands only on an app that is IN the compiled set. Installed-but-disabled is not
    # enough: the overlay would declare a service no compose file defines ("has neither an image nor
    # a build context"), and the WHOLE project stops parsing — measured 2026-10-02 on the MacBook,
    # where disabling any-concurrency (bina-ds contributes SPAN_* env to it) broke every `dc` call.
    enabled = set(order)
    for aid in order:
        contrib = cat[aid].get("contributes") or {}
        for base, env in (contrib.get("env") or {}).items():
            if base not in cat or base not in enabled:
                continue                       # not installed, or installed and switched off
            tgt = (cat[base].get("routing") or [{}])[0].get("service") or base
            bucket = svcs.setdefault(tgt, {}).setdefault("environment", [])
            for k, v in sorted(env.items()):
                bucket.append(f"{k}={v}")
        for base, vols in (contrib.get("volumes") or {}).items():
            # "<app>" targets that app's routing service; "<app>:<service>" targets one named
            # service of it. The second form exists because a base app can be several containers
            # that all need the same mount: n8n runs the scheduler AND two workers, and a workflow
            # can execute on any of them, so a corpus mounted only on the routing service is
            # present or absent depending on which worker picked the job. The app id stays in the
            # key so an uninstalled or misspelled target is still skipped rather than silently
            # creating a service.
            base_id, _, svc_name = base.partition(":")
            if base_id not in cat or base_id not in enabled:
                continue                       # not installed, or installed and switched off
            tgt = svc_name or (cat[base_id].get("routing") or [{}])[0].get("service") or base_id
            svcs.setdefault(tgt, {}).setdefault("volumes", []).extend(vols)

    # ── identity: the hosts the COMMITTED sign-in blueprint resolves ─────────────────────────────
    # That file is the same on every machine, so it spells the host of each base app it owns as
    # `!Env [<NAME>_BASE_URL, <default>]` — resolved WHEN THE BLUEPRINT IS APPLIED, from the
    # environment of the authentik container that applies it, not from .env. So each such variable
    # has to be IN those containers, falling back to the host that is routed here (sso_host_env)
    # rather than to the file's own `.localhost` default.
    #
    # It used to be a hand-written list in platform-base/authentik/docker-compose.yml — three copies
    # of it, one per service — and a name listed there is the same fact in a second place. Read
    # from the blueprint instead: `!Env [NAME, default]` → `NAME=${NAME:-default}`. `*_BASE_URL`
    # only: AUTH_EXTERNAL_URL/AUTH_PROTOCOL are authentik's OWN config and its compose gives them a
    # smarter nested default than a blueprint can state. Gated on authentik being ENABLED: writing
    # environment onto a service that this machine does not run would add a container with no image
    # to the merged compose.
    #
    # ONLY those variables, and ONLY on the services that apply blueprints — the ones that mount
    # them. An installable app's host is not resolved in a container at all: it is written into the
    # generated blueprint as a literal (render_authentik says why). Compiling a variable for every
    # app onto every service of the sign-in app made each app switched on or off a change to the
    # configuration of the sign-in SERVER and of its DATABASE, which the next `bbox run` answered
    # by re-creating both (measured on hp-laptop, 2026-10-05: the worker left holding connections
    # to a database that had just been replaced).
    if "authentik" in order and "authentik" in cat:
        committed = committed_sso_estate()[0]
        env = [f"{k}=${{{k}:-{v}}}" for k, v in sorted(sso_host_env(cat, order).items())
               if k in committed]
        for svc in compose_services(cat["authentik"], mounting="/blueprints/custom"):
            if env:
                svcs.setdefault(svc, {}).setdefault("environment", []).extend(env)

    # ── the CATALOGUE plane: declared engine profiles ─────────────────────────────────────────────
    # `engine.profiles` in app.json is where an identity on a private engine is DECLARED (see
    # ai/context/app-engine-pattern.md §5). The app's own bootstrap reconciler is what creates the
    # profile and its vault instance, so all the compiler has to do is hand the app the declaration —
    # as JSON on an env var named after the app.
    #
    # Rendered here rather than written into each app's compose because it is DERIVED: a hand-written
    # `MAIL_ENGINE_PROFILES={"...json..."}` next to the `engine` block would be the same fact twice,
    # and the copy that drifts is the one nobody reads. The app's own routing service is the target
    # (mail -> mailapi), because the engine reconciler runs inside the service that owns the engine.
    for aid in order:
        eng = cat[aid].get("engine") or {}
        profs = eng.get("profiles")
        if not profs:
            continue
        tgt = (cat[aid].get("routing") or [{}])[0].get("service") or aid
        var = re.sub(r"[^A-Z0-9]", "_", aid.upper()) + "_ENGINE_PROFILES"
        svcs.setdefault(tgt, {}).setdefault("environment", []).append(
            var + "=" + json.dumps(profs, sort_keys=True, separators=(",", ":"),
                                   ensure_ascii=False))

    # The connection (account) plane. The console proxies /connections|/manifest|/readyz for every
    # app that DECLARES it implements platform-service.v1 — the console used to carry the map itself
    # (SVC_BASES = {"drive": "http://drive:8975", "mail": ...}), which is a layer-2 file naming
    # layer-3 apps AND a file you had to edit to add a fourth service. The capability already
    # carried the name and the endpoint; only the contract marker was missing, so nothing here is
    # new information — it just stops being duplicated into the base app.
    plat = {c["name"]: c["endpoint"]
            for aid in order for c in (cat[aid].get("capabilities") or [])
            if c.get("contract") == "platform-service.v1" and c.get("endpoint")}
    if plat and "console" in cat:
        tgt = (cat["console"].get("routing") or [{}])[0].get("service") or "console"
        svcs.setdefault(tgt, {}).setdefault("environment", []).append(
            "PLATFORM_SERVICES=" + json.dumps(plat, sort_keys=True, separators=(",", ":")))

    if not svcs:
        return None
    body = yaml.safe_dump({"services": svcs}, sort_keys=True, allow_unicode=True,
                          default_flow_style=False)
    return ("# GENERATED by platform/manager/reconcile.py — DO NOT EDIT.\n"
            "# Traefik + homepage labels from each app.json `routing`, plus the env each app\n"
            "# declares in `contributes.env` for a base app (the layering rule forbids the base\n"
            "# app from naming its layer-3 consumers).\n" + body)


# ── render ────────────────────────────────────────────────────────────────────
# ── the plan as an approvable artifact ────────────────────────────────────────
# `plan` printed a line and exited. There was nothing between "decide" and "apply" that a human
# could read, keep, or approve — so every apply was a fresh decision taken at apply time, and a
# review could only ever be of the code that would decide, never of the decision itself.
#
# OLM calls this an InstallPlan and gates it behind `installPlanApproval: Manual`; apt prints the
# partitioned plan and waits. Both exist because on a system where a bad apply costs real money,
# "what exactly is about to happen" must be inspectable BEFORE it happens.
#
# The input hash is the load-bearing part: applying a stale plan is worse than having no plan,
# because it looks deliberate. If the catalog or the desired state moved underneath, `apply` refuses.
PLANS = GEN / "plans"


def inputs_digest(cat, state):
    """A stable fingerprint of everything the resolution depends on."""
    h = hashlib.sha256()
    for aid in sorted(cat):
        a = cat[aid]
        h.update(aid.encode())
        h.update(json.dumps({k: v for k, v in sorted(a.items()) if not k.startswith("_")},
                            sort_keys=True, ensure_ascii=False, default=str).encode())
    h.update(json.dumps(state, sort_keys=True, ensure_ascii=False, default=str).encode())
    return h.hexdigest()[:16]


def write_plan(cat, state, order, diags):
    PLANS.mkdir(parents=True, exist_ok=True)
    digest = inputs_digest(cat, state)
    existing = sorted(int(f.stem) for f in PLANS.glob("*.yaml") if f.stem.isdigit())
    pid = f"{(existing[-1] + 1) if existing else 1:04d}"
    bindings = {k: (v.get("provider") if isinstance(v, dict) else v)
                for k, v in (state.get("bindings") or {}).items()}
    doc = {
        "plan": pid,
        "inputs_digest": digest,
        "apps": len(order),
        "start_order": list(order),
        "bindings": bindings,
        "services": lane_services(cat, order),
        "pulled_in": [m.split(":")[0] for lvl, m in diags
                      if lvl == "info" and "pulled in as provider" in m],
        "notes": [m for lvl, m in diags if lvl == "info"],
    }
    write(PLANS / f"{pid}.yaml", 
        yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
    for old in existing[:-19]:
        (PLANS / f"{old:04d}.yaml").unlink(missing_ok=True)
    return pid, digest


# ── generations: every render is archived so a bad apply can be undone ──────────
# Nix's insight is that the rendered configuration is a pure function of (catalog, state), so
# keeping the previous outputs costs almost nothing and buys real rollback. We copy rather than
# symlink-swap: symlinks are unreliable on Windows, and copying keeps `.generated/` itself the live
# path so every existing consumer (scripts/dc, the gates, CI) is untouched.
#
# Honest boundary, stated the way Nix states it: the rendered CONFIGURATION rolls back atomically.
# Docker volumes do not. Rolling back the compose files does not un-migrate a database.
GENS = GEN / "generations"
KEEP_GENERATIONS = 20
_GEN_SKIP = {"generations"}


def _gen_dirs():
    if not GENS.is_dir():
        return []
    return sorted((d for d in GENS.iterdir() if d.is_dir() and d.name.isdigit()),
                  key=lambda d: int(d.name))


def archive_generation():
    """Snapshot the CURRENT .generated/ before it is overwritten. Returns the new id, or None."""
    live = [c for c in GEN.iterdir() if c.name not in _GEN_SKIP] if GEN.is_dir() else []
    if not live:
        return None
    nxt = (int(_gen_dirs()[-1].name) + 1) if _gen_dirs() else 1
    dst = GENS / f"{nxt:04d}"
    dst.mkdir(parents=True, exist_ok=True)
    for c in live:
        (shutil.copytree if c.is_dir() else shutil.copy2)(c, dst / c.name)
    for old in _gen_dirs()[:-KEEP_GENERATIONS]:
        shutil.rmtree(old, ignore_errors=True)
    return dst.name


def restore_generation(gid):
    src = GENS / gid
    if not src.is_dir():
        sys.exit(f"FATAL no generation '{gid}' (see `reconcile.py generations`)")
    archive_generation()          # the state we are leaving is itself worth keeping
    for c in list(GEN.iterdir()):
        if c.name in _GEN_SKIP:
            continue
        shutil.rmtree(c, ignore_errors=True) if c.is_dir() else c.unlink()
    for c in src.iterdir():
        (shutil.copytree if c.is_dir() else shutil.copy2)(c, GEN / c.name)
    return gid



def render(cat, order, state):
    GEN.mkdir(exist_ok=True)
    # FIRST, before a single compose file is written: reconcile .env's derived identity with
    # BUSINESS_NAME. Everything rendered below emits `${DEPLOYMENT_DOMAIN:-localhost}`-shaped
    # expressions that compose resolves against .env, so the slug has to be correct in .env by
    # the time compose reads it — and this is the last code that runs before that.
    sync_identity()
    archive_generation()
    includes, migrated = [], []
    for aid in order:
        a = cat[aid]
        if a.get("compose"):
            rel = (a["_dir"] / a["compose"]).relative_to(REPO).as_posix()
            includes.append(rel); migrated.append(aid)

    # include paths resolve against the PROJECT DIRECTORY (always the repo root: reconcile
    # invokes compose with --project-directory <repo>), so they stay repo-root-relative.
    lines = [
        "# GENERATED by platform/manager/reconcile.py — DO NOT EDIT.",
        "# Source of truth: apps/*/app.json + platform.state.yaml",
        f"# migrated apps ({len(migrated)}): {', '.join(migrated) or '(none yet)'}",
        "",
        "include:",
        # The root compose.yml is the shared `traefik-network` declaration that EVERY service
        # attaches to — it is not the legacy lane, and it is unconditionally required.
        #
        # It used to be emitted only `if (REPO/"production/compose.yml").exists()`, a leftover of
        # the strangler migration. That coupled a REQUIRED include to the existence of a file that
        # is now an empty `include:` — so deleting that vestigial file (the obvious cleanup, and
        # what "the legacy lane is done" invites) would have silently dropped the shared network
        # from every render. The legacy lane is over (platform/legacy-capabilities.yaml is empty,
        # production/compose.yml includes nothing), so the gate is gone and this include stands on
        # its own meaning.
        "# shared external network (root compose.yml) — required by every service",
        "- compose.yml",
    ]
    for inc in includes:
        lines.append(f"- {inc}")

    write(GEN / "compose.yml", "\n".join(lines) + "\n")

    # Routing labels are an OVERLAY, not an include: `include` requires disjoint service sets
    # ("services.X conflicts with imported resource"), whereas -f layering merges. So the
    # canonical invocation is compose_files() below — always use it, never a bare -f compose.yml.
    routing = render_routing(cat, order)
    if routing:
        write(GEN / "routing.override.yml", routing)
    elif (GEN / "routing.override.yml").exists():
        (GEN / "routing.override.yml").unlink()

    # Removing an app's `broker` block (or the app) must REMOVE the cutover, not leave a stale
    # overlay wrapping a command that no longer exists — same unlink-on-empty rule as routing.
    brk = render_broker(cat, order)
    if brk:
        write(GEN / "connections.override.yml", brk)
    elif (GEN / "connections.override.yml").exists():
        (GEN / "connections.override.yml").unlink()

    render_glitchtip(cat, order)
    served, serrs = serve.plan(state, cat)
    if serrs:
        sys.exit("SERVE PLAN REFUSED:\n" + "\n".join(f"  - {e}" for e in serrs))
    render_serve(cat, served, framed_hosts(cat, order))
    render_registries(cat, order, served)
    render_agent_context(cat, order)
    render_authentik(cat, order, served)

    write(GEN / "resolved.json", json.dumps({
        "order": order, "migrated": migrated,
        "instances": state.get("instances", {}),
    }, indent=2, ensure_ascii=False))
    return migrated


def render_serve(cat, served, framed=()):
    """Write the reverse plane: the apps of OTHER offices, routed on this office's own edge.

    The module `serve` owns the decisions (what a `serve:` block means, what is refused, what a tile
    and a router look like); this function owns the ONE thing that is not a decision — where the
    compiled file goes. It goes into traefik's own bind-mounted config directory, exactly like the
    generated authentik blueprint goes into authentik's, because the file provider is the only place
    traefik accepts a service whose server is an address outside the engine: a docker LABEL carrying
    `loadbalancer.server.url` is rejected by traefik v3.3 with "port is missing" and takes the whole
    router down with it (measured on this deployment 2026-09-30 — see platform/manager/serve.py).

    Written into the repo, so it is gitignored compiled output like every other generated artifact —
    and it is written (or removed) on EVERY render, so un-declaring a `serve:` entry removes the
    route in the same breath as the tile.

    `framed` (framed_hosts) rides along for one router: the shell asks an app of THIS office that
    it frames on a host of its own the question it asks a remote one, and the answer is built once."""
    dest = REPO / "platform-base/traefik/config/zz-serve.yaml"
    aliases = GEN / "remote.override.yml"
    doc = serve.render(served, cat, domain=_envfile_value("DEPLOYMENT_DOMAIN") or "localhost",
                       console_port=_console_port(),
                       framed={f"{aid}-frame": host for aid, host in dict(framed).items()})
    if not doc:
        dest.unlink(missing_ok=True)
        aliases.unlink(missing_ok=True)
        return 0
    dest.write_text(doc, encoding="utf-8", newline="\n")
    # Every router above points at `http://<alias>.<office>:<port>` — a NETWORK ALIAS on the link
    # proxy, not the peer's tunnel address (which exists only inside the tunnel container's
    # namespace and is not routable from the edge's network). An alias can only be set when the
    # container is created, so it is a compose overlay; written and removed with the routes, in the
    # same breath, because a router to a name nobody resolves is a 502 with a healthy-looking stack.
    overlay = serve.render_aliases(served)
    if overlay:
        aliases.write_text(overlay, encoding="utf-8", newline="\n")
    else:
        aliases.unlink(missing_ok=True)
    return len(served)


def _office_apps(cat, order) -> dict:
    """The compiled registry row per enabled app — THE CATALOG SOURCE (`apps/dgo-extend/catalog.py`).

    Rendered here and not in the app for the reason every registry is: the app must not author the
    list of the office's own apps, or `office.apps.json` and `console.modules.yaml` become two lists
    of one fact that drift. A linked office's catalog is a projection of THIS file, so an app that is
    disabled here disappears from the peer's console in the same render that removes it from ours.

    What a row carries is only what a peer needs to reach and show the app:
      · `alias`/`name`/`name_en`/`icon`/`group`/`desc`/`order` — the tile;
      · `port` — the port the LINK must reach the app on (its routing port, i.e. the one that serves
        the UI a person opens);
      · `agent_api_port` — the SECOND door of an agent app, read from its own `capabilities[]`
        endpoint (DGO-32): a UI and an adapter, and a link that opens one and not the other leaves a
        CLI accepted by the firewall and answered by nobody;
      · `host` — the authority the app expects to be reached under (its `sso.default_host`), because
        every harness here refuses an authority it was never told about (measured, DGO-32);
      · `module`/`health` — how the peer frames it and what it can probe.
    """
    rows = []
    for aid in order:
        man = cat[aid]
        for r in (man.get("routing") or []):
            m = r.get("module") or {}
            alias = str(m.get("alias") or "").strip().lower()
            if not alias:
                continue            # a routing entry with no tile (apitools' labels) is not an app
            try:
                port = int(r.get("port"))
            except (TypeError, ValueError):
                continue
            row = {
                "app": aid, "alias": alias,
                "name": str(m.get("name") or (man.get("title") or {}).get("he") or aid),
                "name_en": str((man.get("title") or {}).get("en")
                               or m.get("name_en") or aid),
                "icon": str(m.get("icon") or "external"),
                "group": str(m.get("group") or "מרוחק"),
                "desc": str(m.get("desc") or ""),
                "order": m.get("order", 999),
                "port": port,
                # HOW A PEER MAY FRAME IT: under a path of its own console (`embedded`), or only on
                # a host of its own (`external`) — the app's own declarations decide (`_own_host_only`).
                # The MODULE ID travels with it because a link does: the office's task tool hands the
                # owner `#/m/<module id>/<inner route>`, and a peer that only knew the alias could not
                # resolve it (`#/m/project-pln/…` vs its own tile `plane.hp-laptop`), fell through to
                # the FIRST tile and opened the agent instead of the work item (the owner, 2026-10-09).
                "module": {"kind": "external" if _own_host_only(m) else "embedded",
                           "id": str(m.get("id") or aid),
                           "alias": alias,
                           "path": f"/a/{alias}/"},
                "health": "/healthz",
                # The compose service that ANSWERS on that port. It is not decoration and it is not
                # always the app's id: `indox` is served by `incoming-documents` and `mail` by
                # `mailview`, and a peer that connected to the app's id got `502` with an empty body
                # for exactly those two (measured 2026-10-02, the first full pass over a linked
                # office's apps: 13 of 15 answered, the two whose service differs from their id did
                # not). The link's door resolves a NAME, so the name has to cross the link.
                "service": str(r.get("service") or aid),
            }
            agent_port = _agent_door(man, port)
            if agent_port:
                row["agent_api_port"] = agent_port
            authority = str((r.get("sso") or {}).get("default_host") or "").strip().lower()
            if authority:
                row["host"] = authority
            elif r.get("host"):
                row["host"] = f"{r['host']}.localhost"
            rows.append(row)
    rows.sort(key=lambda x: (x.get("order", 999), x["alias"]))
    return {"generated_by": "platform/manager/reconcile.py",
            "source": "apps/*/app.json + platform-base/*/app.json (enabled only)", "apps": rows}


def _own_host_only(module: dict) -> bool:
    """Can a peer frame this app ONLY on a host of its own, never under a path of its console?

    Three declarations say so, and each is the app's own:
      · `external` — at home the shell already frames it on its own host;
      · `embed: false` — at home it is not framed at all (the console itself, n8n…);
      · a `passthrough` — it is embedded at home only because THIS edge also answers paths of the
        console's own origin on its behalf (bina-ds: `/api`, `/plugins`, `/assets` and a websocket;
        browser42: the websocket at `/websockify`).
    What they share: the app's browser code addresses the console's ORIGIN rather than a path under
    it — its page and assets from the root, or an absolute passthrough path — and a console has ONE
    origin, which belongs to that office's own apps. Published as embedded, two tiles of the MacBook
    on hp-laptop's console showed hp-laptop (measured 2026-10-05): בינה loaded its page from the Mac
    and listed hp-laptop's two conversations, not the Mac's 151 — what was typed there would have run
    on the wrong machine — and המרכז drew a console inside the console that listed hp-laptop's apps.
    And hp-laptop's דפדפן showed noVNC's static error screen on the MacBook, every asset under
    `/a/browser42.hp-laptop/app/…` empty and `/websockify` unrouted (measured 2026-10-09).
    """
    return (bool(module.get("external")) or module.get("embed", True) is False
            or bool(module.get("passthrough")))


def _agent_door(man: dict, ui_port: int) -> int:
    """The app's agent API port, or 0 — the port of its first capability endpoint that is not the UI.

    Read from the manifest rather than declared a second time: an app whose adapter listens on 3081
    publishes that in the capability a caller is supposed to use, and asking the manifest is what
    keeps one number in one place. A capability on the SAME port as the UI is the same door (many
    apps are), and publishing it as an agent API would render a duplicate rule for one listener.
    """
    for cap in (man.get("capabilities") or []):
        endpoint = str(cap.get("endpoint") or "")
        m = re.search(r":(\d{2,5})(?:/|$)", endpoint)
        if not m:
            continue
        port = int(m.group(1))
        if port != ui_port and 1 <= port <= 65535:
            return port
    return 0


#: The office column's value for a row that belongs to THIS office. `dgo-extend` gives this office
#: the id `local` until the owner names it (`converge.home_office`), and the column exists to say
#: WHICH office a row comes from — so a local row is `local`, never a blank that reads as unknown.
LOCAL_OFFICE = "local"


def remote_records(served) -> dict:
    """`{"remote.<office>.<alias>.json": record}` — the ONE per-app record of a remote app.

    Built from the validated `serve.plan` entries, and read by two consumers that must not drift: the
    registry writer below, and the app list the CLI and the app manager print (`app_rows`). A second
    builder would be a second answer to "which apps of another office does this office show".
    """
    current = {}
    for entry in (served or []):
        for app in entry["apps"]:
            tile = f"{app['alias']}.{entry['office']}"
            current[f"remote.{entry['office']}.{app['alias']}.json"] = {
                "id": tile,
                "app": app["app"],
                "alias": app["alias"],
                "name": app["name"],
                "name_en": app.get("name_en") or app["name"],
                "icon": app["icon"],
                "group": app["group"],
                "desc": app["desc"],
                "order": app["order"],
                "module": {"kind": "external", "host": tile, "path": app.get("module_path") or "/"},
                "health": app.get("health") or "/healthz",
                "port": app["port"],
                # The DOOR the UI is reached through (DGO-32), when the serving office published
                # one: `<alias>.<office>` resolves to the link proxy, and the door's port is where
                # the Host header picks this very app. Zero = a peer from before the door, and then
                # the app's own port is the door.
                "link_port": int(entry.get("link_port") or 0),
                "agent_api_port": app.get("agent_api_port"),
                "remote": {"office": entry["office"], "label": entry["label"],
                           "link": entry["link"], "address": entry["address"],
                           "commit": entry["commit"]},
            }
    return current


def app_rows(cat, order, served=None) -> list[dict]:
    """ONE list of the apps this office SHOWS: its own enabled apps AND the apps of linked offices.

    The owner's model is "apps just run where they run ... an app installed in both offices appears
    twice, once with the remote mark", so the list a person or an agent reads is one list with an
    office per row — not a local list plus a separate screen for everybody else's. Both columns are
    the compiler's own output: local rows from `_office_apps` (the compiled registry row) and remote
    rows from `remote_records` (what the routes and the tiles are rendered from too).

    TWO ROWS FOR ONE ALIAS IS THEREFORE THE CORRECT ANSWER, not a duplicate: `bina` here and
    `bina.macbook` there are different apps on different machines. `id` is what tells them apart —
    `<alias>` locally, `<alias>.<office>` remotely — and it is the same id the console's shell
    addresses a tile by, which is why a remote row may never be printed under the bare alias.

    Sorted by (order, alias, office) so the two rows of one alias land next to each other, and the
    console's own ordering survives.
    """
    rows = []
    for r in _office_apps(cat, order)["apps"]:
        rows.append({
            "id": r["alias"], "app": r["app"], "alias": r["alias"], "office": LOCAL_OFFICE,
            "name": r["name"], "name_en": r["name_en"], "icon": r["icon"], "group": r["group"],
            "desc": r["desc"], "order": r["order"], "port": r["port"],
            "api_port": r.get("agent_api_port") or None,
            "module": r["module"], "health": r["health"], "host": r.get("host") or "",
            # WHAT THIS ROW COSTS THE MACHINE (DGO-108): the app's own declared ceiling, the same
            # number G30 sums. It is what a person needs in front of them when deciding whether to
            # switch another app on — "4g here, 6g there" is the whole question, and until this
            # column the answer lived three files away in the manifest. Absent for an app that
            # never declared one: an empty cell, never a made-up zero.
            "mem": ((cat.get(r["app"]) or {}).get("resources") or {}).get("memory") or "",
            "remote": None,
        })
    for rec in remote_records(served).values():
        r = rec["remote"]
        rows.append({
            "id": rec["id"], "app": rec["app"], "alias": rec["alias"], "office": r["office"],
            "name": rec["name"], "name_en": rec["name_en"], "icon": rec["icon"],
            "group": rec["group"], "desc": rec["desc"], "order": rec["order"], "port": rec["port"],
            "api_port": rec.get("agent_api_port") or None,
            "module": rec["module"], "health": rec["health"],
            "host": rec["module"].get("host") or "", "remote": r,
        })
    rows.sort(key=lambda x: (x["order"], x["alias"], x["office"]))
    return rows


def print_app_rows(rows) -> None:
    """The list as a human reads it: alias, app, OFFICE, the two doors, and the name.

    `office` is the column the whole feature exists for — a person scanning this has to be able to
    tell "that one runs here" from "that one runs on the other machine" without opening anything.
    """
    head = ("alias", "app", "office", "ui", "api", "mem", "name")
    body = [[r["id"], r["app"], r["office"], str(r["port"]),
             str(r["api_port"] or "—"), r.get("mem") or "—", r["name"]] for r in rows]
    widths = [max(len(str(head[i])), *(len(b[i]) for b in body)) if body else len(head[i])
              for i in range(len(head))]
    print("  ".join(str(head[i]).ljust(widths[i]) for i in range(len(head))))
    print("  ".join("-" * widths[i] for i in range(len(head))))
    for b in body:
        print("  ".join(b[i].ljust(widths[i]) for i in range(len(head))))


def render_remote_entries(reg, served) -> int:
    """One `remote.<office>.<alias>.json` per remote app, and NO stale file left behind.

    This is the registry half of the reverse plane: the console's tile list is compiled
    (`console.modules.yaml`), and these files are the per-app record other surfaces read — the app
    manager's office column, the CLI, and an agent asking "what is `bina.macbook`". Written from the
    SAME validated entries as the routes, so a tile and its record cannot disagree.

    Stale files are removed by name, not by directory sweep: the directory is shared with the other
    registries, and a render that deletes a file it does not own is how one app's artifact disappears
    because another app's list got shorter.
    """
    current = remote_records(served)
    for name in current:
        write(reg / name, json.dumps(current[name], ensure_ascii=False, indent=2) + "\n")
    kept = 0
    for path in reg.glob("remote.*.json"):
        if path.name not in current:
            path.unlink()
        else:
            kept += 1
    return kept


def render_glitchtip(cat, order):
    """Emit the GlitchTip project list from the catalog.

    glitchtip is a LAYER-2 base app: it must not know its consumers by name. Its blueprint used
    to hardcode `my-docs`, `drive`, `mailview`, `apitools`… so uninstalling any of them left
    glitchtip provisioning an error project for a service that no longer existed — and it still
    listed `librechat` and `feature-validation`, both long since parked in attic/.

    Now each app declares `observability.sentry_platform` in its OWN manifest and this derives
    the list, so the set of projects is exactly the set of enabled apps that asked for one."""
    projects = []
    for aid in order:
        o = (cat.get(aid) or {}).get("observability")
        if not o:
            continue
        projects.append({"name": o.get("sentry_project", aid), "platform": o["sentry_platform"]})
    projects.sort(key=lambda p: p["name"])
    write(GEN / "glitchtip.projects.yml", 
        "# GENERATED by platform/manager/reconcile.py from each app's observability{} — DO NOT EDIT.\n"
        "# Source of truth: apps/*/app.json + platform-base/*/app.json\n"
        "projects:\n" + "".join(
            "  - { name: %-20s platform: %s }\n" % (p["name"] + ",", p["platform"]) for p in projects))
    return projects


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("verb", choices=["plan", "render", "up", "validate", "compose-files", "services",
                                     "required-by",
                                     "compose-services", "blueprints", "generations", "rollback",
                                     "apply", "enabled-apps", "set-state", "capability-provider",
                                     "serve-plan", "remote-get", "remote-set", "office-get", "office-set"])
    ap.add_argument("--capability", metavar="NAME",
                    help="capability-provider: the capability name to resolve")
    ap.add_argument("--app", metavar="ID", help="set-state: the app id to write")
    ap.add_argument("--state", metavar="DISPO", choices=list(DISPOSITIONS),
                    help="set-state: enabled | disabled | archived")
    ap.add_argument("--by", default="user", metavar="WHO",
                    help="set-state: provenance recorded with the entry (default: user)")
    ap.add_argument("--create", action="store_true",
                    help="set-state: append the entry if the app has none yet (install path)")
    ap.add_argument("--json", action="store_true",
                    help="plan: print one JSON document (apps, remote, plan) instead of the table. "
                         "Diagnostics move to stderr, so stdout is the document and nothing else.")
    ap.add_argument("--for", dest="roots", action="append", metavar="APP",
                    help="services: root the closure at these app id(s) (repeatable or comma-separated). "
                         "Default: every enabled app in platform.state.yaml.")
    ap.add_argument("--exclude", action="append", metavar="SVC",
                    help="services: drop these compose services from the output (repeatable or "
                         "comma-separated). Trimming a lane stays possible, but stays VISIBLE.")
    a = ap.parse_args()

    # compose-files: the ONE place that answers "which -f files are the stack?". Shell consumers
    # (bbox's dc(), scripts/lib.sh dcx()) read it, so a bare `docker compose` at the repo root —
    # which now sees only the shared-network declaration and zero services — never happens again.
    # Deliberately does not validate or resolve: it must stay usable while a manifest is broken.
    # set-state: THE write path for desired state, for shell callers. Python callers import
    # set_disposition() directly. Exists so bbox and packaging scripts stop carrying their own
    # regex copies of it — see the note on set_disposition().
    if a.verb == "set-state":
        if not a.app or not a.state:
            print("set-state needs --app <id> --state <enabled|disabled|archived>", file=sys.stderr)
            return 2
        try:
            changed = set_disposition(a.app, a.state, by=a.by, create=a.create)
        except ValueError as e:
            print(f"  ERROR {e}", file=sys.stderr)
            return 1
        if not changed:
            # A no-op is not a failure. Distinguish "no entry" (create it) from "already there":
            # an idempotent enable used to exit 1 with a message that read like a typo.
            have = current_disposition(a.app)
            if have is None:
                print(f"'{a.app}' not found in platform.state.yaml (use --create to add it)",
                      file=sys.stderr)
                return 1
            print(f"{a.app} is already {have} — nothing to change")
            return 0
        print(f"{a.app} -> {a.state} (by {a.by})")
        return 0

    # remote-get / remote-set: the `remote:` block for callers outside this process — the control
    # plane (which is how dgo-extend's projection reaches the file) and `bbox dgo project`. The block
    # is JSON on stdout / stdin; a refused block exits 1 with one sentence per reason on stderr.
    # office-get / office-set: the `office:` block for callers outside this process — the control
    # plane's /api/office, which the install wizard writes through. JSON out / JSON in, like the
    # remote pair, and for the same reason (a Hebrew name survives any stdout as \u escapes).
    if a.verb == "office-get":
        print(json.dumps(office_block()))
        return 0
    if a.verb == "office-set":
        raw = sys.stdin.read()
        if not raw.strip():
            print("  ERROR office-set reads the record as JSON on stdin and got nothing — nothing written",
                  file=sys.stderr)
            return 2
        try:
            fields = json.loads(raw)
        except ValueError as e:
            print(f"  ERROR the record is not JSON: {e}", file=sys.stderr)
            return 2
        changed, errs = set_office(fields, by=a.by)
        for e in errs:
            print("  -", e, file=sys.stderr)
        if errs:
            return 1
        print(json.dumps({"written": changed, "office": office_block()}))
        return 0

    if a.verb == "remote-get":
        # ASCII on purpose: this is read by a program, through whatever stdout the caller has. A
        # label with an emoji in it raised UnicodeEncodeError on a cp1255 console and printed nothing.
        print(json.dumps(remote_block()))
        return 0
    if a.verb == "remote-set":
        raw = sys.stdin.read()
        # NOTHING ON STDIN IS NOT AN EMPTY BLOCK. `[]` is how a caller says "no office gives this one
        # anything" and it takes the declaration away; an empty stdin is a caller whose upstream
        # failed. Reading the second as the first erased this office's whole remote block on
        # 2026-10-05 — `remote-get | remote-set`, with the reader dead on the encoding error above.
        if not raw.strip():
            print("  ERROR remote-set reads the block as JSON on stdin and got nothing — "
                  "nothing written (an empty block is the JSON `[]`)", file=sys.stderr)
            return 2
        try:
            block = json.loads(raw)
        except ValueError as e:
            print(f"  ERROR the block is not JSON: {e}", file=sys.stderr)
            return 2
        changed, errs = set_remote(block)
        for e in errs:
            print("  -", e, file=sys.stderr)
        if errs:
            return 1
        apps = sum(len(e.get("apps") or []) for e in block)
        if a.json:
            print(json.dumps({"written": changed, "apps": apps, "offices": len(block)}))
        else:
            print(f"remote: {apps} app(s) of {len(block)} office(s)" + ("" if changed else " — nothing to change"))
        return 0

    if a.verb == "required-by":
        # The enabled apps that cannot run without --app, as one JSON list (empty = nobody).
        known = load_catalog()
        if not a.app or a.app not in known:
            print("required-by needs --app <id> of an app that has a manifest", file=sys.stderr)
            return 2
        print(json.dumps(required_by(a.app, known, load_state())))
        return 0
    if a.verb == "compose-services":
        # The compose services ONE app declares — not `services`' resolved closure. The difference is
        # the point: stopping an app's closure stops the database it depends on. Used by apps/offices
        # when a declaration switches an app off and its containers must actually stop.
        if not a.app:
            print("compose-services needs --app <id>", file=sys.stderr)
            return 2
        cat = load_catalog()
        if a.app not in cat:
            print(f"unknown app '{a.app}'", file=sys.stderr)
            return 1
        for name in compose_services(cat[a.app]):
            print(name)
        return 0

    if a.verb == "compose-files":
        if not (GEN / "compose.yml").exists():
            print("not rendered — run: python3 platform/manager/reconcile.py render", file=sys.stderr)
            return 1
        for p in compose_files():
            print(p)
        return 0

    cat, state = load_catalog(), load_state()
    errs, provided = validate(cat)
    if errs:
        print("MANIFEST VALIDATION FAILED:")
        for e in errs:
            print("  -", e)
        return 1
    if a.verb == "validate":
        print(f"OK — {len(cat)} manifest(s) valid; capabilities: {', '.join(sorted(provided)) or '(none)'}")
        return 0

    # serve-plan: what the `serve:` block in platform.state.yaml actually routes. The render is a
    # traefik file, so "what will the edge do" has to be answerable without reading traefik's YAML —
    # by a human, and by the phase-3 gate. Refusals go to stderr and the exit code says so, exactly
    # like `validate`: a plan that cannot be rendered is not a plan.
    if a.verb == "serve-plan":
        entries, serrs = serve.plan(state, cat)
        for e in serrs:
            print("  -", e, file=sys.stderr)
        if serrs:
            return 1
        print(json.dumps({"remote": serve.describe(entries, cat),
                          "tiles": serve.module_entries(entries, cat),
                          "aliases": sorted({f"{x['alias']}.{e['office']}"
                                             for e in entries for x in e["apps"]}),
                          "traefik": "platform-base/traefik/config/zz-serve.yaml",
                          "aliases_file": ".generated/remote.override.yml"},
                         ensure_ascii=False, indent=2))
        return 0

    # services: the DERIVED answer to "what must this lane start?". Diagnostics go to stderr so
    # stdout stays a clean word list, usable directly as
    #     SERVICES=$(python3 platform/manager/reconcile.py services --for indox)
    if a.verb == "generations":
        gens = _gen_dirs()
        if not gens:
            print("no generations yet — the first `render` archives the current .generated/")
            return 0
        for d in gens:
            n = len(list(d.rglob("*")))
            print(f"  {d.name}  {n:>4} file(s)")
        print(f"rollback with: reconcile.py rollback --for {gens[-1].name}")
        return 0

    if a.verb == "rollback":
        def csv(vals):
            return [x for v in (vals or []) for x in re.split(r"[,\s]+", v) if x]
        want = csv(a.roots)
        gens = _gen_dirs()
        if not gens:
            sys.exit("FATAL nothing to roll back to")
        gid = want[0] if want else gens[-1].name
        restore_generation(gid)
        print(f"rolled back .generated/ to generation {gid}")
        print("  compose files: " + " ".join(f"-f {p}" for p in compose_files()))
        print("  NOTE: this restores the rendered CONFIGURATION. Docker volumes are not "
              "rolled back — a schema migration stays migrated.")
        return 0

    if a.verb == "blueprints":
        # "which app owns which n8n workflow dir" — read from each manifest's `blueprints.n8n`,
        # NOT from a glob. The glob in the push hook could not tell an app's workflows from a
        # stray directory, could not respect platform.state.yaml enablement, and made the layer-2
        # n8n hook enumerate layer-3 app paths by hand. One TAB-separated `app_id<TAB>dir` per line
        # (stdout stays parseable; diagnostics go to stderr).
        def csv(vals):
            return [x for v in (vals or []) for x in re.split(r"[,\s]+", v) if x]
        want = set(csv(a.roots))
        # Enablement is the install state. A DISABLED app's automations must not be pushed —
        # that is the whole "imported on enable, removed on disable" contract, and a gallery app
        # that ships disabled would otherwise have its workflows imported by any full push.
        # An explicit --for still resolves (so `unpush --app X` can clean up after disabling X).
        enabled = enabled_ids(state, cat)
        rows = []
        for aid, app in sorted(cat.items()):
            bp = ((app.get("blueprints") or {}).get("n8n") or "").strip()
            if not bp:
                continue
            if want:
                if aid not in want:
                    continue
            elif aid not in enabled:
                continue
            d = (app["_dir"] / bp).resolve()
            if not d.is_dir():
                print(f"  ERROR {aid}: blueprints.n8n -> {bp} is not a directory", file=sys.stderr)
                return 1
            # REPO-RELATIVE, always. An absolute Windows path ("C:/Users/...") does not glob in the
            # MSYS/Git-Bash shell the hooks run under, so the consumer prefixes ${REPO_ROOT} itself
            # and the same output works on Linux, WSL and Windows (gate G10).
            rows.append((aid, d.relative_to(REPO).as_posix()))
        if want:
            missing = want - {aid for aid, _ in rows}
            if missing:
                print("  ERROR no blueprints.n8n declared for: " + ", ".join(sorted(missing)),
                      file=sys.stderr)
                return 1
        for aid, rel in rows:
            print(f"{aid}\t{rel}")
        return 0

    # capability-provider: "which ENABLED app, if any, declares this capability?" — one app id on
    # stdout, or nothing (exit 1) if no enabled app provides it. Exists so layer 0 (bbox) can reach a
    # singleton service like the app-management control plane by the ROLE it plays (a capability
    # name — see platform-base/app-management/app.json's "control-plane" capability) instead of
    # hardcoding that app's id, which is exactly the app-specific knowledge G31 (layer0-lint) exists
    # to keep out of the CLI. Two enabled providers of the same capability is not resolved here by
    # guessing — ambiguity is reported and the caller gets nothing, same philosophy as plan()'s
    # provider selection above, just without the full binding/default_provider machinery this
    # narrow, read-only lookup does not need.
    if a.verb == "capability-provider":
        if not a.capability:
            print("capability-provider needs --capability <name>", file=sys.stderr)
            return 2
        enabled = enabled_ids(state, cat)
        provs = sorted(aid for aid in enabled
                       if any(c["name"] == a.capability for c in cat[aid].get("capabilities", [])))
        if not provs:
            return 1
        if len(provs) > 1:
            print(f"  ERROR capability '{a.capability}' has {len(provs)} enabled providers "
                  f"({', '.join(provs)}) — ambiguous", file=sys.stderr)
            return 1
        print(provs[0])
        return 0

    # enabled-apps: "<root> <id>" per app the platform should be running, in resolve() order.
    # The compiler already answers this for its own rendering; exposing it lets bbox run each app's
    # own bring-up hook WITHOUT bbox knowing a single app id. That is what removed the
    # app-specific bootstrap functions (portainer's password file, traefik's acme.json, browser42's
    # digest warning) from the CLI: an app's tooling belongs in the app's folder, and the CLI's job
    # is to invoke it generically.
    if a.verb == "enabled-apps":
        order, diags = resolve(cat, state)
        for lvl, m in diags:
            if lvl == "error":
                print("  ERROR " + m, file=sys.stderr)
        if any(lvl == "error" for lvl, _ in diags):
            return 1
        for aid in order:
            app = cat.get(aid) or {}
            d = app.get("_dir")
            if not d:
                continue
            print(f"{pathlib.Path(d).parent.name} {aid}")
        return 0

    if a.verb == "services":
        def csv(vals):
            return [x for v in (vals or []) for x in re.split(r"[,\s]+", v) if x]
        order, diags = resolve(cat, state, roots=csv(a.roots) or None)
        for lvl, m in diags:
            print(("  ERROR " if lvl == "error" else "  info  ") + m, file=sys.stderr)
        if any(lvl == "error" for lvl, _ in diags):
            print("RESOLVE FAILED", file=sys.stderr)
            return 1
        print(" ".join(lane_services(cat, order, csv(a.exclude))))
        return 0

    order, diags = resolve(cat, state)
    hard = [m for lvl, m in diags if lvl == "error"]
    # `--json` makes stdout a DOCUMENT, so everything that is a human note moves to stderr. A caller
    # that pipes this into `jq` must never have to strip a diagnostics line first.
    diag_out = sys.stderr if a.json else sys.stdout
    for lvl, m in diags:
        print(("  ERROR " if lvl == "error" else "  info  ") + m, file=diag_out)
    if hard:
        print(f"RESOLVE FAILED — {len(hard)} error(s)", file=diag_out)
        return 1

    if a.verb == "plan":
        # The apps THIS office shows — its own and its linked offices' — are the first thing the
        # command answers, because that is the question it is asked (`bbox apps list`). The plan
        # (start order + the file `apply` consumes) is still written and still printed below.
        served, serrs = serve.plan(state, cat)
        rows = app_rows(cat, order, served)
        remote = [{"office": e["office"], "label": e["label"], "link": e["link"],
                   "address": e["address"], "commit": e["commit"],
                   "apps": [x["alias"] for x in e["apps"]]} for e in served]
        for e in serrs:
            print("  ERROR " + e, file=sys.stderr)
        if serrs:
            print(f"REMOTE PLAN REFUSED — {len(serrs)} error(s); `render` would refuse too", file=sys.stderr)
            if a.json:
                print(json.dumps({"error": "remote plan refused", "errors": serrs,
                                  "apps": rows, "remote": remote}, ensure_ascii=False, indent=2))
            return 1
        pid, digest = write_plan(cat, state, order, diags)
        # WHAT NOBODY SWITCHED ON AND IS RUNNING ANYWAY (DGO-108). An enabled app may REQUIRE a
        # capability an optional app provides, and the compiler keeps that provider's containers in
        # the office whatever its own line says (drive requires supabase's object store: measured,
        # and the reason that preference is a live one). So the cost of a decision is not the app
        # that was switched on — it is that app PLUS the ones it drags in, and this is the one place
        # a person sees them together. `pulled` is the compiler's own diagnostic, never inferred.
        pulled = []
        for lvl, m in diags:
            if lvl != "info" or "pulled in as provider" not in m:
                continue
            provider, _, rest = m.partition(": pulled in as provider of ")
            cap, _, consumer = rest.partition(" for ")
            pulled.append((provider.strip(), cap.strip().strip("'"), consumer.strip()))
        pulled.sort()
        # Printed for a human, so it is repo-relative when it can be — and a caller that pointed
        # PLANS somewhere else (a test with a temporary state) gets the path it actually wrote.
        try:
            plan_file = (PLANS / (pid + ".yaml")).relative_to(REPO).as_posix()
        except ValueError:
            plan_file = str(PLANS / (pid + ".yaml"))
        if a.json:
            print(json.dumps({"apps": rows, "remote": remote,
                              "offices": [r["office"] for r in remote],
                              "enabled": order,
                              # Machine-readable beside the human section: who is running because
                              # another app needs them, and what each one declares it costs.
                              "pulled_in": [{"app": p, "capability": c, "for": f,
                                             "mem": ((cat.get(p) or {}).get("resources") or {}).get("memory") or ""}
                                            for p, c, f in pulled],
                              "local_apps": sum(1 for r in rows if r["office"] == LOCAL_OFFICE),
                              "remote_apps": sum(1 for r in rows if r["office"] != LOCAL_OFFICE),
                              "plan": {"id": pid, "file": plan_file, "inputs_digest": digest}},
                             ensure_ascii=False, indent=2))
            return 0
        print(f"apps — {len(rows)} row(s): {len(order)} of this office"
              + (f", and {len(remote)} linked office(s): "
                 + ", ".join(f"{e['office']} ({len(e['apps'])})" for e in remote) if remote else ""))
        print_app_rows(rows)
        if pulled:
            print("\n  pulled in by another app — their own line does not switch them on:")
            for provider, cap, consumer in pulled:
                mem = ((cat.get(provider) or {}).get("resources") or {}).get("memory") or "—"
                print(f"    {provider:18s} {mem:>7s}   ← provides {cap} for {consumer}")
        print(f"\nplan {pid} written -> {plan_file}")
        print(f"  inputs digest : {digest}")
        print(f"  apps          : {len(order)}")
        print(f"  start order   : {' -> '.join(order) or '(none)'}")
        print(f"apply it with: reconcile.py apply --for {pid}")
        return 0

    if a.verb == "apply":
        def csv(vals):
            return [x for v in (vals or []) for x in re.split(r"[,\s]+", v) if x]
        want = csv(a.roots)
        have = sorted(f.stem for f in PLANS.glob("*.yaml")) if PLANS.is_dir() else []
        if not have:
            sys.exit("FATAL no plan to apply — run `reconcile.py plan` first")
        pid = want[0] if want else have[-1]
        f = PLANS / f"{pid}.yaml"
        if not f.is_file():
            sys.exit(f"FATAL no plan '{pid}' (have: {', '.join(have)})")
        doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        now = inputs_digest(cat, state)
        if doc.get("inputs_digest") != now:
            sys.exit(f"FATAL plan {pid} is STALE — it was made against inputs {doc.get('inputs_digest')} "
                     f"but the catalog/state is now {now}. Applying it would do something other than "
                     f"what it says. Re-run `reconcile.py plan`.")
        if list(doc.get("start_order") or []) != list(order):
            sys.exit(f"FATAL plan {pid} resolves differently now — refusing to apply.")
        migrated = render(cat, order, state)
        print(f"applied plan {pid} — rendered {len(migrated)} app(s)")
        print("  compose files: " + " ".join(f"-f {p}" for p in compose_files()))
        return 0

    migrated = render(cat, order, state)
    print(f"rendered .generated/compose.yml — {len(migrated)} app(s) from apps/ + platform-base/")
    print("  compose files: " + " ".join(f"-f {p}" for p in compose_files()))
    if a.verb == "up":
        argv = ["docker", "compose"]
        for p in compose_files():
            argv += ["-f", p]
        argv += ["--project-directory", str(REPO), "up", "-d", "--remove-orphans"]
        return subprocess.call(argv, cwd=REPO)
    return 0


def render_agent_context(cat, order):
    """Compile the ENABLED apps' briefs into the one file the office agent reads every session.

    The problem this solves: the agent's prompt used to name apps by hand — one paragraph about
    `computers` inside the persona, and nothing about the next app at all. That is a list living in
    the wrong owner's file, so it can only ever be as current as the last person who remembered to
    edit it. Same disease as console's hand-written tiles and connections' hand-written secret
    manifest, and the same cure: the app DECLARES (`agent.context` → a Markdown file it owns) and
    the compiler renders it. Install an app and its brief appears on the agent's next turn; disable
    it and the brief leaves with it; there is no second list to keep in step.

    The rendered file is NOT a substitute for the app's own documentation — it is the minimum the
    agent needs to know the app EXISTS, what it is for, and which door to knock on. Everything the
    manifest already states mechanically (capability name, interface, endpoint, ops, the tile, the
    secrets it needs) is printed from the manifest, so a brief that repeats it is spending prompt
    budget on a copy. What only the brief can say: what the app is FOR, its vocabulary, its traps.

    Reads (never writes) the app's own file, so the app remains the author. A brief that vanished
    between validate and render renders as a loud placeholder rather than silently dropping the app.
    """
    reg = GEN / "registry"
    reg.mkdir(parents=True, exist_ok=True)

    rows = []
    for aid in order:
        a = cat[aid]
        rel = ((a.get("agent") or {}).get("context") or "").strip()
        if not rel:
            continue
        p = a["_dir"] / rel
        try:
            text = p.read_text(encoding="utf-8").strip()
        except OSError:
            text = (f"!!! This app declares agent.context '{rel}' but the file is unreadable. "
                    f"Run `python3 platform/manager/reconcile.py validate` before trusting anything "
                    f"here — the app is installed and the agent has NOT been told how to operate it.")
        rows.append(((a.get("agent") or {}).get("order", 100), aid, a, rel, text))
    rows.sort(key=lambda r: (r[0], r[1]))

    head = [
        "# אפליקציות הלשכה — מה מותקן ואיך מתפעלים כל אחת",
        "",
        "<!-- GENERATED by platform/manager/reconcile.py from every ENABLED app's `agent` block.",
        "     DO NOT EDIT — edit the app's own brief (apps/<id>/AGENT.md, named in its app.json).",
        "     Regenerate with: python3 platform/manager/reconcile.py render -->",
        "",
        "This is the deployment's own answer to \"what is installed, and how do I drive it\": one",
        "section per ENABLED app, written by the app itself. It is compiled from app.json +",
        "platform.state.yaml, so an app that is not listed here is NOT installed — do not invent it,",
        "and do not carry instructions for one from an earlier session.",
        "",
        "How to use an app (the pattern every app follows):",
        "- Its capability is declared in app.json: name, interface (e.g. `drive.v1`), its in-network",
        "  endpoint on `traefik-network` (e.g. `http://drive:8975`) and the ops it must serve. Call the",
        "  ops over HTTP at that endpoint — never reach into another app's volume, database or files.",
        "- `GET <endpoint>/manifest` is the LIVE contract of a service app: protocols it can connect,",
        "  its ops, its capabilities and its current state. When this file and `/manifest` disagree,",
        "  `/manifest` is right.",
        "- `GET <endpoint>/connections` lists the ACCOUNTS (instances) it holds, and",
        "  `POST <endpoint>/connections/select` chooses the active one. Accounts themselves live in the",
        "  credential plane (`connections`, `http://connections:8990`), never in the app's own config.",
        "- The owner-facing UI is at `/a/<alias>/` on the console host; its connect wizard is built",
        "  from `GET <endpoint>/providers`.",
        "- Anything that needs a machine OUTSIDE the platform (the host, a remote server) goes through",
        "  the `computers` app; anything needing a SECRET goes through the account the app already",
        "  holds — never ask the owner to paste a key into a command line.",
        "",
        f"{len(rows)} app(s) with a brief: "
        + (", ".join(f"`{r[1]}`" for r in rows) if rows else "(none)"),
        "",
    ]

    body = []
    for _, aid, a, rel, text in rows:
        title = (a.get("title") or {}).get("he") or aid
        lines = ["", f"## {title} — `{aid}` (layer {a.get('layer')})"]
        caps = a.get("capabilities") or []
        for c in caps:
            bits = [f"capability `{c.get('name')}`"]
            if c.get("type"):
                bits.append(f"({c['type']}" + (f", {c['interface']}" if c.get("interface") else "") + ")")
            if c.get("endpoint"):
                bits.append(f"→ `{c['endpoint']}`")
            ops = list(c.get("required_ops") or []) + [f"{o}?" for o in (c.get("optional_ops") or [])]
            if ops:
                bits.append("ops: " + ", ".join(f"`{o}`" for o in ops))
            lines.append("- " + " · ".join(bits))
        for r in (a.get("routing") or []):
            m = r.get("module") or {}
            if m.get("alias") and m.get("embed", True) is not False:
                lines.append(f"- UI: `/a/{m['alias']}/` on the console host")
        reqs = [c["id"] for c in (a.get("connections") or []) if c.get("id")]
        if reqs:
            lines.append("- secrets/connections it requires: " + ", ".join(f"`{c}`" for c in reqs))
        lines.append("")
        lines.append(text)
        body += lines

    md = "\n".join(head + body) + "\n"
    write(reg / "agent-context.md", md)

    # The same content, structured, for a consumer that wants the pieces rather than the prose
    # (bina-ds could render its own section from this; the console can show which apps briefed the
    # agent). One compiler pass, two spellings of one fact.
    write(reg / "agent-context.json", json.dumps({
        "generated_by": "platform/manager/reconcile.py",
        "apps": [{"id": aid, "title": (a.get("title") or {}).get("he"),
                  "layer": a.get("layer"), "file": rel,
                  "capabilities": a.get("capabilities") or [],
                  "endpoint": next((c.get("endpoint") for c in (a.get("capabilities") or [])
                                    if c.get("endpoint")), None),
                  "brief": text} for _, aid, a, rel, text in rows],
    }, indent=2, ensure_ascii=False) + "\n")
    return len(rows)


def external_origin(app_id, r, m):
    """The BROWSER origin of an app the shell frames on its OWN host (`module.external`), or None.

    The shell can derive this itself — `externalUrl()` in the console builds
    `<host>.<location.hostname>` — and it still does, as the fallback. But that derivation is only
    true where the host label NESTS: on an unregistered TLD the site is the last two labels, so
    `plane.console.localhost` is same-site with the console's session cookie while `plane.localhost`
    is not. On a real domain the apps already sit BESIDE the console (`plane.<domain>` /
    `console.<domain>`) and nesting would name a host nothing routes.

    So the origin is read from the ONE value that already decides it everywhere else: the host
    variable the app declares (`routing[].sso.base_url_env`, else `module.url_env`). That value is
    what `routing_labels()` renders into `Host()` and what the authentik provider takes as its
    `external_host` — so the address the shell frames is, by construction, a host the edge routes
    AND the identity layer knows. `module.url` is deliberately not the source: for an embedded app
    it is the console PROXY's internal base (`http://project-pln:80`), and a compose service name
    means nothing in a browser.
    """
    var = (r.get("sso") or {}).get("base_url_env") or m.get("url_env") or base_url_env(app_id)
    val = (_envfile_value(var) or "").strip()
    host = val.split("//", 1)[-1].split("/", 1)[0]
    if not host or "." not in host.split(":")[0]:
        return None                      # unset, or a compose service name — not a browser address
    proto = _envfile_value(app_id.upper().replace("-", "_") + "_PROTOCOL")
    if proto not in ("http", "https"):
        proto = "http" if host.split(":")[0].endswith("localhost") else "https"
    return f"{proto}://{host}"


def render_registries(cat, order, served=None):
    """Compile the registries a BASE app reads but must not author.

    console's module tiles and /a/<alias>/ proxy table, and connections' per-service secret
    manifest, were all hand-written lists of layer-3 apps living inside a layer-2 app. Each app
    now declares its own entry (routing[].module{} and connections[]) and the list is derived
    here, into .generated/registry/ which those two apps mount read-only.

    Consequence worth stating: uninstall an app and its tile, its proxy route and its secret
    requirements all disappear on the next render. Nothing has to be remembered and edited in a
    second place, which is exactly the drift that left a `feature-validation` tile 502-ing long
    after the service was parked in attic/."""
    reg = GEN / "registry"
    reg.mkdir(parents=True, exist_ok=True)

    modules, bases, framed = [], {}, framed_hosts(cat, order)
    for aid in order:
        for r in (cat[aid].get("routing") or []):
            m = r.get("module") or {}
            # `embed: false` means the app's UI is on its own host and the shell cannot frame it —
            # n8n, GlitchTip, Authentik. It gets no /a/<alias>/ entry, but its name, icon and
            # description still belong in the manifest: app-management reads the same block for its
            # card. They used to be hardcoded inside console instead, which put five apps' display
            # text in a codebase owning none of them.
            alias = m.get("alias")
            embedded = bool(alias) and m.get("embed", True) is not False
            # `external` = the shell FRAMES this app on its own host instead of proxying it under
            # `/a/<alias>/`. It is declared by an app that is EMBEDDED as well as by one that is not,
            # and it has to win in both cases: the proxy is a rewriter, so an app whose bundle
            # hardcodes root-absolute URLs (Plane's `import "/assets/manifest-*.js"`) renders an
            # empty frame through it, and no attribute rewrite can fix a module specifier inside a
            # script. The `/a/<alias>/` route stays as the card the shell falls back to.
            if m.get("external") and r.get("host"):
                ext = {"id": m.get("id", aid), "name": m["name"], "icon": m["icon"],
                       "group": m["group"], "desc": m.get("desc", ""),
                       "order": m.get("order", 999), "external": True, "host": r["host"],
                       # …and the app's own ALIAS, which is the name a link may legitimately use:
                       # `/a/<alias>/` here, `<alias>.<office>` on a linked office. A link written
                       # with either name has to land on the same screen (app.js, module-ref.js).
                       "alias": alias}
                # NO `url` is rendered, and that is deliberate. The address of a framed app is a
                # function of the BROWSER: the office browser reaches this edge on loopback :80
                # (browser42's localhost-forward.py, which serves port-less and nothing else) while
                # a browser on the host reaches it on :8080. One file cannot carry both, and a
                # literal baked for one is a dead link for the other. So the address stays DERIVED,
                # in the shell, from its own `location` — and the compiler's half of the contract is
                # to make the host it derives exist: `framed_sso_entries()` registers it with the
                # identity layer and `routing_labels()` routes it where this app's own host
                # variable does not already. `module.url` is deliberately not used either: for an
                # embedded app it is the console PROXY's internal base (`http://project-pln:80`),
                # and a compose service name means nothing in a browser.
                if embedded:
                    ext["embed"] = f"/a/{alias}/"
                if aid in framed:
                    # …and where that host is a nested one, the edge says whether the browser is
                    # signed in on it and signs it in (render_serve): the shell asks before framing
                    # a host that cannot show its own sign-in, exactly as for a linked office's app.
                    ext.update(serve.OWN_HOST)
                modules.append((m.get("order", 999), ext))
                if embedded and m.get("url"):
                    bases[alias] = {"env": m.get("url_env"), "default": m["url"]}
                continue
            if not embedded:
                # A module with no alias to embed and nothing external to point at is NOT a tile —
                # whoever added `external` support dropped this `continue`, and the first machine to
                # render with it died on `m["name"]` (KeyError) inside `bbox run`, because apitools
                # declares a routing entry for its LABELS and no module block at all. The failure
                # surfaced as "reconcile render failed" with a traceback nobody reads as "a tile is
                # missing a name".
                continue
            e = {"id": m.get("id", aid), "name": m["name"], "icon": m["icon"],
                 "group": m["group"], "embed": f"/a/{m['alias']}/", "desc": m.get("desc", ""),
                 "order": m.get("order", 999), "alias": m["alias"]}
            if m.get("service"):
                e["service"] = m["service"]
            modules.append((m.get("order", 999), e))
            if m.get("url"):
                bases[m["alias"]] = {"env": m.get("url_env"), "default": m["url"]}
    # The reverse plane's tiles (DGO-30). They are compiled HERE and not merged at runtime like the
    # peer registry is, because a `serve:` entry is a fact of THIS office's desired state: it is
    # rendered from platform.state.yaml, it disappears when the entry does, and the shell must be
    # able to show it before any remote process has ever run. An app that IS installed locally wins
    # its own tile — `module_entries` is given the ids already claimed.
    if served:
        # A remote tile is NAMESPACED BY ITS OFFICE (`bina.macbook`) and is never suppressed by a
        # local app that happens to share the alias: the owner's own rule is "an app installed in
        # both offices appears twice, once with the remote mark" (ai/context/dgo-remote-apps.md).
        modules += [(m.get("order", 900), m) for m in serve.module_entries(served, cat)]

    modules = [e for _, e in sorted(modules, key=lambda t: t[0])]

    write(reg / "console.modules.yaml", 
        "# GENERATED by platform/manager/reconcile.py from each app's routing[].module — DO NOT EDIT.\n"
        + yaml.safe_dump(modules, sort_keys=False, allow_unicode=True, default_flow_style=False))
    write(reg / "console.app_bases.json", 
        json.dumps(bases, indent=2, ensure_ascii=False) + "\n")

    # ── the remote-office plane (DGO-30/DGO-37) ───────────────────────────────────────────────────
    # TWO artifacts, and the split is the whole design: `office.apps.json` is what THIS office knows
    # about its OWN apps (the source a linked office pulls as its catalog — apps/dgo-extend/catalog.py
    # is its only reader), and one `remote.<office>.<alias>.json` per remote app is what a peer's
    # catalog became here. Neither is a second list: the first is a projection of the manifests above,
    # the second of the `remote:` block in platform.state.yaml.
    write(reg / "office.apps.json",
        json.dumps(_office_apps(cat, order), ensure_ascii=False, indent=2) + "\n")
    remote_entries = render_remote_entries(reg, served)

    # A connection is granted to the SERVICE that reads it, because that is what the broker can
    # identify: `identity.identify` names a caller by its compose service, and `service_requires` is
    # the whole authorization input. The default stays what every app had before `connections[].service`
    # existed — the app's FIRST routing service — so this is a widening, not a break: an app whose
    # secret is read by a non-routed service (browser42's task runner, which does the CDP typing)
    # names that service on the connection itself. `service` may also be a LIST, for the case where
    # two services legitimately read the same secret — the browser that holds the profile and the
    # runner that types into it — because declaring the connection twice is two rows that can drift.
    #
    # Merged by service: the manifest is keyed by service name and `service_requires` returns the
    # FIRST match, so two rows for one service would silently hide the second.
    by_service: dict = {}
    for aid in order:
        reqs = cat[aid].get("connections") or []
        if not reqs:
            continue
        default_svc = (cat[aid].get("routing") or [{}])[0].get("service") or aid
        for c in reqs:
            declared = c.get("service") or default_svc
            services = declared if isinstance(declared, list) else [declared]
            for svc in services:
                by_service.setdefault(svc, []).append(
                    {"id": c["id"], "required": bool(c.get("required"))})
    consumers = [{"service": svc, "requires": reqs} for svc, reqs in by_service.items()]
    probes = {}
    for aid in order:
        probes.update(((cat[aid].get("contributes") or {}).get("connection_probes") or {}))

    # Whole catalog entries an app owns. providers/*.yaml is layer-1 config, so portainer's admin
    # password — a secret that exists only because a layer-3 app does — had to be authored there.
    # Declared by the app and compiled here, it appears in the catalog only while the app is
    # installed, which is the behaviour the operator already expects from routes and tiles.
    owned = []
    for aid in order:
        for p in ((cat[aid].get("contributes") or {}).get("connection_providers") or []):
            owned.append({**p, "_app": aid})
    write(reg / "connections.providers.yaml", 
        "# GENERATED by platform/manager/reconcile.py from each app's\n"
        "# contributes.connection_providers — DO NOT EDIT.\n"
        + yaml.safe_dump(owned, sort_keys=False, allow_unicode=True, default_flow_style=False))
    write(reg / "connections.probes.json", 
        json.dumps(probes, indent=2, ensure_ascii=False) + "\n")

    write(reg / "connections.consumers.yaml", 
        "# GENERATED by platform/manager/reconcile.py from each app's connections[] — DO NOT EDIT.\n"
        + yaml.safe_dump(consumers, sort_keys=False, allow_unicode=True, default_flow_style=False))
    return len(modules), len(consumers)


def assert_unique_identities(body):
    """Refuse to WRITE a blueprint whose entries collide on identity.

    `identifiers.name` IS a proxy provider's identity in authentik's importer, and
    `identifiers.slug` is an application's: an entry is resolved BY it, so two entries carrying the
    same one collapse into a single row — and the second application is then rejected
    ("Application with this provider already exists"), because a proxy provider belongs to exactly
    one application. authentik validates the whole file against that and refuses the APPLY, so one
    such pair silently blocks every later entry in the file from ever landing.

    Measured 2026-10-05 on the MacBook office: the framed forge provider reused the app's own
    display name, so `ak apply_blueprint … || exit 1` killed the bootstrap sentinel container in a
    crash loop (262 restarts), its SSO readiness probe never minted its probe token, that probe then
    could not determine the gated host list at all, and every `bbox run` read the silence as "the
    outpost cache is stale", restarted authentik-server, waited four minutes and printed "EVERY
    gated surface is down" — over an office whose SSO was working the entire time.

    Raising here makes the render the gate: a blueprint authentik would reject is never written, and
    the failure names the two colliding entries instead of surfacing three layers away as a 404.
    """
    ident_key = {"authentik_providers_proxy.proxyprovider": "name",
                 "authentik_core.application": "slug"}
    seen = {}
    model = ident = entry = None
    for line in body:
        s = line.strip()
        if s.startswith("- id: "):
            model, ident, entry = None, None, s[len("- id: "):]
            continue
        if s.startswith("model: "):
            model = s[len("model: "):]
            ident = ident_key.get(model)
            continue
        if ident and s.startswith(ident + ":"):
            value = s.split(":", 1)[1].strip().strip('"').strip("'")
            key = (model, ident)
            if value in seen.setdefault(key, {}):
                raise SystemExit(
                    "FATAL the generated authentik blueprint has two entries with the same "
                    f"{ident} '{value}': {seen[key][value]} and {entry}. authentik resolves an entry "
                    "by it, so the two collapse into one row and the WHOLE file is rejected — give "
                    "one of them an identity of its own (see framed_sso_entries).")
            seen[key][value] = entry
            ident = None            # one identity line per entry
    return


def render_authentik(cat, order, served=None):
    """Emit the authentik proxy provider + application for every app whose SSO host needs one.

    authentik is layer 1. Its committed blueprint may describe the base estate it genuinely owns
    (traefik dashboard, portainer, homepage...) but it must not name an installable app — remove
    ollama and the blueprint would still publish an SSO application for it. Which base hosts it
    already owns is READ from that file by sso_providers(); the rest is emitted here.

    Written INTO the blueprints directory authentik already bind-mounts, so this needs no compose
    change; the file is gitignored because it is compiled output. authentik applies blueprints in
    filename order, hence the zz- prefix: base definitions first, generated apps last."""
    out = [(aid, s) for aid, s, _host in sso_providers(cat, order)]
    dest = REPO / BOOTSTRAP_INPUTS_DIR / "blueprints" / GENERATED_BLUEPRINT
    if not out:
        dest.unlink(missing_ok=True)
        return 0
    body = [
        "# GENERATED by platform/manager/reconcile.py from each app's routing[].sso — the apps that",
        "# declare one, plus the hosts a base app publishes that the committed blueprint does not own.",
        "# DO NOT EDIT — edit the app's app.json. Gitignored; see gate G9.",
        "version: 1", "metadata:", "  name: Deployment - Generated App Providers",
        "  labels:", '    blueprints.goauthentik.io/instantiate: "true"',
        # !Context resolves against THIS blueprint's own context block, not a sibling file's.
        # Without this the outpost entry sent authentik_host=None and the whole blueprint failed
        # validation — invisible on a warm database, fatal on a fresh one.
        "context:",
        '  authentik_external_host: !Format ["%s://%s/", !Env [AUTH_PROTOCOL, https], !Env [AUTH_EXTERNAL_URL, auth.localhost]]',
        "entries:"]
    def pair(slug, name, host_expr):
        return [
            f"  - id: provider-{slug}",
            "    model: authentik_providers_proxy.proxyprovider",
            "    state: present", "    identifiers:",
            f"      name: {name} Provider",
            "    attrs:",
            "      authorization_flow: !Find [authentik_flows.flow, [slug, default-provider-authorization-implicit-consent]]",
            "      invalidation_flow: !Find [authentik_flows.flow, [slug, default-provider-invalidation-flow]]",
            "      mode: forward_single",
            f"      external_host: {host_expr}",
            "      access_token_validity: hours=24",
            "      intercept_header_auth: true", "",
            f"  - id: app-{slug}",
            "    model: authentik_core.application",
            "    state: present", "    identifiers:",
            f"      slug: {slug}", "    attrs:",
            f"      name: {name}",
            f"      provider: !KeyOf provider-{slug}",
            "      policy_engine_mode: any", ""]

    host_env = sso_host_env(cat, order)
    n = 0
    for aid, s in out:
        # A framed host (see framed_sso_entries) carries a LITERAL external_host: no variable in
        # this office's .env names it, and inventing one would put the host in two places.
        if s.get("host_expr"):
            body += pair(s["slug"], s["display_name"], s["host_expr"])
            n += 1
            continue
        # Domain flavour — only when the app names the env var that carries its public host.
        # inbox is deliberately local-only, so it declares no base_url_env.
        #
        # The host is written as a LITERAL, resolved here from this office's .env — not as an
        # `!Env` for whichever container applies the file to resolve. Three containers apply it
        # (the worker on every change of the file, the sentinel, the server) and a NEW app's
        # variable reached only the ones re-created since: measured on hp-laptop, 2026-10-05, the
        # worker knew 13 host variables, the server 15 and the sentinel 16 — one blueprint, three
        # answers. The worker is the first to apply, seconds after a render, and it gave a new
        # app's provider the default: `<app>.localhost`. On an office with a domain or a port that
        # is the wrong host — and the SAME host as the app's own -local twin, which is the second
        # provider for one host that freezes the outpost (ONE PROVIDER PER HOST, below). The scheme
        # stays authentik's own setting, which every one of its containers has from its first start.
        own = ""
        if s.get("base_url_env"):
            own = _env_here(s["base_url_env"], s["default_host"], host_env)
            body += pair(s["slug"], s["display_name"],
                         '!Format ["%%s://%%s", !Env [AUTH_PROTOCOL, https], "%s"]' % own)
            n += 1
        # The -local twin: plain http on *.localhost, which is what a laptop deployment resolves.
        # Not when the app's own host IS that host here — an office on `.localhost` whose edge is
        # on :80, where the twin would be the second provider for one host.
        if s.get("local_twin") and _host_of(own) != s["default_host"].lower():
            body += pair(s["slug"] + "-local", s["display_name"] + " Local",
                         "http://" + s["default_host"])
            n += 1

    # ── the reverse plane's hosts (DGO-30) ────────────────────────────────────────────────────────
    # A router is not a served host until the IDENTITY layer knows it. Measured 2026-09-30 on this
    # deployment: the emitted serve router matched and forwardAuth answered 404 with a 3.6 KB page —
    # "the app is missing" — while the router itself was live and healthy-looking in the access log.
    # So every `<alias>.console.<domain>` this office frames needs a proxy provider of its own, with
    # the SAME host the router matches, or SSO turns the tile into a 404 nobody can explain.
    #
    # No `base_url_env`: nothing in this office's .env carries a remote office's host, and inventing
    # a variable would put the host in two places. The compiler knows the domain already.
    # ONE provider per host and never two: two providers for one host leave the outpost with an
    # authority it cannot pick between — measured 2026-09-30, the served tile 404'd at the identity
    # layer while both rows sat in the database. `serve.sso_hosts` owns WHICH hosts those are; this
    # loop only turns them into blueprint entries.
    for rec in serve.sso_hosts(served or [], cat,
                               domain=_envfile_value("DEPLOYMENT_DOMAIN") or "localhost",
                               console_port=_console_port()):
        if rec.get("port_host"):
            body += pair(rec["slug"] + "-port", rec["name"] + " (port)",
                         frame_host_expr(rec["port_host"]))
            n += 1
        body += pair(rec["slug"], rec["name"], frame_host_expr(rec["host"]))
        n += 1

    # The embedded outpost has to list EVERY proxy provider by !KeyOf — base and installable
    # alike — so it is the one entry that inherently knows the whole app set. Leaving it in the
    # committed blueprint would force that file to name layer-3 providers again, and deleting
    # those names without moving this entry is what broke the whole blueprint with
    # "KeyOf: failed to find entry with `id` of `provider-ollama`". So compile it: base provider
    # ids come from the committed file, generated ones from what we just emitted.
    # !KeyOf only resolves entries within the SAME blueprint file, so the base providers defined
    # in deployment-apps.yaml have to be referenced by DB lookup (!Find on their name) instead.
    # This entry must also be applied AFTER those providers exist, which the zz- filename
    # guarantees — authentik applies blueprints in filename order.
    # Parse the YAML rather than regex it: the committed file mixes block and inline mapping
    # styles (`identifiers:\n  name: X` and `identifiers: { name: X }`), and a regex that handles
    # only one form silently found 18 of 29 providers — which would have dropped eleven base apps
    # out of the outpost on a fresh deploy while this machine's stale rows masked it.
    def providers_in(text):
        """[(entry id, provider name, external_host as the blueprint spells it)], tags stripped."""
        return [(e["id"], e["identifiers"]["name"], (e.get("attrs") or {}).get("external_host"))
                for e in (yaml.safe_load(re.sub(r"!\w+", "", text)) or {}).get("entries", [])
                if str(e.get("id", "")).startswith("provider-")
                and isinstance(e.get("identifiers"), dict) and e["identifiers"].get("name")]

    base = providers_in(COMMITTED_AUTHENTIK_BP.read_text(encoding="utf-8"))
    gen_ids = re.findall(r"^  - id: (provider-\S+)", "\n".join(body), re.M)
    gen_host = {pid: expr for pid, _name, expr in providers_in("\n".join(body))}
    # ONE PROVIDER PER HOST ON THE OUTPOST — which is why a new app used to need a restart of the
    # sign-in server, a minute in which every gated host of the office answered 404 or 5xx.
    #
    # The outpost files its applications under `host[:port]`. On a refresh it walks its providers and,
    # for each, stops the application it previously held for that host (authentik 2024.12
    # internal/outpost/proxyv2/refresh.go: `existing, ok := ps.apps[host]` … `existing.Stop()`).
    # `Stop()` is one send on an unbuffered channel that the application's cache loop receives ONCE
    # (ttlcache v3.3.0), so the second provider of a host stops an application that is already
    # stopped — and waits for ever. The refresh never returns, the new table is never swapped in, and
    # the loop that would refresh again is the one that is stuck. The first load, at start-up, has
    # nothing to stop: which is why a restart "fixed" it every time.
    #
    # Measured on hp-laptop, 2026-10-06: 15 hosts carried two providers each — `<app>.localhost` from
    # the app's own variable and `<app>.localhost` again from its -local twin — and across five
    # starts of the server its outpost fetched its providers at start-up, once more five minutes
    # later, and never again; a host declared after that was not served in 345 s, nor after re-saving
    # the outpost, nor after sending it its update. So the list is compiled with one provider for a
    # host, the first that names it: the app's own before its twin, in both blueprints. A host that
    # cannot be told from here ("") is never dropped.
    seen, bind = set(), []
    for ref, expr in ([(f'!Find [authentik_providers_proxy.proxyprovider, [name, "{name.strip()}"]]', expr)
                       for _id, name, expr in base]
                      + [(f"!KeyOf {pid}", gen_host.get(pid)) for pid in gen_ids]):
        host = sso_host_here(expr, host_env)
        if host and host in seen:
            continue
        seen.add(host)
        bind.append(ref)
    # …and THE HOSTS THIS RENDER GATES are stated in the file that gates them: the set the outpost
    # entry below binds, for the readiness probe to ask the outpost about (outpost-ready.py, which
    # records what the two earlier sources of that list cost). In the blueprint's own `context`,
    # where authentik keeps a blueprint's values and reads only the ones an entry asks for — so the
    # list and the providers are one write, and cannot disagree for even a moment.
    body.insert(body.index("context:") + 1,
                "  gated_hosts: " + json.dumps(sorted(h for h in seen if h)))
    body += [
        "  - id: embedded-outpost",
        "    model: authentik_outposts.outpost",
        "    state: present", "    identifiers:",
        "      managed: goauthentik.io/outposts/embedded",
        "    attrs:",
        "      name: authentik Embedded Outpost",
        "      type: proxy", "      config:",
        "        authentik_host: !Context authentik_external_host",
        "      providers:"]
    body += [f"        - {ref}" for ref in bind]
    body.append("")

    assert_unique_identities(body)
    write(dest, "\n".join(body) + "\n")
    return n


if __name__ == "__main__":
    sys.exit(main())
