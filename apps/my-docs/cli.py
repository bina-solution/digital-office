"""cli — «מסמכים שלי», the business's documents, for agents and for the person at the server's shell. Reads only,
but for one deliberate write: `import-history --apply`, the history a business brings with it.

The hooks pipe THIS file into the my-docs container (`dcx exec -T my-docs python - <verb> … <
apps/my-docs/cli.py`), so it runs from the checkout with no image rebuild. my-docs forwards `/api/…`
as-is to apitools' ledger, so these are the ledger's own answers.

    documents [N] [--type <t>] [--status <s>] [--customer <id>]   the newest N documents (default 20)
    show <id>                one document, with its lines
    events <id>              its audit trail
    customers                the customers
    items                    the items
    integrity                numbering continuity and the tamper chain (the ledger's /documents/verify;
                             it loads every issued PDF, and on an office with no signing certificate its
                             first call makes the development one — it changes no document)

    import-history <register.csv> [--pdfs <folder>] [--source <name>] [--apply]
                             the documents another system issued (DGO-2042: A business's earlier documents) into
                             the ledger, as they were issued: the register and the PDFs are read from
                             «קבצים». Without --apply it only says what it would keep; with it, the one
                             write here — a number the ledger holds is skipped, so it can run again.

Not here, on purpose: issue, cancel, pay, allocation (final or money); `send` (it marks a document
sent and e-mails nothing); and download — the first download of an issued document uses up its
«מקור» (AGENT.md).
"""
import base64
import csv
import io
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "http://127.0.0.1:8000/api"
DRIVE = os.environ.get("DRIVE_URL", "http://drive:8975")      # «קבצים», on the office's own network
# the ledger itself: the import is the shell's alone — the screen's pass-through refuses it from a browser
LEDGER = os.environ.get("APITOOLS_URL", "http://apitools:8080").rstrip("/")
# A document id is letters, digits, `_` and `-` (`doc_` + hex). Anything else is refused: the
# pass-through decodes `%2F`, so `x/download` would reach the one GET that writes (it uses up «מקור»).
ID = re.compile(r"[A-Za-z0-9_-]{1,80}")


def get(path, params=None):
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    try:
        with urllib.request.urlopen(url, timeout=150) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            doc = json.loads(e.read() or b"{}")
        except ValueError:
            doc = {}
        sys.exit(f"my-docs: {doc.get('message') or doc.get('error') or e.reason} (HTTP {e.code})")
    except (urllib.error.URLError, TimeoutError, OSError) as e:      # a read timeout too, not a traceback
        sys.exit(f"my-docs: the service does not answer on {API} ({getattr(e, 'reason', e)})")
    except ValueError:
        sys.exit("my-docs: the answer was not JSON")


