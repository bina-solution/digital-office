"""Map a `RepoConfig` to a concrete `DocumentRepo`.

Used by the Flask routes so the rest of the API doesn't care which
backend is in play. Tests inject a custom factory to swap in fakes.

Credential resolution order for each backend:

1. Anything injected explicitly via the transport constructor (tests).
2. The matching n8n credential, if `N8N_DB_DSN` + `N8N_ENCRYPTION_KEY`
   are configured and the per-backend "lookup name" env var is set
   (`GSHEET_CREDS_EMAIL` or `SUPABASE_CREDS_NAME`).
3. The legacy env-var path inside each transport
   (`GOOGLE_SERVICE_ACCOUNT_JSON`, `SUPABASE_BASE_URL` + key).
"""
from __future__ import annotations

import logging
import os
from typing import Callable, Optional

from .core.errors import NotImplementedYet
from .core.models import RepoConfig
from .core.repo import DocumentRepo
from .kafka.admin import KafkaAdmin, NullKafkaAdmin
from .kafka.producer import KafkaProducer, NullKafkaProducer
from .n8n_credentials import N8nCredential, N8nCredentialStore, from_env as _n8n_from_env


logger = logging.getLogger(__name__)


RepoFactory = Callable[[RepoConfig], DocumentRepo]


# ---------- n8n credential resolvers ----------


_GSHEET_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]


def _gsheet_service_account_from_n8n(
    store: N8nCredentialStore,
) -> Optional[object]:
    """Return a service-account `Credentials` from a matching n8n `googleApi`
    cred (n8n stores `email` + `privateKey`), or None when not configured.

    Selected by `GSHEET_SA_CREDS_NAME` (substring match on the cred name).
    Service accounts self-sign JWTs — no refresh dance, no OAuth client.
    """
    name = os.getenv("GSHEET_SA_CREDS_NAME", "").strip()
    if not name:
        return None
    cred_type = os.getenv("GSHEET_SA_N8N_TYPE", "googleApi")
    try:
        record = store.get_latest(cred_type, name_contains=name)
    except LookupError:
        logger.warning("n8n SA cred lookup miss type=%s name=%s", cred_type, name)
        return None

    email = record.data.get("email")
    private_key = record.data.get("privateKey") or record.data.get("private_key")
    if not email or not private_key:
        logger.warning("n8n SA cred %s missing email/privateKey", record.id)
        return None

    # n8n stores the PEM with literal "\n" sequences; google-auth needs
    # real newlines. Idempotent for already-unescaped keys.
    if "\\n" in private_key and "\n" not in private_key:
        private_key = private_key.replace("\\n", "\n")

    from google.oauth2.service_account import Credentials  # type: ignore

    info = {
        "type": "service_account",
        "client_email": email,
        "private_key": private_key,
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    return Credentials.from_service_account_info(info, scopes=_GSHEET_SCOPES)


def _gsheet_credentials_from_n8n(store: N8nCredentialStore) -> Optional[object]:
    """Resolve gsheet credentials from n8n.

    Order:
      1. Service account via `GSHEET_SA_CREDS_NAME` (n8n type `googleApi`).
         No refresh dance — preferred for unattended deployments.
      2. User OAuth2 via `GSHEET_CREDS_EMAIL` (n8n type `googleSheetsOAuth2Api`).
         Token refresh needs `GSHEET_OAUTH_CLIENT_ID/SECRET` env when n8n's
         stored cred doesn't carry its own.
    """
    sa = _gsheet_service_account_from_n8n(store)
    if sa is not None:
        return sa

    email = os.getenv("GSHEET_CREDS_EMAIL", "").strip()
    if not email:
        return None
    cred_type = os.getenv("GSHEET_CREDS_N8N_TYPE", "googleSheetsOAuth2Api")
    try:
        record = store.get_latest(cred_type, name_contains=email)
    except LookupError:
        logger.warning(
            "n8n cred lookup miss type=%s email=%s", cred_type, email
        )
        return None

    token_data = record.data.get("oauthTokenData") or {}
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    client_id = record.data.get("clientId") or os.getenv("GSHEET_OAUTH_CLIENT_ID")
    client_secret = (
        record.data.get("clientSecret") or os.getenv("GSHEET_OAUTH_CLIENT_SECRET")
    )
    scopes = (token_data.get("scope") or "").split() or None

    from google.oauth2.credentials import Credentials  # type: ignore

    return Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=scopes,
    )


def _supabase_credentials_from_n8n(
    store: N8nCredentialStore,
) -> Optional[tuple[str, str]]:
    """Return `(base_url, service_key)` from the latest matching n8n cred."""
    name = os.getenv("SUPABASE_CREDS_NAME", "").strip()
    if not name:
        return None
    cred_type = os.getenv("SUPABASE_CREDS_N8N_TYPE", "supabaseApi")
    try:
        record = store.get_latest(cred_type, name_contains=name)
    except LookupError:
        logger.warning(
            "n8n cred lookup miss type=%s name=%s", cred_type, name
        )
        return None

    base_url = record.data.get("host") or record.data.get("url")
    service_key = (
        record.data.get("serviceRole")
        or record.data.get("service_role_key")
        or record.data.get("apiKey")
    )
    if not base_url or not service_key:
        logger.warning(
            "n8n cred %s is missing host/serviceRole — falling back to env",
            record.id,
        )
        return None
    return base_url, service_key


# ---------- Factories ----------


def default_repo_factory(config: RepoConfig) -> DocumentRepo:
    store = _n8n_from_env()

    if config.backend == "gsheet":
        # Lazy import: avoids loading google-api-python-client unless needed.
        from .backends.gsheet import GSheetRepo
        from .backends.gsheet_transport import GoogleApiTransport

        creds = _gsheet_credentials_from_n8n(store) if store else None
        return GSheetRepo(
            config, transport=GoogleApiTransport(credentials=creds) if creds else GoogleApiTransport()
        )

    if config.backend == "supabase":
        from .backends.supabase import SupabaseRepo
        from .backends.supabase_transport import HttpxSupabaseTransport

        resolved = _supabase_credentials_from_n8n(store) if store else None
        if resolved:
            base_url, service_key = resolved
            # Allow SUPABASE_BASE_URL / SUPABASE_SERVICE_KEY env vars to override n8n creds
            env_url = os.getenv("SUPABASE_BASE_URL", "").strip()
            env_key = os.getenv("SUPABASE_SERVICE_KEY", "").strip()
            if env_url:
                base_url = env_url if env_url.startswith("http") else f"https://{env_url}"
            if env_key:
                service_key = env_key
            transport = HttpxSupabaseTransport(
                base_url=base_url, service_key=service_key
            )
        else:
            transport = HttpxSupabaseTransport()
        return SupabaseRepo(config, transport=transport)

    raise NotImplementedYet(f"unknown backend '{config.backend}'")


def default_kafka_producer() -> KafkaProducer:
    """Build a producer from environment, or a no-op when Kafka isn't configured."""
    if not os.getenv("KAFKA_BOOTSTRAP_SERVERS"):
        return NullKafkaProducer()
    from .kafka.producer import ConfluentKafkaProducer

    return ConfluentKafkaProducer()


def default_kafka_admin() -> KafkaAdmin:
    if not os.getenv("KAFKA_BOOTSTRAP_SERVERS"):
        return NullKafkaAdmin()
    from .kafka.admin import ConfluentKafkaAdmin

    return ConfluentKafkaAdmin()
