"""drive-google — Google Drive, an EXTERNAL engine of «קבצים» (apps/drive/ENGINES.md, DGO-1500).

Nothing of Google runs here: the engine bridges Drive v3 (gdrive.py) for two kinds of account, each a
vault instance —
  * `drive_google_oauth` — a person's account, signed in with Google. The consent is the office's
    credential plane's (connections' google-workspace-grant, through the herd's relay); «קבצים» opens it
    and receives it (its /oauth/<name>/* pages, named in /ops `oauth`), and the grant lands in the vault;
  * `drive_google_service_account` — a service account's JSON key; it sees what was shared with its address.

It serves the generic `drive` app over drive-engine.v1 (engine_rpc.py) and has no screen of its own.
"""
import json
import os
from urllib.parse import quote

from flask import Flask, jsonify

import connections_client as cx
import engine_rpc
from engine_rpc import EngineError
from gdrive import API, GoogleAuthError, GoogleDriveAdapter
from gdrive_sa import GoogleServiceAccountAdapter
from opsupport import AdapterError

_SENTRY_DSN = os.getenv("SENTRY_DSN")
if _SENTRY_DSN:
    try:
        import sentry_sdk

        sentry_sdk.init(dsn=_SENTRY_DSN, environment=os.getenv("SENTRY_ENVIRONMENT", os.getenv("DEPLOYMENT_NAME", "production")),
                        release=os.getenv("SENTRY_RELEASE"), traces_sample_rate=0.0, send_default_pii=False)
    except Exception:  # never let telemetry break the app
        pass

app = Flask(__name__)


class _Streams:
    """The §3 `upload` op streamed (engine_rpc's `op_store`): Drive's resumable upload (store_file — memory
    stays flat for any size), then the file's own resource with every field, the shape op_upload answers
    (md5Checksum included). Without it the op would read the whole file into memory and stop at 64 MB."""

    def op_store(self, src, size, md5, name, mime, folder=""):
        item = self.store_file(src, size, md5, name, mime, folder)
        return self._json("GET", f"{API}/files/{quote(item['id'])}", params={"fields": "*", "supportsAllDrives": "true"})


class OAuthDrive(_Streams, GoogleDriveAdapter):
    pass


class SADrive(_Streams, GoogleServiceAccountAdapter):
    pass


OAUTH, SA = GoogleDriveAdapter.protocol, GoogleServiceAccountAdapter.protocol
BY_PROTOCOL = {OAUTH: OAuthDrive, SA: SADrive}
GRANT = "google-workspace-grant"          # connections' catalog id of the Google consent (providers/30-google.yaml)
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "provider.json"), encoding="utf-8") as _f:
    PROVIDER = json.load(_f)


