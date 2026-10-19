import json, sys, urllib.request, time

def get(url, timeout=8):
    r = urllib.request.urlopen(url, timeout=timeout)
    return json.loads(r.read())

# 1. Health checks
for svc in ["drive", "indox", "console", "n8n"]:
    try:
        r = urllib.request.urlopen(f"http://{svc}.localhost/healthz", timeout=4)
        print(f"[OK] {svc} healthz -> {r.status}")
    except Exception as e:
        print(f"[FAIL] {svc} healthz -> {e}")

# 2. Drive connections
try:
    conns = get("http://drive:8975/api/connections")
    for c in conns:
        print(f"DRIVE_CONN: {c.get('id','?')[:40]} active={c.get('active')} kind={c.get('kind','?')[:20]}")
    active = [c for c in conns if c.get('active')]
    print(f"ACTIVE: {active[0].get('id','?') if active else 'NONE'}")
except Exception as e:
    print(f"[FAIL] drive connections -> {e}")

# 3. INDOX sync state
try:
    state = get("http://localhost:9005/api/sync/state")
    instance = state.get('instance','?')
    pipes = state.get('pipes', [])
    print(f"\nINDOX instance={instance[:30]} pipes={len(pipes)}")
    for p in pipes:
        print(f"  pipe: {p.get('name','?')} enabled={p.get('enabled')} connection={p.get('connection_id','?')[:30]}")
except Exception as e:
    print(f"[FAIL] indox sync state -> {e}")
