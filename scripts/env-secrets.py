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


def owner_for(real):
    """(uid, gid) the rewritten file keeps: the old file's owner, unless that was root — then the owner of the
    directory the file is in (the checkout, for an office's .env). The new file is created by whoever runs this,
    and on an office with two writers that is often root (the follow cycle, bina-ds), while the office's own user
    (Bina Claude) runs bbox as itself: measured on the HP, 2026-11-12 18:36Z, the follow cycle's write left .env
    root:root 0600, and from then on every bbox the office user ran read no .env — DEPLOYMENT_NAME fell back to
    bina-deployment, Plane «does not run on this office», no DGO_BRANCH (DGO-1863). None when nothing is to be
    changed (no fchown here, or root's file in root's directory)."""
    if not hasattr(os, "fchown"):
        return None
    try:
        st = os.stat(real)
        if st.st_uid != 0:
            return st.st_uid, st.st_gid
    except FileNotFoundError:
        pass
    d = os.stat(os.path.dirname(real))
    return (d.st_uid, d.st_gid) if d.st_uid != 0 else None


def write(path, text, backup=True):
    real = os.path.realpath(path)
    owner = owner_for(real)
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
        if owner:
            try:
                os.fchown(fh.fileno(), *owner)   # the open file, never a path that could be swapped meanwhile
            except OSError:                      # not root (EPERM), an unmapped id (EINVAL): the writer owns what it
                pass                             # wrote and may read it, and the write itself must not fail here
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
#: copied into n8n's credentials (N8N_COPIES) — is a TOKEN: no stored data behind it. The verb rotates a token, and an
#: n8n-copy key (a token n8n also keeps, re-seeded with it).
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
#: The signing class, in the order it is minted: the secret first, then the two keys signed with the NEW secret.
SIGNING = ("SUPABASE_JWT_SECRET", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_KEY")
# The database's OWN copy (app.settings.jwt_secret, written once at init by volumes/db/jwt.sql) is NOT moved: nothing
# in this stack reads it — PostgREST sets that setting on every request from its own environment
# (PGRST_APP_SETTINGS_JWT_SECRET, apps/supabase/docker-compose.yml), and GoTrue and realtime do not run — and the
# `postgres` role may not ALTER DATABASE … SET on supabase/postgres once its init demoted it (the signing class's
# reader). db is still recreated with the rest: compose gives it the secret, so leaving it would be a restart of the
# platform database at the next deploy instead of this planned one.
#: Secret-SHAPED names that are not secrets this office keeps: lists of which keys travel, an address GlitchTip
#: issues (a DSN carries its project key, and GlitchTip makes it again).
NOT_SECRETS = re.compile(r"^DGO_(SERVE|TAKE)_SECRETS$|_SENTRY_DSN$")
#: Files that COPY a key into n8n's own database: the env-managed credentials `bbox n8n push` re-PATCHes, which a
#: recreate does not (apps/n8n/app.json). A key they name rotates only with that push — not by the token step.
N8N_COPIES = re.compile(r"^apps/n8n/(blueprint\.yml$|credentials/)")
#: The copies that push re-PATCHes from .env (its step 1.5) are the `  <id>: {json}` lines after
#: `credential_overrides:` in the blueprint, each `${VAR}` in its data's strings — and only those: a copy in
#: apps/n8n/credentials/ is imported once and never re-seeded. `--reseed-only` runs that step alone (DGO-1015).
N8N_BLUEPRINT = "apps/n8n/blueprint.yml"
N8N_OVERRIDE = re.compile(r"^\s{2}([A-Za-z0-9_-]+):\s*(\{.*\})\s*$")
N8N_RESEED = ("apps", "n8n", "hooks", "push")
#: What the re-seed says that may be repeated: its own summary lines — credential ids, variable names and counts,
#: never a value nor n8n's answer body.
RESEED_SAID = re.compile(r"reseeded \d+/\d+ .*|reseed-only: .*|SKIP [A-Za-z0-9_-]+|could not log in as owner|"
                         r"reseed [A-Za-z0-9_-]+ HTTP \d+|is BEHIND its office's branch|'[A-Za-z0-9_.-]+' not running|"
                         r"LOCKED — another push is already running|still locked after \d+m|"
                         r"n8n push refused[^.]*\. Nothing was changed|"
                         r"N8N_ENCRYPTION_KEY in \.env does not match the running instance")
STEPS = {
    "token": "mint a new value; recreate every consumer below together (./scripts/dc up -d <services>); --check",
    "locked": "data on this office was made with it (LOCKED_BY): its own app's step, not this verb's",
    "n8n-copy": "n8n keeps a copy in its env-managed credentials: the re-seed proven on today's .env, mint, write "
                ".env, recreate the readers, then `bbox n8n push all --reseed-only` re-PATCHes the copy (nothing "
                "restarted) — or all of it is undone, n8n's copy included; a key n8n itself reads goes with "
                "`bbox n8n push all`",
    "app-made": "the app issues it (its own hook or API: n8n push-app, meet's prepare, plane's, portainer's): rotate "
                "through that app, never mint it here",
    "db-role": "verified backup; ALTER ROLE … PASSWORD inside the database; write .env; recreate the consumers; --check",
    "redis": "the release lane's recreate moves it to a secret file (DGO-1651)",
    "signing": "the three rotate together, whichever is named (a key re-signed with the same secret leaves the old one "
               "valid): mint the secret, sign both keys with the new one, recreate every reader of the three (db "
               "included: a planned restart of the platform database), re-seed n8n's copy of the service key — or "
               "undo all of it",
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
    keys = list(SIGNING) if cls == "signing" else [key]   # the signing class's readers are those of all three
    per = [consumers(k, root) for k in keys]
    c = {b: sorted({x for p in per for x in p[b]}) for b in per[0]}
    lines = [f"{key} — {cls}: {STEPS[cls]}"]
    if len(keys) > 1:
        lines.append(f"  rotates with: {', '.join(k for k in keys if k != key)} — the readers below are all three's")
    lines += [
             f"  compose services that read it ({len(c['services'])}):"] + [f"    {s}" for s in c["services"]]
    lines += [f"  services that load a whole env file, and so read it too ({len(c['whole_env'])}):"] + \
        [f"    {s}" for s in c["whole_env"]]
    lines += [f"  blueprints that name it ({len(c['blueprints'])}):"] + [f"    {b}" for b in c["blueprints"]]
    lines += [f"  code and docs that name it ({len(c['code'])}):"] + [f"    {x}" for x in c["code"]]
    return lines


def n8n_overrides(root):
    """{credential id: the ${VAR}s its data names} — n8n's env-managed credentials as the push hook's step 1.5 reads
    them: each line after `credential_overrides:` shaped `  <id>: {json}`, the names in its data's strings; an entry
    whose JSON does not parse is dropped, as the hook drops it."""
    try:
        with open(os.path.join(root, N8N_BLUEPRINT), encoding="utf-8") as fh:
            lines = fh.read().split("\n")
    except OSError:
        return {}
    out, on = {}, False
    for ln in lines:
        on = on or ln.startswith("credential_overrides:")
        m = N8N_OVERRIDE.match(ln) if on else None
        if not m:
            continue
        try:
            spec = json.loads(m.group(2))
        except ValueError:
            continue
        data = spec.get("data") if isinstance(spec, dict) else None
        names = set()
        for v in (data.values() if isinstance(data, dict) else ()):
            if isinstance(v, str):
                names.update(re.findall(r"\$\{([A-Za-z0-9_]+)\}", v))
        out[m.group(1)] = names
    return out


def lease_readers(key, root):
    """The services that LEASE `key` from connections when they start (an app's `broker`: its blank_env names the
    key, its entrypoint asks connections for it). Compose blanks the key in them, so its dry run never sees them
    change: a rotation recreates them itself, after connections serves the new value."""
    import glob
    out = set()
    for f in glob.glob(os.path.join(root, "apps", "*", "app.json")) + \
            glob.glob(os.path.join(root, "platform-base", "*", "app.json")):
        try:
            with open(f, encoding="utf-8") as fh:
                app = json.load(fh)
            broker = app.get("broker") or {}
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(broker, dict) and key in (broker.get("blank_env") or []):
            # the compiler's own fallback for a broker that names no service: its first route's, then the app's id
            # (platform/manager/reconcile.py, the Go twin render.go)
            routing = app.get("routing") or [{}]
            service = broker.get("service") or (routing[0].get("service") if isinstance(routing[0], dict) else None) \
                or app.get("id")
            if service:
                out.add(service)
    return sorted(out)


def _env_resolved(lines, name):
    """read_env's value (scripts/lib.sh), which the push hook hands its re-seed: the FIRST `name=` line, `${X}` and
    `${X:-default}` resolved leftmost first, 20 at most — so «set» means here what it means there."""
    def raw(n):
        return next((ln[len(n) + 1:].replace("\r", "") for ln in lines if ln.startswith(n + "=")), "")
    v = raw(name)
    for _ in range(20):                                # read_env's own steps, an unclosed `${` included
        i = v.find("${")
        if i < 0:
            break
        pre, rest = v[:i], v[i + 2:]
        j = rest.find("}")
        sub, rest = (rest[:j], rest[j + 1:]) if j >= 0 else (rest, rest)
        ref, dflt = sub.split(":-", 1) if ":-" in sub else (sub, "")
        v = pre + (raw(ref) or dflt) + rest
    return v


def _n8n_gap(key, root, lines):
    """Why the re-seed would leave n8n's copy of `key` on the old value — None when it would not: no
    credential_overrides entry names it, or one that does names another variable .env leaves empty (the hook SKIPS
    that whole credential rather than blank it, and calls the run fine)."""
    mine = {cid: names for cid, names in n8n_overrides(root).items() if key in names}
    if not mine:
        return f"n8n's copy is not one the re-seed reaches (no credential_overrides entry in {N8N_BLUEPRINT} names it)"
    empty = sorted({n for names in mine.values() for n in names if n != key and not _env_resolved(lines, n)})
    if empty:
        return (f"the re-seed would SKIP n8n's credential {', '.join(sorted(mine))} and leave it on the old value — "
                f"{', '.join(empty)} empty in .env")
    return None


def rotate(path, key, root=None, run=subprocess.run, popen=subprocess.Popen, killpg=os.killpg):
    """Rotate ONE key of the TOKEN or N8N-COPY class — or the SIGNING class's three together — on this office (DGO-1015)
    → (exit code, one sentence, names only). The signing secret and the two keys it signs go as one (a key re-signed
    with the same secret leaves the old key valid): every reader of the three recreated together, then n8n's copy of
    the service key re-seeded; a failure at any step undoes every step before it. The database's own init-time copy
    is not moved — nothing here reads it (see SIGNING).

    A token has no stored data behind it: a new value in .env (backed up by write()), and every RUNNING, enabled
    service that reads it — interpolated, or through the office's whole .env — recreated together and waited on
    until healthy. Or nothing: any failure, a refused proof, Ctrl-C, SIGTERM or SIGHUP puts the key's own lines back
    and recreates the same services with them. An n8n-copy key is a token n8n also keeps in an env-managed
    credential: the re-seed (`apps/n8n/hooks/push --reseed-only`, no restart) runs once on today's .env as its own
    proof, then after the readers it re-PATCHes that copy from the new .env; if it does not take, everything is
    undone and it runs again on the old .env (a cut-off one waited out inside n8n first) — said, on a signal too.
    Refused, writing nothing: another class (--plan names its steps); a key a blueprint holds a copy of; an n8n copy
    the re-seed does not reach or would SKIP (another variable of that credential empty); a key n8n itself reads (its
    restart is the full push's); n8n present but not running, or under another project; a re-seed that does not run
    on today's .env; another file
    than the office's own .env; a key .env sets in another form than `KEY=` (export, indent); a reader restarting or
    paused; a reader whose container is not what the compose says now (it would deploy that too). Proof, from compose
    itself — the repo's own stale check (scripts/lib.sh stale_containers): `--dry-run up -d --no-build --no-deps
    <readers>` names NO container to recreate before the write, and EVERY reader after it. A caller outside this
    office that kept the old value is not seen here: --plan's code list is where to look first."""
    root = root or ROOT
    cls = rotation_class(key, root)
    if cls not in ("token", "n8n-copy", "signing") or key not in TABLE:
        return 2, (f"{key}: class {cls} — only the token, n8n-copy and signing classes rotate by this verb so far; "
                   f"--plan says its steps")
    if os.path.realpath(path) != os.path.realpath(os.path.join(root, ".env")):
        return 2, f"{key}: compose reads the office's own .env, not {path}; nothing written"
    # the signing class rotates WHOLE: a key re-signed with the same secret leaves the old key valid, so the secret
    # and both keys it signs go together, whichever of the three was named
    keys = list(SIGNING) if cls == "signing" else [key]
    per = {k: consumers(k, root) for k in keys}
    c = {b: sorted({x for k in keys for x in per[k][b]}) for b in per[keys[0]]}
    c["seeded_keys"] = [k for k in keys if per[k]["n8n_copies"]]
    c["lease"] = sorted({s for k in keys for s in lease_readers(k, root)})
    key = keys[0]
    if c["blueprints"]:
        return 2, f"{key}: a blueprint holds a copy this cannot reach; nothing written"
    beyond = [p for p in c["n8n_copies"] if p != N8N_BLUEPRINT]
    if beyond:
        return 2, (f"{key}: {', '.join(beyond)} holds a copy the re-seed never reaches (only {N8N_BLUEPRINT}'s "
                   f"credential_overrides are re-seeded); nothing written")
    import fcntl
    lock = open(os.path.realpath(path) + ".rotate.lock", "a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        return 1, f"{key}: another rotation holds this office's .env; nothing written"
    try:
        return _rotate_locked(path, keys, root, c, run, popen, killpg)
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


def _relet(popen, killpg, dc, services, timeout=900):
    """Lease readers recreated even though compose sees no change in them, so each asks connections again at start."""
    return _group(popen, killpg, [dc, "up", "-d", "--no-build", "--no-deps", "--force-recreate", "--wait",
                                  "--wait-timeout", "180", *services], timeout) == 0


def _up_wait(popen, killpg, dc, targets, timeout=900):
    """`up -d --no-deps --wait`, in a process group of its own (_group) → whether it came up."""
    return _group(popen, killpg, [dc, "up", "-d", "--no-build", "--no-deps", "--wait", "--wait-timeout", "180",
                                  *targets], timeout) == 0


def _reseed(popen, killpg, root, timeout=1200):
    """`apps/n8n/hooks/push --reseed-only` (DGO-1015): n8n's env-managed credentials re-PATCHed from .env as it is
    now, nothing restarted; strict — a credential that does not take, or no owner session, exits 3 → (taken, what it
    said: its own summary lines, names and counts only, whether it ENDED by itself). The limit is past the hook's own
    15-minute wait for its lock, so a held lock is said in the hook's words."""
    import tempfile
    with tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace") as fh:
        rc = _group(popen, killpg, ["bash", os.path.join(root, *N8N_RESEED), "--reseed-only"], timeout, out=fh)
        fh.seek(0)
        said = [m.group(0) for m in map(RESEED_SAID.search, fh.read().split("\n")) if m]
    tail = f", exit {rc}" if rc else f", no answer in {timeout} s — stopped" if rc is None else ""
    return rc == 0, ("; ".join(said[-3:]) or "nothing said") + tail, rc is not None


#: A re-seed cut off from outside (a signal, the limit) still runs INSIDE n8n — `docker exec`'s process outlives its
#: client — and its PATCHes of the new value could land after the undo's of the old one: waited out first (2 min).
#: Matched by the marker the hook puts FIRST in the re-seed's node script (`/*dgo-reseed*/`): busybox's pgrep reads only
#: the first 1023 bytes of a command line, and a phrase deeper in the script is never seen.
RESEED_SETTLE = ('command -v pgrep >/dev/null 2>&1 || exit 2; i=0; '
                 'while pgrep -f "[d]go-reseed" >/dev/null 2>&1; do '
                 'i=$((i+1)); [ "$i" -ge 120 ] && exit 1; sleep 1; done')


def _reseed_settled(run, dc):
    """Whether no cut-off re-seed still runs inside n8n (False: one still runs, or it cannot be told)."""
    return _sh(run, [dc, "exec", "-T", "n8n", "sh", "-c", RESEED_SETTLE], timeout=180)[0] == 0


def _group(popen, killpg, cmd, timeout, out=None):
    """`cmd` in a process group of its own → its exit code, None when it overran `timeout`: an interruption stops
    ALL of it (dc runs compose in a subshell, which a plain kill of dc leaves running) and waits for it before
    anything is restored. `out`, a file: its stdout and stderr; none: both dropped."""
    import signal
    p = popen(cmd, stdout=out if out is not None else subprocess.DEVNULL,
              stderr=subprocess.STDOUT if out is not None else subprocess.DEVNULL, start_new_session=True)

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
        return p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        stop()
        return None
    except BaseException:
        stop()
        raise


def _rotate_locked(path, keys, root, c, run, popen, killpg):
    import signal
    dc = os.path.join(root, "scripts", "dc")
    key = keys[0]                                        # what a sentence names: the one key, or the signing secret
    plains = {k: re.compile(r"^%s=" % re.escape(k)) for k in keys}

    def whose(ln):
        return next((k for k in keys if plains[k].match(ln)), None)
    lines = read(path)                                   # read UNDER the lock
    for k in keys:
        if any(re.match(r"^\s*(export\s+)?%s\s*=" % re.escape(k), ln) and not plains[k].match(ln) for ln in lines):
            return 2, f"{k}: .env sets it in a form other than `{k}=…` (export, indent, spaces); nothing written"
    old = {k: [ln for ln in lines if plains[k].match(ln)] for k in keys}
    missing = [k for k in keys if not old[k]]
    if missing:
        return 2, f"{', '.join(missing)}: not in the office's .env; nothing written"
    rc, out = _sh(run, [dc, "config", "--services"])
    seen = _states(run, dc)
    if rc != 0 or seen is None:
        return 1, f"{key}: the office's services could not be read (./scripts/dc config / ps); nothing written"
    states, service_of = seen
    # a lease reader takes the key from connections at start (lease_readers): out of compose's proof, recreated by
    # this verb itself after connections serves the new value
    lease = sorted(set(c.get("lease", [])) & set(out.split()))
    readers = sorted(({s.split(": ", 1)[1] for s in c["services"] + c["whole_env"]} & set(out.split())) - set(lease))
    # a container that exists and is not running keeps the env it was made with: `docker start`, a restart
    # policy or a boot brings it back on the OLD value while .env says the new one — so it is refused, as a
    # restarting or paused one is. A reader with no container at all is made fresh, with the new value.
    unsettled = [s for s in readers + lease if states.get(s) not in (None, "running")]
    if unsettled:
        return 2, (f"{key}: {', '.join(unsettled)} exists but is not running (it would come back on the old value) "
                   f"— start it or remove it first; nothing written")
    leased = [s for s in lease if states.get(s) == "running"]
    if leased and states.get("connections") != "running":
        return 2, (f"{key}: {', '.join(leased)} lease(s) it from connections, which is not running here — start it "
                   f"first; nothing written")
    seed = bool(c["n8n_copies"])                       # n8n keeps a copy: the re-seed is the rotation's last step
    n8n_up = False
    if seed:
        for k in c["seeded_keys"]:
            gap = _n8n_gap(k, root, lines)
            if gap:
                return 2, f"{k}: {gap}; nothing written"
        # n8n itself reading it means recreating n8n: in-flight chains killed and their doc_step locks left held —
        # the full push restarts the runners after it and sweeps those locks (apps/n8n/hooks/push), this does not
        if any(s.startswith("apps/n8n/") for s in c["services"] + c["whole_env"]):
            return 2, (f"{key}: n8n itself reads it, so its rotation restarts n8n — that is `bbox n8n push all`'s "
                       f"(the runners after it, the doc_step locks swept), not this verb's; nothing written")
        if states.get("n8n") not in (None, "running"):
            return 2, (f"{key}: n8n exists but is not running (it would come back holding the old copy) — start it "
                       f"or remove it first; nothing written")
        if "n8n" not in states:
            elsewhere = _foreign(run, dc, ["n8n"])
            if elsewhere is None:
                return 1, f"{key}: the engine could not be asked which containers it holds; nothing written"
            if elsewhere:
                return 2, (f"{key}: n8n runs under another compose project ({', '.join(elsewhere)}) — its copy would "
                           f"stay on the old value; nothing written")
        n8n_up = states.get("n8n") == "running"
    targets = [s for s in readers if states.get(s) == "running"]
    absent = [s for s in readers + lease if s not in states]   # no container compose lists — unless another
    if leased and "connections" not in targets:                 # project has one; a lease reader asks connections,
        return 2, (f"{key}: {', '.join(leased)} lease(s) it from connections, which this rotation would not recreate "
                   f"— it would keep serving the old value; nothing written")   # which must serve the new value
    foreign = _foreign(run, dc, absent)
    if foreign is None:
        return 1, f"{key}: the engine could not be asked which containers it holds; nothing written"
    if foreign:
        return 2, (f"{key}: {', '.join(foreign)} runs under another compose project (it keeps the old value) — "
                   f"bbox status names it; nothing written")
    if targets or leased:                              # a lease reader's force-recreate would deploy what it has pending
        pending = _recreates(run, dc, targets + leased)
        if pending is None:
            return 1, f"{key}: compose's dry run did not answer; nothing written"
        if pending:
            return 2, (f"{key}: {', '.join(sorted(pending))} would be recreated already — deploy that first, so the "
                       f"rotation carries the key alone; nothing written")
    if n8n_up:
        # the re-seed proves itself on the .env as it is, before anything moves: its push guard, its lock, n8n's key
        # fingerprint, the owner's session and EVERY env-managed credential taking — an office where it cannot run
        # is told now, not after the readers were recreated twice (it PATCHes today's values again: a push's own step)
        handlers = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT)}
        try:
            ok, hook, _ = _reseed(popen, killpg, root)
        finally:                                       # a proof stopped at its limit leaves them ignored (_group's
            for s, h in handlers.items():              # stop): put back, so the rotation — or the next — can be
                signal.signal(s, h if h is not None else signal.SIG_DFL)   # stopped and undone
        if not ok:
            return 1, (f"{key}: n8n's re-seed does not run on this office as it is ({hook}) — fix that first, so the "
                       f"rotation can carry n8n's copy; nothing written")
    new = {}
    for k in keys:                                     # in order: the signing secret first, then the keys signed
        new[k] = make(k, new)                          # with the NEW one; a token's kind needs no other value
    mine = {k: f"{k}={new[k]}" for k in keys}
    del new

    relet = []                                         # the lease readers were recreated: lease the old value again

    def restore(up=True):
        cur, olds, back = read(path), {k: iter(old[k]) for k in keys}, {v: k for k, v in mine.items()}
        write(path, "\n".join(next(olds[back[ln]], ln) if ln in back else ln for ln in cur), backup=False)  # the
        ok = (not targets) or (not up) or _up_wait(popen, killpg, dc, targets)              # rotation's backup holds it
        if up and relet:                               # after connections is back on the old value
            ok = _relet(popen, killpg, dc, leased) and ok
        return ok

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
    reseeded = []                                      # the re-seed started: its PATCHes may have taken — undo them too

    def unseed(ended):
        """n8n back on the restored .env → what to say of it. A re-seed cut off from outside may still PATCH inside
        n8n: waited out first, and said when it could not be."""
        settled = ended or _reseed_settled(run, dc)
        if not _reseed(popen, killpg, root)[0]:
            return "; n8n could NOT be re-seeded with the old one: run `bbox n8n push all --reseed-only` now"
        if not settled:
            return (", n8n re-seeded with the old one — but the cut-off re-seed could not be seen to end inside n8n: "
                    "run `bbox n8n push all --reseed-only` again in two minutes")
        return ", n8n re-seeded with the old one"

    def seeded(said):
        """An n8n-copy key's last step: n8n's copy follows the new .env — or the rotation is undone, n8n's copy
        included (the re-seed runs again on the restored .env)."""
        if not seed:
            return 0, said
        if not n8n_up:
            return 0, (f"{said}; n8n has no container here — once it runs, `bbox n8n push all --reseed-only` gives its "
                       f"credentials the new value")
        reseeded.append(True)
        ok, hook, ended = _reseed(popen, killpg, root)
        if ok:
            return 0, f"{said}; n8n's credentials re-seeded ({hook})"
        calm()
        back = restore()
        untouched = "Nothing was changed" in hook       # its push guard refused before any PATCH: n8n holds the old
        return 1, (f"{key}: n8n's credentials did not take the new value ({hook}) — .env restored"
                   + (f", {', '.join(targets + (leased if relet else []))} recreated with the old one "
                      f"({'healthy' if back else 'NOT healthy: look at them now'})" if targets else "")
                   + (", n8n untouched (its re-seed was refused before any PATCH)" if untouched else unseed(ended)))
    try:
        write(path, "\n".join(mine.get(whose(ln), ln) for ln in read(path)))   # the newest .env, its key(s)
        if not targets:
            return seeded(f"{key}: rotated; no service that reads it has a container yet — it is made with the new "
                          f"value")
        after = _recreates(run, dc, targets)
        recreated = {service_of.get(n) for n in after or ()}
        missed = [t for t in targets if after is None or t not in recreated]
        if missed:
            calm()
            restore(up=False)                          # nothing was recreated: the readers still run the old value
            return 1, (f"{key}: compose would not recreate {', '.join(missed)} with the new value — it never reached "
                       f"it; .env restored, nothing recreated")
        if _up_wait(popen, killpg, dc, targets):
            signed = f" with the two keys it signs ({', '.join(keys[1:])})" if len(keys) > 1 else ""
            said = f"{key}: rotated{signed}; {len(targets)} service(s) recreated and healthy: {', '.join(targets)}"
            if leased:                                 # connections serves the new value now: they lease it again
                relet.append(True)
                if not _relet(popen, killpg, dc, leased):
                    calm()
                    back = restore()
                    return 1, (f"{key}: {', '.join(leased)} did not come back healthy on the new lease — .env restored, "
                               f"{', '.join(targets + leased)} recreated with the old one "
                               f"({'healthy' if back else 'NOT healthy: look at them now'})")
                said += (f"; {', '.join(leased)} leased it again from connections (a value SAVED in connections' "
                         f"vault would win over .env for them — issues/a-connections-vault-override-wins-over-a-"
                         f"rotated-key-for-its-lease-readers.yaml)")
            return seeded(said)
        calm()
        back = restore()
        return 1, (f"{key}: {', '.join(targets)} did not come back healthy with the new value — .env restored and they "
                   f"were recreated with the old one ({'healthy' if back else 'NOT healthy: look at them now'})")
    except BaseException:
        calm()
        back = restore()
        if reseeded or relet:                              # n8n and the lease readers back on the old one, SAID
            try:
                said = unseed(False) if reseeded else ""
            except Exception:                              # noqa: BLE001 — the first error is the one raised
                said = "; n8n could NOT be re-seeded with the old one: run `bbox n8n push all --reseed-only` now"
            print(f"env-secrets: {key}: stopped — .env restored"
                  + (f", {', '.join(targets + (leased if relet else []))} recreated with the old one "
                     f"({'healthy' if back else 'NOT healthy: look at them now'})" if targets else "")
                  + said, file=sys.stderr)
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
            done = set()
            for key in keys:
                whole = rotation_class(key) == "signing"     # the class rotates as one: once, whichever are named
                if (whole and "signing" in done) or key in done:
                    continue
                done.add("signing" if whole else key)
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
