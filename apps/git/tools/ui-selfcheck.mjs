/* ui-selfcheck.mjs — the parts of the browser app that can be PROVEN without a browser.
 *
 * Why this exists. The screen is vanilla JS driven by hash routes, and its historical defects were
 * pure-logic bugs a screenshot would have shown as "the page is empty": a router that rejoined a
 * repository name out of the wrong segments, a branch picker that threw its own choice away, a menu
 * mounted into an element the console also owns. None of those need a browser — they need the
 * functions called with the strings the app really produces.
 *
 * So this file EVALUATES THE SHIPPED SOURCE (`static/app.js`) in a Node VM with a small DOM stub and
 * exercises its pure functions and both screens against canned service answers. It is dev tooling: it
 * is not copied into the image (see Dockerfile) and it is not served.
 *
 * Since DGO-57 the app is deliberately TWO screens — accounts and mirror declarations. The last
 * section is therefore a guard in the opposite direction: it fails if repository display (repo list,
 * file tree, code viewer, issues/PRs/releases) grows back into this app, or if the shared design
 * blocks the platform syncs (gate G27) are dropped from the page while it is being trimmed.
 *
 *   node apps/git/tools/ui-selfcheck.mjs          # exits non-zero on the first failed assertion
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(here, '..', 'static', 'app.js'), 'utf8');
const page = readFileSync(join(here, '..', 'static', 'index.html'), 'utf8');

/* ── a DOM stub just real enough for the module to LOAD and for a render to be READ ─────────────── */
const els = new Map();
function el(id) {
  if (!els.has(id)) {
    els.set(id, {
      id, className: '', style: {}, dataset: {}, value: '', textContent: '', innerHTML: '',
      classList: {
        _s: new Set(),
        add(c) { this._s.add(c); }, remove(c) { this._s.delete(c); },
        toggle(c, on) { if (on === undefined) { this._s.has(c) ? this._s.delete(c) : this._s.add(c); }
                        else if (on) { this._s.add(c); } else { this._s.delete(c); } },
        contains(c) { return this._s.has(c); },
      },
      addEventListener() {}, removeChild() {}, appendChild() {}, querySelector: () => null,
      querySelectorAll: () => [], setAttribute() {}, getAttribute: () => null, onclick: null,
    });
  }
  return els.get(id);
}
const document = {
  getElementById: (id) => el(id), querySelector: () => null, querySelectorAll: () => [],
  createElement: () => el(''), addEventListener() {}, body: el('body'), title: '',
};
const mainHtml = () => (els.get('main') || {}).innerHTML || '';

/* ── the service, canned: a route table, so a render can be asserted against a real answer ──────── */
const ACCOUNTS = [
  { id: 'a1', login: 'solomon', label: 'GitHub — solomon', provider: 'github', state: 'unknown' },
  { id: 'a3', login: 'office', label: "הפורג' של הלשכה", provider: 'forgejo', state: 'unknown' },
];
/** Drain the microtask queue: the screen paints from the cheap list and CORRECTS itself after the
 *  probe, so "what the owner sees" is the second paint and the first one is a separate assertion. */