class Engine:
    def ops(self):
        return {**PROVIDER, "service": "drive-google", "routes": [],
                "protocols": {OAUTH: {"private": False}, SA: {"private": False}},
                # «קבצים»'s consent door for this engine: /oauth/google/{start,return,finish} on its own address
                # (the herd's relay sends Google's answer only to …/oauth/google/return pages)
                # `protocol`: what this door serves — connections narrows the consent to it where the office
                # connects it read-only (OAUTH_READONLY_PROTOCOLS, EXU-24); elsewhere the grant stays Drive + Gmail
                "oauth": {"google": {"grant": GRANT, "protocol": OAUTH, "provider": "Google",
                                     "connected": "Google Drive ו־Gmail של החשבון זמינים עכשיו בלשכה.",
                                     "connected_read_only": "Google Drive של החשבון זמין עכשיו בלשכה, לקריאה בלבד."}},
                "engines": [
                    {"id": OAUTH, "app": "drive", "name": "Google Drive", "icon": "cloud",
                     "private": False, "creates_profiles": False,
                     "description": "החשבון שלך ב־Google. הקבצים נשארים ב־Drive; המערכת עובדת עליהם ישירות."},
                    {"id": SA, "app": "drive", "name": "Google Drive — חשבון שירות", "icon": "cloud",
                     "private": False, "creates_profiles": False,
                     "description": "גישה דרך Service Account — ללא צורך בהתחברות של משתמש."}],
                "providers": [
                    {"id": "google_drive", "name": "Google Drive", "icon": "cloud", "engine": OAUTH, "private": False,
                     "description": "החשבון שלך ב־Google. הקבצים נשארים ב־Drive; המערכת עובדת עליהם ישירות.",
                     "auth_methods": [
                         {"id": "oauth", "label": "התחברות עם Google", "protocol": OAUTH, "needs": [],
                          "recommended": True, "private": False,
                          "can": "צפייה, העלאה, העברה, שינוי שם ומחיקה בקבצים של החשבון שתאשר.",
                          "explain": "נפתח חלון של Google. אחרי האישור החשבון נבדק ונפתח כאן — גם ה־Drive "
                                     "וגם ה־Gmail שלו. אפשר לסגור את החלון בכל שלב: לא ייווצר חיבור.",
                          # relative: the screen opens it under its own base (the console's /a/drive…/ or the
                          # app's own host); «קבצים» serves it for the engine named in /ops `oauth`
                          "start_url": "oauth/google/start",
                          # the consent it opens, by connections' name for it: a screen where «קבצים» is not
                          # served (a linked office's tile) asks connections' own start by this (EXU-19)
                          "grant": GRANT},
                         {"id": "service_account", "label": "שיתוף תיקייה עם הלשכה (חשבון שירות)",
                          # `needs` names what a connect screen asks for (the console's wizard reads it; `fields`
                          # below are Files' own words for the same key). `needs: []` drew this way as the
                          # office's own storage there, «אין מה להזין», with no key asked (DGO-1634)
                          "protocol": SA, "needs": ["service_account_json"], "recommended": False, "private": False,
                          # an account of this way is an ADDRESS people share folders with: the screen
                          # shows it to copy, and checks what arrived
                          "share": True,
                          "fields": [{"name": "service_account_json",
                                      "label": "תוכן קובץ ה־JSON של חשבון השירות", "type": "textarea"}],
                          "can": "רואה ועובד על התיקיות ששיתפו עם הכתובת שלו: צפייה, הורדה, העברה, שינוי שם "
                                 "ומחיקה. העלאת קבצים אינה אפשרית בחשבון שירות.",
                          "explain": "חשבון שירות הוא כתובת של הלשכה ב־Google. משתפים איתה ב־Google Drive את "
                                     "התיקיות שהלשכה צריכה (שיתוף › עורך), והן מופיעות כאן. את קובץ ה־JSON "
                                     "שלו מורידים פעם אחת ב־Google Cloud Console, במסך Service Accounts › Keys.",
                          "help_url": "https://cloud.google.com/iam/docs/service-account-overview"}]}]}

    def adapter(self, cid):
        inst = cx.get_instance(cid)
        if not inst:
            raise AdapterError(f"unknown connection {cid!r}", 404)
        cls = BY_PROTOCOL.get(inst.get("protocol"))
        if not cls:
            raise AdapterError(f"no adapter for protocol {inst.get('protocol')!r}", 501)
        return cls(inst)             # each fetches its own grant lazily and keeps its own token cache

    def as_error(self, e):
        if isinstance(e, GoogleAuthError):
            return EngineError(str(e), getattr(e, "status", 503), "auth")
        if isinstance(e, AdapterError):
            return EngineError(e.message, e.status, "adapter")
        return None

    def check_key(self, cid, key):
        """A Google account has no profiles of the office's storage: «קבצים» checks a presented profile key
        with the engine that issues them, and nothing here can contradict it."""
        return None

    def accounts(self, instances):
        return [dict(i, engine=i.get("protocol"), is_private=False, app="drive")
                for i in instances if i.get("protocol") in BY_PROTOCOL]

    def connect(self, b):
        proto, label, secret, hint = b.get("protocol"), b.get("label"), b.get("secret"), b.get("account_hint")
        if proto not in BY_PROTOCOL or not label or secret is None:
            return {"error": "protocol, label and secret required"}, 400
        if proto == SA:
            raw = (secret or {}).get("service_account_json") or ""
            try:
                parsed = json.loads(raw) if isinstance(raw, str) else raw
            except (ValueError, TypeError):
                return {"error": "ה־JSON של חשבון השירות אינו תקין"}, 400
            if not isinstance(parsed, dict) or parsed.get("type") != "service_account" \
                    or not parsed.get("client_email") or not parsed.get("private_key"):
                return {"error": "קובץ JSON אינו חשבון שירות תקין — חסרים שדות type / client_email / private_key"}, 400
            secret, hint = parsed, hint or parsed.get("client_email")
        return cx.add_instance(proto, label, secret, hint)

    def disconnect(self, cid):
        if not cx.get_instance(cid):
            return {"error": f"unknown connection {cid!r}"}, 404
        return cx.delete_instance(cid)


ENGINE = Engine()
app.register_blueprint(engine_rpc.blueprint(ENGINE))


@app.get("/healthz")
def healthz():
    return jsonify({"status": "ok"})
