// The Digital Office desktop app (DGO-1972). One window holds the offices a person works in: each office is its own
// console in its own session, a rail beside them once there are two, a first run that connects to an office or opens
// the one on this computer, and a tray icon that keeps the app (and the office's notices) alive when the window is
// closed. A thin shell: every screen inside the window is the office's own; the app adds only what a tab cannot.
//
// Security (Electron's checklist, as the research set it): every renderer sandboxed, no Node in any page; office
// pages get the five functions of preload-office.js and nothing else; a page leaves its office only for the system's
// browser; camera, microphone and screen sharing are granted to the office's meetings alone (offices.js mayGrant).
'use strict';
const {
  app, BaseWindow, BrowserWindow, WebContentsView, Menu, Tray, Notification, nativeImage, session, shell, ipcMain, net,
  desktopCapturer, dialog, screen, webContents,
} = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const O = require('./offices');
const local = require('./local');
const words = require('./ui/i18n');

app.enableSandbox();
if (!app.requestSingleInstanceLock()) app.exit(0);

const UI = path.join(__dirname, 'ui');
const ICONS = app.isPackaged ? path.join(process.resourcesPath, 'icons')
  : path.join(__dirname, '..', '..', '..', 'platform-base', 'console', 'static', 'icons');   // the console's own icons
const RAIL = 64;

let t, lang;                 // the words, once the system's language is known
let pendingLink = null;      // a dgo:// link that came before the window (macOS opens the app with it)
let win, tray, rail, welcome;
let settingsFile;
const views = new Map();     // origin → the office's WebContentsView
const state = { offices: [], current: null, adding: false, bounds: null, toldTray: false };
const live = { running: false, starting: false, dgo: null };
const badges = new Map();
let quitting = false;

// ── what the app keeps: the offices, the one on screen, the window's place ──────────────────────────────────────
function load() {
  try {
    const s = JSON.parse(fs.readFileSync(settingsFile, 'utf8'));
    state.offices = (s.offices || []).filter((o) => O.isOfficeOrigin(o.origin));
    state.current = state.offices.some((o) => o.origin === s.current) ? s.current : state.offices[0]?.origin || null;
    state.bounds = s.bounds || null;
    state.toldTray = !!s.toldTray;
  } catch { /* the first run: nothing kept yet */ }
}

function save() {
  const s = { offices: state.offices, current: state.current, bounds: state.bounds, toldTray: state.toldTray };
  fs.mkdirSync(path.dirname(settingsFile), { recursive: true });
  fs.writeFileSync(`${settingsFile}.tmp`, JSON.stringify(s, null, 2));
  fs.renameSync(`${settingsFile}.tmp`, settingsFile);
}

function officesOut() {
  return {
    current: state.current,
    offices: state.offices.map((o) => {
      const { local: isLocal, label } = O.labelOf(o.origin);
      return { origin: o.origin, label, local: isLocal, running: isLocal && live.running, badge: badges.get(o.origin) || 0 };
    }),
  };
}

// ── one GET with no cookies and no redirect followed: how the app asks an address what it is ────────────────────
let probeSession;
function ask(url) {
  return new Promise((resolve) => {
    let done = false;
    const end = (r) => { if (!done) { done = true; clearTimeout(timer); resolve(r); } };
    const req = net.request({ url, session: probeSession, redirect: 'manual', useSessionCookies: false });
    const timer = setTimeout(() => { req.abort(); end({ status: 0, error: 'unreachable' }); }, 8000);
    req.on('redirect', (status, _method, location) => { req.abort(); end({ status, location }); });
    req.on('response', (res) => {
      let body = '';
      res.on('data', (c) => { if (body.length < 65536) body += c; });
      res.on('end', () => { let json = null; try { json = JSON.parse(body); } catch { /* not JSON */ } end({ status: res.statusCode, json }); });
    });
    req.on('error', () => end({ status: 0, error: 'unreachable' }));
    req.end();
  });
}

