# Human-verification challenges (captcha) and the office browser

What the office browser meets, how the checks actually decide in 2026, what passes and what fails,
and what this deployment does about it. Written 2026-10-09 for work item **DGO-504 (cap-001)**, from
the measured case below plus the sources named at the end. Sources are dated where the page carries a
date; everything attributed to a vendor is *their* claim, not a measurement of ours.

## The case that produced this file

2026-10-09, the office browser (browser42) opened `claude.ai/code/session_01QiKPMAiRudn1ZkBTibk5UT`
for the owner. The profile had never signed in to claude.ai, so the page was the sign-in screen; the
click on **"Continue with Google"** raised a **Cloudflare Turnstile image round** ("Click on the item
used for gardening") *inside a cross-origin iframe*. Two things were true and both are the reason
this file exists:

- `bbox b42 task inspect` — the office's own loop — returned **no controls at all**: the challenge
  frame is not the page, and the inspector reads the page. The agent was blind to it.
- Solving it needed a click inside that frame. It was done by hand: a screenshot, a guess at the page
  coordinates, and `xdotool` — an off-loop tool, and exactly the kind of thing that should never be
  the only way.

After the challenge was passed and the Google OAuth flow finished, the profile held `.claude.ai`'s
`sessionKey` (verified in the protected profile snapshot taken 03:47 the same night).

## How the checks actually decide (2026)

Cloudflare's bot management is layered and **configured per zone**, so two sites behind it behave
differently toward the same browser ([scraping-wiki, Cloudflare](https://raw.githubusercontent.com/TheWebScrapingClub/scraping-wiki/6c3e24e2a837834125245432bd5922a6cdef382e/entities/cloudflare.md), last updated 2026-04-22):

- **Transport level**: TLS characteristics and HTTP/2 fingerprint. A user-agent that disagrees with
  the real TLS signature is a flag before any content is served.
- **JS detection (JSD)** collects browser-environment signals and, on success, issues `cf_clearance`;
  the `__cf_bm` cookie is issued separately and is short-lived. `cf_clearance` is **session-bound**
  (IP + user-agent): injecting it into a mismatched context "reliably fails", and where a zone allows
  it, it can live for months.
- **Turnstile** runs in three modes: *managed* (may show a round — our case), *non-interactive*
  (silent), *invisible*. The same source: non-interactive Turnstile is the mode a stealth browser is
  expected to pass silently.
- **ML bot score 1–99** against a zone-specific threshold; **rate limiting is enforced separately**
  from bot detection, so "blocked at request 30" can be volume policy rather than a detection.
- **Origin exposure** (2025-11): a split-DNS setup — `www` proxied, apex left in DNS-only — leaks the
  real origin; that is an *operator* misconfiguration and not something this office will ever be on
  the other end of.

## What passes and what fails, per approach

| Approach | Vendor-claimed / measured result | Date & source |
|---|---|---|
| Stock Playwright/Puppeteer | reCAPTCHA v3 ≈0.1 (bot); Turnstile FAIL | [CloakBrowser README](https://github.com/CloakHQ/CloakBrowser/blob/main/README.md) (Oct 2026) |
| `playwright-stealth` / `undetected-chromedriver` / `puppeteer-extra` | flag-based or JS-injected patches; the patches themselves are detected | same README; scraping-wiki calls uc "largely stagnant" |
| **CloakBrowser** (Chromium with C++ source-level patches) | reCAPTCHA v3 **0.9**, Turnstile non-interactive **PASS**, Turnstile **managed = single click**, CDP "not detected", TLS ja3n/ja4 matching Chrome | CloakBrowser README, last tested Oct 2026, Chromium 154 |
| **Camoufox** (Firefox-based) | best on *strict* Cloudflare configs — 99% on a lenient zone, **31%** on Indeed (rate-limited after ~29 URLs); Chrome-based tools 0% there | scraping-wiki benchmark, 2026 |
| Solver APIs (2Captcha / CapSolver) | 8/8 on demo types, ~$3/1000, Turnstile ~5 s; **hCaptcha is the hard one** (timeouts >100 s) | [clawdbrunner/captcha-solver SKILL.md](https://github.com/clawdbrunner/captcha-solver/blob/main/SKILL.md) (tests dated 2026-05-12 / 2026-05-20) |
| Free local solvers | click a Turnstile checkbox; ALTCHA proof-of-work; Prosopo | same skill, "Layer 2" |

The layered shape the field converged on is prevention → free local solving → paid API, and the
honest summary of that skill's own numbers is that **prevention is what works** ("CloakBrowser handles
~80% of CAPTCHAs by prevention — most sites never trigger a challenge").

## What this office does — and the three things it deliberately does not

**The office browser already is the prevention layer.** `browser42-browser` runs `cloakserve` (the
CloakBrowser engine — `ps` shows it in the container) with a **persistent profile** (`cloakprofile`),
an owner-warmed cookie jar, and a real Google session. Prevention is therefore not a new dependency;
it was already installed, and the case above happened on a *first visit with no cookies at all* —
which the vendor's own troubleshooting names as the common cause of first-visit challenges.

**The solve lives in the one task loop** — `bbox b42 task captcha` (new, 2026-10-09):

```bash
./bbox b42 task captcha <slug> detect        # the challenge, its instruction, its targets, a picture
./bbox b42 task captcha <slug> click <index>   # ONE human-like click (0,4,7 = several in one round)
./bbox b42 task captcha <slug> click '@x:y'    # by PAGE pixel, when the DOM hides the widget
```

- `detect` answers `{present, kind, frame_url, instruction, options[{index,x,y,size,role,label}],
  attempts, token, screenshot}` — the targets are in **page** coordinates, the frame's own coordinates
  plus its offset, and the picture is saved as task evidence so a caller that can *see* decides.
- `click <index>` presses that one target with a curved approach, a settle and a press
  (`_human_click`), then reports what it caused. Kinds recognised: turnstile, recaptcha, hcaptcha,
  datadome, altcha.
- **After 3 clicks the verb refuses by name** (`captcha_attempts_exhausted`) and names the hand-off:
  the owner at `http://browser42.localhost:8080/view/`. A challenge is a security control; an agent
  that keeps clicking is how an account gets flagged, and an account lockout costs the owner far more
  than one unsolved round.
- A page whose own address merely *names* a widget is not a challenge — measured bug, kept as a test
  (`test_a_demo_page_that_names_recaptcha_is_not_a_challenge`).

**It does not use solver services, farms, or token vendors, and that is a decision with reasons:**
1. A Turnstile/reCAPTCHA token is bound to the client that earned it (fingerprint, IP, session). A
   token solved elsewhere is rejected or lowers this profile's trust — paying for it can *cost* more
   than it buys.
2. It requires shipping a page's identity — sitekey, URL, often a screenshot — to a stranger. This
   browser holds the owner's mail, drive, Plane and Claude sessions; a page screenshot is company
   data. The instruction here is explicit: nothing leaves the office.
3. A token farm is a business in *other people's* captchas. This browser's job is the owner's own
   logins; the whole point is to look like what it is.

**Three habits of our own driver that the vendor names as scoring signals** (and what to do instead),
from the CloakBrowser README's "reCAPTCHA v3 scores are low" section:
- `page.wait_for_timeout()` is a CDP round trip → use a native sleep. The captcha path does.
- `fill()` sets a value with no keyboard events → type with a delay where it matters.
- Frequent `evaluate()`/screenshot traffic before a check → keep it down around a challenge.
- Spend ≥15 s on the page and space requests ≥30 s apart, or the score drops regardless of the
  fingerprint.

## Measured proof (2026-10-09, this office)

| Page | What happened |
|---|---|
| `demo.turnstile.workers.dev` (Cloudflare's own demo) | `captcha detect` → `present:false`, **`token:true`** — the non-interactive widget resolved with no interaction at all (prevention layer working) |
| `google.com/recaptcha/api2/demo` | `detect` → `kind:"recaptcha"`, anchor frame, instruction *"I'm not a robot"*, 1 target at (60, 372.5); `click 0` → attempts 1; re-`detect` → **`token:true`**; screenshot shows the green checkmark. No image round was raised. |

Unit tests: `apps/browser42/test_group_manager.py` (36 tests, including the frame-matcher cases) run
inside the browser container.

## Round two (same night): what makes the IMAGE round work, and what a widget hides

The first pass proved a checkbox round. The owner then asked for the round that actually stopped the
office — "this one in particular" — to work by itself. Four things were measured on live pages, and
each of them is now code:

1. **A challenge is not always an iframe with a telling URL.** On a full-page interstitial the widget
   frame reported **an empty URL**, so a URL match can never find it; the page's own words
   (`Performing security verification`, `Verify you are human`) do, and a frame that fails both is
   probed by *content* (`kind: turnstile-frame`). `frames` and `scanned` travel in every answer so
   the next reader can see what the loop actually looked at.
2. **Cloudflare's newest widget is unreadable to the DOM.** On `nowsecure.nl` and on a demo page the
   checkbox was on screen and *every* DOM read returned nothing — page JavaScript, a shadow-DOM walk
   and a Playwright locator alike (a closed shadow root). The way through is the one the owner
   watched happen by hand: **look at the picture and click the pixel.** `captcha click '@x:y'` does
   exactly that, and it works even when `detect` found nothing (`present:false` carries a `hint` that
   says so). The picture is a viewport screenshot in CSS pixels, which are the units `page.mouse`
   takes — no coordinate conversion, no X-level tool.
3. **"No frame" is not "solved".** On a hostile demo page a click emptied the widget box and the
   interstitial never moved on; the first version reported that as `solved`. Every click now reports
   `solved` (a token came out), `advanced` (a new round with new pictures) or `same`, and a page-level
   marker that is still there means `same`.
4. **The tiles have to be separate pictures.** One screenshot of the whole widget cannot be read tile
   by tile; `captcha detect` now crops each tile (`options[].tile`) so a caller that can see answers
   a grid in one turn. A multi-select round is one round: `captcha click 0,4,7`.

### Measured, 2026-10-09 (this office, through the loop)

| Page | Result |
|---|---|
| `google.com/recaptcha/api2/demo` | `detect` → anchor frame, instruction "I'm not a robot", 1 target; `click 0` → `changed:"solved"`, **`token:true`**, green check in the picture |
| `nowsecure.nl` (a deliberately hard Cloudflare test page, widget rotated and DOM-unreadable) | `detect` → `present:false` + hint; the widget picture showed the checkbox; `click '@300:292'` → **`token:true`** and the page's own widget answers **"Success!"** |
| `nopecha.com/demo/cloudflare` (a solver vendor's demo, hostile by design) | the interstitial was detected and the checkbox was clicked by pixel (its box emptied), but the page never resolved — reported honestly as `same`, not as a pass |
| `demo.turnstile.workers.dev` | no interactive tier at all — the non-interactive widget resolved silently (`token:true`) |

Honest summary: **the loop now reads and answers every shape of this challenge that the office has
met, and one of them (`nowsecure.nl`) was passed end to end on a page that no DOM read could see.**
What still costs a round is a *hostile* host that deliberately keeps the profile distrusted; there is
no click that fixes that, and the answer is not to keep clicking (three rounds, then the owner).

## Boundaries — what stays a human's, on purpose

- **The owner's password / 2FA / an account-specific challenge** is his: this verb never types a
  credential and never answers a challenge that asks for something only he knows.
- **A round that fails 3 times** goes to him at `/view` rather than escalating.
- **A blocked login is never worth a locked account**: if the office meets a challenge on a provider
  that threatens lockout (mail, bank, cloud console), the answer is to stop and tell the owner, not
  to push the loop.

## Not done yet (honest list)

- No specialised grid geometry per vendor: the caller picks a target by index, which works for the
  checkbox round and hand-solved image rounds; an *automated* image round still needs the agent's own
  vision in the loop (that is the design — the agent sees, the browser clicks).
- `humanize=True` (the vendor's Bézier-curve engine) lives in their Python/JS wrapper; this container
  drives Chromium over CDP, so the human-like motion is implemented in `_human_click` instead.
- No proxy: this browser is the owner's own machine and IP. A datacenter IP is a separate reputation
  problem this deployment does not have.

## Sources

- [CloakBrowser README](https://github.com/CloakHQ/CloakBrowser/blob/main/README.md) — patches, test table (last tested Oct 2026), configuration for anti-bot sites, troubleshooting (first-visit challenges, `--disable-http2`, "reCAPTCHA v3 scores are low").
- [CloakHQ/cloakbrowser](https://hub.docker.com/r/cloakhq/cloakbrowser) — the engine `cloakserve`, the container this office runs.
- [The Web Scraping Club — Cloudflare entity](https://raw.githubusercontent.com/TheWebScrapingClub/scraping-wiki/6c3e24e2a837834125245432bd5922a6cdef382e/entities/cloudflare.md) (updated 2026-04-22) — TLS/HTTP-2, JSD, `cf_clearance` binding, Turnstile modes, ML score vs rate limiting, per-tool benchmarks.
- [clawdbrunner/captcha-solver SKILL.md](https://github.com/clawdbrunner/captcha-solver/blob/main/SKILL.md) — the three-layer model, per-type success table, solver costs (tests dated 2026-05).
- [waguriagentic/captcha-solver](https://github.com/waguriagentic/captcha-solver) — a local sidecar built on the same engine (what a hosted solver would mean here).
- [Kameleo — clicking the Turnstile checkbox](https://kameleo.io/blog/click-cloudflare-turnstile-checkbox) — the managed-mode checkbox as the single interaction a passing session needs.
