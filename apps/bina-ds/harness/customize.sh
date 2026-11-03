#!/bin/sh
# customize.sh — the one node-side change that lets stock dsh live behind the platform's SSO edge.
#
# Stock dsh authenticates a browser with a per-process launch token exchanged once on GET /?token=…
# for a signed cookie. Behind the platform edge every request already carries the identity authentik
# established (X-authentik-username, added by Traefik's forwardAuth after a successful SSO check) —
# the same header every embedded first-party app trusts, because none of them has a login of its
# own. When DSH_TRUST_PROXY_AUTH_HEADER names that header, a request carrying it is authenticated;
# without the env var nothing changes. The Host/Origin trust fence (trustedHosts) stays as shipped.
# Owner-approved 2026-09-17.
#
# The edit asserts its anchor occurs EXACTLY once, so a harness version bump that moves the code
# fails the image build loudly instead of shipping an app the console cannot open.
set -eu
ROOT="${1:-.}"
CONN="$(find "$ROOT/node_modules/.pnpm" -path '*/node_modules/@deepseek-ai/dsh-client-connection/lib/index.js' | head -1)"
[ -n "$CONN" ] || { echo "customize: dsh-client-connection not found under $ROOT" >&2; exit 1; }
node - "$CONN" <<'JS'
const fs = require('node:fs')
const [file] = process.argv.slice(2)
const anchor = '\tisAuthenticated(request) {\n\t\tconst authority = requestAuthority(request.headers);'
const patched = '\tisAuthenticated(request) {\n' +
  // The office's agent.v1 adapter (apps/bina-ds/adapter) calls the harness on loopback with the
  // action token entrypoint.sh minted into the volume — a real credential, compared in constant time
  // with the harness's own launch-token comparator. Unset token = this line accepts nothing.
  '\t\tconst apiToken = process.env.BINA_DS_API_TOKEN;\n' +
  '\t\tconst authz = header(request.headers, "authorization");\n' +
  '\t\tif (apiToken !== undefined && apiToken.length >= 32 && authz !== undefined && authz.startsWith("Bearer ") && tokenMatches(authz.slice(7), apiToken)) return true;\n' +
  '\t\t// bina-ds customization: the identity the platform edge already established is the authentication.\n' +
  '\t\tconst proxyHeader = process.env.DSH_TRUST_PROXY_AUTH_HEADER;\n' +
  '\t\tif (proxyHeader !== undefined && proxyHeader !== "" && header(request.headers, proxyHeader.toLowerCase()) !== undefined) return true;\n' +
  '\t\tconst authority = requestAuthority(request.headers);'
const s = fs.readFileSync(file, 'utf8')
const count = s.split(anchor).length - 1
if (count !== 1) { console.error(`customize: anchor matched ${count} times in ${file}`); process.exit(1) }
fs.writeFileSync(file, s.replace(anchor, patched))
console.log('customize: patched ' + file)
JS

# ── the page "owns the host" behind the edge ──────────────────────────────────────────────────
# Stock dsh keeps the operator's settings (the Models page: providers, keys, catalog) readable
# and writable only from a LOOPBACK page — a remote browser gets a memory-only settings scope and
# the Models page fails with "settings are unavailable in this browser". The page authority here is
# the console (console.<domain>), never loopback, but it is reached only through SSO: the person
# looking at it IS the operator. So, under the same env switch as the auth trust above, the host
# injects one page global and the browser half counts it as "owns the host" — the very hook the
# harness reserves for shells that assemble their own transport (ClientTransportHooks.ownsHost).
node - "$CONN" <<'JS'
const fs = require('node:fs')
const [file] = process.argv.slice(2)
const anchor = '\t\twebCtx.on("webserver/index-inject", (table) => {\n\t\t\ttable.push({\n\t\t\t\tkind: "global",\n\t\t\t\tname: "__DSH_CONNECTION_RECOVERY__",\n\t\t\t\tvalue: recovery\n\t\t\t});'
const patched = anchor + '\n\t\t\t// bina-ds customization: behind the SSO edge the page is the operator\'s own surface.\n\t\t\tif (process.env.DSH_TRUST_PROXY_AUTH_HEADER) table.push({ kind: "global", name: "__DSH_PAGE_OWNS_HOST__", value: true });'
const s = fs.readFileSync(file, 'utf8')
const count = s.split(anchor).length - 1
if (count !== 1) { console.error(`customize: index-inject anchor matched ${count} times in ${file}`); process.exit(1) }
fs.writeFileSync(file, s.replace(anchor, patched))
console.log('customize: patched (page-owns-host row) ' + file)
JS
CLIENT="$(dirname "$CONN")/client.js"
[ -f "$CLIENT" ] || { echo "customize: $CLIENT not found" >&2; exit 1; }
node - "$CLIENT" <<'JS'
const fs = require('node:fs')
const [file] = process.argv.slice(2)
const anchor = 'isLoopback: transport?.ownsHost === true || pageLocation === void 0 || isLoopbackHostname(pageLocation.hostname),'
const patched = 'isLoopback: transport?.ownsHost === true || globalThis.__DSH_PAGE_OWNS_HOST__ === true || pageLocation === void 0 || isLoopbackHostname(pageLocation.hostname),'
const s = fs.readFileSync(file, 'utf8')
const count = s.split(anchor).length - 1
if (count !== 1) { console.error(`customize: isLoopback anchor matched ${count} times in ${file}`); process.exit(1) }
fs.writeFileSync(file, s.replace(anchor, patched))
console.log('customize: patched (page-owns-host) ' + file)
JS