const flush = async () => { for (let i = 0; i < 25; i++) await Promise.resolve(); };
const ANSWERS = {
  'connections?probe=0': { ok: true, connections: ACCOUNTS, active: 'a1' },
  // the SAME accounts, probed: one live, one code-only, one credential that needs the owner
  'connections?probe=1': { ok: true, active: 'a1', connections: [
    { id: 'a1', login: 'solomon', label: 'GitHub — solomon', provider: 'github', state: 'ok' },
    { id: 'a2', login: 'deploy', label: 'GitLab — deploy token', provider: 'gitlab',
      state: 'git_only', note: 'קוד בלבד (clone/push) — אין API לאימות' },
    { id: 'a3', login: 'office', label: "הפורג' של הלשכה", provider: 'forgejo', state: 'needs_action',
      reason: 'הטוקן פג — יש לחבר מחדש' },
  ] },
  providers: { ok: true, providers: [
    { id: 'github', name: 'GitHub', auth_methods: [
      { id: 'pat', label: 'טוקן אישי', recommended: true, explain: 'יצירה בהגדרות החשבון',
        fields: [{ name: 'token', label: 'טוקן', required: true, type: 'password' }] }] },
    { id: 'forgejo', name: "פורג' מקומי", auth_methods: [
      { id: 'password', label: 'סיסמה', fields: [
        { name: 'user', label: 'משתמש', required: true, type: 'text', dir: 'ltr' },
        { name: 'password', label: 'סיסמה', required: true, type: 'password' }] }] },
  ] },
  'api/mirrors': { ok: true, forge: 'http://forge.example:8080', interval_seconds: 900,
    guards: { max_bytes: 2147483648, min_free_mb: 2048 }, mirrors: [
      { id: 'm1', source_account: 'a1', source_repo: 'solomonBoltin/deployment-hacohen',
        target_owner: 'office', target_repo: 'deployment-hacohen', last_status: 'ok',
        last_run: Math.floor(Date.now() / 1000) - 150, bytes: 1324000000,     // unix seconds, as mirrors.py writes it
        browse_url: 'http://forge.example:8080/office/deployment-hacohen' },
      { id: 'm2', source_account: 'a1', source_repo: 'solomonBoltin/broken-repo',
        target_owner: 'office', target_repo: 'broken-repo', last_status: 'error',
        last_error: 'GIT_MIRROR_MAX_BYTES exceeded', browse_url: 'http://forge.example:8080/office/broken-repo' }] },
};
const calls = [];
/* The shared menu is a CONTRACT, and its own side is executed by platform-base/bina-ui/test_bina_nav.mjs. What
 * this file can prove is this app's half: that it DECLARES a menu (and what it declares) instead of
 * building rows, and that a pick moves the app the way a person expects. So the component is a spy. */
const navMounts = [];          // every declaration handed to BinaNav.mount, in order
const navCalls = [];           // setActive/setBrand/… made on the live nav
const opened = [];             // window.open calls
let liveNav = null;
const BinaNav = {
  mount(el, cfg) {
    navMounts.push({ el, cfg });
    liveNav = {
      el, cfg,
      setActive: (id) => navCalls.push(['setActive', id]),
      setBrand: (o) => navCalls.push(['setBrand', o]),
      setBadge: (id, v) => navCalls.push(['setBadge', id, v]),
      setMeta: (id, v) => navCalls.push(['setMeta', id, v]),
      open: () => navCalls.push(['open']),
    };
    return liveNav;
  },
  svg: () => '<svg></svg>',
};
const lastNav = () => navMounts[navMounts.length - 1];
const navIds = (which) => {
  const n = lastNav(); if (!n) return null;
  const sec = (n.cfg.sections || []).find((x) => x.id === which) || (n.cfg.sections || [])[which];
  return (sec && sec.items ? sec.items : []).map((i) => i.id);
};
const sandbox = {
  BinaNav,
  document, window: { addEventListener() {}, open(...a) { opened.push(a); } }, location: { hash: '#/', reload() {} },
  fetch: async (path, opt) => {
    calls.push({ path, method: (opt && opt.method) || 'GET', body: opt && opt.body });
    const key = String(path);
    if (opt && opt.method && opt.method !== 'GET') return { ok: true, status: 200, json: async () => ({ ok: true }) };
    return { ok: true, status: 200, json: async () => (ANSWERS[key] || { ok: false, error: 'no canned answer: ' + key }) };
  },
  console, setTimeout: () => 0, clearTimeout() {}, URLSearchParams, Date, Math, JSON,
};
vm.createContext(sandbox);

/* The module is top-level consts/functions + a boot IIFE. Strip the boot call so importing it does not
 * go through the service before the canned answers above are what it sees; then expose what is tested. */
const body = src.replace(/\(async function boot\(\)[\s\S]*?\}\)\(\);\s*$/m, '');
vm.runInContext(`${body}
globalThis.__x = { parseHash, esc, timeAgo, bytes, PROVIDER_HE, ICO, S, acctById, _acctLabel, renderTop,
  loadAccounts, viewAccounts, renderAccounts, renderWizard, loadMirrors, viewMirrors, router, binaTell,
  renderNav, navSections, brandSub, markRoute, startConnect,
  get FORGE_URL() { return FORGE_URL; } };`,
sandbox, { filename: 'app.js' });
const X = sandbox.__x;

let pass = 0, fail = 0;
function is(name, got, want) {
  if (JSON.stringify(got) === JSON.stringify(want)) { pass++; return; }
  fail++;
  console.error(`FAIL  ${name}\n      got  ${JSON.stringify(got)}\n      want ${JSON.stringify(want)}`);
}
function truthy(name, got) {
  if (got) { pass++; return; }
  fail++;
  console.error(`FAIL  ${name} — got ${JSON.stringify(got)}`);
}
const has = (hay, needle) => String(hay).includes(needle);

