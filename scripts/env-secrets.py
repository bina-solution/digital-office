#!/usr/bin/env python3
"""env-secrets — every office mints its own secrets; none comes from the template (DGO-1220, part 2).

    python3 scripts/env-secrets.py [--env FILE] --fill        fill every table key that is missing or empty
    python3 scripts/env-secrets.py [--env FILE] --if-fresh    the same, only while the office has no data yet
    python3 scripts/env-secrets.py [--env FILE] --check       write nothing; name the keys still public — by
                                                              PUBLIC_FILE and by every value .env.ex ever held
                                                              in this checkout's git history (in memory only)
    python3 scripts/env-secrets.py [--env FILE] --rotate [KEY…] --plan
                                                              how each key (default: every key --check names)
                                                              is rotated, and every consumer; writes nothing

WHY. .env.ex carried the office's real secrets, on purpose (a52d8118), and every way an office is made
except ci-env.sh — debian-install.sh, scripts/onboarding, packaging/linux/header.sh, README's `cp` — copied
it to .env, so offices shared them with each other and with whoever holds the template. The template is
empty now; this is the one place a key's value is made.

WHAT. TABLE names every secret the office makes itself and how. A key counts as missing when it is absent,
empty, or a known placeholder; only those are filled. A value that is already real is never touched. The
Supabase anon/service keys are HS256 JWTs signed by the office's own SUPABASE_JWT_SECRET.

FRESH. A secret that unlocks data cannot change once the data exists: a new CONNECTIONS_ROOT_KEY locks
the vault, a new POSTGRES_PASSWORD meets a database made with the old one. So `--if-fresh` (what `bbox run`,
converge and the installer call) fills every key only while none of DATA_VOLUMES exists on this machine.
With data, it makes only an EMPTY key whose own app keeps no data yet (LOCKED_BY): an app switched on later
needs its keys. A real value, or a placeholder in use, is never replaced; the keys still empty or still a
value the template once published (PUBLIC, sha256 only) are named, which is the hand-off to the rotation
item (DGO-1015). When docker cannot be asked, nothing is written.

NEVER a value on the screen: names and counts only. The file is backed up before a write (.env.bak-<time>),
written whole through a temp file, mode 0600, through a symlink to where it points (binaos.env).
"""
import base64
import datetime
import hashlib
import hmac
import json
import os
import re
import secrets
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

#: key -> how it is made: ("hex", bytes) | ("urlsafe", bytes) | ("pw", bytes) | ("jwt", role)
TABLE = {
    "POSTGRES_PASSWORD": ("hex", 24),
    "REDIS_PASSWORD": ("hex", 24),
    "N8N_ENCRYPTION_KEY": ("hex", 32),
    "N8N_USER_MANAGEMENT_JWT_SECRET": ("hex", 32),
    "N8N_OWNER_PASSWORD": ("pw", 24),
    "N8N_RUNNERS_AUTH_TOKEN": ("hex", 32),
    "N8N_WEBHOOK_PASS": ("hex", 24),
    "BS_WEBHOOK_PASS": ("hex", 24),
    "SETTINGS_AUTH_PASS": ("hex", 24),
    "CHAT_AUTH_PASS": ("hex", 24),
    "CHAT_API_TOKEN": ("hex", 32),   # an office service's proof to chat: `X-Chat-Office-Token` (edge_caller.js)
    "CHAT_READ_TOKEN": ("hex", 32),  # the same header, READ only: GET /api/accounts, /api/readyz (the office agent)
    "MCP_AUTH_TOKEN": ("hex", 24),
    "AGENT_RUNNER_TOKEN": ("hex", 32),
    "DISPATCHER_TOKEN": ("hex", 32),
    "CONNECTIONS_ROOT_KEY": ("urlsafe", 32),
    "BROWSER42_MCP_TOKEN": ("hex", 32),
    "EXAMPLEM_API_TOKEN": ("hex", 32),
    "ASSETS_API_TOKEN": ("hex", 32),
    "LOANS_API_TOKEN": ("hex", 32),
    "AUTHENTIK_SECRET_KEY": ("hex", 48),
    "AUTHENTIK_POSTGRES_PASSWORD": ("hex", 24),
    "AUTHENTIK_BOOTSTRAP_PASSWORD": ("pw", 24),
    "AUTHENTIK_BOOTSTRAP_TOKEN": ("hex", 32),
    "FORWARD_AUTH_SECRET": ("hex", 48),
    "GLITCHTIP_SECRET_KEY": ("hex", 32),
    "GLITCHTIP_DB_PASSWORD": ("hex", 24),
    "SUPABASE_DB_PASSWORD": ("hex", 24),
    "SUPABASE_JWT_SECRET": ("hex", 32),
    "SUPABASE_ANON_KEY": ("jwt", "anon"),
    "SUPABASE_SERVICE_KEY": ("jwt", "service_role"),
    "SUPABASE_COOKIE_KEY": ("hex", 24),
    "SUPABASE_DASHBOARD_PASSWORD": ("hex", 24),
    "PLANE_DB_PASSWORD": ("hex", 24),
    "PLANE_S3_SECRET_KEY": ("hex", 24),
    "LOCALMAIL_PW": ("hex", 24),
    "CHAT_RELAY_KEY": ("hex", 32),
    "CHAT_SESSION_SECRET": ("hex", 32),
    "OPENHANDS_JWT_SECRET": ("hex", 32),
}