# ── the app's own bundles load from under the console's path prefix ───────────────────────────
# The console frames this app under `/a/bina/` and injects `<base href="/a/bina/">`, and the
# platform's contract for an embedded app is relative URLs (platform-base/console/app.py). The
# harness keeps its boot manifest in a global (`__DSH_BOOT__`) whose every entry addresses its
# bundle at the ROOT — `/plugins/??@scope/pkg/client.js,@scope/other/client.js&rev=<hash>` — and a
# root-absolute URL IGNORES `<base>`: the browser asked the CONSOLE's origin for it, the console's
# own SPA fallback answered 200 `text/html` for a `<script>`, and the page reported "Failed to load
# plugins" with every entry listed (measured 2026-10-11 in a fresh capture, `ui-map`, bina tile:
# `/a/bina/plugins/??…` → 200 JS, `/plugins/??…` → 200 HTML, 6251 bytes of the console's index).
# So the load hook resolves the URL against the page's own base PATH — `/` when the harness IS the
# origin, which is every non-framed case, where this is a no-op. Same exactly-once discipline.
HOSTBUNDLE="$(find "$ROOT/node_modules/.pnpm" -path '*/node_modules/@deepseek-ai/dsh-client-modules/lib/client.js' | head -1)"
[ -n "$HOSTBUNDLE" ] || { echo "customize: dsh-client-modules client.js not found under $ROOT" >&2; exit 1; }
node - "$HOSTBUNDLE" <<'JS'
const fs = require('node:fs')
const [file] = process.argv.slice(2)
const anchor = [
  '\t\tconst defaultLoadBundle = (url) => new Promise((resolve, reject) => {',
  '\t\t\tconst el = document.createElement("script");',
  '\t\t\tel.async = true;',
  '\t\t\tel.src = url;',
].join('\n')
const helper = [
  '\t\t// bina-ds customization: an embedded app is served under a PATH PREFIX (`/a/bina/`), while',
  '\t\t// the boot manifest addresses its bundles at the root. Resolve against the page\'s base path',
  '\t\t// — "/" at the harness\'s own origin, so nothing changes where it owns the origin.',
  '\t\tconst mountedUrl = (url) => {',
  '\t\t\ttry {',
  '\t\t\t\tconst path = new URL(document.baseURI || document.location.href).pathname.replace(/\\/+$/, "");',
  '\t\t\t\treturn path !== "" && url.startsWith("/") && !url.startsWith("//") ? path + url : url;',
  '\t\t\t} catch { return url; }',
  '\t\t};',
].join('\n')
const patched = [helper, anchor.replace('el.src = url;', 'el.src = mountedUrl(url);')].join('\n')
const s = fs.readFileSync(file, 'utf8')
const count = s.split(anchor).length - 1
if (count !== 1) { console.error(`customize: defaultLoadBundle anchor matched ${count} times in ${file}`); process.exit(1) }
fs.writeFileSync(file, s.replace(anchor, patched))
console.log('customize: patched (prefixed bundle urls) ' + file)
JS

