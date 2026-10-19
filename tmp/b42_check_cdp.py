import json, time, urllib.request
for i in range(20):
    try:
        r = urllib.request.urlopen("http://localhost:9222/json/version", timeout=4)
        v = json.loads(r.read())
        print("CDP:", v.get("Browser","?")[:50])
        break
    except Exception as e:
        if i == 19: print("CDP FAILED:", e)
        time.sleep(2)
