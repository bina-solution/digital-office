#!/bin/sh
# customize.sh — the node-side changes that let stock dsh live behind the platform's SSO edge.
#
# Written against @deepseek-ai/dsh 0.2.2-rc.3 (EXU-64). Every edit asserts its anchor occurs EXACTLY
# once, so a harness version bump that moves the code fails the image build loudly instead of
# shipping an app the console cannot open — and first looks for its own result, so a second run over
# the same tree says "already applied" instead of patching twice. 0.2.x ships its browser halves minified (`client.browser.js`)
# and renames their locals per build, so an anchor in a minified file names only what the minifier
# keeps (exported names, property names, string literals) — never a local function name.
set -eu
ROOT="${1:-.}"
CONN="$(find "$ROOT/node_modules/.pnpm" -path '*/node_modules/@deepseek-ai/dsh-client-connection/lib/index.js' | head -1)"
[ -n "$CONN" ] || { echo "customize: dsh-client-connection not found under $ROOT" >&2; exit 1; }

# ── who is signed in: the edge, and the office's own adapter ──────────────────────────────────
# Stock dsh authenticates a browser with a per-process launch token exchanged once on GET /?token=…
# for a signed cookie (`BrowserAuth.authenticate`, which every check — the index, /api, the operator
# credential — goes through). Behind the platform edge every request already carries the identity
# the office's sign-in established (X-authentik-username, added by Traefik's forwardAuth) — the same
# header every embedded first-party app trusts, because none of them has a login of its own. When
# DSH_TRUST_PROXY_AUTH_HEADER names that header, a request carrying it is a signed-in BROWSER; and the
# office's agent.v1 adapter (apps/bina-ds/adapter), which calls the harness on loopback with the action
# token entrypoint.sh minted into the volume, is one too — compared in constant time with the
# harness's own comparator. Without the env vars nothing changes. The Host/Origin trust fence
# (trustedHosts) stays as shipped: an authority it refuses is still refused. Owner-approved 2026-09-17.
node - "$CONN" <<'JS'
const fs = require('node:fs')
const [file] = process.argv.slice(2)
const anchor = '\tauthenticate(request, secure) {\n\t\tconst authority = requestAudience(request.headers, secure);'
const patched = anchor + '\n' +
  '\t\t// bina-ds customization: the edge\'s sign-in, or the office adapter\'s token, is a browser session.\n' +
  '\t\tconst binaToken = process.env.BINA_DS_API_TOKEN;\n' +
  '\t\tconst binaAuthz = header(request.headers, "authorization");\n' +
  '\t\tconst binaEdge = process.env.DSH_TRUST_PROXY_AUTH_HEADER;\n' +
  '\t\tconst binaByToken = binaToken !== undefined && binaToken.length >= 32 && binaAuthz !== undefined && binaAuthz.startsWith("Bearer ") && tokenMatches(binaAuthz.slice(7), binaToken);\n' +
  '\t\tconst binaByEdge = binaEdge !== undefined && binaEdge !== "" && header(request.headers, binaEdge.toLowerCase()) !== undefined;\n' +
  '\t\tif (authority !== void 0 && (binaByToken || binaByEdge)) {\n' +
  '\t\t\tconst binaNow = Date.now();\n' +
  '\t\t\treturn { version: COOKIE_PAYLOAD_VERSION, authority, issuedAt: binaNow, expiresAt: binaNow + this.maxAgeMilliseconds };\n' +
  '\t\t}'
const s = fs.readFileSync(file, 'utf8')
if (s.includes('const binaByEdge')) { console.log('customize: already applied (edge + adapter sign-in) ' + file); process.exit(0) }
const count = s.split(anchor).length - 1
if (count !== 1) { console.error(`customize: authenticate anchor matched ${count} times in ${file}`); process.exit(1) }
fs.writeFileSync(file, s.replace(anchor, patched))
console.log('customize: patched (edge + adapter sign-in) ' + file)
JS

# ── the page "owns the host" behind the edge ──────────────────────────────────────────────────
# Stock dsh keeps the operator's settings (the Models page: providers, keys, catalog) readable
# and writable only from a LOOPBACK page — a remote browser gets a memory-only settings scope and
# the Models page fails with "settings are unavailable in this browser". The page authority here is
# the console or azaria.<domain>, never loopback, but it is reached only through the office's sign-in:
# the person looking at it IS the operator. So, under the same env switch as the sign-in above, the
# host injects one page global and the browser half counts it as "owns the host" — the very hook the
# harness reserves for shells that assemble their own transport (ClientTransportHooks.ownsHost).
node - "$CONN" <<'JS'
const fs = require('node:fs')
const [file] = process.argv.slice(2)
const anchor = '\t\twebCtx.on("webserver/index-inject", (table) => {\n\t\t\ttable.push({\n\t\t\t\tkind: "global",\n\t\t\t\tname: "__DSH_CONNECTION_RECOVERY__",\n\t\t\t\tvalue: recovery\n\t\t\t});'
const patched = anchor + '\n\t\t\t// bina-ds customization: behind the SSO edge the page is the operator\'s own surface.\n\t\t\tif (process.env.DSH_TRUST_PROXY_AUTH_HEADER) table.push({ kind: "global", name: "__DSH_PAGE_OWNS_HOST__", value: true });'
const s = fs.readFileSync(file, 'utf8')
if (s.includes('name: "__DSH_PAGE_OWNS_HOST__"')) { console.log('customize: already applied (page-owns-host row) ' + file); process.exit(0) }
const count = s.split(anchor).length - 1
if (count !== 1) { console.error(`customize: index-inject anchor matched ${count} times in ${file}`); process.exit(1) }
fs.writeFileSync(file, s.replace(anchor, patched))
console.log('customize: patched (page-owns-host row) ' + file)
JS
CLIENT="$(dirname "$CONN")/client.browser.js"
[ -f "$CLIENT" ] || { echo "customize: $CLIENT not found" >&2; exit 1; }
node - "$CLIENT" <<'JS'
const fs = require('node:fs')
const [file] = process.argv.slice(2)
const anchor = 'isLoopback:transport?.ownsHost===true||'
const patched = 'isLoopback:transport?.ownsHost===true||globalThis.__DSH_PAGE_OWNS_HOST__===true||'
const s = fs.readFileSync(file, 'utf8')
if (s.includes('globalThis.__DSH_PAGE_OWNS_HOST__===true')) { console.log('customize: already applied (page-owns-host) ' + file); process.exit(0) }
const count = s.split(anchor).length - 1
if (count !== 1) { console.error(`customize: isLoopback anchor matched ${count} times in ${file}`); process.exit(1) }
fs.writeFileSync(file, s.replace(anchor, patched))
console.log('customize: patched (page-owns-host) ' + file)
JS

