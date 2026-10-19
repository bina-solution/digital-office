import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, MemoryRouter } from 'react-router-dom';
import App from './App';
import { BASE_PATH } from './api';
import './index.css';

// Routing has to work in two very different hosts:
//
// 1. **Served over http(s)** — the real platform, standalone or embedded in the console under
//    `/a/incoming/`. BrowserRouter with basename = the mount prefix, so client-side routing,
//    hard-refresh and deep links all resolve under whichever prefix the app is mounted at.
//
// 2. **Inside the offline simulation**, where the app lives in an `about:srcdoc` iframe. There is no
//    real URL there: `location.pathname` is the opaque string `srcdoc` and `<base>` is
//    `about:srcdoc`, so BASE_PATH resolves to `srcdoc`. BrowserRouter CANNOT work in that host —
//    react-router v6 normalises the basename with `basename.replace(/^\/*/, '/')`, turning `srcdoc`
//    into `/srcdoc`, which no longer prefixes the real pathname `srcdoc`. `stripBasename` then
//    returns null and <Router> renders **null**: the entire app silently vanishes — empty #root, no
//    error, no warning, nothing on the console. (That failure mode is why this comment is long.)
//
// So when we're not on a real http(s) URL, route in memory instead. MemoryRouter keeps history in
// JS, independent of the document URL — exactly right for a srcdoc iframe.
const REAL_URL =
  typeof window !== 'undefined' && /^https?:$/.test(window.location.protocol);

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {REAL_URL ? (
      <BrowserRouter basename={BASE_PATH}>
        <App />
      </BrowserRouter>
    ) : (
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>
    )}
  </StrictMode>,
);
