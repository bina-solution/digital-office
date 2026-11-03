#!/usr/bin/env bash
# bina-claude's entrypoint: the account's home on the volume, the agent.v1 adapter, then the web terminal.
set -euo pipefail

STATE="${BINA_CLAUDE_STATE:-/data/bina-claude}"
OFFICE="${BBOX_REPO_HOST:-/workspace/office}"
mkdir -p "${HOME}" "${STATE}"
# The desktop app's home (bina-claude-desktop mounts this folder of the volume as its /config; a volume
# subpath must exist before it is mounted), owned by the desktop's user (PUID 1000).
mkdir -p /data/desktop && chown 1000:1000 /data/desktop

# /workspace/office is the short, ASCII spelling of the checkout (mounted at its HOST path, which on the
# Mac has a Hebrew name and a trailing space) — the same symlink bina-ds keeps.
if [ "${OFFICE}" != /workspace/office ] && [ -d "${OFFICE}" ]; then
  mkdir -p /workspace && ln -sfn "${OFFICE}" /workspace/office
fi
git config --global --get-all safe.directory | grep -qxF '*' || git config --global --add safe.directory '*'

# The action token of the agent.v1 door: minted once, root-only, read by `bbox agent` through the engine
# (AGENT_TOKEN_FILE), never an .env value — the contract's rule (ai/context/agent-contract.md).
TOKEN_FILE="${AGENT_TOKEN_FILE:-${STATE}/api-token}"
if [ ! -s "${TOKEN_FILE}" ]; then
  umask 077
  head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' > "${TOKEN_FILE}"
fi
chmod 600 "${TOKEN_FILE}"

# The brief Claude reads in every session it starts here: who it is in this office and how it reaches
# the others. The repo's AGENTS.md is the office's own entry file; this only points Claude at it.
# Written into BOTH homes: this container's (the terminal, the API) and the desktop app's (/data/desktop,
# its /config), whose sessions otherwise knew nothing of the office (DGO-1275, the owner's phone: "not
# sure what dgo means"). The desktop runs no docker, so its `bbox` lives in the terminal tile.
brief() {   # brief <where> — the text; <where> is "terminal" or "desktop"
  cat <<EOF
# Bina Claude — the office's Claude

You run inside the digital office (DGO) of this machine, as the app \`bina-claude\`. The office is
its checkout, \`/workspace/office\` — work there, whatever folder this session opened in; its entry
file is \`/workspace/office/AGENTS.md\`. Read it before you change anything, and keep its
non-negotiables (production, \`./scripts/dc\` never bare \`docker compose\`, explain a dangerous command
first, commit only on this office's own branch).

The other agents of the office are a CLI away:
- Azaria (bina-ds): \`./bbox agent list\`, \`./bbox agent new -F "<text>"\`, \`./bbox agent send <id> "<text>"\`
- yourself, as other callers see you: \`./bbox agent --app bina-claude list\`
- work items: \`./bbox project-pln tasks show <REF>\`
EOF
  if [ "$1" = desktop ]; then
    cat <<EOF

This is the DESKTOP app (Claude Desktop, streamed into the office console). You read and edit the
checkout here; this container has no docker, so \`./bbox\` and \`./scripts/dc\` do not run in it. They run
in the office's Bina Claude terminal (the tile «בינה קלוד · מסוף», the same checkout, with docker) — say
the exact command there, or hand it to Azaria.
EOF
  fi
}
mkdir -p "${HOME}/.claude"
brief terminal > "${HOME}/.claude/CLAUDE.md"
# The desktop's home belongs to the desktop's user (uid 1000), and so does every write into it: as root, a
# link that user left there (CLAUDE.md → /var/run/docker.sock) would have root write or chown whatever it
# points at, in the container that holds docker and the API token (the second reader). As 1000, a link
# reaches nothing 1000 could not already write. Each file goes to a temp name, then is renamed into place.
as_desktop() { setpriv --reuid=1000 --regid=1000 --clear-groups "$@"; }
if as_desktop mkdir -p /data/desktop/.claude; then
  brief desktop | as_desktop sh -c 'cat > "$1.new" && mv -f "$1.new" "$1"' _ /data/desktop/.claude/CLAUDE.md \
    || echo "[bina-claude] desktop brief not written" >&2
  # …and the office itself in reach of every desktop session, whatever folder the app opened it in: Claude
  # Desktop has no documented default folder for a new Code session, but reads the CLI's settings files,
  # so the checkout is an additional directory there and its own CLAUDE.md/AGENTS.md load with it. MERGED
  # into the user's settings.json, never written over it: the app and its owner keep their own keys.
  as_desktop node - /data/desktop/.claude/settings.json "${OFFICE}" <<'JS' || echo "[bina-claude] desktop settings not merged" >&2
const fs = require("fs"), [file, office] = process.argv.slice(2);
let s = {};
try { s = JSON.parse(fs.readFileSync(file, "utf8")); } catch (e) { if (e.code !== "ENOENT") process.exit(1); }
if (!s || typeof s !== "object" || Array.isArray(s)) process.exit(1);
s.permissions = s.permissions && typeof s.permissions === "object" ? s.permissions : {};
const had = Array.isArray(s.permissions.additionalDirectories) ? s.permissions.additionalDirectories : [];
s.permissions.additionalDirectories = [...new Set([...had, "/workspace/office", office])];
s.env = { ...(s.env && typeof s.env === "object" ? s.env : {}), CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD: "1" };
fs.writeFileSync(file + ".new", JSON.stringify(s, null, 2) + "\n");
fs.renameSync(file + ".new", file);
JS
else
  echo "[bina-claude] the desktop's home is not writable as its user — brief and settings skipped" >&2
fi

# The adapter is restarted if it ever stops: the terminal is PID 1's child, the API must not die with
# a crash of its own.
( while :; do node /opt/bina-claude/adapter/server.mjs || true; sleep 2; done ) &
# …and so is the terminal's front door (adapter/gate.mjs): ttyd itself listens on loopback only.
( while :; do node /opt/bina-claude/adapter/gate.mjs || true; sleep 2; done ) &

# The web terminal: ONE tmux session, created on the first visit and re-attached by every later one
# (and by `./bbox bina-claude attach`). Claude Code starts in it; when it exits, a shell remains, and
# `claude` brings it back. ttyd listens on the container's loopback; the only way in is gate.mjs on
# :7681, which admits the edge and the console by address. The header check (-H) stays as a second lock.
cd "${OFFICE}" 2>/dev/null || cd /
exec ttyd --port 7682 --interface 127.0.0.1 --writable \
  --auth-header "${BINA_CLAUDE_AUTH_HEADER:-X-authentik-username}" \
  -t titleFixed="Bina Claude" -t disableLeaveAlert=true \
  tmux new-session -A -s main -c "${OFFICE}" "claude; exec bash -l"
