"""cli — «מכונה», the office machine's numbers, for agents and for the person at the server's shell. Reads only.

The hooks pipe THIS file into the machine container (`dcx exec -T machine python - <verb> <
platform-base/machine/cli.py`), so it runs from the checkout with no image rebuild, and talks to the
service's own API on 127.0.0.1.

    overview                 CPU, memory, disk and every container's use — check this before a build
    storage                  what holds the disk: images, volumes, build cache
    cleanup-options          what a cleanup could free, and which actions this office allows
    power                    the power policy, and the host's own power facts

Running a cleanup (it prunes the whole engine) and changing the power policy (whether the Mac may
sleep) stay on the screen and the API, on the owner's words (AGENT.md).
"""
import json
import sys
import urllib.error
import urllib.request

API = "http://127.0.0.1:8080"
ROUTES = {"overview": "/api/overview", "storage": "/api/storage", "cleanup-options": "/api/cleanup/options",
          "power": "/api/power"}


def main(argv):
    path = ROUTES.get(argv[0] if argv else "")
    if not path:
        sys.exit(__doc__)
    try:
        with urllib.request.urlopen(API + path, timeout=120) as r:
            data = json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            said = json.loads(e.read() or b"{}").get("detail")
        except (ValueError, AttributeError):
            said = None
        sys.exit(f"machine: {said or e.reason} (HTTP {e.code})")
    except (urllib.error.URLError, TimeoutError, OSError) as e:      # a read timeout too, not a traceback
        sys.exit(f"machine: the service does not answer on {API} ({getattr(e, 'reason', e)})")
    except ValueError:
        sys.exit("machine: the answer was not JSON")
    if path == "/api/storage" and isinstance(data, dict) and not data.get("generated_at"):
        # the disk is measured in the background (app.py): a cold service has no measurement yet
        print("machine: the disk is being measured now — ask again in a minute; this answer is empty, "
              "not a clean disk", file=sys.stderr)
    print(json.dumps(data, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
