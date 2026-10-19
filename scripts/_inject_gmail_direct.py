#!/usr/bin/env python3
"""Self-contained gmail injector (replaces the missing data/_runs/build_mime.py path).
Builds MIME emails on the host and writes a payload JSON of {raw_base64,labels,folder} for the
companion node poster to push to mailapi:8970/append. Labels are NAMES (inbox canonical).

  python scripts/_inject_gmail_direct.py --bs 5
  python scripts/_inject_gmail_direct.py --link 5 --link-url http://pdfsrv:8088
Output: data/_runs/inject_payload.json
"""
# Hebrew output: python defaults stdout to the ANSI codepage on Windows (cp1255) and dies
# with UnicodeEncodeError. Linux/macOS are already UTF-8 — a no-op there.
import sys as _sys
if hasattr(_sys.stdout, "reconfigure"): _sys.stdout.reconfigure(encoding="utf-8")
import os, sys, csv, base64, json, random, re
from email.message import EmailMessage
from email.utils import formatdate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LBL_BS = "אינדוקס - דוחות גיול - לטיפול"          # BS_TO_SYNC (tag_rules)
LBL_LINK = "לטיפול-אוטומציה-קישור-למסמך"          # DOC_LINK_TO_SYNC
LBL_DOC = "אינדוקס - מסמכים כללי - לטיפול"        # DOC_TO_SYNC
TO = "person2@example.com"


def arg(flag, d=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else d


def _rows(dtype, n, ext=None):
    base = os.path.join(ROOT, "data", "data-set-2", dtype)
    rows = [r for r in csv.DictReader(open(os.path.join(base, "dataset.csv"), encoding="utf-8"))
            if r.get("LOCAL_PATH") and os.path.exists(os.path.join(base, r["LOCAL_PATH"]))]
    if ext:
        rows = [r for r in rows if r["LOCAL_PATH"].lower().endswith(ext)]
    random.shuffle(rows)
    return base, rows[:n]


def build_bs(n):
    base, rows = _rows("balance_sheet", n)
    out = []
    for i, r in enumerate(rows):
        cn = (r.get("COMPANY_NAME") or "ספק").strip() or "ספק"
        fp = os.path.join(base, r["LOCAL_PATH"])
        fn = os.path.basename(fp)
        m = EmailMessage()
        m["From"] = f"{cn} <supplier{i}@example.com>"
        m["To"] = TO
        m["Date"] = formatdate(localtime=True)
        m["Subject"] = f"דוח גיול - {cn} (הזרקת בדיקה {i+1})"
        m.set_content(f"מצורף דוח גיול / כרטסת עבור {cn}.\nהזרקת בדיקה gmail-bs.")
        data = open(fp, "rb").read()
        ext = fn.rsplit(".", 1)[-1].lower()
        maintype, subtype = ("application", "pdf") if ext == "pdf" else ("image", ext)
        m.add_attachment(data, maintype=maintype, subtype=subtype, filename=fn)
        out.append({"raw_base64": base64.b64encode(m.as_bytes()).decode(), "labels": [LBL_BS], "folder": "INBOX"})
    return out


def build_doc(n):
    """gmail-doc: invoice/shipment emails WITH attachment, pre-labeled DOC_TO_SYNC."""
    base, rows = _rows("invoice", n)
    out = []
    for i, r in enumerate(rows):
        cn = (r.get("COMPANY_NAME") or "ספק").strip() or "ספק"
        fp = os.path.join(base, r["LOCAL_PATH"])
        fn = os.path.basename(fp)
        m = EmailMessage()
        m["From"] = f"{cn} <supplier{i}@example.com>"
        m["To"] = TO
        m["Date"] = formatdate(localtime=True)
        m["Subject"] = f"חשבונית מס - {cn} (הזרקת בדיקה {i+1})"
        m.set_content(f"מצורפת חשבונית/תעודה עבור {cn}.\nהזרקת בדיקה gmail-doc.")
        data = open(fp, "rb").read()
        ext = fn.rsplit(".", 1)[-1].lower()
        maintype, subtype = ("application", "pdf") if ext == "pdf" else ("image", ext)
        m.add_attachment(data, maintype=maintype, subtype=subtype, filename=fn)
        out.append({"raw_base64": base64.b64encode(m.as_bytes()).decode(), "labels": [LBL_DOC], "folder": "INBOX"})
    return out


def build_link(n, link_url):
    base, rows = _rows("invoice", n, ".pdf")   # LDrY's resolver needs Content-Type application/pdf
    out = []
    for i, r in enumerate(rows):
        cn = (r.get("COMPANY_NAME") or "ספק").strip() or "ספק"
        fn = os.path.basename(r["LOCAL_PATH"])
        url = f"{link_url.rstrip('/')}/{fn}"
        m = EmailMessage()
        m["From"] = f"{cn} <noreply@morning.co>"          # portal-ish sender (DOC_LINK rule)
        m["To"] = TO
        m["Date"] = formatdate(localtime=True)
        m["Subject"] = f"חשבונית מס - {cn} (קישור, הזרקת בדיקה {i+1})"
        m.set_content(f"שלום,\nהחשבונית שלך זמינה בקישור הבא:\n{url}\n\nבברכה, {cn}")
        m.add_alternative(f"<p>שלום,</p><p>החשבונית שלך זמינה: <a href='{url}'>צפייה במסמך</a></p>", subtype="html")
        out.append({"raw_base64": base64.b64encode(m.as_bytes()).decode(), "labels": [LBL_LINK],
                    "folder": "INBOX", "_url": url})
    return out


payload = []
if arg("--doc"):
    payload += build_doc(int(arg("--doc")))
if arg("--bs"):
    payload += build_bs(int(arg("--bs")))
if arg("--link"):
    payload += build_link(int(arg("--link")), arg("--link-url", "http://pdfsrv:8088"))
outp = os.path.join(ROOT, "data", "_runs", "inject_payload.json")
os.makedirs(os.path.dirname(outp), exist_ok=True)
json.dump(payload, open(outp, "w", encoding="utf-8"), ensure_ascii=False)
print(f"built {len(payload)} emails -> {outp}")
for p in payload:
    print("  ", p["labels"][0], p.get("_url", "(attachment)"))
