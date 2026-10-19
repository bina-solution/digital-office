import UI from "./ui.js";

const button = document.getElementById("browser42_navigation_button");

button.addEventListener("click", () => {
    if (!UI.rfb) return;
    UI.sendKey(0xffc8, "F11");
});