/* ── the router: two routes, and the query string must not become part of a segment ─────────────── */
function route(hash) { sandbox.location.hash = hash; return X.parseHash(); }
is('route: #/mirrors', route('#/mirrors').parts, ['mirrors']);
is('route: #/accounts', route('#/accounts').parts, ['accounts']);
is('route: the empty hash is the accounts screen', route('#/').parts, []);
is('route: a trailing slash adds no empty segment', route('#/mirrors/').parts, ['mirrors']);
is('route: a query is parsed, not glued to a segment', route('#/mirrors?x=1').q.get('x'), '1');

/* ── helpers, with the inputs the service really produces ───────────────────────────────────────── */
is('esc: null is empty', X.esc(null), '');
is('esc: a repository name is inert', X.esc('a<b>&"c"'), 'a&lt;b&gt;&amp;&quot;c&quot;');
is('timeAgo: no date is empty, not "1970"', X.timeAgo(''), '');
is('timeAgo: an unparsable date is empty', X.timeAgo('not-a-date'), '');
is('timeAgo: a moment ago', X.timeAgo(new Date(Date.now() - 40_000).toISOString()), 'עכשיו');
is('timeAgo: unix seconds — what the mirror registry keeps — are a time too',
   X.timeAgo(Math.floor(Date.now() / 1000) - 7200), 'לפני 2 שע׳');
is('bytes: 0 bytes is not blank', X.bytes(0), '0B');
is('bytes: undefined is blank (no "undefinedB")', X.bytes(undefined), '');
is('bytes: gigabytes', X.bytes(1324000000), '1.23GB');
is('bytes: megabytes', X.bytes(5 * 1024 * 1024), '5MB');
is('providers: the four the office speaks', Object.keys(X.PROVIDER_HE).sort(),
   ['forgejo', 'generic', 'github', 'gitlab']);
truthy('icons: every icon is an svg', Object.values(X.ICO).every((s) => has(s, '<svg')));

/* ── the menu: DECLARED here, built by the shared component (the adoption DGO-53 asks for) ─────── */
X.S.accounts = ACCOUNTS; X.S.active = 'a1';
X.S.loaded = true;
X.renderNav();
truthy('menu: the declaration is mounted into the page\'s one <aside>',
       lastNav() && lastNav().el.id === 'sideNav');
is('menu: it declares its identity, so the rail state is remembered per app', lastNav().cfg.id, 'git');
is('menu: the two screens are the two rows', navIds('screens'), ['accounts', 'mirrors']);
truthy('menu: the brand names the app and the account it is acting as',
       lastNav().cfg.brand.name === 'ניהול גרסאות'
       && has(lastNav().cfg.brand.sub, 'solomon') && has(lastNav().cfg.brand.sub, 'GitHub'));
truthy('menu: the one primary action is connecting an account',
       has(lastNav().cfg.primary.label, 'חשבון') && lastNav().cfg.primary.icon === 'plus');
truthy('menu: the forge is reachable from the menu footer, and it opens the app\'s own origin',
       lastNav().cfg.footer.items[0].id === 'forge'
       && (lastNav().cfg.footer.items[0].onClick(), opened.length === 1 && has(opened[0][0], 'forge')));
truthy('menu: no search box is declared — this app has nothing to search',
       !lastNav().cfg.search);
is('brand line: the source account id resolves to a label', X._acctLabel('a1'), 'GitHub — solomon');
is('brand line: an unknown id is shown as itself, never as "undefined"', X._acctLabel('aX'), 'aX');
X.S.accounts = []; X.S.active = null;
is('brand line: no account connected says so', X.brandSub(), 'אין חשבון מחובר');
X.S.accounts = ACCOUNTS; X.S.active = 'a1';
X.S.loaded = false;

/* ── the accounts screen ────────────────────────────────────────────────────────────────────────── */
/* The screen is the one on top, or it declines to repaint itself when the probe answers — that guard
 * is part of the app, so the test has to stand where a person would. */
sandbox.location.hash = '#/accounts';
await X.viewAccounts();
const acc = mainHtml();
truthy('accounts: every connected account is listed',
       has(acc, 'GitHub — solomon') && has(acc, X.esc("הפורג' של הלשכה")));
