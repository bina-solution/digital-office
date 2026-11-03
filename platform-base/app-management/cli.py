"""cli — «ניהול אפליקציות», the control plane, for agents and for the person at the server's shell. Reads only.

The hooks pipe THIS file into the app-management container (`dcx exec -T app-management python - <verb>
… < platform-base/app-management/cli.py`), so it runs from the checkout with no image rebuild, and
talks to the control plane's own API on 127.0.0.1.

    apps                     every app: declared state and running state
    room <id>                does this machine have room for the app (cpu, memory)
    job <id>                 the progress or result of the app's last enable or move — the calls that
                             run as a job (gone after a restart)
    catalog                  the signed local catalog index (`bbox catalog build`), when this office
                             has built one; the apps this office can switch on are in `apps`
    office                   this office's own record

Enable, disable, archive, uninstall, move and install start or stop services and can delete data:
they stay on the apps screen and the API, on the owner's words (AGENT.md).
"""
import json
import re
import sys
import urllib.error
import urllib.request

API = "http://127.0.0.1:8080"
APP_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")


def get(path):
    try:
        with urllib.request.urlopen(API + path, timeout=120) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            doc = json.loads(e.read() or b"{}")
        except ValueError:
            doc = {}
        doc = doc if isinstance(doc, dict) else {}
        said = doc.get("error") or doc.get("message")
        if doc and not said:
            # a failed bring-up answers 500 with its whole result (create_errors, hooks) and no `error`
            print(json.dumps(doc, ensure_ascii=False, indent=1))
        sys.exit(f"app-management: {said or e.reason} (HTTP {e.code})")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        sys.exit(f"app-management: the service does not answer on {API} ({getattr(e, 'reason', e)})")
    except ValueError:
        sys.exit("app-management: the answer was not JSON")


def main(argv):
    verb, args = (argv[0] if argv else ""), argv[1:]
    if verb == "apps":
        data = get("/api/apps")
    elif verb in ("room", "job") and args:
        if not APP_ID.fullmatch(args[0]):
            sys.exit(f"app-management: {args[0]!r} is not an app id")
        data = get(f"/api/apps/{args[0]}/{verb}")
    elif verb == "catalog":
        data = get("/api/catalog")
        if isinstance(data, dict) and data.get("error"):      # answered 200, with no index behind it
            sys.exit(f"app-management: no signed catalog index here ({data['error']})")
    elif verb == "office":
        data = get("/api/office")
    else:
        sys.exit(__doc__)
    print(json.dumps(data, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