#: Keys of an OUTSIDE provider: the owner pastes them, and a random value would read as configured. Empty.
EXTERNAL = ("GMAIL_IMAP_APP_PW", "N8N_GOOGLE_OAUTH_CLIENT_SECRET", "N8N_GMAIL_OAUTH_CLIENT_SECRET",
            "GOOGLE_OAUTH_CLIENT_SECRET", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "GEMINI_API_KEY",
            "OPENHANDS_GEMINI_API_KEY", "GOOGLE_VISION_API_KEY", "JINA_API_KEY", "TELEGRAM_BOT_TOKEN", "PRIORITY_PASS", "PRIORITY_TEST_PASS",
            "DOCUMENT_AI_SA_PRIVATE_KEY", "GOOGLE_WORKSPACE_AGENT_OPENAI_API_KEY")

#: Made by the app that owns it (an empty value is how it knows to): n8n issues its API key (apps/n8n/hooks/
#: push-app ensure_api_key); meet, glitchtip, portainer and plane mint their admin/owner secrets in their
#: prepare hooks; browser42's two are the owner's own choice and stay empty. Never filled here.
APP_MADE = ("N8N_API_KEY", "GLITCHTIP_ADMIN_PASSWORD", "PORTAINER_ADMIN_PASSWORD", "PLANE_OWNER_PASSWORD",
            "BROWSER42_VNC_PASSWORD", "BROWSER42_STATE_PASSPHRASE", "MEET_JWT_SECRET", "MEET_JICOFO_PASSWORD",
            "MEET_JVB_PASSWORD", "MEET_JIBRI_XMPP_PASSWORD", "MEET_JIBRI_RECORDER_PASSWORD", "MEET_TURN_SECRET")

#: A value that stands for "not set": the template's old words and the compose files' literal fallbacks.
PLACEHOLDER = re.compile(r"CHANGE_ME|change_me\w*|dev-root-key-not-for-production|your[-_]\S*|<[^>]*>")

#: The volumes a secret of .env unlocks, matched by suffix (converge.py DATA_VOLUMES, and n8n, glitchtip,
#: plane): none of them on this machine means the office has no data, and --if-fresh fills every key.
DATA_VOLUMES = ("connections_vault", "supabase_db_data", "authentik_postgres_data", "postgres_storage",
                "n8n_storage", "glitchtip_postgres_data", "project_pln_db", "project_pln_minio")

#: On an office WITH data, a key is still made when it is EMPTY (or absent) and the volumes its own app keeps
#: data in are not there yet: an app switched on later (glitchtip, plane, browser42) needs its keys, and its
#: compose refuses an empty one (`:?`). Keys listed here are locked by those volumes; a key not listed locks
#: no data (a token, a webhook password) and an empty one is made. A placeholder word on an office with
#: data is in use as it stands (a compose fallback), so it is named, never replaced.
LOCKED_BY = {
    "CONNECTIONS_ROOT_KEY": ("connections_vault",),
    "POSTGRES_PASSWORD": ("postgres_storage",),
    "N8N_ENCRYPTION_KEY": ("postgres_storage", "n8n_storage"),
    "N8N_USER_MANAGEMENT_JWT_SECRET": ("postgres_storage", "n8n_storage"),
    "N8N_OWNER_PASSWORD": ("postgres_storage", "n8n_storage"),
    "AUTHENTIK_SECRET_KEY": ("authentik_postgres_data",),
    "AUTHENTIK_POSTGRES_PASSWORD": ("authentik_postgres_data",),
    "AUTHENTIK_BOOTSTRAP_PASSWORD": ("authentik_postgres_data",),
    "AUTHENTIK_BOOTSTRAP_TOKEN": ("authentik_postgres_data",),
    "GLITCHTIP_SECRET_KEY": ("glitchtip_postgres_data",),
    "GLITCHTIP_DB_PASSWORD": ("glitchtip_postgres_data",),
    "SUPABASE_DB_PASSWORD": ("supabase_db_data",),
    "SUPABASE_JWT_SECRET": ("supabase_db_data",),
    "SUPABASE_ANON_KEY": ("supabase_db_data",),
    "SUPABASE_SERVICE_KEY": ("supabase_db_data",),
    "PLANE_DB_PASSWORD": ("project_pln_db",),
    "PLANE_S3_SECRET_KEY": ("project_pln_minio",),
}

#: sha256 of every value the template ever published for a TABLE key (read from .env.ex's history, in
#: memory; no value is in the repo). An office still on one of them runs a public secret.
PUBLIC_FILE = os.path.join(HERE, "env-secrets.public-sha256")


def _value(line):
    return line.split("=", 1)[1].strip().strip("'\"")


def missing(value):
    return not value or bool(PLACEHOLDER.fullmatch(value))