truthy('accounts: the active one is marked and not offered as "select" again',
       has(acc, '<span class="chip ok">פעיל</span>') && !has(acc, 'data-act="select" data-id="a1"'));
truthy('accounts: another account CAN be made active', has(acc, 'data-act="select" data-id="a3"'));
truthy('accounts: every account can be probed and disconnected',
       has(acc, 'data-act="probe" data-id="a1"') && has(acc, 'data-act="del" data-id="a1"'));
truthy('accounts: no account is called a twin when every user is connected once', !has(acc, 'אותו משתמש כמו'));
truthy('accounts: a button per provider the service offers',
       has(acc, 'data-p="github"') && has(acc, 'data-p="forgejo"'));
truthy('accounts: the vault is read, never the app\'s own config',
       calls.some((c) => c.path === 'connections?probe=0'));
truthy('accounts: the instant paint says the state is NOT CHECKED, not that it is fine',
       has(acc, 'לא נבדק') && !has(acc, 'מחובר'));
await flush();
const probed = mainHtml();
truthy('accounts: the state of a credential is PROBED, not assumed',
       calls.some((c) => c.path === 'connections?probe=1'));
truthy('accounts: a live credential reads as connected', has(probed, 'מחובר'));
truthy('accounts: a code-only credential says so instead of showing a green chip',
       has(probed, 'קוד בלבד'));
truthy('accounts: a credential that needs the owner says so, with the reason',
       has(probed, 'דורש טיפול') && has(probed, 'הטוקן פג — יש לחבר מחדש'));
truthy('accounts: the service\'s own state words never reach the screen',
       !has(probed, 'needs_action') && !has(probed, 'git_only'));

/* a vault that cannot be read, and then can: the complaint must not outlive the failure, and an
 * unreadable vault must never be dressed up as "no accounts connected" */
const probedAnswer = ANSWERS['connections?probe=1'];
ANSWERS['connections?probe=1'] = { ok: true, connections: [], active: null, reason: 'הוולט אינו זמין' };
X.S.loaded = false;
await X.loadAccounts(true, true);
X.renderAccounts(ANSWERS.providers.providers);
const broke = mainHtml();
truthy('vault: an unreadable vault is reported as a vault problem, not as "no accounts"',
       has(broke, 'הוולט אינו זמין') && !has(broke, 'לא מחובר אף חשבון'));
ANSWERS['connections?probe=1'] = probedAnswer;
X.S.loaded = false;
await X.loadAccounts(true, true);
truthy('vault: a read that succeeds clears the previous complaint', X.S.vault_error === null);
ANSWERS['connections?probe=1'] = { ok: true, active: 'a1', connections: [probedAnswer.connections[0]] };
X.S.loaded = false;
await X.loadAccounts(true, true);
X.renderAccounts(ANSWERS.providers.providers);
truthy('accounts: the list carries no title of its own — the page names it, the menu counts it',
       !has(mainHtml(), '<h2>חשבונות</h2>') && has(mainHtml(), '<h2>חיבור חשבון חדש</h2>'));
X.S.accounts = [
  { id: 't1', account_hint: 'Solomon@github.com', label: 'GitHub — solomon', provider: 'github', state: 'unknown' },
  { id: 't2', login: 'solomon', label: 'my github', provider: 'github', state: 'ok' },
  { id: 't3', login: 'solomon', label: 'GitLab — solomon', provider: 'gitlab', state: 'ok' }];
X.renderAccounts(ANSWERS.providers.providers);
truthy('accounts: two accounts of one user at one provider each name the other — and only those two',
       has(mainHtml(), 'אותו משתמש כמו „my github”') && has(mainHtml(), 'אותו משתמש כמו „GitHub — solomon”')
       && (mainHtml().match(/אותו משתמש כמו/g) || []).length === 2);
ANSWERS['connections?probe=1'] = probedAnswer;
X.S.loaded = false;
await X.loadAccounts(true, true);
X.renderAccounts(ANSWERS.providers.providers);

/* the wizard: choosing a provider must not post anything, and must offer that provider's methods */
X.S.wiz.provider = ANSWERS.providers.providers[0];
const before = calls.length;
truthy('wizard: methods come from the provider, not from a hardcoded list',
       (X.S.wiz.provider.auth_methods || []).some((m) => m.id === 'pat'));
