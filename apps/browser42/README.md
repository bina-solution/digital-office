# browser42 — the office browser

**The human hand-off (DGO-571).** When the office browser needs a person — a captcha round that three
clicks did not pass, a sign-in only the owner can do — every escape path carries ONE address instead of
a generic "open the live view": `bbox b42 handoff <slug>` prints it, the `captcha_attempts_exhausted`
refusal names it, and the owner gets it in the office's notice centre (`notifications:8977`, source
`browser42`, one notice per slug and per episode). The address is a console deep link,
`<console>/a/browser42/handoff/<slug>` (built from `CONSOLE_BASE_URL` + `AUTH_PROTOCOL`, the way a
project-pln work item's link is); opening it reaches `handoff.py` (:8767 inside `browser42-browser`,
only through Caddy's `/handoff/*`, which adds the token the route requires, and the app's
`/a/browser42/handoff` passthrough in `app.json`), which wakes the browser the one way
(`/json/version`, one launch at a time — a request that waited 20 s gets a "waking…" page that reloads
into the same launch), brings that group's tab to the front through the extension broker (action
`front` — the same window, never a new one; after an idle sleep the extension finds the tab again by
its last address and re-tags it), leaves compact presentation (F11) so the tab strip and the group's
name on it are visible, and lands on the live view. A tab it could not bring to the front is said, not
pretended: the view opens with `?lost=<slug>` and the viewer's status line names it. A **stalled** task
is different: the watchdog releases its tab (the reaper would reap a terminal task's tab anyway), so its
notice says so and links the live view, promising no tab. The limit, stated plainly: noVNC shows a
whole **screen**, not a tab, so the promise is "the right tab in front with its group named on the
strip" — the person still sees the other groups' tabs beside it.