def post(path, body):
    req = urllib.request.Request(LEDGER + path, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            doc = json.loads(e.read() or b"{}")
        except ValueError:
            doc = {}
        sys.exit(f"my-docs: {doc.get('message') or doc.get('error') or e.reason} (HTTP {e.code})")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        sys.exit(f"my-docs: the ledger does not answer on {LEDGER} ({getattr(e, 'reason', e)})")


def drive_file(path):
    """A file's bytes from «קבצים», or None when there is none at that path."""
    url = DRIVE + "/api/fs/content?" + urllib.parse.urlencode({"path": path})
    try:
        with urllib.request.urlopen(url, timeout=120) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        sys.exit(f"my-docs: the drive refused {path} (HTTP {e.code})")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        sys.exit(f"my-docs: the drive does not answer on {DRIVE} ({getattr(e, 'reason', e)})")


def import_history(args):
    """The register (a CSV: type, number, issued, client, amount, pays, cancels, description, file) and each
    document's PDF (<number>.pdf in --pdfs) → the ledger's POST /documents/import, a few at a time."""
    register, pdfs, source, apply = "", "", "morning", False
    it = iter(args)
    for a in it:
        if a in ("--pdfs", "--source"):
            value = next(it, "")
            if not value or value.startswith("--"):
                sys.exit(f"my-docs: {a} needs a value")
            pdfs, source = (value, source) if a == "--pdfs" else (pdfs, value)
        elif a == "--apply":
            apply = True
        elif not register:
            register = a
        else:
            sys.exit(f"my-docs: what is {a!r}?")
    if not register:
        sys.exit("my-docs: import-history <register.csv in «קבצים»> [--pdfs <folder>] [--source <name>] [--apply]")
    raw = drive_file(register)
    if raw is None:
        sys.exit(f"my-docs: no register at {register} in «קבצים»")
    docs, missing = [], []
    for r in csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))):
        d = {k: (r.get(k) or "").strip() for k in ("type", "number", "client", "amount", "pays", "cancels",
                                                     "description")}
        d["date"] = (r.get("issued") or r.get("date") or "").strip()
        d["file"] = os.path.basename((r.get("file") or "").strip())
        if pdfs:
            pdf = drive_file(pdfs.rstrip("/") + "/" + d["number"] + ".pdf")
            if pdf is None:
                missing.append(d["number"])
            else:
                d["pdf_b64"] = base64.b64encode(pdf).decode("ascii")
        docs.append(d)
    by_type = {}
    for d in docs:
        by_type.setdefault(d["type"], []).append(d["number"])
    print(f"{len(docs)} documents in {register}" + (f", PDFs from {pdfs}" if pdfs else ", no PDFs (--pdfs)"))
    for t, nums in by_type.items():
        print(f"  {t}: {len(nums)}  ({min(nums, key=int)}–{max(nums, key=int)})")
    pays = [f"{d['number']}→{d['pays']}" for d in docs if d["pays"]]
    cancels = [f"{d['number']} cancels {d['cancels']}" for d in docs if d["cancels"]]
    print(f"  pays: {len(pays)} ({', '.join(pays[:6])}{'…' if len(pays) > 6 else ''})")
    for c in cancels:
        print(f"  {c}")
    if missing:
        print(f"  no PDF for: {', '.join(missing)} — the ledger keeps a document only with its original")
    if not apply:
        print("nothing was written — --apply keeps them in the ledger")
        return
    if missing:
        sys.exit("my-docs: nothing imported — every document needs its PDF")
    got = {"imported": [], "skipped": []}
    for i in range(0, len(docs), 4):                  # the rows in parts; their links and series once all are in
        out = post("/documents/import", {"source": source, "documents": docs[i:i + 4]})
        got["imported"] += out.get("imported") or []
        got["skipped"] += out.get("skipped") or []
    bare = [{k: v for k, v in d.items() if k != "pdf_b64"} for d in docs]
    got.update(post("/documents/import/settle", {"source": source, "documents": bare}))
    print(json.dumps(got, ensure_ascii=False, indent=1))


def main(argv):
    verb, args = (argv[0] if argv else ""), argv[1:]
    if verb == "documents":
        params, it = {"limit": 20}, iter(args)
        for a in it:
            if a in ("--type", "--status", "--customer"):
                value = next(it, "")
                if not value or value.startswith("--"):
                    sys.exit(f"my-docs: {a} needs a value")
                params["customer_id" if a == "--customer" else a[2:]] = value
            elif re.fullmatch(r"[0-9]{1,4}", a):
                params["limit"] = max(1, min(200, int(a)))
            else:
                sys.exit(f"my-docs: what is {a!r}?\n{__doc__}")
        data = get("/documents", params)
    elif verb in ("show", "events") and args:
        if not ID.fullmatch(args[0]):
            sys.exit(f"my-docs: {args[0]!r} is not a document id")
        doc = "/documents/" + args[0]
        data = get(doc if verb == "show" else doc + "/events")
    elif verb in ("customers", "items"):
        data = get("/" + verb)
    elif verb == "integrity":         # not `verify`: that name is the platform's health hook for every app
        data = get("/documents/verify")
    elif verb == "import-history":
        return import_history(args)
    else:
        sys.exit(__doc__)
    print(json.dumps(data, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
