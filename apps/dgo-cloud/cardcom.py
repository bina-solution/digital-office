"""dgo-cloud.cardcom — the shekel rail: Cardcom API v11, plain HTTP (DGO-1893).

The spec is Cardcom's own swagger (research_notes/DGO cloud 2026-11-15/cardcom-v11-swagger.json) and its knowledge base:
  LowProfile/Create        the hosted payment page. `ChargeAndCreateToken` charges the first month and returns a card
                           token; a `Document` asks Cardcom to issue the tax invoice/receipt and mail it.
  LowProfile/GetLpResult   THE ONLY TRUTH about a page. The return to our site and the webhook are triggers: a
                           payment counts when ResponseCode 0, TranzactionInfo.ResponseCode 0, and the amount and
                           ReturnValue are ours (the webhook carries no signature; KB 27006768727698).
  Transactions/Transaction a month's charge on the saved token. ExternalUniqTranId is the idempotency key
                           (`sub<id>-p<period>`): a repeat answers 608, and ExternalUniqUniqTranIdResponse returns the
                           first result instead — a charge can never run twice. Cardcom's KB recommends exactly this
                           (tokens + our own schedule) over its recurring module for a fixed-price subscription
                           (article 27008148287634).
  Transactions/RefundByTransactionId   a refund (needs CARDCOM_API_PASSWORD).

Test terminal: 1000, card 4580280000000008, any future date, CVV 123, amounts under ₪5,000 (article 27008168721426); the
ApiName for it comes from Cardcom's support. CARDCOM_SIMULATE=1 (never on a live office) answers locally instead, so the
whole path runs end to end on a laptop: the «page» is /dev/cardcom/<lp> on this server.
"""
import json
import os
import secrets
import threading
import urllib.error
import urllib.request

BASE = os.environ.get("CARDCOM_BASE", "https://secure.cardcom.solutions").rstrip("/")


class PayError(Exception):
    """Cardcom refused or did not answer — the text is for the log and the admin, not the buyer."""


def configured():
    return simulated() or bool(os.environ.get("CARDCOM_TERMINAL") and os.environ.get("CARDCOM_API_NAME"))


def simulated():
    return os.environ.get("CARDCOM_SIMULATE", "") == "1"


def mode():
    if simulated():
        return "simulate"
    if not configured():
        return "off"
    return "test" if os.environ.get("CARDCOM_TERMINAL") == "1000" else "live"


def _creds():
    return {"TerminalNumber": int(os.environ.get("CARDCOM_TERMINAL", "0") or 0),
            "ApiName": os.environ.get("CARDCOM_API_NAME", "")}


def _post(path, body, timeout=30):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            d = json.load(e)
        except ValueError:
            d = {}
        info = d.get("ErrorInfo") or d
        raise PayError(f"cardcom {path} HTTP {e.code}: {info.get('ResponseCode', '')} {info.get('Description', '')}"
                       .strip()) from e
    except (OSError, ValueError) as e:
        raise PayError(f"cardcom {path}: {e}") from e


def document(name, email, tax_id, lines, kind="TaxInvoiceAndReceipt"):
    """The tax document Cardcom issues with the charge. Prices are the shekels the buyer pays, VAT included.
    `lines` is [(description, shekels)]."""
    d = {"DocumentTypeToCreate": kind, "Name": (name or email or "לקוח")[:50], "Email": (email or "")[:50],
         "IsSendByEmail": bool(email),
         "Products": [{"Description": desc[:250], "UnitCost": round(amount, 2), "Quantity": 1} for desc, amount in lines]}
    if tax_id:
        d["TaxId"] = str(tax_id)[:50]
    return d


# ── the simulator (CARDCOM_SIMULATE=1): the same shapes, answered from memory ───────────────────────────────
_SIM = {}
_SIM_LOCK = threading.Lock()


def sim_pay(lp_id, ok=True):
    """What the /dev/cardcom page does when its «pay» button is pressed."""
    with _SIM_LOCK:
        p = _SIM.get(lp_id)
        if not p:
            return False
        p["paid"] = ok
        return True


def sim_page(lp_id):
    with _SIM_LOCK:
        return dict(_SIM.get(lp_id) or {})


def create_page(amount_agorot, return_value, ok_url, fail_url, webhook_url, email, doc, token=True, lang="he"):
    """A hosted payment page → (LowProfileId, Url)."""
    shekels = round(amount_agorot / 100, 2)
    if simulated():
        lp = "sim-" + secrets.token_hex(8)
        with _SIM_LOCK:
            _SIM[lp] = {"amount": shekels, "return": return_value, "ok": ok_url, "fail": fail_url, "paid": None,
                        "token": token, "email": email, "doc": doc}
        return lp, "/dev/cardcom/" + lp
    body = dict(_creds(), Operation="ChargeAndCreateToken" if token else "ChargeOnly", Amount=shekels, ISOCoinId=1,
                Language=lang, ReturnValue=str(return_value), SuccessRedirectUrl=ok_url, FailedRedirectUrl=fail_url,
                CancelRedirectUrl=fail_url, WebHookUrl=webhook_url,
                UIDefinition={"CardOwnerEmailValue": email or "", "IsHideCardOwnerIdentityNumber": False},
                Document=doc)
    r = _post("/api/v11/LowProfile/Create", body)
    if int(r.get("ResponseCode", -1)) != 0 or not r.get("Url"):
        raise PayError(f"LowProfile/Create: {r.get('ResponseCode')} {r.get('Description', '')}")
    return r["LowProfileId"], r["Url"]


