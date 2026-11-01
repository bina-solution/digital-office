#!/usr/bin/env bash
# ci-screenshots.sh — drive browser42 (over CDP) to LOG IN to each app and
# screenshot its real main page (not the login wall), as visual CI evidence.
# Non-fatal: always exits 0 (screenshots are an artifact, not a gate).
# Outputs PNGs to $CI_SHOTS (default ci-artifacts/screenshots).
#
# Auth handled per app:
#   authentik    — log in as akadmin (sets the SSO session cookie for *.localhost)
#   redisinsight — Authentik-gated: same SSO cookie (+ accept first-run consent)
#   n8n          — own login (owner email/password); needs N8N_SECURE_COOKIE=false
#   portainer    — own login (admin / PORTAINER_ADMIN_PASSWORD)
#   glitchtip    — own login (a superuser created here via manage.py)
set -uo pipefail
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
. "${SCRIPT_DIR}/lib.sh"   # UTF-8 io (Hebrew labels) + npath(); no-op on Linux
read_env() { grep -E "^$1=" "${REPO_ROOT}/.env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '\r'; }
DN="$(read_env DEPLOYMENT_NAME)"; DN="${DN:-bina-deployment}"
cn() { docker ps --format '{{.Names}}' | grep -E "^$1(-${DN})?$" | head -1; }
B42="$(cn browser42-browser)"
OUT="${CI_SHOTS:-${REPO_ROOT}/ci-artifacts/screenshots}"; mkdir -p "$OUT"

[ -z "$B42" ] && { echo "browser42 not running — skipping screenshots"; exit 0; }

# Credentials from the (CI) .env.
AK_PASS="$(read_env AUTHENTIK_BOOTSTRAP_PASSWORD)"
N8N_EMAIL="$(read_env N8N_OWNER_EMAIL)"; N8N_PASS="$(read_env N8N_OWNER_PASSWORD)"
PT_PASS="$(read_env PORTAINER_ADMIN_PASSWORD)"
GT_EMAIL="$(read_env GLITCHTIP_ADMIN_EMAIL)"; GT_PASS="$(read_env GLITCHTIP_ADMIN_PASSWORD)"

# Ensure a GlitchTip account exists so we can log in (idempotent; ignore "exists").
GT="$(cn glitchtip)"
if [ -n "$GT" ] && [ -n "$GT_EMAIL" ]; then
  echo "Ensuring GlitchTip superuser ${GT_EMAIL} ..."
  docker exec -e DJANGO_SUPERUSER_EMAIL="$GT_EMAIL" -e DJANGO_SUPERUSER_PASSWORD="$GT_PASS" \
    "$GT" python manage.py createsuperuser --no-input 2>&1 | tail -2 || true
fi

echo "Capturing app screenshots via $B42 ..."
docker exec -i \
  -e AK_USER=akadmin -e AK_PASS="$AK_PASS" \
  -e N8N_EMAIL="$N8N_EMAIL" -e N8N_PASS="$N8N_PASS" \
  -e PT_USER=admin -e PT_PASS="$PT_PASS" \
  -e GT_EMAIL="$GT_EMAIL" -e GT_PASS="$GT_PASS" \
  "$B42" python3 - <<'PY' 2>&1 || true
import os, re
from playwright.sync_api import sync_playwright
OUT = "/data/output"
def env(k, d=""): return os.environ.get(k, d)

def fill_first(page, selector, value):
    el = page.locator(selector).first
    el.wait_for(state="visible", timeout=15000)
    el.fill(value)
    return el

with sync_playwright() as p:
    b = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    # Use a context that IGNORES cert errors: in CI some apps (redisinsight, browser42)
    # redirect http->https (X-Forwarded-Proto) and the self-signed cert otherwise hard-
    # fails the nav (ERR_CERT_AUTHORITY_INVALID). SSO is re-established inline per app
    # (self-heal), so a fresh context is fine. Fall back to the existing context if the
    # CDP browser doesn't allow new contexts.
    try:
        ctx = b.new_context(ignore_https_errors=True)
        page = ctx.new_page()
    except Exception:
        ctx = b.contexts[0]; page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.set_default_timeout(20000)

    # ── Authentik SSO helpers ────────────────────────────────────────────────
    def on_ak_wall():
        # On the Authentik login wall? Detect by URL OR by the flow's text — the
        # IDENTIFICATION stage has NO password field and the redisinsight outpost
        # URL isn't /flow/, so a password-only check misses it.
        try:
            if "/flow/" in page.url or "outpost.goauthentik.io" in page.url:
                return True
            return page.get_by_text(re.compile(r"Welcome to authentik|Login to continue|Email or Username", re.I)).count() > 0
        except Exception:
            return False

    def settle():
        # Let redirect chains finish before deciding anything (CI is slower than local,
        # so a fixed sleep raced the redirect to the /flow/ login).
        try: page.wait_for_load_state("networkidle", timeout=9000)
        except Exception: pass
        page.wait_for_timeout(1500)

    def ak_login():
        # Complete the Authentik flow: identification (username) then password. Fill the
        # VISIBLE username first (gating on password COUNT skipped it when a hidden pw
        # field existed). Retry up to 3x until we're off the /flow/ URL (CI timing).
        for attempt in range(3):
            try:
                tb = page.get_by_role("textbox").first
                if tb.count():
                    try: tb.wait_for(state="visible", timeout=10000)
                    except Exception: pass
                    if tb.is_visible():
                        tb.fill(env("AK_USER", "akadmin")); tb.press("Enter"); page.wait_for_timeout(3000)
                pw = page.locator("input[type=password]").first
                if pw.count():
                    try: pw.wait_for(state="visible", timeout=12000)
                    except Exception: pass
                    if pw.is_visible():
                        pw.fill(env("AK_PASS")); pw.press("Enter")
                        try: page.wait_for_url(lambda u: "/flow/" not in u, timeout=20000)
                        except Exception: page.wait_for_timeout(5000)
                page.wait_for_timeout(2000)
                if "/flow/" not in page.url:
                    return
            except Exception as e:
                print("  ak_login attempt", attempt, type(e).__name__, str(e)[:60])
            page.wait_for_timeout(2000)

    def open_gated(url):
        # Navigate to an Authentik-gated app; if it lands on the login wall, log in
        # inline and retry. Self-healing — doesn't depend on the SSO session carrying
        # over from an earlier app (which proved flaky). settle() first so the redirect
        # to /flow/ has actually landed before on_ak_wall() decides.
        page.goto(url, wait_until="domcontentloaded"); settle()
        for _ in range(3):
            if not on_ak_wall():
                break
            ak_login()
            page.goto(url, wait_until="domcontentloaded"); settle()

    # ── authentik: log in, land on the user app library (/if/user/, logged-in) ──
    def authentik():
        open_gated("http://auth.localhost/if/user/")


    def redisinsight():
        open_gated("http://redisinsight.localhost/")
        # first-run "EULA and Privacy settings" — Submit stays DISABLED until the
        # "I have read and understood the Terms" toggle (last switch) is on.
        try:
            sw = page.get_by_role("switch")
            if sw.count():
                sw.nth(sw.count() - 1).click(); page.wait_for_timeout(800)  # accept Terms
            submit = page.get_by_role("button", name=re.compile(r"submit", re.I))
            if submit.count() and submit.first.is_enabled():
                submit.first.click(); settle()   # let the DB list render before the shot
        except Exception as e:
            print("  redisinsight eula:", type(e).__name__, str(e)[:80])

    def n8n_login():
        # Log in to n8n if the signin form is showing. Idempotent.
        page.goto("http://n8n.localhost/signin", wait_until="domcontentloaded"); settle()
        if "/signin" not in page.url and "/setup" not in page.url:
            return  # already authenticated
        try:
            fill_first(page, "input[type=email], input[name=email]", env("N8N_EMAIL"))
            fill_first(page, "input[type=password]", env("N8N_PASS"))
            page.get_by_role("button", name=re.compile("sign in|log in", re.I)).first.click()
            settle(); page.wait_for_timeout(1500)
        except Exception as e:
            print("  n8n login:", type(e).__name__, str(e)[:80])

    def n8n_workflows():
        # Open the workflows list, re-logging-in if the n8n session dropped (it proved
        # flaky between targets — a fresh nav sometimes bounced to /signin).
        page.goto("http://n8n.localhost/home/workflows", wait_until="domcontentloaded"); settle()
        if "/signin" in page.url:
            n8n_login()
            page.goto("http://n8n.localhost/home/workflows", wait_until="domcontentloaded"); settle()

    def n8n():
        n8n_login()
        n8n_workflows()

    def n8n_active():
        # The "active" view = functional proof: filter to Status=Published (running).
        n8n_workflows()
        applied = False
        try:
            # Open the filter panel, then the Status dropdown (exact n8n test-ids).
            page.locator('[data-test-id="resources-list-filters-trigger"]').first.click()
            page.wait_for_timeout(1200)
            page.locator('[data-test-id="status-dropdown"]').first.click()
            page.wait_for_timeout(900)
            # n8n 2.x status options are "Published" / "Unpublished" (NOT "Active") —
            # a published workflow is one with a live active version (i.e. running).
            opt = page.get_by_role("option", name=re.compile(r"^\s*Published\s*$", re.I))
            if not opt.count():
                opt = page.locator('.el-select-dropdown__item, li, [role=option]').filter(has_text=re.compile(r"^\s*Published\s*$", re.I))
            if opt.count():
                opt.first.click(); applied = True
            page.wait_for_timeout(1200)
            page.keyboard.press("Escape")   # close popover
            page.wait_for_timeout(1600)
        except Exception as e:
            print("  n8n-active filter:", type(e).__name__, str(e)[:90])
        print("  n8n-active: filter (Published) applied =", applied, "url:", page.url[:60])

    def portainer():
        page.goto("http://portainer.localhost/", wait_until="domcontentloaded"); page.wait_for_timeout(2500)
        try:
            fill_first(page, "input#username, input[name=username]", env("PT_USER", "admin"))
            fill_first(page, "input#password, input[type=password]", env("PT_PASS"))
            page.get_by_role("button", name=re.compile("login|log in", re.I)).first.click()
            page.wait_for_timeout(4000)
        except Exception as e:
            print("  portainer login:", type(e).__name__, str(e)[:80])

    def glitchtip():
        page.goto("http://glitchtip.localhost/", wait_until="domcontentloaded"); page.wait_for_timeout(2500)
        try:
            fill_first(page, "input[type=email], input[name=email]", env("GT_EMAIL"))
            fill_first(page, "input[type=password]", env("GT_PASS"))
            page.get_by_role("button", name=re.compile("log in|login|sign in", re.I)).first.click()
            page.wait_for_timeout(4000)
        except Exception as e:
            print("  glitchtip login:", type(e).__name__, str(e)[:80])

    # ── the unified console shell (המרכז) + the redesigned apps it federates ──
    def console():
        # The my-docs/מסמכים שלי-styled business-system shell. Land on the dashboard (skip the
        # first-run install redirect) so the shot shows the real portal + nav.
        open_gated("http://console.localhost/#/")
        page.wait_for_timeout(2500)

    def connections():
        open_gated("http://connections.localhost/")
        page.wait_for_timeout(2000)

    def mailview():
        open_gated("http://mail.localhost/")
        page.wait_for_timeout(2000)

    def drive():
        open_gated("http://drive.localhost/")
        page.wait_for_timeout(2000)

    def chat():
        # the chat service's admin panel — Authentik-gated like the other
        # business apps.
        open_gated("http://chat.localhost/")
        page.wait_for_timeout(2500)

    def any_concurrency():
        open_gated("http://any-concurrency.localhost/")

    def machine():
        open_gated("http://machine.localhost/")
        # Trigger + wait for live stats to populate (cards stop showing "-"). CI is slower
        # to fetch (more containers, cold first poll), so click Refresh and poll longer for
        # a number+unit (12.3% / 4 GB) so the shot shows real stats, not the placeholders.
        # CI fetches stats for ~28 containers over the docker socket on 2 vCPUs — slow on
        # the first poll. Poll up to ~100s, clicking Refresh between tries to kick the fetch.
        for _ in range(6):
            try:
                page.wait_for_function(
                    "() => /\\b\\d+(\\.\\d+)?\\s*(%|[KMGT]i?B)\\b/.test(document.body.innerText)",
                    timeout=16000)
                break
            except Exception:
                try:
                    btn = page.get_by_role("button", name=re.compile(r"refresh", re.I))
                    if btn.count(): btn.first.click()
                except Exception:
                    pass
                page.wait_for_timeout(1500)
        page.wait_for_timeout(1500)

    def browser42_view():
        # Drive browser42's own Chromium to browser42.localhost THROUGH traefik (not the
        # internal caddy hostname) — verifies browser42 both WORKS and is reachable on
        # its real domain in-network ("browser42 opening browser42"). Self-heal Authentik.
        open_gated("http://browser42.localhost/view/")
        page.wait_for_timeout(4000)   # let the noVNC handshake finish (Connecting -> Connected)

    TARGETS = [
        ("console",        console),       # the unified business-system shell (המרכז)
        ("connections",    connections),   # credential plane + install/settings
        ("mail",           mailview),      # mailview ops console
        ("drive",          drive),    # drive UI
        ("chat",           chat),          # the chat service admin panel
        ("auth-login",     authentik),     # authentik admin (after login)
        ("n8n",            n8n),
        ("n8n-active",     n8n_active),    # workflows filtered to Status=Active
        ("glitchtip",      glitchtip),
        ("portainer",      portainer),
        ("redisinsight",   redisinsight),
        ("any-concurrency", any_concurrency),
        ("machine",        machine),
        ("browser42-view", browser42_view),
    ]
    for name, fn in TARGETS:
        try:
            fn()
        except Exception as e:
            print(f"  {name}: NAV/LOGIN ERR {type(e).__name__}: {str(e)[:90]}")
        # Retry the screenshot with decreasing timeouts; the heavy/animated pages (n8n,
        # redisinsight post-EULA) sometimes don't settle for animations="disabled", so
        # later attempts drop that option and just grab the frame.
        shot_ok, last_e = False, None
        for kw in ({"animations": "disabled", "timeout": 25000}, {"timeout": 12000}, {"timeout": 6000}):
            try:
                page.screenshot(path=f"{OUT}/app-{name}.png", **kw); shot_ok = True; break
            except Exception as e:
                last_e = e
                try: page.wait_for_timeout(1500)
                except Exception: pass
        print(f"  {name}: {page.url[:70]}" + ("" if shot_ok else f"  SHOT ERR {type(last_e).__name__}"))
PY
# Pull the PNGs out of the browser42 /data mount into the artifact dir.
docker cp "$B42:/data/output/." "$OUT/" 2>/dev/null || true
ls "$OUT"/app-*.png >/dev/null 2>&1 && { echo "Saved $(ls "$OUT"/app-*.png | wc -l | tr -d ' ') screenshots to $OUT"; ls "$OUT"/app-*.png; } || echo "No screenshots captured (non-fatal)."
exit 0
