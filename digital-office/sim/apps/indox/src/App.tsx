import { Link, Navigate, Route, Routes, useLocation, useNavigate, useParams } from 'react-router-dom';
import { useCallback, useEffect, useState } from 'react';
import { api, AuthMe } from './api';
import DashboardPage from './pages/DashboardPage';
import { ColumnsOf } from './words';
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
const EMBEDDED =
  typeof window !== 'undefined' &&
  (() => {
    try {
      return window.self !== window.top;
    } catch {
      // cross-origin access throws → we're framed
      return true;
    }
  })();

// The sections of the INDOX section-app. `match` decides which tab is active for a given pathname
// (מסמכים owns the repo/document routes).
//
// מסמכים points straight at the ACTIVE INSTANCE'S TABLE. It used to point at /repos, which made
// reaching the table a three-click journey through two pure-navigation screens ("pick a מאגר" →
// "open the table"). Both are now redirects (see <Routes> below), so the table is one click away and
// instance selection lives where it belongs — the top-bar switcher, exactly like Drive and Mail.
const sections = (
  activeInstance: string | null,
): { to: string; label: string; match: (p: string) => boolean }[] => [
  { to: '/', label: 'לוח בקרה', match: (p) => p === '/' },
  {
    to: activeInstance ? `/repos/${activeInstance}/documents` : '/repos',
    label: 'מסמכים',
    match: (p) => p.startsWith('/repos'),
  },
  { to: '/sync', label: 'סנכרון', match: (p) => p.startsWith('/sync') },
  { to: '/settings', label: 'הגדרות', match: (p) => p.startsWith('/settings') },
  { to: '/tests', label: 'בדיקות', match: (p) => p.startsWith('/tests') },
  { to: '/extraction', label: 'חילוץ מסמכים', match: (p) => p.startsWith('/extraction') },
];

/** `/repos` → the active instance's table. Keeps deep links and the back button off the dead screen. */
function ReposIndexRedirect({ active }: { active: string | null }) {
  if (!active) return null;                       // still resolving the active instance
  return <Navigate to={`/repos/${active}/documents`} replace />;
}

/** `/repos/:repo` → that repo's table. A per-instance deep link still lands on the right table. */
function RepoIndexRedirect() {
  const { repo } = useParams<{ repo: string }>();
  return <Navigate to={`/repos/${repo}/documents`} replace />;
}

export default function App() {
  const [me, setMe] = useState<AuthMe | null>(null);
  const [active, setActive] = useState<string | null>(null);
  const navigate = useNavigate();
  const { pathname } = useLocation();

  useEffect(() => {
    api.authMe().then(setMe).catch(() => setMe(null));
  }, []);

  // Which instance are we looking at? Everything the app shows — table, settings, sync registry —
  // follows this one value on the server side, so the client only needs its id (for links).
  const refreshActive = useCallback(
    (opts?: { resetView?: boolean }) =>
      api
        .listInstances()
        .then((r) => {
          setActive(r.active);
          // Switching instance returns to the app's DEFAULT view (לוח בקרה) rather than forcing the
          // documents tab. Only /repos/:repo/* carries an instance id, so staying put would either
          // strand you on the previous instance's table or make every switch feel like a jump to
          // מסמכים. Landing on the default is the honest behaviour until sub-routing is per-instance;
          // once it is, this should instead PRESERVE the open sub-tab and just swap the data under it.
          if (opts?.resetView) navigate('/', { replace: true });
          return r.active;
        })
        .catch(() => null),
    [navigate],
  );

  useEffect(() => {
    refreshActive();
  }, [refreshActive]);

  // The top-bar switcher lives in the console shell (overlay/switcher.js, same-origin parent). After it
  // flips the active instance it calls this to re-point the app at the new instance. Mirrors
  // window.__chatReload in the chat client.
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

  const SECTIONS = sections(active);

  return (
    <div className="app-shell flex flex-col">
      <header className="tabstrip">
        {!EMBEDDED && (
          <Link to="/" className="brand">
            <span className="logo">מ</span>
            מסמכים נכנסים
          </Link>
        )}
        <nav style={{ display: 'flex', alignItems: 'center' }}>
          {SECTIONS.map((s) => (
            <Link
              key={s.to}
              to={s.to}
              className={`tab${s.match(pathname) ? ' active' : ''}`}
            >
              {s.label}
            </Link>
          ))}
        </nav>
        <div className="spacer" />
        {/* no global "live" pill: it would falsely claim auto-refresh on static
            pages, and the sync page renders its own truthful interactive toggle */}
        <div className="me" style={{ marginInlineStart: 12 }}>
          {/* (who this is was not READ — yet, or the service did not answer: that is not «לא מאומת») */}
          {!me ? null : me.authenticated ? (
            <span>
              {me.username}
              {me.is_admin && (
                <span className="pill healthy" style={{ marginInlineStart: 6 }}>
                  מנהל
                </span>
              )}
            </span>
          ) : (
            <span style={{ color: 'var(--amber)' }}>לא מאומת</span>
          )}
        </div>
      </header>
      <main className="wrap flex-1">
        <ColumnsOf repo={active}>
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          {/* the two screens that used to stand between מסמכים and the table are now redirects */}
          <Route path="/repos" element={<ReposIndexRedirect active={active} />} />
          <Route path="/sync" element={<SyncStatePage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/tests" element={<TestsPage />} />
          <Route path="/extraction" element={<ExtractionPage />} />
          <Route path="/extraction/:type/:name" element={<ExtractionDocPage />} />
          <Route path="/repos/:repo" element={<RepoIndexRedirect />} />
          <Route path="/repos/:repo/documents" element={<DocumentBrowserPage />} />
          <Route path="/repos/:repo/documents/:id" element={<DocumentDetailPage />} />
        </Routes>
        </ColumnsOf>
      </main>
    </div>
  );
}
