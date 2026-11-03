import UI from "./ui.js";

const button = document.getElementById("browser42_navigation_button");

button.addEventListener("click", () => {
    if (!UI.rfb) return;
    UI.sendKey(0xffc8, "F11");
});

// The hand-off (handoff.py) could not bring the group's tab to the front — it was released, or not
// found after the browser woke — and said so with `?lost=<slug>` (carried here by the Caddyfile's
// /view/ redir). Say it on the viewer, once, in noVNC's own status line, instead of leaving the
// person to hunt. The slug is checked before it is shown; the status line is text, never markup.
const lost = new URLSearchParams(window.location.search).get("lost");
if (lost && /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(lost)) {
    setTimeout(() => UI.showStatus(
        `הכרטיסייה של «${lost}» לא נמצאה — אם היא עוד פתוחה, בחר אותה מרצועת הכרטיסיות למעלה`,
        "warn", 15000), 3000);
}
