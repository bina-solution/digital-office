import {
  Link, Navigate, Route, Routes, useLocation, useNavigate, useParams,
} from 'react-router-dom';
import { useCallback, useContext, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { api, AuthMe, InstanceAccount } from './api';
import { InstancesContext, pageOf } from './instancesContext';
import InstanceSwitcher from './components/InstanceSwitcher';
import PipelineBar from './components/PipelineBar';
import ErrorBoundary from './components/ErrorBoundary';
import { Ic, ToastHost } from './components/DataGrid';
import { IC } from './icons';
import NotFoundPage from './pages/NotFoundPage';
import ActionLogPage from './pages/ActionLogPage';
import DashboardPage from './pages/DashboardPage';
import DocumentBrowserPage from './pages/DocumentBrowserPage';
import DocumentDetailPage from './pages/DocumentDetailPage';
import SyncStatePage from './pages/SyncStatePage';
import SettingsPage from './pages/SettingsPage';
import TestsPage from './pages/TestsPage';
import ExtractionPage from './pages/ExtractionPage';
import ExtractionDocPage from './pages/ExtractionDocPage';

// Embedded = rendered inside the console iframe (console.localhost/a/incoming/).
// When embedded the console already shows the app name + dark rail, so we hide
// the brand and render only the light tab-strip (no second dark chrome).
export const EMBEDDED =
  typeof window !== 'undefined' &&
  (() => {
    try {
      return window.self !== window.top;
    } catch {
      // cross-origin access throws → we're framed
      return true;
    }
  })();

/* [url-is-the-selector 2026-08-24, owner order] Inside the console the shell mirrors our
   route into its own hash (#/m/<id>/inner?query), so the browser's address bar is ALWAYS a
   copyable deep link — one selector for navigation, display and actions, in both mounts.
   We report; the shell writes (replaceState, no history spam). */
function RouteReporter() {
  const loc = useLocation();
  useEffect(() => {
    if (!EMBEDDED) return;
    try {
      window.parent.postMessage(
        { type: 'bina:route', path: `${loc.pathname}${loc.search}` },
        window.location.origin,
      );
    } catch {
      /* opaque parent — nothing to mirror */
    }
  }, [loc.pathname, loc.search]);
  return null;
}

// The sections of the INDOX section-app. `match` decides which tab is active for a given pathname
// (מסמכים owns the repo/document routes).
//
// מסמכים points straight at the ACTIVE INSTANCE'S TABLE. It used to point at /repos, which made
// reaching the table a three-click journey through two pure-navigation screens ("pick a מאגר" →
// "open the table"). Instance selection now lives where it belongs — the top-bar switcher, exactly
// like Drive and Mail — so the table is one click away.
//
// The repo screens are GONE, matching the sim. They were pure navigation — "pick a מאגר" then "open
// the table" — and instance selection now lives in the top-bar switcher, exactly like Drive and Mail.
// /repos and /repos/:repo redirect rather than 404 so old links still land somewhere sensible.
//
// EVERY TAB CARRIES THE INSTANCE. They used to be bare (`/sync`, `/settings`, …), and a bare path
// resolves to the FIRST ENABLED instance — so selecting לוי and clicking הגדרות put you on הכהן's
// settings with לוי still showing in the chip. Only the documents tab was scoped, and it was scoped
// with `active`, the REPO, which is what produced `/i/incoming-documents-main/documents` in the nav.
// The argument here is the INSTANCE; `match` compares against `pageOf(p)` so a tab still highlights
// whether or not the URL carries a tenant.
const sections = (
  activeInstance: string | null,
): { to: string; label: string; match: (p: string) => boolean; icon: string }[] => {
  const at = (sub: string) =>
    activeInstance ? `/i/${encodeURIComponent(activeInstance)}${sub}` : sub;
  return [
  { to: at('/dashboard'), label: 'לוח בקרה', match: (p) => ['/', '/dashboard'].includes(pageOf(p)), icon: 'activity' },
  {
    to: at('/documents'),
    label: 'מסמכים',
    match: (p) => p.startsWith('/repos') || pageOf(p).startsWith('/documents'),
    icon: 'file',
  },
  { to: at('/sync'), label: 'סנכרון', match: (p) => pageOf(p).startsWith('/sync'), icon: 'refresh' },
  /* יומן פעולות sits between סנכרון and הגדרות because that is where it belongs in the reading
     order of this app: לוח בקרה is the state, מסמכים is the rows, סנכרון is what brings them in,
     and the action log is what the pipeline DID to them — the last of the four "what is
     happening" tabs, before the two that are configuration and tooling. */
  { to: at('/actions'), label: 'יומן פעולות', match: (p) => pageOf(p).startsWith('/actions'), icon: 'clock' },
  { to: at('/settings'), label: 'הגדרות', match: (p) => pageOf(p).startsWith('/settings'), icon: 'sliders' },
  { to: at('/tests'), label: 'בדיקות', match: (p) => pageOf(p).startsWith('/tests'), icon: 'check' },
  { to: at('/extraction'), label: 'חילוץ מסמכים', match: (p) => pageOf(p).startsWith('/extraction'), icon: 'zap' },
  ];
};

/**
 * `/documents` → the ACTIVE instance's table.
 *
 * The instance-agnostic entry point to the table: anything that wants "the documents" without
 * knowing which instance is live (the dashboard link, the nav tab before the active id has
 * resolved) points here. Falls back to the מאגרים list only when there is no active instance at
 * all — a server without the instances endpoints, or a fresh install with no repos.
 */
function ActiveDocsRedirect({ active, resolved }: { active: string | null; resolved: boolean }) {
  /* THE QUERY STRING IS THE WHOLE POINT OF THE LINK, so the hop must carry it.
     Every drill-down on the dashboard targets `/documents?status=…` / `?type=…` / `?source=…`
     and lands here to be resolved to the active instance. This redirect used to rebuild the
     path and drop `search`, so clicking a bar that said 134 documents opened the unfiltered
     table — all 25,576 rows, no chip, nothing on screen contradicting the number you had just
     clicked. That is the worst failure this app can have: an observation you cannot act on,
     silently answered with something else. */
  const { search } = useLocation();
  const { accounts } = useContext(InstancesContext);
  if (!resolved) return null; // still resolving the active instance
  if (!active)
    /* No active instance — say so. The old fallback navigated to /repos, which routes right
       back HERE: a self-redirect rendering a permanently blank screen (the repos list it
       pointed at was removed when instance selection moved to the top-bar switcher). */
    return (
      <div className="callout bad">
        אין מופע פעיל — בחרו מופע במתג המופעים שבסרגל העליון.
      </div>
    );
  /* THE INSTANCE, NOT `active`. `active` is the repo the BFF is pointed at; putting it in the
     path produced /i/incoming-documents-main/documents, which the registry then rejected with
     "instance 'incoming-documents-main' is not in public.indox_instances" — the old model
     surfacing as an error message on the app's front door. */
  /* A SELF-REDIRECT IS A HANG, NOT A FALLBACK. `docsPathFor` returns `/documents` when it cannot
     name an instance — and `/documents` is THIS component, so navigating there recurses until the
     stack dies ("Maximum call stack size exceeded", blank app). The registry loads async, so an
     empty `accounts` on first render is normal, not an error: wait for it, then say so if it is
     genuinely empty. */
  const target = docsPathFor(search, accounts);
  if (!target.startsWith('/i/')) {
    if (!accounts.length) return null; // registry still loading — render nothing, not a loop
    return (
      <div className="callout bad">
        אין מופע פעיל — בחרו מופע במתג המופעים שבסרגל העליון.
      </div>
    );
  }
  return <Navigate to={target} replace />;
}

/** `/i/<instance>/documents`, with the instance taken from the link's own `?instance=` or the
 *  first enabled entry of the registry — and never from the repo. One helper so the three
 *  redirects that need this answer cannot drift apart. */
/** WHICH INSTANCE DOES AN INSTANCE-LESS URL MEAN? The link's own `?instance=`, else the first
 *  enabled entry of the registry — and NEVER `active`, which is the REPO name and is what produced
 *  `/i/incoming-documents-main/documents`, a repo sitting in the instance slot. `accounts` holds
 *  INSTANCES; `active` holds a repo. Empty string when the registry has not arrived yet, which
 *  every caller must treat as "do not navigate", not as "no instance". */
function resolveInstance(search: string, accounts: InstanceAccount[]): string {
  return (
    new URLSearchParams(search).get('instance') ||
    accounts.find((a) => a.enabled !== false)?.id ||
    ''
  );
}

/** `/extraction/:type/:name` from before the scoping — same document, under the instance. */
function LegacyExtractionRedirect() {
  const { type, name } = useParams();
  return (
    <ScopedRedirect
      to={`/extraction/${encodeURIComponent(type ?? '')}/${encodeURIComponent(name ?? '')}`}
    />
  );
}

/** An instance-less page path → the same page under the resolved instance, query string intact.
 *  One component for all six legacy routes so they cannot drift apart. */
function ScopedRedirect({ to }: { to: string }) {
  const { search } = useLocation();
  const { accounts } = useContext(InstancesContext);
  const q = new URLSearchParams(search);
  const inst = resolveInstance(search, accounts);
  // Nothing resolved yet: render nothing. Navigating would land back on this same route.
  if (!inst) return null;
  q.delete('instance');
  const rest = q.toString();
  return (
    <Navigate to={`/i/${encodeURIComponent(inst)}${to}${rest ? `?${rest}` : ''}`} replace />
  );
}

function docsPathFor(search: string, accounts: InstanceAccount[]): string {
  const q = new URLSearchParams(search);
  const inst = resolveInstance(search, accounts);
  q.delete('instance');
  const rest = q.toString();
  /* No instance resolved yet: hand back `/documents` UNCHANGED and let the caller decide. It must
     never be returned as a navigation target — `/documents` routes to ActiveDocsRedirect, which is
     what calls this, so navigating there is a loop. Both callers check `startsWith('/i/')`. */
  return inst
    ? `/i/${encodeURIComponent(inst)}/documents${rest ? `?${rest}` : ''}`
    : `/documents${search}`;
}

/** `/repos/:repo…` — the OLD shape, where the path named a repo. It redirects to the instance
 *  route rather than being kept alive, because a URL is the most visible piece of a data model:
 *  keeping it would go on telling every operator that the thing they are looking at is a repo.
 *
 *  The repo name in the path is DISCARDED, not translated — there is nothing to translate it to.
 *  A repo was never an instance, which is exactly the confusion this removes. The query string
 *  survives, so a shared link's filters, sort, page and `?instance=` all still land. */
function useLegacyTarget(): string {
  const { search } = useLocation();
  const { accounts } = useContext(InstancesContext);
  return docsPathFor(search, accounts);
}

function LegacyRepoRedirect() {
  const target = useLegacyTarget();
  // same reasoning as ActiveDocsRedirect: never navigate to a route that lands back here
  return target.startsWith('/i/') ? <Navigate to={target} replace /> : null;
}

/** A legacy DOCUMENT link keeps its document id — that part still means the same thing. */
function LegacyRepoDocRedirect() {
  const { id } = useParams();
  const base = useLegacyTarget();
  const [path, query = ''] = base.split('?');
  return (
    <Navigate
      to={`${path}/${encodeURIComponent(id ?? '')}${query ? `?${query}` : ''}`}
      replace
    />
  );
}

/** `/i/:instance` with no page — the instance's documents are the app's front door. */
function InstanceRootRedirect() {
  const { instance } = useParams();
  const { search } = useLocation();
  return <Navigate to={`/i/${encodeURIComponent(instance ?? '')}/documents${search}`} replace />;
}

export default function App() {
  const [me, setMe] = useState<AuthMe | null>(null);
  const [active, setActive] = useState<string | null>(null);
  // The full instance list, fetched here ONCE and shared via InstancesContext — see that file's
  // doc comment for why: InstanceSwitcher and SyncStatePage used to each run their own
  // `listInstances()`, three redundant `GET /accounts` calls through the console's single-threaded
  // proxy on one cold load.
  const [accounts, setAccounts] = useState<InstanceAccount[]>([]);
  // `active === null` is ambiguous on its own — "not fetched yet" and "server has no instances"
  // look the same, and a redirect must not fire on the first. This disambiguates them.
  const [activeResolved, setActiveResolved] = useState(false);
  const navigate = useNavigate();
  const { pathname } = useLocation();

  useEffect(() => {
    api.authMe().then(setMe).catch(() => setMe(null));
  }, []);

  // Which instance are we looking at? Everything the app shows — table, settings, sync registry —
  // follows this one value on the server side, so the client only needs its id (for links).
  const refreshActive = useCallback(
    (opts?: { resetView?: boolean }) =>
      /* TWO DIFFERENT THINGS, AND CONFLATING THEM BROKE THE APP.
         `active` is a REPO NAME — every route is /repos/:repo/documents and the redirect below
         builds one from it. The INSTANCE is a different identifier entirely (`hacohen`), lives in
         `public.indox_instances`, and rides in `?instance=`. Setting `active` to a instance id made
         the app navigate to /repos/hacohen/documents, which is not a repo and 404s.

         So: the repo registry still answers "which table am I routed at", and the instance registry
         answers "whose data is in it". The top-bar switcher shows INSTANCES; the switcher inside
         the grid shows that instance's TABLES. */
      Promise.all([
        // Model A, kept only until the create-instance flow stops using it: it lists REPOS and
        // never listed instances, which is why it now says so in its name.
        api.listRepoAccountsLegacy().catch(() => null),
        api.listInstances().catch(() => null),
      ])
        .then(([r, ir]) => {
          if (ir?.instances?.length) {
            /* EVERY FIELD THE TYPE DECLARES, and no cast.
               This mapping first used `as unknown as InstanceAccount[]`, which silenced the very
               error that mattered: the switcher renders `a.docs.toLocaleString()`, `docs` was
               never set, and the app crashed to a blank screen the moment a second instance made
               the list render. The counts are filled in below from each instance's own tables; they
               start at 0 so a slow or failed count degrades to a zero, never to `undefined`. */
            setAccounts(
              ir.instances.map((x): InstanceAccount => ({
                id: x.id,
                provider: 'indox',
                label: x.label || x.id,
                identity: x.schema_name,
                color: '',
                status: x.enabled === false ? 'warning' : 'ok',
                reason: x.enabled === false ? 'מושבת' : undefined,
                backend: 'supabase',
                enabled: x.enabled !== false,
                docs: 0,
                registry: 0,
                settings_count: 0,
                companies: 0,
              })),
            );
            /* Real per-instance numbers, one request each, folded in as they arrive. The switcher
               is usable immediately with zeros rather than blocked on N round trips. */
            for (const x of ir.instances) {
              api
                .instanceTables(x.id, true)
                .then((tt: { tables: { name: string; rows?: number | null }[] }) => {
                  const n = (name: string) =>
                    tt.tables.find((z) => z.name === name)?.rows ?? 0;
                  setAccounts((prev) =>
                    prev.map((a) =>
                      a.id === x.id
                        ? {
                            ...a,
                            docs: n('incoming_documents'),
                            settings_count: n('settings'),
                            companies: n('companies'),
                          }
                        : a,
                    ),
                  );
                })
                .catch(() => {
                  /* a instance whose counts cannot be read still lists, showing zeros */
                });
            }
          } else if (r) {
            setAccounts(Array.isArray(r.accounts) ? r.accounts : []);
          }
          setActive(r?.active || null);
          setActiveResolved(true);
          if (opts?.resetView) navigate('/', { replace: true });
          return r?.active ?? null;
        })
        .catch(() => {
          // The instances endpoints are additive: an older BFF simply 404s. Resolving to "no active
          // instance" keeps every pre-instances screen working instead of hanging the app on a
          // redirect that can never fire.
          setActiveResolved(true);
          return null;
        }),
    [navigate],
  );

  useEffect(() => {
    refreshActive();
  }, [refreshActive]);

  /* BIND THE INSTANCE ONTO EVERY REQUEST.
     The switcher already resolves which instance the operator is looking at — from `?instance=` in
     the URL, falling back to the first ENABLED one. That value used to reach only the screens that
     remembered to pass it, so the dashboard, the sync board and the action log kept reading
     `public`: a chooser the data did not honour. Mirroring it into api.setInstance() puts it on
     every request through the one `call()` helper instead, so a new screen is scoped by default
     rather than by whoever wrote it remembering.

     This also has to be in place BEFORE the compatibility views are dropped. Until then an
     un-scoped read quietly answers for instance one; afterwards it fails outright. Neither is an
     acceptable thing to leave a screen doing. */
  /* READ THE PARENT'S HASH WHEN EMBEDDED — this app runs in an iframe at /a/incoming/ inside the
     console shell, and the SHELL owns the address bar. Reading only `window.location.hash` meant
     `?instance=` never arrived: every request went out unscoped and answered for instance one, which
     is exactly how the action log showed הכהן's 71 rows while לוי was selected. Same-origin, so
     the parent's hash is readable; wrapped because a cross-origin parent must degrade to the
     app's own URL rather than throw on every render. */
  const instanceInUrl = (() => {
    /* The PATH is where the instance lives. Embedded that path rides in the SHELL's hash
       (`#/m/incoming/i/<id>/…`); standalone the app is a plain path router and there is no hash
       at all — so reading only `location.hash` found nothing outside the console and every
       direct visit to `/i/<id>/…` silently bound the FIRST instance instead of the named one.
       That is how the app behaves for the ui-qa harness, which drives it without the shell.
       `?instance=` stays as a fallback so a legacy link resolves before the page normalises it. */
    const fromUrl = (h: string) =>
      /\/i\/([^/?#]+)/.exec(h)?.[1] ||
      new URLSearchParams(h.split('?')[1] || '').get('instance');
    if (EMBEDDED) {
      try {
        const v = fromUrl(window.parent.location.hash);
        if (v) return v;
      } catch {
        /* cross-origin parent — fall through to our own URL */
      }
    }
    return fromUrl(window.location.hash) || fromUrl(window.location.pathname + window.location.search);
  })();
  const firstEnabledInstance =
    accounts.find((a) => a.enabled !== false)?.id ?? null;
  const boundInstance = instanceInUrl || firstEnabledInstance;
  /* BOUND DURING RENDER, NOT IN AN EFFECT — and that ordering is the whole point.
     React runs CHILD effects before PARENT effects, so a screen's first fetch fires before this
     component's effect would have run. Bound in an effect, the very first request of every page
     load went out with no instance and answered for instance one: the action log showed hacohen's 71
     rows while `לוי` was selected and its own log holds none. `setInstance` is a module-level
     assignment, not React state, so calling it during render is safe and happens early enough. */
  api.setInstance(boundInstance);
  useEffect(() => {
    // Screens that cached rows for the previous instance must not keep showing them.
    window.dispatchEvent(new CustomEvent('indox:instance-changed'));
  }, [boundInstance]);

  // The top-bar switcher lives in the console shell (overlay/switcher.js, same-origin parent). After it
  // flips the active instance it calls this to re-point the app at the new instance. Mirrors
  // window.__chatReload in the chat client. The in-app <InstanceSwitcher> calls the same hook, so
  // both entry points converge on one refresh path.
  useEffect(() => {
    const w = window as unknown as { __indoxReload?: () => void };
    w.__indoxReload = () => {
      refreshActive({ resetView: true });
      window.dispatchEvent(new CustomEvent('indox:instance-changed'));
    };
    return () => {
      delete w.__indoxReload;
    };
  }, [refreshActive]);

  /* THE INSTANCE, NOT `active`. `active` is the REPO the BFF is pointed at; passing it here put
     `/i/incoming-documents-main/…` in every nav tab — a repo name in the instance slot, on the one
     part of the screen everybody clicks. `boundInstance` is the instance the page is being viewed
     as, which is what these links must preserve. */
  const SECTIONS = sections(boundInstance);

  /* THE MENU IS A DECLARATION. `SECTIONS` is this app's own view model (which screens exist and
     which one matches the path) and BinaNav is the office's shared component; this file states the
     data and the component owns the row, the active tint, the rail and the drawer — exactly the
     shape bina-table has. It replaced hand-built `.bnv-item` JSX, which was a second implementation
     of the same row, free to drift from the other ten apps.
     `BinaNav` is bundled by the page (gate G27 splices bina-nav.js into index.html). The footer is
     REACT (InstanceSwitcher), so it is portalled into the element the component leaves for it. */
  const navRef = useRef<HTMLElement | null>(null);
  const navApi = useRef<{ setItems?: (id: string, items: unknown[], n?: number) => void;
                           destroy?: () => void } | null>(null);
  const [navFoot, setNavFoot] = useState<HTMLElement | null>(null);
  const sectionsRef = useRef(SECTIONS);
  sectionsRef.current = SECTIONS;
  const navItems = () => sectionsRef.current.map((s) => ({
    id: s.to,
    label: s.label,
    href: s.to,
    active: s.match(pathname),
    icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        + 'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="'
        + ((IC as Record<string, string>)[s.icon] || '') + '"/></svg>',
  }));

  useEffect(() => {
    const el = navRef.current;
    // bina-nav:unsized — this shell is still `app-shell flex`, not the component's `.bnv-host` +
    // `.appgrid` (the remaining DGO-54 step for this app). The menu's contract test reads this
    // word here and skips that one promise for this file, instead of keeping a list of exceptions.
    const BN = (window as unknown as { BinaNav?: { mount: (e: HTMLElement, c: unknown) => never } }).BinaNav;
    if (!el || !BN) return;
    navApi.current = BN.mount(el, {
      id: 'indox',
      brand: { name: 'מסמכים', sub: 'INDOX', avatar: 'מ' },
      sections: [{ id: 'main', title: 'מסכים', items: navItems() }],
      footer: { html: '<div id="indox-nav-foot"></div>' },
    });
    setNavFoot(document.getElementById('indox-nav-foot'));
    return () => { navApi.current?.destroy?.(); navApi.current = null; };
    // mounted once: the rows are UPDATED below, so the menu object never jumps under the reader
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    navApi.current?.setItems?.('main', navItems(), 0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname, boundInstance]);

  return (
    <InstancesContext.Provider value={{ accounts, active, refresh: refreshActive }}>
    <div className="app-shell flex">
      {/* THE SIDE MENU — the same component and the same 36px row as every other app
          (platform-base/bina-ui/bina-nav.css, gate G27). It replaced a top tab strip that could
          not fit seven labels: at 390px the last two tabs were cut with no scrollbar and no way
          to reach them. A menu has a scroll region instead, and the phone gets one column. */}
      <aside className="side bnv" id="sideNav" ref={navRef} aria-label="ניווט" />
      {navFoot && createPortal(
        <>
          <InstanceSwitcher
            accounts={accounts}
            active={
              instanceInUrl ||
              (accounts.find((a) => a.enabled !== false)?.id ?? null)
            }
            onSwitched={() => refreshActive({ resetView: false })}
          />
          <div className="bnv-foot-text">
            <div className="me">
              {/* (who this is was not READ — yet, or the service did not answer: that is not «לא מאומת») */}
              {!me ? null : me.authenticated ? (
                <span>
                  {me.username}
                  {me.is_admin && <span className="pill healthy">מנהל</span>}
                </span>
              ) : (
                <span style={{ color: 'var(--amber)' }}>לא מאומת</span>
              )}
            </div>
          </div>
        </>,
        navFoot,
      )}
      <div className="app-main">
      {/* Between the menu and the outlet, so the pipeline's state is on EVERY screen rather
          than on the one page someone thought to look at. It renders nothing until its first
          answer, and nothing at all against a BFF that predates the endpoint. */}
      <PipelineBar />
      <RouteReporter />
      {/* THE ONE NOTICE CHANNEL: every screen's action feedback lands here (DataGrid.useToasts) */}
      <ToastHost />
      <main className="wrap flex-1">
        {/* ROUTE-LEVEL BOUNDARY, keyed by the path: a screen that throws shows its error under
            the live tab strip instead of blanking the app, and navigating away resets it. */}
        <ErrorBoundary
          key={pathname}
          homeTo={boundInstance ? `/i/${encodeURIComponent(boundInstance)}/dashboard` : '/'}
        >
        <Routes>
          <Route path="/" element={<ScopedRedirect to="/dashboard" />} />
          <Route
            path="/documents"
            element={<ActiveDocsRedirect active={active} resolved={activeResolved} />}
          />
          {/* /repos was a pure-navigation screen: pick a מאגר, then open its table. Instance
              selection now lives in the top-bar switcher, so the list has nothing left to do
              and the route redirects to the active instance table. */}
          <Route
            path="/repos"
            element={<ActiveDocsRedirect active={active} resolved={activeResolved} />}
          />
          {/* THE BARE PAGE PATHS ARE REDIRECTS NOW, not pages.
              An instance-less path has to guess which instance it means, and it guessed "the first
              enabled one" — so every screen except the grid answered for הכהן no matter which
              instance was selected, while the chip went on saying לוי. These keep old links and
              bookmarks working by resolving the instance ONCE and sending you to the scoped URL. */}
          <Route path="/sync" element={<ScopedRedirect to="/sync" />} />
          <Route path="/actions" element={<ScopedRedirect to="/actions" />} />
          <Route path="/settings" element={<ScopedRedirect to="/settings" />} />
          <Route path="/tests" element={<ScopedRedirect to="/tests" />} />
          <Route path="/extraction" element={<ScopedRedirect to="/extraction" />} />
          <Route path="/dashboard" element={<ScopedRedirect to="/dashboard" />} />
          {/* the deep extraction link keeps its two segments; they are already encoded per-segment
              by the page that builds them, so they are re-emitted verbatim. */}
          <Route path="/extraction/:type/:name" element={<LegacyExtractionRedirect />} />
          {/* the instance-details facts (backend, target table, columns, row/registry counts)
              are carried by the switcher panel now, so this redirects rather than 404s for
              anyone holding an old link. */}
          {/* THE INSTANCE IS IN THE PATH; THE REPO IS GONE.
              Every document link used to read /repos/incoming-documents-main/documents — a REPO
              NAME in the one URL a person actually looks at, from a model where "instance" meant
              "a registered repo". Two of them existed (main and its archive), so the address bar
              advertised the old duplication on the app's main screen.
              Now: /i/:instance/documents, with the TABLE as `?table=` because a table is a view
              onto an instance, not a different place. The legacy shapes below redirect rather
              than 404, carrying their query string, so old links and bookmarks still land. */}
          <Route path="/i/:instance/documents" element={<DocumentBrowserPage />} />
          <Route path="/i/:instance/documents/:id" element={<DocumentDetailPage />} />
          {/* EVERY screen is instance-scoped, not just the grid — that is what makes the instance
              survive a click on the nav, a bookmark and a shared link, instead of being re-guessed
              on arrival. The pages themselves needed no change: `boundInstance` already reads the
              `/i/<id>` segment, so putting it in the URL is the whole fix. */}
          <Route path="/i/:instance/dashboard" element={<DashboardPage />} />
          <Route path="/i/:instance/sync" element={<SyncStatePage />} />
          <Route path="/i/:instance/actions" element={<ActionLogPage />} />
          <Route path="/i/:instance/settings" element={<SettingsPage />} />
          <Route path="/i/:instance/tests" element={<TestsPage />} />
          <Route path="/i/:instance/extraction" element={<ExtractionPage />} />
          <Route path="/i/:instance/extraction/:type/:name" element={<ExtractionDocPage />} />
          <Route path="/i/:instance" element={<InstanceRootRedirect />} />
          <Route path="/repos/:repo" element={<LegacyRepoRedirect />} />
          <Route path="/repos/:repo/documents" element={<LegacyRepoRedirect />} />
          <Route path="/repos/:repo/documents/:id" element={<LegacyRepoDocRedirect />} />
          {/* anything else is a 404 with words on it — never an empty outlet */}
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
        </ErrorBoundary>
      </main>
      </div>
    </div>
    </InstancesContext.Provider>
  );
}