async function probe(address) {
  let tries;
  try { tries = O.candidates(address); } catch (e) { return { error: e.message }; }
  let answered = false;
  for (const origin of tries) {
    const r = await ask(`${origin}/manifest.webmanifest`);
    if (r.status) answered = true;
    const seen = O.readProbe(origin, r);
    if (seen.kind !== 'not-office') return seen;
  }
  return answered ? { kind: 'not-office' } : { error: 'unreachable' };
}

// ── an office's session and pages: what they may do ──────────────────────────────────────────────────────────────
const hardened = new Set();
function harden(ses, scope) {
  if (hardened.has(ses)) return;
  hardened.add(ses);
  ses.setPermissionRequestHandler((wc, permission, cb, details) =>
    cb(O.mayGrant(permission, details.requestingUrl || wc.getURL(), scope)));
  ses.setPermissionCheckHandler((_wc, permission, requestingOrigin) => O.mayGrant(permission, requestingOrigin, scope));
  // a meeting's «share screen»: the system's own picker where there is one (macOS 15+); elsewhere the person chooses
  // the screen, or cancels — never shared without being asked
  ses.setDisplayMediaRequestHandler(async (request, callback) => {
    if (!O.mayGrant('display-capture', request.securityOrigin || request.frame?.url || '', scope)) return callback(null);
    try {
      const screens = await desktopCapturer.getSources({ types: ['screen'] });
      if (!screens.length) return callback(null);
      // asked on the window the meeting is in: a meeting opened in its own window, else the app's
      const asker = request.frame && webContents.fromFrame(request.frame);
      const owner = (asker && BrowserWindow.fromWebContents(asker)) || win;
      if (owner === win) showWindow();
      const { response } = await dialog.showMessageBox(owner, {
        type: 'question', message: t.shareTitle, detail: t.shareText, noLink: true, defaultId: 0, cancelId: screens.length,
        buttons: [...screens.map((s, i) => s.name || `${t.screen} ${i + 1}`), t.cancel],
      });
      callback(response < screens.length ? { video: screens[response] } : null);
    } catch {
      callback(null);
    }
  }, { useSystemPicker: true });
}

function guard(wc, scope) {
  const leave = (e, url) => {
    if (O.inScope(url, scope)) return;
    e.preventDefault();
    if (O.mayOpenOutside(url)) shell.openExternal(url);
  };
  wc.on('will-navigate', leave);                       // the top frame only
  wc.on('will-redirect', (e, url) => { if (e.isMainFrame) leave(e, url); });   // a frame inside the page is the page's
  wc.setWindowOpenHandler(({ url }) => {
    if (O.inScope(url, scope)) {
      return { action: 'allow', overrideBrowserWindowOptions: { autoHideMenuBar: true, icon: iconPath(256),
        webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false } } };
    }
    if (O.mayOpenOutside(url)) shell.openExternal(url);
    return { action: 'deny' };
  });
  wc.on('did-create-window', (child) => guard(child.webContents, scope));
}

function officeView(origin) {
  if (views.has(origin)) return views.get(origin);
  const scope = O.scopeOf(origin);
  const ses = session.fromPartition(O.partitionFor(origin));
  harden(ses, scope);
  const v = new WebContentsView({ webPreferences: {
    session: ses, preload: path.join(__dirname, 'preload-office.js'),
    sandbox: true, contextIsolation: true, nodeIntegration: false, webSecurity: true, spellcheck: true,
  } });
  guard(v.webContents, scope);
  v.webContents.on('page-title-updated', (_e, title) => { if (state.current === origin && !state.adding) win.setTitle(title); });
  v.webContents.loadURL(`${origin}/`);
  win.contentView.addChildView(v);
  views.set(origin, v);
  return v;
}

/** Which office sent an IPC: the top frame of an office's own page, or nobody. */
function fromOffice(e) {
  for (const [origin, v] of views) {
    if (v.webContents !== e.sender) continue;
    const frame = e.senderFrame;
    if (!frame || frame !== e.sender.mainFrame || !O.inScope(frame.url, O.scopeOf(origin))) return null;
    return origin;
  }
  return null;
}