def _b64url(b):
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def jwt_hs256(payload, secret):
    head = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(secret.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest()
    return f"{head}.{body}.{_b64url(sig)}"


def make(key, values):
    kind, arg = TABLE[key]
    if kind == "hex":
        return secrets.token_hex(arg)
    if kind == "urlsafe":
        return secrets.token_urlsafe(arg)
    if kind == "pw":                          # a mixed-case password, for logins that ask for one
        return "Ci" + secrets.token_hex(arg) + "9X"
    now = int(time.time())
    return jwt_hs256({"role": arg, "iss": "supabase", "iat": now, "exp": now + 10 * 365 * 24 * 3600},
                     values["SUPABASE_JWT_SECRET"])


def read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().split("\n")
    except FileNotFoundError:
        return []


def fill(path, may=None):
    """Fill every missing TABLE key in `path`, in place; with `may(key, value)`, only the keys it allows.
    Returns the names filled (never a value)."""
    lines = read(path)
    current = {}
    for ln in lines:
        m = re.match(r"^([A-Z0-9_]+)=", ln)
        if m:
            current[m.group(1)] = _value(ln)          # the last line of a key is what compose reads
    values, filled = dict(current), []
    # the JWT secret first: the two Supabase keys are signed with it, and a new secret re-signs both
    order = ["SUPABASE_JWT_SECRET"] + [k for k in TABLE if k != "SUPABASE_JWT_SECRET"]
    for key in order:
        if not missing(current.get(key, "")) and not (key in ("SUPABASE_ANON_KEY", "SUPABASE_SERVICE_KEY")
                                                       and "SUPABASE_JWT_SECRET" in filled):
            continue
        if may is not None and not may(key, current.get(key)):
            continue
        values[key] = make(key, values)
        filled.append(key)
    if not filled:
        return []
    out, done = [], set()
    for ln in lines:
        m = re.match(r"^([A-Z0-9_]+)=", ln)
        if m and m.group(1) in filled:
            out.append(f"{m.group(1)}={values[m.group(1)]}")   # every line of the key gets the one value
            done.add(m.group(1))
        else:
            out.append(ln)
    rest = [k for k in filled if k not in done]
    if rest:
        while out and out[-1] == "":
            out.pop()
        out += ["", "# minted for this office by scripts/env-secrets.py (DGO-1220)"]
        out += [f"{k}={values[k]}" for k in rest]
        out.append("")
    write(path, "\n".join(out))
    return filled


def write(path, text, backup=True):
    real = os.path.realpath(path)
    if backup and os.path.exists(real):
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        for n in range(1000):        # two writes in one second (a rotation and its restore) never collide
            bak = f"{real}.bak-{stamp}-{os.getpid()}" + (f"-{n}" if n else "")
            try:
                fd = os.open(bak, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                break
            except FileExistsError:
                continue
        with open(real, "rb") as src, os.fdopen(fd, "wb") as dst:
            dst.write(src.read())
    tmp = f"{real}.{os.getpid()}.tmp"
    with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, real)


def data_volumes():
    """The DATA_VOLUMES suffixes present on this machine (empty = no data), or None when docker cannot be
    asked (which is never "no data")."""
    try:
        out = subprocess.run(["docker", "volume", "ls", "--format", "{{.Name}}"], capture_output=True,
                             text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    pat = re.compile(r"(?:^|_)(%s)$" % "|".join(DATA_VOLUMES))
    return {m.group(1) for m in map(pat.search, out.stdout.split()) if m}


def public_hashes():
    try:
        with open(PUBLIC_FILE, encoding="utf-8") as fh:
            return {ln.strip() for ln in fh if re.fullmatch(r"[0-9a-f]{64}", ln.strip())}
    except FileNotFoundError:
        return set()


TEMPLATES = (".env.ex", ".env.example")


def history_hashes(*places):
    """sha256 of every value a TABLE or secret-named key ever had in the templates (TEMPLATES), read from the git
    history of each checkout in `places` (each repository once) in ONE `git log -p` apiece — every ref, every side
    of a merge (`--full-history -m`) — kept in memory and never written (DGO-1015). PUBLIC_FILE holds only
    high-entropy values — a short one's hash could be reversed, and the file is public — so an office still running
    the template's 8-character database password was named by nothing; its own history names it. A DSN's embedded
    password (`scheme://user:pw@`) counts too. set() without a git history."""
    out, seen = set(), set()
    for where in places:
        try:
            top = subprocess.run(["git", "-C", where, "rev-parse", "--show-toplevel"], capture_output=True,
                                 encoding="utf-8", errors="replace", timeout=30).stdout.strip()
            if not top or top in seen:
                continue
            seen.add(top)
            r = subprocess.run(["git", "-C", top, "log", "--all", "--full-history", "-m", "-p", "--format=", "--",
                                *TEMPLATES], capture_output=True, encoding="utf-8", errors="replace", timeout=120)
        except (OSError, subprocess.TimeoutExpired):
            continue
        for ln in (r.stdout if r.returncode == 0 else "").splitlines():
            m = re.match(r"^[+-]([A-Z0-9_]+)=", ln)
            if m and (m.group(1) in TABLE or SECRETISH.search(m.group(1))):
                v = _value(ln[1:])
                for one in (v, *DSN_PW.findall(v)):
                    if not missing(one) and "$" not in one:          # `${POSTGRES_PASSWORD}` names, holds nothing
                        out.add(hashlib.sha256(one.encode()).hexdigest())
    return out


#: The password inside a connection string: postgres://user:PASSWORD@host
DSN_PW = re.compile(r"://[^:/@\s]+:([^@\s]+)@")


#: A key whose name says it is a secret, whether or not this script makes it (an outside provider's, an app's own).
SECRETISH = re.compile(r"PASS|SECRET|TOKEN|_KEY$|_PW$|PRIVATE|DSN")


def public_outside_table(path, known=None):
    """Names of secret-named keys this script does NOT make (EXTERNAL, APP_MADE, any other) that still hold a value
    a template once published, by its own git history and PUBLIC_FILE — each needs its own owner's rotation
    (DGO-1015). A DSN counts when its embedded password was published."""
    if known is None:
        known = public_hashes() | history_hashes(os.path.dirname(os.path.realpath(path)), ROOT)
    out = []
    for ln in read(path):
        m = re.match(r"^([A-Z0-9_]+)=", ln)
        if m and m.group(1) not in TABLE and SECRETISH.search(m.group(1)):
            v = _value(ln)
            if any(not missing(one) and "$" not in one and hashlib.sha256(one.encode()).hexdigest() in known
                   for one in (v, *DSN_PW.findall(v))):
                out.append(m.group(1))
    return out


#: How a key is rotated (DGO-1015), first match wins. A TABLE key named nowhere — and not LOCKED_BY data, nor
#: copied into n8n's credentials (N8N_COPIES) — is a TOKEN: no stored data behind it, and the only class the
#: verb rotates itself.
ROTATION = {
    # an identity others verify: chat's relay signs every event with it, and a new key makes every event already
    # signed unverifiable (apps/chat/app.json: "must stay stable … never re-minted")
    "locked": {"CHAT_RELAY_KEY"},
    "db-role": {"POSTGRES_PASSWORD", "AUTHENTIK_POSTGRES_PASSWORD", "GLITCHTIP_DB_PASSWORD", "SUPABASE_DB_PASSWORD",
                "PLANE_DB_PASSWORD", "SUPABASE_POSTGRES_PASSWORD", "SUPABASE_AUTHENTICATOR_PASSWORD", "N8N_DB_DSN"},
    "redis": {"REDIS_PASSWORD"},
    "signing": {"SUPABASE_JWT_SECRET", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_KEY"},
    "encryption": {"N8N_ENCRYPTION_KEY", "CONNECTIONS_ROOT_KEY", "BROWSER42_STATE_PASSPHRASE"},
    "account": {"N8N_OWNER_PASSWORD", "GLITCHTIP_ADMIN_PASSWORD", "AUTHENTIK_BOOTSTRAP_PASSWORD",
                "AUTHENTIK_BOOTSTRAP_TOKEN", "SUPABASE_DASHBOARD_PASSWORD", "PLANE_S3_SECRET_KEY", "LOCALMAIL_PW",
                "PLANE_OWNER_PASSWORD", "PORTAINER_ADMIN_PASSWORD", "BROWSER42_VNC_PASSWORD"},
    "app-made": set(APP_MADE),
    "external": set(EXTERNAL),
}
#: Secret-SHAPED names that are not secrets this office keeps: lists of which keys travel, an address GlitchTip
#: issues (a DSN carries its project key, and GlitchTip makes it again).
NOT_SECRETS = re.compile(r"^DGO_(SERVE|TAKE)_SECRETS$|_SENTRY_DSN$")
#: Files that COPY a key into n8n's own database: the env-managed credentials `bbox n8n push` re-PATCHes, which a
#: recreate does not (apps/n8n/app.json). A key they name rotates only with that push — not by the token step.
N8N_COPIES = re.compile(r"^apps/n8n/(blueprint\.yml$|credentials/)")
STEPS = {
    "token": "mint a new value; recreate every consumer below together (./scripts/dc up -d <services>); --check",
    "locked": "data on this office was made with it (LOCKED_BY): its own app's step, not this verb's",
    "n8n-copy": "n8n keeps a copy in its credentials: mint, write .env, recreate the readers AND `bbox n8n push` "
                "(it re-PATCHes the env-managed credentials) — not built yet",
    "app-made": "the app issues it (its own hook or API: n8n push-app, meet's prepare, plane's, portainer's): rotate "
                "through that app, never mint it here",
    "db-role": "verified backup; ALTER ROLE … PASSWORD inside the database; write .env; recreate the consumers; --check",
    "redis": "the release lane's recreate moves it to a secret file (DGO-1651)",
    "signing": "mint the secret; re-sign SUPABASE_ANON_KEY and SUPABASE_SERVICE_KEY from it; recreate every consumer "
               "of the three — n8n credentials that hold a key included",
    "account": "change it through the app's own CLI or API first, then .env; recreate the app",
    "encryption": "LAST, after a verified backup: decrypt what it protects inside its container, swap the key, "
                  "re-encrypt; nothing on screen",
    "external": "the provider's own console (the owner's item, DGO-1795), then paste it in the connections screen",
}


def rotation_class(key, root=None):
    if NOT_SECRETS.search(key):
        return None
    for cls, keys in ROTATION.items():
        if key in keys:
            return cls
    if not (key in TABLE or SECRETISH.search(key)):
        return None
    if key in LOCKED_BY:
        return "locked"
    if consumers(key, root)["n8n_copies"]:
        return "n8n-copy"
    return "token"


_TREES = {}


def _tree(root):
    """[(path, text)] of the tracked text files a key's consumers live in, read once per run and root."""
    if root not in _TREES:
        rows = []
        try:
            files = subprocess.run(["git", "-C", root, "ls-files", "-z"], capture_output=True, timeout=60).stdout
        except (OSError, subprocess.TimeoutExpired):
            files = b""
        for rel in sorted(p for p in files.decode("utf-8", "replace").split("\0") if p):
            if rel.split("/")[0] not in ("apps", "platform-base", "scripts", "platform", "packaging") \
                    or "/legacy/" in rel or rel == "scripts/env-secrets.py" or rel.startswith("scripts/test_"):
                continue
            try:
                with open(os.path.join(root, rel), encoding="utf-8") as fh:
                    rows.append((rel, fh.read()))
            except (OSError, UnicodeDecodeError):
                continue
        _TREES[root] = rows
    return _TREES[root]


def _compose_services(text):
    """[(service, its lines)] of a compose file's `services:` block — a reading by indentation, no YAML library
    (this script runs before an office has one)."""
    out, svc, inside = [], None, False
    for ln in text.splitlines():
        if re.match(r"^services:\s*$", ln):
            inside = True
            continue
        if inside and re.match(r"^\S", ln):
            inside = False
        m = inside and re.match(r"^  ([A-Za-z0-9_.-]+):\s*$", ln)
        if m:
            svc = m.group(1)
            out.append((svc, []))
        elif inside and svc:
            out[-1][1].append(ln.split("#", 1)[0])
    return out


_INDEX = {}


def _index(root):
    """One pass over the tree per run and root: {"interp": {KEY: [(compose, service)]}, "whole_env": [(compose,
    service)], "named": {KEY: [path]}}. A service reads the whole .env only when an `env_file` entry resolves to
    the office's own `.env` (relative to its compose file) — n8n's `path: .env` is apps/n8n/.env, optional and
    absent, and reads nothing of the office's."""
    if root in _INDEX:
        return _INDEX[root]
    office_env = os.path.realpath(os.path.join(root, ".env"))
    idx = {"interp": {}, "whole_env": [], "named": {}}
    for rel, text in _tree(root):
        for tok in set(re.findall(r"(?<![A-Za-z0-9_])[A-Z][A-Z0-9_]{2,}(?![A-Za-z0-9_])", text)):
            idx["named"].setdefault(tok, []).append(rel)
        if not re.search(r"(^|/)docker-compose[^/]*\.ya?ml$", rel):
            continue
        here = os.path.dirname(os.path.join(root, rel))
        for svc, lines in _compose_services(text):
            for tok in set(re.findall(r"\$\{?([A-Z][A-Z0-9_]*)", "\n".join(lines))):
                idx["interp"].setdefault(tok, []).append((rel, svc))
            files = []
            for i, ln in enumerate(lines):
                m = re.match(r"^(\s+)env_file:\s*(\S*)\s*$", ln)
                if not m:
                    continue
                if m.group(2):                                   # env_file: ../../.env
                    files.append(m.group(2))
                ind = len(m.group(1))
                for nxt in lines[i + 1:]:                        # - ../../.env | - path: .env (+ required: …)
                    if not nxt.strip():
                        continue
                    depth = len(nxt) - len(nxt.lstrip())
                    if depth < ind or (depth == ind and not nxt.lstrip().startswith("- ")):
                        break
                    f = re.match(r"^\s*-?\s*(?:path:\s*)?([^\s:]+)\s*$", nxt)
                    if f:
                        files.append(f.group(1))
            if any(os.path.realpath(os.path.join(here, f.strip("'\""))) == office_env for f in files):
                idx["whole_env"].append((rel, svc))
    _INDEX[root] = idx
    return idx


def consumers(key, root=None):
    """Who reads `key`, from the tracked tree at `root`: compose services that interpolate it (`${KEY…}`, `$KEY`),
    services that load the office's whole .env (they read every key), the files that copy it into n8n's
    credentials (N8N_COPIES), and the blueprints and code or docs that name it. Names only."""
    root = root or ROOT
    idx = _index(root)
    out = {"services": [f"{r}: {s}" for r, s in idx["interp"].get(key, [])],
           "whole_env": [], "n8n_copies": [], "blueprints": [], "code": []}
    out["whole_env"] = [f"{r}: {s}" for r, s in idx["whole_env"] if f"{r}: {s}" not in out["services"]]
    for rel in idx["named"].get(key, []):
        if re.search(r"(^|/)docker-compose[^/]*\.ya?ml$", rel):
            continue
        bucket = "n8n_copies" if N8N_COPIES.search(rel) else "blueprints" if "/blueprint/" in rel else "code"
        out[bucket].append(rel)
    return out


def rotation_plan(key, root=None):
    """Lines that say how `key` would be rotated and who it touches — writes nothing, prints no value."""
    cls = rotation_class(key, root)
    if cls is None:
        return [f"{key}: not a secret this office keeps — nothing to rotate"]
    c = consumers(key, root)
    lines = [f"{key} — {cls}: {STEPS[cls]}",
             f"  compose services that read it ({len(c['services'])}):"] + [f"    {s}" for s in c["services"]]
    lines += [f"  services that load a whole env file, and so read it too ({len(c['whole_env'])}):"] + \
        [f"    {s}" for s in c["whole_env"]]
    lines += [f"  blueprints that name it ({len(c['blueprints'])}):"] + [f"    {b}" for b in c["blueprints"]]
    lines += [f"  code and docs that name it ({len(c['code'])}):"] + [f"    {x}" for x in c["code"]]
    return lines


def rotate(path, key, root=None, run=subprocess.run, popen=subprocess.Popen, killpg=os.killpg):
    """Rotate ONE key of the TOKEN class on this office (DGO-1015) → (exit code, one sentence, names only).

    A token has no stored data behind it: a new value in .env (backed up by write()), and every RUNNING, enabled
    service that reads it — interpolated, or through the office's whole .env — recreated together and waited on
    until healthy. Or nothing: any failure, a refused proof, Ctrl-C, SIGTERM or SIGHUP puts the key's own lines back
    and recreates the same services with them. Refused, writing nothing: another class (--plan names its steps); a
    key a blueprint or n8n's credentials hold a copy of; another file than the office's own .env; a key .env sets in
    another form than `KEY=` (export, indent); a reader restarting or paused; a reader whose container is not what the
    compose says now (it would deploy that too). Proof, from compose itself — the repo's own stale check
    (scripts/lib.sh stale_containers): `--dry-run up -d --no-build --no-deps <readers>` names NO container to
    recreate before the write, and EVERY reader after it. A caller outside this office that kept the old value is
    not seen here: --plan's code list is where to look first."""
    root = root or ROOT
    cls = rotation_class(key, root)
    if cls != "token" or key not in TABLE:
        return 2, f"{key}: class {cls} — only the token class rotates by this verb so far; --plan says its steps"
    if os.path.realpath(path) != os.path.realpath(os.path.join(root, ".env")):
        return 2, f"{key}: compose reads the office's own .env, not {path}; nothing written"
    c = consumers(key, root)
    if c["blueprints"] or c["n8n_copies"]:
        return 2, f"{key}: a blueprint or n8n's credentials hold a copy this cannot reach; nothing written"
    import fcntl
    lock = open(os.path.realpath(path) + ".rotate.lock", "a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        return 1, f"{key}: another rotation holds this office's .env; nothing written"
    try:
        return _rotate_locked(path, key, root, c, run, popen, killpg)
    finally:
        lock.close()


def _sh(run, cmd, timeout=300):
    try:
        r = run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout or ""
    except (OSError, subprocess.TimeoutExpired):
        return None, ""


def _states(run, dc):
    """({service: its container's state}, {container name: service}) from `dc ps -a --format json` (an array, or
    one object a line) — the second is how a dry run's container names are read back; None unread."""
    rc, out = _sh(run, [dc, "ps", "-a", "--format", "json"])
    if rc != 0:
        return None
    out = out.strip()
    try:
        rows = json.loads(out) if out.startswith("[") else [json.loads(x) for x in out.splitlines() if x.strip()]
    except ValueError:
        return None
    states, service_of = {}, {}
    for r in rows:
        if "com.docker.compose.oneoff=True" in (r.get("Labels") or ""):
            continue                                   # a `dc run` one-off is not the service's container
        svc = r.get("Service")
        if not svc:
            return None                                # a row compose cannot place: refuse rather than guess
        prev = states.get(svc)                         # several containers of one service: running only if all are
        states[svc] = r.get("State") if prev in (None, r.get("State")) else "mixed"
        service_of[r.get("Name")] = svc
    return states, service_of


def _foreign(run, dc, services):
    """The container names of `services` (as the compiled compose names them — `container_name`, else compose's
    `<project>-<svc>-1`) that the ENGINE holds in any project — scripts/lib.sh foreign_containers' reading: a reader
    compose does not list may still run, from another clone, on the old value. None when either cannot be read."""
    if not services:
        return []
    rc, out = _sh(run, [dc, "config", "--format", "json"])
    try:
        cfg = json.loads(out) if rc == 0 else None
    except ValueError:
        cfg = None
    if not isinstance(cfg, dict):
        return None
    defs = cfg.get("services") or {}
    names = {(defs.get(s) or {}).get("container_name") or f"{cfg.get('name', '')}-{s}-1" for s in services}
    rc, out = _sh(run, ["docker", "ps", "-a", "--format", "{{.Names}}"])
    return None if rc != 0 else sorted(set(out.split()) & names)


#: A dry run is a question: past the self-update guard (scripts/lib.sh compose_self_guard drops --dry-run), as
#: stale_containers asks it through _dcx_run_for.
DRY_ENV = dict(os.environ, COMPOSE_GUARD_OFF="1")


def _recreates(run, dc, targets):
    """The containers compose would RECREATE for `targets` now (its own dry run, as stale_containers reads it)."""
    try:                                              # compose prints its progress on STDERR (stale_containers: 2>&1)
        r = run([dc, "--dry-run", "up", "-d", "--no-build", "--no-deps", *targets],
                capture_output=True, text=True, timeout=120, env=DRY_ENV)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    plain = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", (r.stdout or "") + "\n" + (r.stderr or ""))
    # «Container <name> … Recreate» wherever it sits in the line, as lib.sh's stale_containers reads it: compose 2.40
    # prefixes every dry-run line with «DRY-RUN MODE -», and wanting «Container» first read every dry run as nothing
    # to recreate — the pending check never refused, and the after check failed every rotation that had readers
    names = set()
    for ln in plain.splitlines():
        t = ln.split()
        if t and t[-1] == "Recreate":
            i = next((j for j in range(len(t) - 2) if t[j] == "Container"), None)
            if i is not None:
                names.add(t[i + 1])
    return names


def _up_wait(popen, killpg, dc, targets, timeout=900):
    """`up -d --no-deps --wait` in a process group of its own: an interruption stops ALL of it (dc runs compose in
    a subshell, which a plain kill of dc leaves running) and waits for it before anything is restored."""
    import signal
    p = popen([dc, "up", "-d", "--no-build", "--no-deps", "--wait", "--wait-timeout", "180", *targets],
              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

    def stop():
        for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):   # a second signal must not cut the stop short:
            signal.signal(s, signal.SIG_IGN)                       # the caller's `finally` puts its handlers back
        for sig, grace in ((signal.SIGTERM, 30), (signal.SIGKILL, 30)):
            try:
                killpg(p.pid, sig)
            except OSError:
                pass
            try:
                p.wait(timeout=grace)
                return
            except subprocess.TimeoutExpired:
                continue
    try:
        return p.wait(timeout=timeout) == 0
    except subprocess.TimeoutExpired:
        stop()
        return False
    except BaseException:
        stop()
        raise


def _rotate_locked(path, key, root, c, run, popen, killpg):
    import signal
    dc = os.path.join(root, "scripts", "dc")
    plain = re.compile(r"^%s=" % re.escape(key))
    lines = read(path)                                   # read UNDER the lock
    if any(re.match(r"^\s*(export\s+)?%s\s*=" % re.escape(key), ln) and not plain.match(ln) for ln in lines):
        return 2, f"{key}: .env sets it in a form other than `{key}=…` (export, indent, spaces); nothing written"
    old = [ln for ln in lines if plain.match(ln)]
    if not old:
        return 2, f"{key}: not in the office's .env; nothing written"
    rc, out = _sh(run, [dc, "config", "--services"])
    seen = _states(run, dc)
    if rc != 0 or seen is None:
        return 1, f"{key}: the office's services could not be read (./scripts/dc config / ps); nothing written"
    states, service_of = seen
    readers = sorted({s.split(": ", 1)[1] for s in c["services"] + c["whole_env"]} & set(out.split()))
    # a container that exists and is not running keeps the env it was made with: `docker start`, a restart
    # policy or a boot brings it back on the OLD value while .env says the new one — so it is refused, as a
    # restarting or paused one is. A reader with no container at all is made fresh, with the new value.
    unsettled = [s for s in readers if states.get(s) not in (None, "running")]
    if unsettled:
        return 2, (f"{key}: {', '.join(unsettled)} exists but is not running (it would come back on the old value) "
                   f"— start it or remove it first; nothing written")
    targets = [s for s in readers if states.get(s) == "running"]
    absent = [s for s in readers if s not in states]   # no container compose lists — unless another project has one
    foreign = _foreign(run, dc, absent)
    if foreign is None:
        return 1, f"{key}: the engine could not be asked which containers it holds; nothing written"
    if foreign:
        return 2, (f"{key}: {', '.join(foreign)} runs under another compose project (it keeps the old value) — "
                   f"bbox status names it; nothing written")
    if targets:
        pending = _recreates(run, dc, targets)
        if pending is None:
            return 1, f"{key}: compose's dry run did not answer; nothing written"
        if pending:
            return 2, (f"{key}: {', '.join(sorted(pending))} would be recreated already — deploy that first, so the "
                       f"rotation carries the key alone; nothing written")
    mine = f"{key}={make(key, {})}"                    # a token's kind (hex, urlsafe, pw) needs no other value

    def restore(up=True):
        cur, olds = read(path), iter(old)
        write(path, "\n".join(next(olds, ln) if ln == mine else ln for ln in cur), backup=False)  # the rotation's
        return (not targets) or (not up) or _up_wait(popen, killpg, dc, targets)                 # backup holds it

    sigs = (signal.SIGTERM, signal.SIGHUP, signal.SIGINT)

    def interrupted(*_):                               # the FIRST signal stops the rotation; any after it is
        for s in sigs:                                 # ignored from this instant, so none can cut the stop or
            signal.signal(s, signal.SIG_IGN)           # the restore short
        raise KeyboardInterrupt("signal")
    previous = {s: signal.getsignal(s) for s in sigs}
    for s in sigs:                                     # an inherited ignore (nohup) stays an ignore
        if previous[s] is not signal.SIG_IGN:
            signal.signal(s, interrupted)

    def calm():                                        # the restore itself is not cut off by a second signal
        for s in sigs:
            signal.signal(s, signal.SIG_IGN)
    try:
        write(path, "\n".join(mine if plain.match(ln) else ln for ln in read(path)))   # the newest .env, its key
        if not targets:
            return 0, f"{key}: rotated; no service that reads it has a container yet — it is made with the new value"
        after = _recreates(run, dc, targets)
        recreated = {service_of.get(n) for n in after or ()}
        missed = [t for t in targets if after is None or t not in recreated]
        if missed:
            calm()
            restore(up=False)                          # nothing was recreated: the readers still run the old value
            return 1, (f"{key}: compose would not recreate {', '.join(missed)} with the new value — it never reached "
                       f"it; .env restored, nothing recreated")
        if _up_wait(popen, killpg, dc, targets):
            return 0, f"{key}: rotated; {len(targets)} service(s) recreated and healthy: {', '.join(targets)}"
        calm()
        back = restore()
        return 1, (f"{key}: {', '.join(targets)} did not come back healthy with the new value — .env restored and they "
                   f"were recreated with the old one ({'healthy' if back else 'NOT healthy: look at them now'})")
    except BaseException:
        calm()
        restore()
        raise
    finally:
        for s, h in previous.items():
            signal.signal(s, h if h is not None else signal.SIG_DFL)


def still_public(path, history=False, known=None):
    """Names of TABLE keys that are missing, or hold a value the template once published — with `history`, also
    every value the git history of the env file's checkout and of this script's shows it publishing
    (history_hashes); `known` is that set when the caller already read it."""
    out = []
    if known is None:
        known = public_hashes()
        if history:
            known |= history_hashes(os.path.dirname(os.path.realpath(path)), ROOT)
    current = {}
    for ln in read(path):
        m = re.match(r"^([A-Z0-9_]+)=", ln)
        if m:
            current[m.group(1)] = _value(ln)
    for key in TABLE:
        v = current.get(key, "")
        if missing(v) or hashlib.sha256(v.encode()).hexdigest() in known:
            out.append(key)
    return out


def main(argv):
    path = os.path.join(ROOT, ".env")
    if "--env" in argv:
        path = argv[argv.index("--env") + 1]
    modes = [m for m in ("--fill", "--if-fresh", "--check", "--rotate") if m in argv]
    if len(modes) > 1:                    # `--rotate --fill --plan` would have minted: one mode a run, said
        print(f"env-secrets: one mode at a time — {' and '.join(modes)} were given together; nothing written",
              file=sys.stderr)
        return 2
    if "--fill" in argv:
        filled = fill(path)
        print(f"env-secrets: {len(filled)} secret(s) minted for this office" + (f": {', '.join(filled)}" if filled else ""))
        return 0
    if "--if-fresh" in argv:
        present = data_volumes()
        if present is None:
            left = still_public(path)
            print("env-secrets: docker could not be asked whether this office has data, so nothing is written"
                  + (f". {len(left)} secret(s) are empty or still public: {', '.join(left)}" if left else ""),
                  file=sys.stderr)
            return 0
        if not present:
            filled = fill(path)
            print(f"env-secrets: no data on this machine yet — {len(filled)} secret(s) minted for this office"
                  + (f": {', '.join(filled)}" if filled else ""))
            return 0
        # Data exists: an EMPTY key whose own app keeps no data yet is still made (an app switched on later
        # needs its keys); a key whose data exists, or that holds a placeholder in use, is only named.
        def may(key, value):
            return not value and not (set(LOCKED_BY.get(key, ())) & present)
        filled = fill(path, may)
        if filled:
            print(f"env-secrets: this office has data — {len(filled)} empty secret(s) of apps that keep none yet "
                  f"minted: {', '.join(filled)}")
        left = still_public(path)
        if left:
            print(f"env-secrets: this office has data, so these are not replaced. {len(left)} secret(s) are empty or "
                  f"still a value the template published: {', '.join(left)} — rotate them (DGO-1015)", file=sys.stderr)
        return 0
    if "--rotate" in argv:
        at = argv.index("--rotate")
        words = [a for i, a in enumerate(argv) if i > at and not a.startswith("--") and argv[i - 1] != "--env"]
        keys = [a for a in words if re.fullmatch(r"[A-Z][A-Z0-9_]*", a)]
        if len(keys) != len(words):
            print("env-secrets: --rotate takes key NAMES only (A-Z, 0-9, _) — a word that is not one was refused "
                  "and is not repeated here", file=sys.stderr)
            return 2
        if "--plan" not in argv:
            if not keys:
                print("env-secrets: --rotate KEY… names the keys it rotates (--plan alone may take them all)",
                      file=sys.stderr)
                return 2
            rc = 0
            for key in keys:
                code, said = rotate(path, key)
                print(f"env-secrets: {said}", file=sys.stderr if code else sys.stdout)
                rc = max(rc, code)
            return rc
        if not keys:
            known = public_hashes() | history_hashes(os.path.dirname(os.path.realpath(path)), ROOT)
            keys = still_public(path, known=known) + public_outside_table(path, known)
        for key in keys:
            print("\n".join(rotation_plan(key)))
        return 0
    if "--check" in argv:
        known = public_hashes() | history_hashes(os.path.dirname(os.path.realpath(path)), ROOT)   # read once
        left = still_public(path, known=known)
        print(f"env-secrets: {len(left)} secret(s) empty or still public" + (f": {', '.join(left)}" if left else ""))
        other = public_outside_table(path, known)
        if other:
            print(f"env-secrets: {len(other)} more secret-named key(s) this script does not make still hold a value "
                  f"the template published: {', '.join(other)}")
        return 1 if left or other else 0
    sys.stderr.write(__doc__.split("\n\n")[1] + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
