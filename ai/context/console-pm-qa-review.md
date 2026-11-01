# Console (המרכז) — PM page-by-page QA review

Autonomous product-manager pass over the unified business-system shell at `console.localhost`.
Every page was screenshotted at 1440×900 through the console (browser42 → `console:8000`, fresh
context) to review the *actual* user experience — nav + topbar + content together.

## Product state after this pass

The console is the single portal. Two kinds of surface:

| Surface | Mechanism | Console visible? |
|---|---|---|
| dashboard (home), install | **native** console view | yes |
| פנקס, דרייב, מייל, בוט ווצאפ, כל מקביל, מכונה, אימות מערכת, חיבורים | **same-origin embed** `/a/<name>/` | yes |
| מסמכים נכנסים (n8n), התראות (glitchtip), אפליקציות (homepage) | **launch card** (opens the full tool) | — |

## What changed this pass

1. **Install wizard focused on the human.** Leads with *"צעדים שדורשים אותך"* — only the
   actionable connections (needs_action/missing/unset). The 35-item catalog is collapsed behind
   *"כל החיבורים — מתקדם"*. Group headers + statuses are Hebrew; dropped the `env · env` noise.
   Added `title_he` to the user-facing Google/WhatsApp/Gmail catalog entries so the onboarding
   steps read Hebrew-native (חיבור חשבון Google · מפתח Gemini · חיבור מכשיר ווצאפ).
2. **Home is the native dashboard.** *"לוח בקרה"* renders the console's own live KPI strip
   (mail · running · attention · healthy/total · install steps) + module grid, instead of opening
   the homepage service board in a new tab.
3. **פנקס (morning) embeds in-shell.** Relativized its asset + API URLs; console nav stays visible.
4. **Proxy hardening.** Root-absolute `href/src/action` refs are rewritten to the proxied path
   (a `<base>` only rebases *relative* URLs). Proxied HTML is now sent `no-cache` — without it the
   browser cached the rewritten shell and masked console-side embed changes inside the iframe.
5. **De-duplicated embedded chrome.** Each embedded app repeated its own sidebar brand/logo,
   doubling the header. Injected embed CSS hides `.side/.sidebar .brand` for proxied apps
   (scoped to sidebars, so single-column apps keep their page title). drive/mail/whatsapp now read
   as one product with a functional sub-nav, not two stacked brands.

## Page-by-page verdicts

- **לוח בקרה** — native, live KPIs, module grid. ✓
- **מסך התקנה** — focused, Hebrew-native, business-identity form. ✓
- **פנקס** — embedded; onboarding form loads through the proxy. ✓
- **דרייב** — embedded; folder panel + upload; brand de-duped. ✓
- **מייל** — embedded; label nav + search; brand de-duped. ✓
- **בוט ווצאפ** — embedded; **SSO-only, live QR, no own login**; brand de-duped. ✓
- **כל מקביל** — (other track) KPI cards + windowed service▸process timeline. ✓
- **מכונה** — embedded; single column; `api/overview` returns 200 (~s to load Docker stats). ✓
- **אימות מערכת** — embedded; test suite list. ✓ (test IDs English — technical, fine)
- **חיבורים ומפתחות** — embedded; Bina status table. ✓ (infra titles English — advanced view)
- **מסמכים נכנסים / התראות / אפליקציות** — launch cards (see below).

## Deliberate limits (not bugs)

- **Heavy third-party SPAs can't be path-prefix embedded.** n8n / glitchtip / homepage bake an
  empty `basePath`, so under the `/a/` proxy they hydrate blank. Cross-origin iframe to their own
  host is the only alternative and is blocked/degraded: **glitchtip sends `X-Frame-Options: DENY`**;
  n8n would show a separate in-frame login (third-party cookies not sent across `*.localhost`).
  A blank embed is worse than an honest launch card, so these open the full tool. A native INDOX
  page (querying the pipeline data directly) is the real long-term answer for מסמכים נכנסים.
- **Infra connection titles stay English** in the advanced connections view (`Redis password`,
  `Authentik Django secret key`, …). Translating machine-secret names hurts more than it helps;
  the Hebrew treatment is applied where a human acts (the install wizard).

## Open / watch

- `authentik-postgres-password` probe intermittently `probe failed: Name or service not known`
  (Docker DNS degradation, see [[docker-desktop-dns-degradation]]) — makes the install-steps pill
  flap 3↔4. Infra-transient, not a console defect.
