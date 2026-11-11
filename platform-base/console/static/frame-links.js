/* frame-links.js — a link INSIDE an embedded app that names the CONSOLE is the shell's to open.
 *
 * WHAT WAS MEASURED (2026-10-12, DGO-501/ui2-060). The office's own task tool hands the owner
 * `http://console.<host>/#/m/project-pln/bina/projects/<id>/issues/<id>`, and it arrives inside an
 * app's frame — the chat, a document, a notification. An `<a>` in that frame is SAME-ORIGIN (every
 * embedded app is proxied under `/a/<id>/` on this very host), so the browser's default action
 * navigated the FRAME: the chat window turned into the console, and the desk never moved. Measured
 * on the live office: the frame went from `/a/bina/` to `/#/m/project-pln/…` with the desktop
 * unchanged. The owner asked for the opposite, in these words: «הכל באותו דסקטופ כשרק הקישור משתנה
 * בלי שנוצר דף חדש בכרום».
 *
 * WHY ONE PLACE. The shell already knows how to move itself — setting the top-level hash is what a
 * copied link does, and route() turns it into a window (desktop) or the content frame (classic). So
 * the fix is not "every app learns to ask the shell"; it is "the frame stops eating the click", and
 * that belongs where the frames are loaded: here, for every app, once.
 *
 * WHAT IS A CONSOLE LINK, EXACTLY — the console's own origin, pathname `/`, and a `#/…` fragment.
 * An app's own links live under `/a/<id>/` and are never touched; an external site, a download and
 * a link that asks for its own tab (ctrl/⌘/middle-click) stay the browser's.
 *
 * The half that can be held without a browser is `isConsoleLink` and `wantsOwnTab`
 * (platform-base/console/test_frame_links.mjs); the live half is a console driven on a deep link
 * (scripts/ui-coverage/desktop-links.py).
 */
(function () {
  "use strict";

  function isConsoleLink(href, origin) {
    if (typeof href !== "string" || !href) return false;
    let u;
    try { u = new URL(href, origin); } catch (e) { return false; }
    if (String(u.origin) !== String(origin)) return false;
    // the console is served at its ROOT — which is the mount point when this shell is framed by
    // another office's console (`window.DGO_MOUNT`, mount.js), and "/" otherwise.
    var root = (window.DGO_MOUNT || "") + "/";
    if (u.pathname !== root && u.pathname !== "") return false;
    return /^#\/[^#]*$/.test(u.hash || "");
  }

  // A person who holds ctrl/⌘/shift, or clicks with the middle button, asked for their own tab —
  // and that is a request the shell does not overrule.
  function wantsOwnTab(e) {
    return !!(e && (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || (e.button || 0) > 0));
  }

  function attach(win, open) {
    // `win` is a frame's window. Cross-origin frames cannot be read at all — the try/catch IS the
    // rule: an app on its own host (Plane, the forge) is not ours to intercept, and its own
    // navigation is not this bug.
    let doc;
    try { doc = win && win.document; } catch (e) { return false; }
    if (!doc || doc.__binaFrameLinks) return false;
    doc.__binaFrameLinks = true;
    doc.addEventListener("click", function (e) {
      const a = e.target && e.target.closest ? e.target.closest("a[href]") : null;
      if (!a) return;
      if (!isConsoleLink(a.href, location.origin)) return;
      if (wantsOwnTab(e)) return;
      e.preventDefault();
      open(a.href);
    });
    return true;
  }

  // Every frame the shell or the desktop loads — the capture phase catches an iframe's load, which
  // does not bubble, and every load re-attaches because a navigation replaces the document.
  function watch(open) {
    const one = (f) => { try { if (f && f.contentWindow) attach(f.contentWindow, open); } catch (e) { /* cross-origin */ } };
    document.addEventListener("load", (e) => {
      if (e.target && e.target.tagName === "IFRAME") one(e.target);
    }, true);
    document.querySelectorAll("iframe").forEach(one);
  }

  window.BinaFrameLinks = { isConsoleLink, wantsOwnTab, attach, watch };
})();
