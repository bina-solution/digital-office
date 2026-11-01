"""sites-render — the renderer the beauty check asks, and the reason it is a SEPARATE container.

The beauty score (`beautiful-score`, the owner's own project) is a measurement of PIXELS, and the
only honest way to get those pixels for a live site is to render it the way a browser does. That
needs headless Chromium: ~1.2 GB of image and 400–700 MB of RAM while a page is being rendered.

Putting that inside the sites API would mean the app that answers "is my site up?" shares a memory
cgroup with a browser, and a scan that spikes would take the monitoring down with it. So the browser
lives here, in a service whose entire job is to render and score on demand, and the API talks to it
over HTTP. When this container is unhealthy the API keeps monitoring and says so on the check.

Three properties this service keeps, because a score nobody can reproduce is a score nobody acts on:

  * the SAME renderer the site's own CI uses — headless Chromium through `beautiful.render`, not a
    static CSS engine, so the number here is the number `beautiful <url>` prints;
  * every viewport the designer checks (desktop 1280×800, tablet 768×1024, mobile 375×812), because
    a page that scores 90 on a laptop and 48 on a phone is a broken page, not an average;
  * the PNGs are KEPT, under the shared volume, so "the score dropped 12 points" can be answered by
    looking at the two screenshots instead of arguing about the formula.
"""
from __future__ import annotations

import inspect
import logging
import os
import re
import shutil
import threading
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sites.render")

RENDER_DIR = Path(os.environ.get("SITES_RENDER_DIR", "/renders"))
KEEP_RUNS = int(os.environ.get("SITES_RENDER_KEEP", "5"))
VIEWPORTS = ("desktop", "tablet", "mobile")
MAX_SESSIONS = int(os.environ.get("SITES_RENDER_CONCURRENCY", "1"))

app = FastAPI(title="sites-render", docs_url=None, redoc_url=None, openapi_url=None)
_lock = threading.Semaphore(MAX_SESSIONS)


def backends() -> dict:
    out = {"playwright": False, "weasyprint": False, "chromium": False}
    try:
        import playwright.sync_api  # noqa: F401
        out["playwright"] = True
    except ImportError:
        pass
    try:
        import weasyprint  # noqa: F401
        out["weasyprint"] = True
    except Exception:                                        # noqa: BLE001
        pass
    try:
        out["chromium"] = bool(list(Path(os.environ.get(
            "PLAYWRIGHT_BROWSERS_PATH", "/ms-playwright")).glob("chromium*")))
    except OSError:
        pass
    return out


@app.get("/healthz")
def healthz():
    b = backends()
    return {"status": "ok" if (b["playwright"] and b["chromium"]) else "degraded", **b}


@app.get("/readyz")
def readyz():
    b = backends()
    if not (b["playwright"] and b["chromium"]):
        return JSONResponse({"ready": False, "reason": "אין דפדפן זמין לרינדור", **b},
                            status_code=503)
    return {"ready": True, **b}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9.-]", "_", (text or "").lower())[:80] or "site"


def _prune(site_dir: Path) -> None:
    runs = sorted([p for p in site_dir.iterdir() if p.is_dir()], key=lambda p: p.name)
    for old in runs[:-KEEP_RUNS]:
        shutil.rmtree(old, ignore_errors=True)


class ScoreRequest(BaseModel):
    """The body, as a MODEL and not as `await request.json()` — and that is a hard requirement, not
    style. This endpoint must be a SYNC `def`: Playwright's synchronous API refuses to run inside an
    asyncio event loop ("It looks like you are using Playwright Sync API inside the asyncio loop"),
    and an `async def` route executes in exactly that loop. A sync route runs in Starlette's
    threadpool, where there is no loop and the browser is happy. Reading the body with `await` would
    force the route back to `async` and break the renderer it exists to run."""
    url: str = ""
    viewports: list[str] | None = None
    mode: str = "ui"
    site: str | None = None
    run: str | None = None
    components: bool = True


@app.post("/score")
def score(req: ScoreRequest):
    """Render one URL at the requested viewports and score each render.

    Blocking on purpose: FastAPI runs this `def` in its threadpool, so the render does not hold the
    event loop, and the semaphore keeps ONE Chromium alive at a time — a scan stack that renders
    four pages at once is how a 768M container gets OOM-killed by its own good intentions.
    """
    body = req.model_dump()
    url = (body.get("url") or "").strip()
    if not re.match(r"^https?://", url, re.I):
        return JSONResponse({"ok": False, "error": "צריך כתובת מלאה (https://…)"}, status_code=400)
    viewports = [v for v in (body.get("viewports") or VIEWPORTS) if v in VIEWPORTS] or list(VIEWPORTS)
    mode = body.get("mode") if body.get("mode") in ("ui", "classic", "art", "logo", "web") else "ui"
    components = bool(body.get("components", True))
    site = _slug(body.get("site") or url.split("//")[-1].split("/")[0])
    run_id = body.get("run") or time.strftime("%Y%m%d-%H%M%S")
    out_dir = RENDER_DIR / site / str(run_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    with _lock:
        bversion = None
        try:
            from beautiful.render import score_html
            from beautiful import __version__ as bversion
        except Exception as e:                                # noqa: BLE001
            return JSONResponse({"ok": False, "error": f"ספריית beautiful אינה זמינה: {e}"},
                                status_code=503)
        started = time.time()
        try:
            # The signature is PROBED rather than assumed: `components` exists on the project's main
            # branch and not in the pinned release, and a hardcoded kwarg turns that difference into
            # "the beauty check is broken" instead of "the numbers are a version older".
            kwargs = {"save_dir": str(out_dir)}
            if "components" in inspect.signature(score_html).parameters:
                kwargs["components"] = components
            reports = score_html(url, viewports, mode, **kwargs)
        except Exception as e:                                # noqa: BLE001
            log.warning("render failed for %s: %s: %s", url, type(e).__name__, e)
            reason = str(e)
            if "Executable doesn't exist" in reason or "playwright install" in reason:
                reason = "הדפדפן של הרינדור אינו מותקן בקונטיינר"
            elif "Timeout" in type(e).__name__ or "timeout" in reason.lower():
                reason = "האתר לא נטען בזמן הרינדור"
            return JSONResponse({"ok": False, "error": reason, "url": url,
                                 "seconds": round(time.time() - started, 1)}, status_code=502)

    shots = sorted(p.name for p in out_dir.glob("*.png"))
    pages = []
    for vp, r in (reports or {}).items():
        shot = next((s for s in shots if vp in s), None)
        pages.append({
            "viewport": vp,
            "score": r.get("score"), "mode": r.get("mode") or mode,
            "classic": r.get("classic"), "factors": r.get("factors") or {},
            "hints": r.get("hints") or [], "penalties": r.get("penalties") or [],
            "components": (r.get("components") or [])[:25],
            "screenshot": f"{site}/{run_id}/{shot}" if shot else None,
        })
    pages.sort(key=lambda p: VIEWPORTS.index(p["viewport"]) if p["viewport"] in VIEWPORTS else 9)
    _prune(RENDER_DIR / site)
    return {"ok": True, "url": url, "mode": mode, "backend": "playwright-chromium",
            "beautiful": bversion, "seconds": round(time.time() - started, 1), "pages": pages,
            "run": str(run_id), "dir": f"{site}/{run_id}", "screenshots": shots}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8981")))