// ── the window: one office, or the rail and the office on screen, or the first run ───────────────────────────────
function shellView(file) {
  const v = new WebContentsView({ webPreferences: {
    preload: path.join(__dirname, 'preload-shell.js'), sandbox: true, contextIsolation: true, nodeIntegration: false,
  } });
  v.webContents.on('will-navigate', (e) => e.preventDefault());
  v.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  v.webContents.loadFile(path.join(UI, file));
  win.contentView.addChildView(v);
  return v;
}

// Chromium counts a view's x from the leading edge: under a right-to-left locale, x=0 is the window's RIGHT side
// (measured: with LANG=he_IL the rail set at width−64 was drawn on the left)
const MIRRORED_LOCALE = /^(ar|fa|he|iw|ps|ur|yi)\b/i;

function layout() {
  const [w, h] = win.getContentSize();
  const showWelcome = state.adding || !state.offices.length;
  const showRail = !showWelcome && state.offices.length >= 2;
  // the rail stands on the side the office's own menu is on: the right in Hebrew, the left in English
  const railAtZero = (t.dir === 'rtl') === MIRRORED_LOCALE.test(app.getLocale());
  welcome.setVisible(showWelcome);
  welcome.setBounds({ x: 0, y: 0, width: w, height: h });
  rail.setVisible(showRail);
  rail.setBounds({ x: railAtZero ? 0 : w - RAIL, y: 0, width: RAIL, height: h });
  const office = { x: showRail && railAtZero ? RAIL : 0, y: 0, width: showRail ? w - RAIL : w, height: h };
  for (const [origin, v] of views) {
    v.setVisible(!showWelcome && origin === state.current);
    v.setBounds(office);
  }
  win.setTitle(showWelcome ? t.title : views.get(state.current)?.webContents.getTitle() || t.title);
}

function broadcast() {
  const out = officesOut();
  rail.webContents.send('dgo:offices', out);
  welcome.webContents.send('dgo:offices', out);
  refreshTray();
}

function open(origin, at) {
  if (!state.offices.some((o) => o.origin === origin)) return;
  state.current = origin;
  state.adding = false;
  const v = officeView(origin);
  if (at && O.inScope(at, O.scopeOf(origin))) v.webContents.loadURL(at);
  save();
  layout();
  broadcast();
}

function connect(origin) {
  if (!O.isOfficeOrigin(origin)) return;
  if (!state.offices.some((o) => o.origin === origin)) {
    const o = { origin, added: new Date().toISOString() };
    if (O.labelOf(origin).local) state.offices.unshift(o);    // «this computer» first: Ctrl+1, the rail's top
    else state.offices.push(o);
  }
  open(origin);
}

function addMode(on = true) {
  state.adding = on || !state.offices.length;
  if (on) welcome.webContents.reload();
  layout();
}

function showWindow() {
  if (win.isMinimized()) win.restore();
  win.show();
  win.focus();
}

// ── the office on this computer ───────────────────────────────────────────────────────────────────────────────────
function localOut() {
  return { running: live.running, starting: live.starting, installed: !!live.dgo, origin: local.ORIGIN };
}

async function pollLocal() {
  const was = live.running;
  live.running = await local.running(ask);
  if (live.running !== was) {
    if (live.running) live.starting = false;
    welcome.webContents.send('dgo:local-state', localOut());
    broadcast();
  }
}

async function startLocal() {
  if (!live.dgo || live.starting || live.running) return localOut();
  live.starting = true;
  welcome.webContents.send('dgo:local-state', localOut());
  local.start(live.dgo, (line) => welcome.webContents.send('dgo:local-line', line)).then(async (code) => {
    live.starting = false;
    welcome.webContents.send('dgo:local-line', `dgo run → ${code}`);
    await pollLocal();
    welcome.webContents.send('dgo:local-state', localOut());   // a failed start brings its button back, too
    broadcast();
  });
  return localOut();
}

// ── the tray, the menu, links into the app ───────────────────────────────────────────────────────────────────────
function iconPath(size) {
  return path.join(ICONS, size > 192 ? 'icon-512.png' : 'icon-192.png');
}