# ── the copy button copies from inside a frame ────────────────────────────────────────────────
# The owner, 2026-10-09 14:50, with the tooltip „העתקה" showing under a message: «העתקה לא עובד».
# The window was HIS office's בינה framed by ANOTHER office's console (the title carries the
# office: „בינה ודעת · HP"), and that frame is cross-origin BY DESIGN — this app owns its origin
# (/api, /plugins and a websocket at the root), so `platform/manager/serve.py:through_console`
# gives its remote tile no `/a/<alias>/` proxy and the shell frames it on its own nested host.
# In a cross-origin frame the async Clipboard API is denied by default (Permissions Policy
# `clipboard-write` allows `self`), and the stock helper answered that refusal with
# `catch { return false }` — no fallback, no message, and the button simply did nothing.
# The web surface needs no clipboard perms: the legacy path copies inside the same user gesture,
# which is not gated by the policy. So one word of the minified helper goes away and the legacy
# path becomes the fallback it was written to be. Same exactly-once discipline as above.
FRONT="$(find "$ROOT/node_modules/.pnpm" -path '*dsh-web-frontend/dist/assets/index-*.js' | head -1)"
[ -n "$FRONT" ] || { echo "customize: dsh-web-frontend dist bundle not found under $ROOT" >&2; exit 1; }
node - "$FRONT" <<'JS'
const fs = require('node:fs')
const [file] = process.argv.slice(2)
const anchor = 'async function Rn(t){if(navigator.clipboard?.writeText)try{return await navigator.clipboard.writeText(t),!0}catch{return!1}const r='
const patched = 'async function Rn(t){if(navigator.clipboard?.writeText)try{return await navigator.clipboard.writeText(t),!0}catch{}const r='
const s = fs.readFileSync(file, 'utf8')
const count = s.split(anchor).length - 1
if (count !== 1) { console.error(`customize: writeClipboard anchor matched ${count} times in ${file}`); process.exit(1) }
fs.writeFileSync(file, s.replace(anchor, patched))
console.log('customize: patched (clipboard fallback) ' + file)
JS

# ── the interface opens in the office's language, whatever the browser asks for ───────────────
# The Hebrew pack adds the `he` language; which language is ACTIVE is this same plugin's durable
# setting, and nothing ever wrote it — so the client resolved `detectBrowserLocale(navigator.languages)
# ?? "en"` (`lib/client.js`, `resolveInitialLocale`) and a phone whose own language is not Hebrew got
# the stock English screen inside the owner's own office (DGO-550, measured 2026-10-13: «Into the
# Unknown», «Describe what you want to build…», «Open sidebar», while every one of those strings had a
# Hebrew value in the dictionaries the pack ships, and `settings.yaml` carried no `locale` section).
#
# The registration carries the office's composition DEFAULT — `base` — and the settings provider
# resolves schema defaults, then `base`, then the OWNER's layer. So Hebrew is what the interface
# opens in, and an explicit choice in Settings → שפה still wins in every direction: the language row
# writes the user layer through `setLocale` (which writes even when the value already matches, so a
# person who picks Hebrew keeps it at the top of that stack too). One line, exactly-once like the
# rest of this file; the harness version bump that moves it fails the build instead of shipping an
# agent that opens in the wrong language.
LOCALEHOST="$(find "$ROOT/node_modules/.pnpm" -path '*/node_modules/@deepseek-ai/dsh-client-locale/lib/index.js' | head -1)"
[ -n "$LOCALEHOST" ] || { echo "customize: dsh-client-locale not found under $ROOT" >&2; exit 1; }
node - "$LOCALEHOST" <<'JS'
const fs = require('node:fs')
const [file] = process.argv.slice(2)
const anchor = 'settingsCtx.settings.register(LOCALE_SETTINGS_NAMESPACE, LocaleSettingsSchema);'
const patched = 'settingsCtx.settings.register(LOCALE_SETTINGS_NAMESPACE, LocaleSettingsSchema, { base: { preference: "he" } });'
const s = fs.readFileSync(file, 'utf8')
const count = s.split(anchor).length - 1
if (count !== 1) { console.error(`customize: locale registration anchor matched ${count} times in ${file}`); process.exit(1) }
fs.writeFileSync(file, s.replace(anchor, patched))
console.log('customize: patched (office language default) ' + file)
JS
