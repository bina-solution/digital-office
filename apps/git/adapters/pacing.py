"""git.adapters.pacing — GitHub's limits on writes, kept before GitHub has to enforce them (DGO-2155, DGO-2138 §7.4).

GitHub's secondary rate limits allow no more than 80 content-generating requests a minute and 500 an hour per account
(docs: «About secondary rate limits»). Past them GitHub answers 403/429 and may block the account for a while, and the
office writes in the owner's name (issues, PRs, releases, files, and each client's repository through the App). So
each account's writes are counted here, process-wide:
- a write that fits goes now;
- one that needs a short wait (up to MAX_WAIT) waits;
- one that would wait longer is refused at once with the time to retry, never by holding a request open for an hour.
Reads are not counted: GitHub's primary limit (5,000/h, its own headers) covers them.

Pure: the clock and the sleep are arguments, so the tests drive it with no time passing.
"""
from __future__ import annotations

import threading
import time
from collections import deque

LIMITS = ((60.0, 80), (3600.0, 500))      # (window seconds, writes allowed in it)
MAX_WAIT = 20.0
WRITES = frozenset({"POST", "PATCH", "PUT", "DELETE"})


class Paced(Exception):
    def __init__(self, retry_after: float):
        super().__init__(f"retry after {retry_after:.0f}s")
        self.retry_after = retry_after


class WritePacer:
    def __init__(self, limits=LIMITS, max_wait: float = MAX_WAIT, now=time.monotonic, sleep=time.sleep):
        self.limits, self.max_wait, self.now, self.sleep = limits, max_wait, now, sleep
        self._seen: dict[str, deque] = {}
        self._lock = threading.Lock()

    def _wait_needed(self, q: deque, t: float) -> float:
        need = 0.0
        for window, allowed in self.limits:
            inside = [x for x in q if t - x < window]
            if len(inside) >= allowed:
                need = max(need, window - (t - inside[-allowed]))
        return need

    def take(self, key: str, method: str) -> float:
        """Admits one request of `method` for account `key`. Returns the seconds it waited. Raises Paced when the
        wait would pass max_wait. A read is admitted at once and not counted."""
        if method.upper() not in WRITES:
            return 0.0
        with self._lock:
            q = self._seen.setdefault(key, deque())
            t = self.now()
            longest = max(w for w, _ in self.limits)
            while q and t - q[0] >= longest:
                q.popleft()
            need = self._wait_needed(q, t)
            if need > self.max_wait:
                raise Paced(need)
            q.append(t + need)              # the slot is reserved now: a write behind it counts it, waiting or not
        if need > 0:
            self.sleep(need)                # outside the lock: one account's wait never holds another's writes
        return need


PACER = WritePacer()
