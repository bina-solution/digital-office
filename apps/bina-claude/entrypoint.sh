#!/usr/bin/env bash
# bina-claude's entrypoint: the agent.v1 adapter over the official Claude Desktop app — and nothing else.
# Claude Desktop («קלוד דסקטופ», DGO-1920) is ONLY the desktop app, with ONE sign-in; there is no terminal (the
# owner, 2026-11-09, DGO-1684: «Delete the terminal and make sure nobody gets mixed up again»).
set -euo pipefail

STATE="${BINA_CLAUDE_STATE:-/data/bina-claude}"
OFFICE="${BBOX_REPO_HOST:-/workspace/office}"
# Which copy of the app this is: bina-claude, or an instance (instances/<id>/, DGO-1920) told by DGO_INSTANCE_ID.
APP="${DGO_INSTANCE_ID:-bina-claude}"
mkdir -p "${HOME}" "${STATE}"
# The desktop app's home (bina-claude-desktop mounts this folder of the volume as its /config; a volume
# subpath must exist before it is mounted), owned by the desktop's user — the checkout's owner, declared per
# office (BINA_CLAUDE_DESKTOP_PUID/PGID, docker-compose.yml says why; 1000 by default).
DUID="${BINA_CLAUDE_DESKTOP_PUID:-1000}"; DGID="${BINA_CLAUDE_DESKTOP_PGID:-1000}"
mkdir -p /data/desktop && chown "${DUID}:${DGID}" /data/desktop

# The action token of the agent.v1 door: minted once, root-only, read by `bbox agent` through the engine
# (AGENT_TOKEN_FILE), never an .env value — the contract's rule (ai/context/agent-contract.md).
TOKEN_FILE="${AGENT_TOKEN_FILE:-${STATE}/api-token}"
if [ ! -s "${TOKEN_FILE}" ]; then
  umask 077
  head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' > "${TOKEN_FILE}"
fi
chmod 600 "${TOKEN_FILE}"

# The brief every session of the desktop app reads: who it is in this office and how it reaches the others.
# The repo's AGENTS.md is the office's own entry file; this only points Claude at it (DGO-1275, the owner's
# phone: "not sure what dgo means").
brief() {
  cat <<EOF
# Claude Desktop — the office's Claude

Claude Desktop («קלוד דסקטופ») is ONLY the official Claude Desktop app, with ONE sign-in. There is no
terminal: never propose /login, /remote-control or a terminal to anyone.

You run inside the digital office (DGO) of this machine, in the desktop app of \`${APP}\`. The office
is its checkout, \`/workspace/office\` — work there, whatever folder this session opened in; its entry
file is \`/workspace/office/AGENTS.md\`. Read it before you change anything, and keep its
non-negotiables (production, \`./scripts/dc\` never bare \`docker compose\`, explain a dangerous command
first, commit only on this office's own branch). \`./bbox\` and \`./scripts/dc\` run here: this app has
the office's docker.

The other agents of the office are a CLI away:
- Azaria (bina-ds): \`./bbox agent list\`, \`./bbox agent new -F "<text>"\`, \`./bbox agent send <id> "<text>"\`
- yourself, as other callers see you: \`./bbox agent --app ${APP} list\`
- work items: \`./bbox project-pln tasks show <REF>\`
- every copy of Claude Desktop on this office, each its own account: \`./bbox apps instance list\`
EOF
}
# The desktop's home belongs to the desktop's user, and so does every write into it: as root, a link that
# user left there (CLAUDE.md → /var/run/docker.sock) would have root write or chown whatever it points at, in
# the container that holds docker and the API token (the second reader). As that user, a link reaches nothing
# the user could not already write (where the user is root, the app already holds the engine's socket).
# Each file goes to a temp name, then is renamed into place.
as_desktop() { setpriv --reuid="${DUID}" --regid="${DGID}" --clear-groups "$@"; }
if as_desktop mkdir -p /data/desktop/.claude; then
  brief | as_desktop sh -c 'cat > "$1.new" && mv -f "$1.new" "$1"' _ /data/desktop/.claude/CLAUDE.md \
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
  # …and the office is a TRUSTED folder of the app, so a new session can open IN it and the folder picker
  # offers it (DGO-1684; the owner, 2026-11-09: «i want to be able to choos the dgo folder … or if it can be
  # by default as the workspace folder for the claude session like we did here on the mac»). Claude records
  # trust in ~/.claude.json, `projects[<path>].hasTrustDialogAccepted` — measured on the Mac's own app, where
  # the office's checkout is trusted exactly so. Merged, never written over: the app keeps the rest.
  as_desktop node - /data/desktop/.claude.json "${OFFICE}" <<'JS' || echo "[bina-claude] desktop trust not merged" >&2
const fs = require("fs"), [file, office] = process.argv.slice(2);
let c = {};
try { c = JSON.parse(fs.readFileSync(file, "utf8")); } catch (e) { if (e.code !== "ENOENT") process.exit(1); }
if (!c || typeof c !== "object" || Array.isArray(c)) process.exit(1);
c.projects = c.projects && typeof c.projects === "object" ? c.projects : {};
for (const p of new Set(["/workspace/office", office])) {
  const had = c.projects[p] && typeof c.projects[p] === "object" ? c.projects[p] : {};
  c.projects[p] = { allowedTools: [], ...had, hasTrustDialogAccepted: true };
}
fs.writeFileSync(file + ".new", JSON.stringify(c, null, 2) + "\n");
fs.renameSync(file + ".new", file);
JS
else
  echo "[bina-claude] the desktop's home is not writable as its user — brief and settings skipped" >&2
fi

# The adapter, brought back if it ever stops: the container lives as long as this loop.
while :; do node /opt/bina-claude/adapter/server.mjs || true; sleep 2; done
