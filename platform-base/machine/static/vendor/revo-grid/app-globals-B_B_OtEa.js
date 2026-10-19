/*!
 * Built by Revolist OU ❤️
 */
import { a as setMode } from './index-Chp_81rd.js';
import { g as getTheme } from './theme.service-BmnDvr6P.js';

function global () {
    setMode(elm => {
        let theme = elm.theme || elm.getAttribute('theme');
        if (typeof theme === 'string') {
            theme = theme.trim();
        }
        const parsedTheme = getTheme(theme);
        if (parsedTheme !== theme) {
            elm.setAttribute('theme', parsedTheme);
        }
        return parsedTheme;
    });
}

const appGlobalScript = global || (() => {});
const globalScripts = appGlobalScript;

export { globalScripts as g };
