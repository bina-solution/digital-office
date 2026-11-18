// The bridge an OFFICE's page gets (its console, in the office's own session): five things a desktop app does that a
// browser tab cannot, and nothing else — no file, no process, no other office. The main process answers only the
// top frame of a page that is the office's own (main.js `fromOffice`); a frame inside it is never answered.
'use strict';
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('dgoDesktop', {
  version: 1,
  /** The number on the app's icon and on this office in the rail: what the office has waiting. */
  setBadge: (n) => ipcRenderer.send('office:badge', Math.max(0, Math.floor(Number(n) || 0))),
  /** A notice from the system, which opens this office when it is clicked. */
  notify: (title, body) => ipcRenderer.send('office:notify', String(title || '').slice(0, 200), String(body || '').slice(0, 1000)),
  /** A link for the system's browser or mail (https, http, mailto, tel — nothing else). */
  openExternal: (url) => ipcRenderer.send('office:open-external', String(url || '')),
  /** Another office of this app, by its place in the rail (1…) or its address. */
  switchOffice: (which) => ipcRenderer.send('office:switch', String(which || '')),
  /** Whether the office on this computer runs. */
  engineStatus: () => ipcRenderer.invoke('office:engine-status'),
});