function refreshTray() {
  if (!tray) return;
  const out = officesOut();
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: t.trayOpen, click: showWindow },
    { type: 'separator' },
    ...out.offices.map((o) => ({
      label: `${o.local ? t.thisComputer : o.label}${o.badge ? ` (${o.badge})` : ''}`, type: 'radio',
      checked: o.origin === out.current, click: () => { showWindow(); open(o.origin); },
    })),
    ...(out.offices.length ? [{ type: 'separator' }] : []),
    { label: `${t.thisComputer}: ${live.running ? t.trayOn : t.trayOff}`, enabled: false },
    ...(!live.running && live.dgo ? [{ label: t.start, click: startLocal }] : []),
    { label: `${t.addOffice}…`, click: () => { showWindow(); addMode(); } },
    { type: 'separator' },
    { label: t.quit, click: () => { quitting = true; app.quit(); } },
  ]));
  const total = [...badges.values()].reduce((a, b) => a + b, 0);
  tray.setToolTip(total ? `${t.title} (${total})` : t.title);
  app.setBadgeCount(total);
}

function buildMenu() {
  const officeItems = Array.from({ length: 9 }, (_, i) => ({
    label: `${t.office} ${i + 1}`, accelerator: `CmdOrCtrl+${i + 1}`,
    click: () => { const o = state.offices[i]; if (o) open(o.origin); },
  }));
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    ...(process.platform === 'darwin' ? [{ role: 'appMenu' }] : []),
    { role: 'editMenu' },
    { label: t.office, submenu: [
      { label: `${t.addOffice}…`, accelerator: 'CmdOrCtrl+Shift+N', click: () => addMode() },
      { label: t.reload, accelerator: 'CmdOrCtrl+R', click: () => views.get(state.current)?.webContents.reload() },
      { type: 'separator' }, ...officeItems,
    ] },
    { role: 'viewMenu', submenu: [{ role: 'resetZoom' }, { role: 'zoomIn' }, { role: 'zoomOut' }, { type: 'separator' },
      { role: 'togglefullscreen' }, ...(app.isPackaged ? [] : [{ role: 'toggleDevTools' }])] },
    { role: 'windowMenu' },
  ]));
}

/** dgo://open?office=<host>&path=/#/m/indox — a link that opens an office of this app at a screen. */
function deepLink(link) {
  let u;
  try { u = new URL(link); } catch { return; }
  if (u.protocol !== 'dgo:' || u.hostname !== 'open') return;
  const host = (u.searchParams.get('office') || '').toLowerCase();
  const o = state.offices.find((x) => { const s = O.scopeOf(x.origin); return s.host === host || s.domain === host; });
  if (!o) return;
  showWindow();
  const at = new URL(u.searchParams.get('path') || '/', o.origin).href;
  open(o.origin, at);
}

// ── IPC: the app's own screens ───────────────────────────────────────────────────────────────────────────────────
function fromShell(e) { return e.sender === rail?.webContents || e.sender === welcome?.webContents; }
const shellHandle = (channel, fn) => ipcMain.handle(channel, (e, ...a) => (fromShell(e) ? fn(...a) : null));

ipcMain.on('dgo:hello', (e) => { e.returnValue = fromShell(e) ? { locale: lang, version: app.getVersion() } : {}; });
shellHandle('dgo:offices', () => officesOut());
shellHandle('dgo:probe', (address) => probe(address));
shellHandle('dgo:connect', (origin) => connect(origin));
shellHandle('dgo:open', (origin) => open(origin));
shellHandle('dgo:add', () => addMode());
shellHandle('dgo:back', () => addMode(false));
shellHandle('dgo:local-status', () => localOut());
shellHandle('dgo:local-start', () => startLocal());
shellHandle('dgo:local-install', () => shell.openExternal(local.INSTALL_URL));

