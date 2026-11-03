"""cli — the office's git accounts and repositories, for agents and for the person at the server's shell. Reads only.

The hooks pipe THIS file into the git container (`dcx exec -T git python - <verb> … < apps/git/cli.py`),
so it runs from the checkout with no image rebuild, and talks to the service's own API on 127.0.0.1.

    overview                     the forge, the repositories, the accounts, the mirrors — each half
                                 names its own failure
    repos [account] [query]      the repositories, of one account or all, matching a query — among
                                 the 100 most recently pushed of each account (an unknown account
                                 answers an empty list, not an error)
    repo <account> <repo> [ref]  one repository: its branches, its files at a ref
    mirrors                      the local mirrors and how each one is doing

Adding an account or a mirror, and anything that pushes, stays on the screen and the API (AGENT.md).
"""
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "http://127.0.0.1:8978"


def get(path, params=None):
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    try:
        with urllib.request.urlopen(url, timeout=120) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            doc = json.loads(e.read() or b"{}")
        except ValueError:
            doc = {}
        sys.exit(f"git: {doc.get('message') or doc.get('detail') or doc.get('error') or e.reason} (HTTP {e.code})")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        sys.exit(f"git: the service does not answer on {API} ({getattr(e, 'reason', e)})")
    except ValueError:
        sys.exit("git: the answer was not JSON")


def main(argv):
    verb, args = (argv[0] if argv else ""), argv[1:]
    if verb == "overview":
        data = get("/api/overview")
    elif verb == "repos":
        data = get("/api/repos", {"account": args[0] if args else "", "q": args[1] if len(args) > 1 else ""})
    elif verb == "repo" and len(args) >= 2:
        data = get("/api/repo", {"account": args[0], "repo": args[1], "ref": args[2] if len(args) > 2 else ""})
    elif verb == "mirrors":
        data = get("/api/mirrors")
    else:
        sys.exit(__doc__)
    print(json.dumps(data, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
