#!/usr/bin/env python3
"""
Send a Facebook DM fast via the shared browser42 Chromium (CDP).

Run from the host (container name is deployment-specific — resolve it, don't hardcode):
  C=$(docker ps --filter name=browser42-browser --format '{{.Names}}' | head -1)
  docker exec -e FB_NAME="Bar Lax" -e FB_MSG="hi" -i "$C" python3 - < scripts/fb-send.py

Env:
  FB_NAME  recipient name (people search picks the first match; verify in the screenshot)
  FB_MSG   message text (default "hi")
  FB_URL   optional: exact profile URL to skip search (e.g. https://www.facebook.com/willi.bolotin)
  FB_DRY   if "1", type but DON'T press Enter (safe preview)

Shares the browser per the own-your-tab rule (ai/context/browser42-cli.md): it reuses ONE tab
tagged `b42:fb-send` across runs (no new tab each time; the browser42-reaper sidecar caps
total tabs — this script doesn't), and ends with os._exit(0) so the tab AND the Facebook
login survive for the next run.

Assumes the profile is already logged in. The ONLY composer it will type into is a
"Write to <name>" box opened from the profile's blue Message button — it never touches a
"Comment as ..." timeline box (that would post publicly). Softly dismisses incidental
popups incl. the Messenger E2EE "Enter your PIN" gate ("Don't restore messages").
Screenshot -> /data/output/fb-send.png (host: data/browser42/output/fb-send.png).

CAVEATS learned the hard way:
- full_page screenshots can HANG (autoplaying profile videos). Use clip= + timeout, or skip.
- `docker restart browser42-browser` DROPS the live Facebook session (must re-login via
  /view). Prefer fixing a wedged CDP some other way; only restart as a last resort.
"""
import os, sys
from playwright.sync_api import sync_playwright

NAME = os.environ.get("FB_NAME", "").strip()
MSG  = os.environ.get("FB_MSG", "hi")
URL  = os.environ.get("FB_URL", "").strip()
DRY  = os.environ.get("FB_DRY", "") == "1"
SHOT = "/data/output/fb-send.png"
SESSION  = "b42:fb-send"          # reuse one tab across runs (own-your-tab rule)
if not NAME and not URL:
    print("ERR: set FB_NAME or FB_URL"); sys.exit(2)

def soft_popups(page):
    """Dismiss incidental popups with the softest option (autopilot)."""
    for label in ["Don't restore messages", "Not now", "Not Now"]:
        try:
            page.get_by_role("button", name=label, exact=True).first.click(timeout=1200)
            print("dismissed:", label)
        except Exception:
            pass

def dm_composer(page):
    """STRICT: only a 'Write to <name>' DM box. Returns locator or None — never a comment box."""
    boxes = page.get_by_role("textbox")
    pick = None
    for i in range(boxes.count()):
        al = (boxes.nth(i).get_attribute("aria-label") or "").strip()
        if not al.lower().startswith("write to"):
            continue
        if NAME and NAME.split()[0].lower() in al.lower():
            return boxes.nth(i), al      # best: names the recipient
        pick = (boxes.nth(i), al)
    return pick if pick else (None, None)

def _name(pg):
    try: return pg.evaluate("window.name")
    except Exception: return ""

# --- connect, reuse my tagged tab (own-your-tab rule; never `with`/close()) ---
# The 8-tab cap is enforced by the browser42-reaper sidecar — not here.
p = sync_playwright().start()
b = p.chromium.connect_over_cdp("http://localhost:9222")
ctx = b.contexts[0]

page = next((pg for pg in ctx.pages if _name(pg) == SESSION), None)   # reuse my session tab
if page is None:
    page = ctx.new_page(); page.evaluate(f"window.name={SESSION!r}")

def done(code):
    sys.stdout.flush(); os._exit(code)   # keep my tab + FB login alive; never b.close()/ctx.close()

page.bring_to_front()

# 1) resolve the profile URL (people search) unless given
if not URL:
    page.goto("https://www.facebook.com/search/people/?q=" + NAME.replace(" ", "%20"),
              wait_until="domcontentloaded")
    page.wait_for_timeout(4500)
    soft_popups(page)
    cands = page.evaluate("""(name) => {
      const out=[]; const fn=name.toLowerCase().split(' ')[0];
      document.querySelectorAll('a[href*=\"facebook.com/\"]').forEach(a=>{
        const t=(a.innerText||'').trim();
        if(t && t.toLowerCase().includes(fn)) out.push({t:t.slice(0,40),h:a.getAttribute('href').split('?')[0]});
      });
      // de-dupe by href
      const seen=new Set(),res=[]; out.forEach(o=>{if(!seen.has(o.h)){seen.add(o.h);res.push(o);}});
      return res.slice(0,8);
    }""", NAME)
    print("people candidates:", cands)
    if not cands:
        page.screenshot(path=SHOT); print("ERR: no profile match for", NAME); done(1)
    URL = cands[0]["h"]

# 2) open profile, click the blue Message button
page.goto(URL, wait_until="domcontentloaded")
page.wait_for_timeout(4500)
soft_popups(page)
name_h1 = ""
try: name_h1 = page.locator("h1").first.inner_text().strip()
except: pass
print("profile:", URL, "| name:", name_h1)
try:
    page.get_by_role("button", name="Message").first.click(timeout=6000)
except Exception as e:
    page.screenshot(path=SHOT); print("ERR: no Message button:", str(e)[:60]); done(1)
page.wait_for_timeout(3500)
soft_popups(page)
page.wait_for_timeout(1000)

# 3) STRICT composer
box, al = dm_composer(page)
if box is None:
    page.screenshot(path=SHOT); print("ERR: no 'Write to' DM composer found"); done(1)
print("composer:", repr(al))
box.click(); page.wait_for_timeout(400)
box.type(MSG, delay=90)
page.wait_for_timeout(700)
page.screenshot(path=SHOT)
if DRY:
    print("DRY: typed into", repr(al), "but NOT sent"); done(0)
box.press("Enter")
page.wait_for_timeout(2500)
page.screenshot(path=SHOT)
sent_ok = (box.inner_text().strip() in ("", "\n")) and page.get_by_text(MSG, exact=True).count() >= 1
print("SENT_OK:", sent_ok, "to", name_h1 or URL)
done(0)