is('wizard: picking a provider sends no request', calls.length, before);
X.S.wiz.method = X.S.wiz.provider.auth_methods[0];
await X.renderWizard();
const fields = el('fields').innerHTML;
truthy('wizard: a labelled field per method field', has(fields, 'id="w-token"') && has(fields, 'טוקן'));
truthy('wizard: a password field is type=password', has(fields, 'type="password"'));
truthy('wizard: the save button is named for what it does', has(fields, 'אמת ושמור'));
X.S.wiz.method = ANSWERS.providers.providers[1].auth_methods[0];
await X.renderWizard();
truthy('wizard: an ltr field is marked dir="ltr" (a token typed into an RTL box is a token with a typo)',
       has(el('fields').innerHTML, 'dir="ltr"'));

/* ── the mirrors screen ─────────────────────────────────────────────────────────────────────────── */
await X.viewMirrors();
const mir = mainHtml();
truthy('mirrors: the mirrored repository is listed', has(mir, 'solomonBoltin/deployment-hacohen'));
truthy('mirrors: a synced mirror reads as synced', has(mir, 'מסונכרן'));
truthy('mirrors: …and says when, before its size — never a separator with nothing before it',
       /לפני [23] דק׳ · 1\.23GB/.test(mir) && !/<span> · /.test(mir));
truthy('mirrors: a failed one says so in Hebrew — never the bare "error" or "new" of the registry',
       has(mir, 'הסנכרון נכשל') && !has(mir, '>error<') && !has(mir, '>new<'));
truthy('mirrors: the list carries no title of its own either', !has(mir, '<h2>מראות</h2>'));
truthy('one spelling of the forge on the screen', !has(mir, 'פורג׳') && !has(acc, 'פורג׳'));
truthy('mirrors: its copy in the forge is named', has(mir, 'office/deployment-hacohen'));
truthy('mirrors: sync and remove are offered per row',
       has(mir, 'data-sync="m1"') && has(mir, 'data-del="m1"'));
truthy('mirrors: a failed sync shows its reason, not a bare "error"',
       has(mir, 'GIT_MIRROR_MAX_BYTES exceeded') && has(mir, 'class="err"'));
truthy('mirrors: the source account is named by label, not by vault id', has(mir, 'GitHub — solomon'));
truthy('mirrors: …and the raw vault id is nowhere on the screen', !has(mir, '>a1<'));
truthy('mirrors: the forge origin comes from the service, not from a hardcoded host',
       X.FORGE_URL === 'http://forge.example:8080');
truthy('mirrors: the "open the forge" link points at that origin',
       has(mir, 'href="http://forge.example:8080"') && has(mir, 'id="open-forge"'));
truthy('mirrors: the row deep-links into the forge copy',
       has(mir, 'href="http://forge.example:8080/office/deployment-hacohen"'));
truthy('mirrors: the automatic sync interval is stated, in minutes', has(mir, 'כל 15 דק׳'));
truthy('mirrors: declaring one needs a source account and an owner/repo',
       has(mir, 'id="m-acct"') && has(mir, 'id="m-repo"') && has(mir, 'owner/repo'));
truthy('mirrors: the local forge is not offered as a MIRROR SOURCE (a copy of a copy)',
       !has(mir, '<option value="a3"'));

/* the route that renders them: the screen, the title and the menu must agree about where you are */
navCalls.length = 0;
sandbox.location.hash = '#/mirrors';
await X.router();
truthy('router: the mirrors row is the one marked current',
       navCalls.some((c) => c[0] === 'setActive' && c[1] === 'mirrors'));
truthy('router: the page title names the screen', has(document.title, 'מראות'));
truthy('router: the shell\'s own heading names it too', el('viewTitle').textContent === 'מראות');
navCalls.length = 0;
sandbox.location.hash = '#/';
await X.router();
truthy('router: #/ lands on accounts, and the menu says so',
       navCalls.some((c) => c[0] === 'setActive' && c[1] === 'accounts'));

/* a pick in the menu moves the app — the declaration is not decoration */
const mountsBefore = navMounts.length;
sandbox.location.hash = '#/accounts';
lastNav().cfg.onPick('mirrors');
is('pick: the mirrors row routes to the mirrors screen', sandbox.location.hash, '#/mirrors');
lastNav().cfg.onPick('mirror:m1');
is('pick: a mirror row goes to the screen that owns it', sandbox.location.hash, '#/mirrors');
lastNav().cfg.onPick('accounts');
is('pick: the accounts row routes back', sandbox.location.hash, '#/accounts');
is('pick: a pick never remounts the menu (a phone drawer must not slam shut)', navMounts.length, mountsBefore);
/* …and the mirrors are rows in it, with the state the service reported */
X.S.loaded = false;
await X.viewMirrors();
is('menu: the declared mirrors are rows', navIds('mirrors'), ['mirror:m1', 'mirror:m2']);
const mrow = lastNav().cfg.sections.find((x) => x.id === 'mirrors').items[0];
truthy('menu: a row carries the repository and its state', has(mrow.label, 'deployment-hacohen')
       && mrow.meta === 'מסונכרן');