# ── the app's own bundles load from under the console's path prefix ───────────────────────────
# The console frames this app under `/a/bina/` and injects `<base href="/a/bina/">`, and the
# platform's contract for an embedded app is relative URLs (platform-base/console/app.py). The
# harness keeps its boot manifest in a global (`__DSH_BOOT__`) whose every entry addresses its
# bundle at the ROOT — `/plugins/??@scope/pkg/client.js,…&rev=<hash>` — and a root-absolute URL
# IGNORES `<base>`: the console's own SPA fallback answered 200 `text/html` for a `<script>`, and the
# page reported "Failed to load plugins" (measured 2026-10-11, `ui-map`, the bina tile). So the load
# hook resolves the URL against the page's own base PATH — `/` when the harness IS the origin
# (azaria.<domain>, bina.<domain>), where this is a no-op.
HOSTBUNDLE="$(find "$ROOT/node_modules/.pnpm" -path '*/node_modules/@deepseek-ai/dsh-client-modules/lib/client.js' | head -1)"
[ -n "$HOSTBUNDLE" ] || { echo "customize: dsh-client-modules client.js not found under $ROOT" >&2; exit 1; }
node - "$HOSTBUNDLE" <<'JS'
const fs = require('node:fs')
const [file] = process.argv.slice(2)
const anchor = 'defaultLoadBundle=url=>new Promise((resolve,reject)=>{const el=document.createElement(`script`);el.async=true;el.src=url;'
const mounted = '(u=>{try{const p=new URL(document.baseURI||document.location.href).pathname.replace(/\\/+$/,"");return p!==""&&u.startsWith("/")&&!u.startsWith("//")?p+u:u}catch{return u}})(url)'
const patched = anchor.replace('el.src=url;', 'el.src=' + mounted + ';')
const s = fs.readFileSync(file, 'utf8')
if (s.includes('el.src=' + mounted + ';')) { console.log('customize: already applied (prefixed bundle urls) ' + file); process.exit(0) }
const count = s.split(anchor).length - 1
if (count !== 1) { console.error(`customize: defaultLoadBundle anchor matched ${count} times in ${file}`); process.exit(1) }
fs.writeFileSync(file, s.replace(anchor, patched))
console.log('customize: patched (prefixed bundle urls) ' + file)
JS

# ── the copy button copies from inside a frame ────────────────────────────────────────────────
# The owner, 2026-10-09 14:50, with the tooltip „העתקה" showing under a message: «העתקה לא עובד».
# The window was HIS office's agent framed by ANOTHER office's console — cross-origin BY DESIGN — and
# in a cross-origin frame the async Clipboard API is denied by default (Permissions Policy
# `clipboard-write` allows `self`); the stock helper answered that refusal with `catch{return!1}` —
# no fallback, no message, and the button simply did nothing. The legacy path copies inside the same
# user gesture, which the policy does not gate, so the early return goes and the legacy path becomes
# the fallback it was written to be. The helper's NAME is the minifier's and changes per build, so it
# is matched by its body, and the body must occur exactly once.
FRONT="$(find "$ROOT/node_modules/.pnpm" -path '*dsh-web-frontend/dist/assets/index-*.js' | head -1)"
[ -n "$FRONT" ] || { echo "customize: dsh-web-frontend dist bundle not found under $ROOT" >&2; exit 1; }
node - "$FRONT" <<'JS'
const fs = require('node:fs')
const [file] = process.argv.slice(2)
const re = /(async function [A-Za-z0-9_$]+\(([A-Za-z_$][A-Za-z0-9_$]*)\)\{if\(navigator\.clipboard\?\.writeText\)try\{return await navigator\.clipboard\.writeText\(\2\),!0\}catch\{)return!1(\})/g
const s = fs.readFileSync(file, 'utf8')
if (!/navigator\.clipboard\.writeText\([A-Za-z_$][A-Za-z0-9_$]*\),!0\}catch\{return!1\}/.test(s) && /navigator\.clipboard\.writeText\([A-Za-z_$][A-Za-z0-9_$]*\),!0\}catch\{\}/.test(s)) { console.log('customize: already applied (clipboard fallback) ' + file); process.exit(0) }
const count = [...s.matchAll(re)].length
if (count !== 1) { console.error(`customize: writeClipboard anchor matched ${count} times in ${file}`); process.exit(1) }
fs.writeFileSync(file, s.replace(re, '$1$3'))
console.log('customize: patched (clipboard fallback) ' + file)
JS

# The interface's language is no longer patched here: 0.2.x made the active language the `locale`
# row's own config, so the office's Hebrew default is DECLARED in harness/profile/cordis.patch.yml.
