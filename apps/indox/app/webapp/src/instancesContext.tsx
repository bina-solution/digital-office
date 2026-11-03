import { createContext, useContext } from 'react';
import { useParams } from 'react-router-dom';
import { InstanceAccount } from './api';

/**
 * The active-instance list, fetched ONCE by App.tsx and shared from here.
 *
 * Before this existed, `App.tsx` (top-bar auth/nav), `InstanceSwitcher.tsx` (the chip) and
 * `SyncStatePage.tsx` (the "which instance are these pipes" badge) each ran their OWN
 * `api.listInstances()` on mount — three separate `GET /accounts` round trips for the identical
 * list, on every cold load. Cheap when hit directly (curl inside the container), but every one of
 * those round trips also crosses the console's proxy (`platform-base/console/app.py`'s `/a/<app>/`
 * embed), which is a SINGLE-THREADED Flask dev server (`python app.py`, no gunicorn) — see the
 * perf investigation this fix came out of. On that path requests do not overlap; they queue. Three
 * redundant fetches are three redundant turns in that queue, on top of whatever else (console's own
 * `/api/overview` connections probe, etc.) is already ahead of them. Cutting the count is the lever
 * available from this side of the proxy; the proxy itself is platform-base, out of this app's reach.
 *
 * `refresh()` is `App.tsx`'s existing `refreshActive` — the ONE place that calls `listInstances()`
 * now. Anything that used to re-fetch after a mutation (selecting/adding/removing an instance) calls
 * this instead, same as it already triggered `window.__indoxReload` for the shell case.
 */
export interface InstancesState {
  accounts: InstanceAccount[];
  active: string | null;
  refresh: () => void;
}

export const InstancesContext = createContext<InstancesState>({
  accounts: [],
  active: null,
  refresh: () => {},
});

export function useInstances(): InstancesState {
  return useContext(InstancesContext);
}

/**
 * The instance an INSTANCE-SCOPED page is being viewed as, straight off the route.
 *
 * Every screen lives under `/i/:instance/…`, so this is simply that segment. It exists as a hook
 * rather than a `useParams()` at each call site so a page cannot accidentally read a DIFFERENT
 * identifier — `active`, the repo name, was the one lying around, and it is what put
 * `/i/incoming-documents-main/documents` in the nav.
 */
export function useInstanceParam(): string | null {
  const { instance } = useParams<{ instance: string }>();
  return instance ?? null;
}

/**
 * Build a link that STAYS IN THE INSTANCE YOU ARE IN.
 *
 * A plain `to="/sync"` is instance-less, and an instance-less path resolves to the first enabled
 * instance — so from לוי's settings, "צפה בסנכרון" silently landed on הכהן's pipes. Every in-app
 * link goes through this, so the instance survives navigation the same way it survives a reload:
 * because it is in the URL.
 */
export function useInstanceLink(): (sub: string) => string {
  const instance = useInstanceParam();
  return (sub: string) =>
    instance ? `/i/${encodeURIComponent(instance)}${sub}` : sub;
}

/** A pathname with any `/i/<instance>` prefix stripped — what PAGE is this, regardless of tenant.
 *  Nav-tab matching is written once against the page's own path this way. */
export function pageOf(pathname: string): string {
  return pathname.replace(/^\/i\/[^/]+/, '') || '/';
}