// ── IPC: an office's page (preload-office.js) ────────────────────────────────────────────────────────────────────
ipcMain.on('office:badge', (e, n) => {
  const origin = fromOffice(e);
  if (!origin) return;
  badges.set(origin, Math.min(9999, Math.max(0, Number(n) || 0)));
  broadcast();
});
ipcMain.on('office:notify', (e, title, body) => {
  const origin = fromOffice(e);
  if (!origin || !Notification.isSupported()) return;
  const n = new Notification({ title: String(title).slice(0, 200), body: String(body).slice(0, 1000), icon: iconPath(192) });
  n.on('click', () => { showWindow(); open(origin); });
  n.show();
});
ipcMain.on('office:open-external', (e, url) => { if (fromOffice(e) && O.mayOpenOutside(url)) shell.openExternal(url); });
ipcMain.on('office:switch', (e, which) => {
  if (!fromOffice(e)) return;
  const i = Number(which) - 1;
  const o = Number.isInteger(i) ? state.offices[i] : state.offices.find((x) => O.scopeOf(x.origin).host === which);
  if (o) open(o.origin);
});
ipcMain.handle('office:engine-status', (e) => (fromOffice(e) ? { running: live.running } : null));

// ── the app's life ───────────────────────────────────────────────────────────────────────────────────────────────
app.on('web-contents-created', (_e, wc) => wc.on('will-attach-webview', (ev) => ev.preventDefault()));
app.on('second-instance', (_e, argv) => {
  const link = argv.find((a) => a.startsWith('dgo://'));
  if (!win) { pendingLink = link || pendingLink; return; }     // launched twice before the window exists
  showWindow();
  if (link) deepLink(link);
});
// a site that asks for a client certificate gets none: Electron would otherwise hand it the first one, unasked
app.on('select-client-certificate', (e, _wc, _url, _list, callback) => { e.preventDefault(); callback(); });
app.on('open-url', (e, link) => { e.preventDefault(); if (win) deepLink(link); else pendingLink = link; });
app.on('activate', () => win && showWindow());
app.on('before-quit', () => { quitting = true; });

app.whenReady().then(() => {
  t = words(app.getPreferredSystemLanguages()[0] || app.getLocale());
  lang = t.dir === 'rtl' ? 'he' : 'en';
  app.setAppUserModelId('il.co.digital-office.desktop');
  if (!app.isDefaultProtocolClient('dgo')) app.setAsDefaultProtocolClient('dgo');
  settingsFile = path.join(app.getPath('userData'), 'offices.json');
  probeSession = session.fromPartition('probe', { cache: false });
  load();
  live.dgo = local.findDgo();

  const b = state.bounds;
  const onScreen = b && screen.getAllDisplays().some((d) => {
    const a = d.workArea;
    return b.x < a.x + a.width && b.x + b.width > a.x && b.y < a.y + a.height && b.y + b.height > a.y;
  });
  win = new BaseWindow({ width: 1280, height: 820, minWidth: 720, minHeight: 480, ...(onScreen ? b : {}),
    title: t.title, icon: iconPath(512), autoHideMenuBar: true, show: false });
  welcome = shellView('welcome.html');
  rail = shellView('rail.html');
  if (state.current) officeView(state.current);
  buildMenu();
  tray = new Tray(nativeImage.createFromPath(iconPath(192)).resize({ width: 16, height: 16 }));
  tray.on('click', showWindow);
  refreshTray();
  layout();
  win.show();

  win.on('resize', layout);
  // the place to come back to: the window's normal bounds, never those of maximised, full screen or minimised
  for (const ev of ['resize', 'move']) win.on(ev, () => { state.bounds = win.getNormalBounds(); });
  win.on('close', (e) => {
    save();
    if (quitting || process.platform === 'darwin' && !tray) return;
    e.preventDefault();                       // the office keeps its notices: the window hides, the tray stays
    win.hide();
    if (!state.toldTray && process.platform !== 'darwin' && Notification.isSupported()) {
      state.toldTray = true;
      save();
      new Notification({ title: t.title, body: t.keepsRunning, icon: iconPath(192) }).show();
    }
  });
  pollLocal();
  setInterval(pollLocal, 15000);
  const link = pendingLink || process.argv.find((a) => a.startsWith('dgo://'));
  if (link) deepLink(link);
});