truthy('menu: a failed sync is the only thing that earns a badge',
       lastNav().cfg.sections.find((x) => x.id === 'mirrors').items[1].badge === '!');

/* the office's notice (`binaTell`, the copied block) is the app's only feedback: a failure must look
   like one — and the toast the screen once had beside it must not grow back */
const said = X.binaTell('נכשלה הפעולה', 'bad');
truthy('notice: a failure is announced and coloured',
       has(said.textContent, 'נכשלה') && has(said.className, 'bad'));
truthy('notice: the script carries the office\'s block and no toast of its own',
       has(src, '@bina-ask:start') && has(src, '@bina-ask:end') && !/\btoast\(/.test(src) && !has(page, 'id="toast"'));

/* ── the direction (DGO-57): Forgejo displays repositories — this app must not ────────────────────
 *    A guard, not a description: the open-source forge is the tile, and two places that show a
 *    repository is one place too many. It fails if the removed half grows back. */
for (const gone of ['mdToHtml', 'repoRow', 'dedupe', 'viewRepo', 'loadRepos', 'newRepo', 'renderSide', 'tabbody']) {
  truthy(`direction: no repository display (${gone}) in the shipped script`, !has(src, gone));
}
truthy('direction: no repository route is parsed', !/#\/r\//.test(src));
truthy('direction: the script never carries a provider token itself', !/fetch\([^)]*token/.test(src));
truthy('direction: the two screens are the app', has(src, 'viewAccounts') && has(src, 'viewMirrors'));

/* ── the page: the blocks the platform syncs must survive a rewrite (gate G27) ──────────────────── */
for (const marker of ['@bina-theme-tokens:start', '@bina-theme-tokens:end',
                      '@bina-nav:start', '@bina-nav:end', '@bina-nav-js:start', '@bina-nav-js:end']) {
  truthy(`page: carries ${marker}`, has(page, marker));
}
truthy('page: declares Hebrew and RTL', has(page, '<html lang="he" dir="rtl">'));
truthy('page: loads the shipped script', has(page, 'static/app.js'));
truthy('page: the menu has its ONE empty <aside> to mount into (the adopter promise)',
       /<aside[^>]*id="sideNav"[^>]*>\s*<\/aside>/.test(page));
truthy('page: the container and the grid the component measures are declared',
       has(page, 'class="bnv-host"') && has(page, 'appgrid'));
/* At phone width the side column is 0px and the drawer is out of flow, so auto-placement puts the
   CONTENT in the 0px track and the screen comes up empty (measured: main {x:390,w:0}). The app pins
   both cells; this is the assertion that keeps it from being "tidied" away. */
truthy('page: the content is pinned to the content column (a phone shows a page, not a top bar)',
       /\.appgrid\s*>\s*\.main\s*\{[^}]*grid-column\s*:\s*2/.test(page));
truthy('page: the drawer control the COMPONENT owns is there, and it is the component\'s',
       has(page, 'id="navToggle"') && has(page, 'data-nav-toggle='));
truthy('page: the elements the script binds exist',
       has(page, 'id="main"') && has(page, 'id="viewTitle"')
       && has(page, 'id="sideNav"'));
/* the hand-made navigation this app used to own: a tab strip of its own. It is GONE, and a
   reappearing one is the exact drift the adoption was for — it renders fine and is a second menu. */
truthy('page: no navigation of the app\'s own is left (no tab strip, no hand-built rows)',
       !has(page, 'id="nav-accounts"') && !has(page, 'id="nav-mirrors"')
       && !has(page, 'class="tab"') && !has(page, 'class="bnv-item'));
truthy('page: no sidebar of its own — the shell owns navigation',
       !has(page, 'id="side"') && !has(page, 'class="shell"'));
truthy('page: the RTL bug is not reintroduced (a 1fr column before the menu puts the menu on the left)',
       !/grid-template-columns:\s*1fr\s+262px/.test(page));

console.log(`\nui-selfcheck — ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
