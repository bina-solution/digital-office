/* module-ref.js — which tile a link's `<app>` names, when the name is not this office's id.
 *
 * A pure function, in its own file for the same reason `ext-route.js` and `dock-budget.js` are: it
 * is the part that can be WRONG while everything still looks like it works (a link that opens SOME
 * tile looks like a link that works), so it is the part a test can hold —
 * `platform-base/console/test_module_ref.mjs`.
 *
 * WHY A LINK NEEDS THIS. A console URL is `#/m/<app>/<the app's inner route>`, and `<app>` was read
 * as the module id of THIS office. Two ways that breaks on the office the link is READ on:
 *
 *   · `#/m/plane/bina/projects/<id>/issues/<id>` — the app's own ALIAS (`/a/<alias>/` here,
 *     `<alias>.<office>` on a linked office). The registry carries it as `alias`.
 *   · `#/m/project-pln/…` — the MODULE ID on the office that WROTE the link. On a linked office that
 *     app is a tile named `<alias>.<office>` carrying the writer's id in `remote.module_id`.
 *
 * Measured 2026-10-09 (the owner, «הקישור למשימה עדיין לא עובד»): the office's own task tool hands
 * him `#/m/project-pln/…`; on a linked office no module had that id, `route()` fell through to
 * `MODULES[0]`, rewrote the address to it and opened the AGENT — the wrong window, silently, with the
 * link itself looking like it worked. A local tile still wins over a remote one of the same name,
 * and the order is fixed so the same address always lands on the same tile.
 */
(function () {
  "use strict";

  // The names a module answers to, most specific first: its own id, its alias here, then — for a
  // tile of a linked office — what it is called THERE (the id `#/m/…` carries, and its alias).
  function names(m) {
    const r = (m && m.remote) || {};
    return [m && m.id, m && m.alias, r.module_id, r.alias]
      .filter((x) => typeof x === "string" && x !== "");
  }

  function resolve(modules, ref) {
    if (!ref) return null;
    const list = Array.isArray(modules) ? modules : [];
    for (const m of list) if (m && m.id === ref) return m;                  // exact, local or remote
    for (const m of list) if (m && !m.remote && names(m).includes(ref)) return m;   // this office's name
    for (const m of list) if (m && m.remote && names(m).includes(ref)) return m;    // the name it has there
    return null;
  }

  window.BinaModuleRef = { resolve };
})();