def page_result(lp_id):
    """What became of a page, read from Cardcom (never from the browser):
    {"paid": bool|None (None = not finished yet), "tran_id", "amount", "return", "token", "card_exp" (MMYY),
     "last4", "doc_number", "doc_url", "error"}"""
    if simulated():
        p = sim_page(lp_id)
        if not p:
            raise PayError("no such simulated page")
        if p["paid"] is None:
            return {"paid": None}
        if not p["paid"]:
            return {"paid": False, "error": "הכרטיס סורב (סימולציה)"}
        return {"paid": True, "tran_id": "sim" + lp_id[-6:], "amount": p["amount"], "return": p["return"],
                "token": ("simtok-" + lp_id) if p["token"] else "", "card_exp": "1230", "last4": "0008",
                "doc_number": "S" + lp_id[-5:], "doc_url": ""}
    r = _post("/api/v11/LowProfile/GetLpResult", dict(_creds(), LowProfileId=lp_id))
    code = int(r.get("ResponseCode", -1))
    t = r.get("TranzactionInfo") or {}
    pend = r.get("PendingReason") or {}
    if pend.get("ResponseCode") in (5117, 5118, 5119) or (code != 0 and not t):
        # the buyer has not finished (or the page was left): nothing happened yet
        return {"paid": None, "error": r.get("Description", "")}
    if code != 0 or int(t.get("ResponseCode", -1)) != 0:
        return {"paid": False, "error": f"{t.get('ResponseCode', code)} {t.get('Description') or r.get('Description', '')}"}
    tok = r.get("TokenInfo") or {}
    doc = r.get("DocumentInfo") or {}
    mm, yy = tok.get("CardMonth") or t.get("CardMonth"), tok.get("CardYear") or t.get("CardYear")
    exp = f"{int(mm):02d}{int(yy) % 100:02d}" if mm and yy else ""
    return {"paid": True, "tran_id": str(t.get("TranzactionId") or r.get("TranzactionId") or ""),
            "amount": float(t.get("Amount") or 0), "return": str(r.get("ReturnValue") or ""),
            "token": str(tok.get("Token") or ""), "card_exp": exp, "last4": str(t.get("Last4CardDigits") or ""),
            "doc_number": str(doc.get("DocumentNumber") or t.get("DocumentNumber") or ""),
            "doc_url": str(doc.get("DocumentUrl") or t.get("DocumentUrl") or "")}


_SIM_EXT = {}


def _tran(t):
    ok = int(t.get("ResponseCode", -1)) == 0
    return {"paid": ok, "tran_id": str(t.get("TranzactionId") or ""), "doc_number": str(t.get("DocumentNumber") or ""),
            "doc_url": str(t.get("DocumentUrl") or ""),
            "error": "" if ok else f"{t.get('ResponseCode')} {t.get('Description', '')}"}


def charge_token(token, card_exp, amount_agorot, ext_id, doc):
    """A month on the saved card → {"paid": True|False|None, "tran_id", "doc_number", "doc_url", "error"}.
    None is NOT a decline: no answer (a timeout, an HTTP error) or 608 (this key was used already) — the caller asks
    lookup_ext() what the key's charge became. Idempotent by ext_id."""
    shekels = round(amount_agorot / 100, 2)
    if simulated():
        if token.endswith("-noanswer"):
            return {"paid": None, "error": "timeout (simulated)"}
        bad = token.endswith("-decline")
        r = {"paid": not bad, "tran_id": "sim" + ext_id, "doc_number": "S" + ext_id[-6:], "doc_url": "",
             "error": "הכרטיס סורב (סימולציה)" if bad else ""}
        _SIM_EXT[ext_id] = r
        return r
    body = dict(_creds(), Amount=shekels, ISOCoinId=1, Token=token, CardExpirationMMYY=card_exp,
                ExternalUniqTranId=ext_id, ExternalUniqUniqTranIdResponse=True, NumOfPayments=1, Document=doc)
    try:
        t = _post("/api/v11/Transactions/Transaction", body, timeout=45)
    except PayError as e:
        return {"paid": None, "error": str(e)}
    if int(t.get("ResponseCode", -1)) == 608:
        return {"paid": None, "error": "608 (the key was used)"}
    return _tran(t)


def lookup_ext(ext_id):
    """What became of the charge made with this idempotency key → the same shape as charge_token; paid None when
    Cardcom knows no such charge or does not answer (then nothing happened that we can count)."""
    if simulated():
        return dict(_SIM_EXT.get(ext_id) or {"paid": None, "error": "no such charge (simulated)"})
    try:
        t = _post("/api/v11/Transactions/GetTransactionByExternalUniqTran",
                  dict(_creds(), ExternalUniqTranId=ext_id), timeout=30)
    except PayError as e:
        return {"paid": None, "error": str(e)}
    t = t.get("TranzactionInfo") or t
    if not t.get("TranzactionId"):
        return {"paid": None, "error": f"no charge under {ext_id}"}
    return _tran(t)


def refund(tran_id, amount_agorot=None):
    if simulated():
        return {"ok": True, "new_tran_id": "simref" + str(tran_id)}
    pw = os.environ.get("CARDCOM_API_PASSWORD", "")
    if not pw:
        raise PayError("refund needs CARDCOM_API_PASSWORD")
    body = {"ApiName": os.environ.get("CARDCOM_API_NAME", ""), "ApiPassword": pw, "TransactionId": int(tran_id)}
    if amount_agorot:
        body["PartialSum"] = round(amount_agorot / 100, 2)
    r = _post("/api/v11/Transactions/RefundByTransactionId", body)
    if int(r.get("ResponseCode", -1)) != 0:
        raise PayError(f"refund: {r.get('ResponseCode')} {r.get('Description', '')}")
    return {"ok": True, "new_tran_id": str(r.get("NewTranzactionId") or "")}
