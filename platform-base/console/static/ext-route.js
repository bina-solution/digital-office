/* ext-route.js — where a window on an app's OWN host points, and what the address bar says.
 *
 * Two pure functions, in their own file for the same reason `dock-budget.js` is: they are the part of
 * desktop.js that can be WRONG without anything looking wrong — a link that opens the app but not the
 * screen it names looks like a link that works — so they are the part a test can hold
 * (`platform-base/console/test_ext_route.mjs`, gate `console-deeplink-lint`).
 *
 * WHY THE ROUTE MATTERS. An app that lives on its own host (Plane, the forge) is framed by the
 * console on `plane.<console host>`, and a console URL is
 * `#/m/<module>/<the app's inner route>` — `#/m/project-pln/bina/projects/<id>/issues/<id>`. The
 * route is the difference between "opens Plane inside the office" and "opens Plane inside the office,
 * at the work item you were sent". It was dropped for these windows until 2026-10-08 (the content
 * frame has always applied it — app.js `openModule`).
 *
 * The deep link is the SAME composition read backwards: the address bar of such a window names the
 * MODULE (so the copied link opens the same screen inside the office), never the desktop's internal
 * window id (`ext:<id>`, which names no module — a reload of it fell through route() to the first
 * tile, which is a teleport rather than a 404 anybody can see).
 */
(function () {
  "use strict";

  // The address a framed window loads: the app's own origin plus the inner route the link carried.
  function framedUrl(url, route) {
    return String(url || "") + String(route || "");
  }

  // The console deep link of a window: the module's id when it names one, that window's id otherwise.
  function deepLink(moduleId, windowId, route) {
    return "#/m/" + String(moduleId || windowId || "") + String(route || "");
  }

  window.BinaExtRoute = { framedUrl, deepLink };
})();
