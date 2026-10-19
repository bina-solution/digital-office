/**
 * office-links, node half: an empty apply so the Loader has a host-side row.
 *
 * Everything this plugin does is in the browser (lib/client.js) — the harness's markdown renderer
 * sends every http(s) link to a new tab, and a link to a screen of THIS office belongs in the tab
 * the person is already in. No host-side state, no service, no configuration.
 */
export function apply() {}
