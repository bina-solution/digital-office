"""Python webhook integration example for any-concurrency.

Usage:
    pip install httpx
    python examples/python-webhook.py
"""

import time
import uuid
import httpx

BASE_URL = "http://localhost:8080"


def span_id() -> str:
    return str(uuid.uuid4())


def now_ms() -> int:
    return int(time.time() * 1000)


class SpanContext:
    """Context manager that opens a span on entry and closes it on exit."""

    def __init__(self, src: str, svc: str, label: str = "", **meta):
        self.id = span_id()
        self.src = src
        self.svc = svc
        self.label = label or svc
        self.meta = meta
        self._start = None

    def __enter__(self):
        self._start = now_ms()
        httpx.post(f"{BASE_URL}/ingest/span", json={
            "id": self.id,
            "src": self.src,
            "svc": self.svc,
            "label": self.label,
            "status": "running",
            "s": self._start,
            "meta": self.meta,
        })
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        status = "error" if exc_type else "success"
        err = str(exc_val) if exc_val else None
        meta = {**self.meta, **({"error": err} if err else {})}
        httpx.post(f"{BASE_URL}/ingest/span/{self.id}/close", json={
            "status": status,
            "meta": meta,
        })
        return False  # don't suppress exceptions


# ── Example 1: simple open/close ─────────────────────────────────────────────

def example_simple():
    sid = span_id()
    start = now_ms()

    httpx.post(f"{BASE_URL}/ingest/span", json={
        "id": sid,
        "src": "my-app",
        "svc": "data-import",
        "label": "Import customer CSV",
        "status": "running",
        "s": start,
        "meta": {"file": "customers.csv", "rows": 5200},
    })

    time.sleep(1.5)  # simulate work

    httpx.post(f"{BASE_URL}/ingest/span/{sid}/close", json={
        "status": "success",
        "meta": {"rows_processed": 5200},
    })
    print(f"[example_simple] span {sid} submitted")


# ── Example 2: context manager ────────────────────────────────────────────────

def example_context_manager():
    with SpanContext("my-app", "send-email", label="Welcome email", user_id="u-42"):
        time.sleep(0.3)
        print("[example_context_manager] email sent")


# ── Example 3: batch ingest ───────────────────────────────────────────────────

def example_batch():
    t = now_ms()
    spans = [
        {"id": span_id(), "src": "pipeline", "svc": f"step-{i}", "label": f"Step {i}",
         "s": t + i * 200, "e": t + i * 200 + 180, "status": "success"}
        for i in range(5)
    ]
    resp = httpx.post(f"{BASE_URL}/ingest/spans", json=spans)
    print(f"[example_batch] ingested {resp.json()}")


# ── Example 4: error span ─────────────────────────────────────────────────────

def example_error():
    try:
        with SpanContext("my-app", "risky-job", label="Risky operation"):
            time.sleep(0.2)
            raise ValueError("something went wrong")
    except ValueError:
        pass
    print("[example_error] error span submitted")


if __name__ == "__main__":
    print("any-concurrency Python webhook examples")
    print(f"Target: {BASE_URL}\n")

    example_simple()
    example_context_manager()
    example_batch()
    example_error()

    print("\nDone — open http://localhost:8080 to see the spans")
