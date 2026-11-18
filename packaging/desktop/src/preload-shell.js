// The bridge of the app's OWN screens (ui/welcome.html, ui/rail.html — local files): what they may ask the main
// process. The office's pages never get this one; theirs is preload-office.js.
'use strict';
const { contextBridge, ipcRenderer } = require('electron');

const hello = ipcRenderer.sendSync('dgo:hello');
const EVENTS = new Set(['offices', 'local-state', 'local-line']);

contextBridge.exposeInMainWorld('dgo', {
  locale: hello.locale,
  version: hello.version,
  offices: () => ipcRenderer.invoke('dgo:offices'),
  probe: (address) => ipcRenderer.invoke('dgo:probe', String(address || '')),
  connect: (origin) => ipcRenderer.invoke('dgo:connect', String(origin)),
  open: (origin) => ipcRenderer.invoke('dgo:open', String(origin)),
  addOffice: () => ipcRenderer.invoke('dgo:add'),
  back: () => ipcRenderer.invoke('dgo:back'),
  local: {
    status: () => ipcRenderer.invoke('dgo:local-status'),
    start: () => ipcRenderer.invoke('dgo:local-start'),
    install: () => ipcRenderer.invoke('dgo:local-install'),
  },
  on: (event, cb) => {
    if (EVENTS.has(event)) ipcRenderer.on(`dgo:${event}`, (_e, data) => cb(data));
  },
});
