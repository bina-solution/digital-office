"""Exception hierarchy. All errors map to the canonical envelope in §3.3.

Each exception carries a stable machine-readable `code` (used as the
`error` field in the JSON response) plus an HTTP `status` for the route
handler to translate into a Flask response.
"""
from __future__ import annotations


class IncomingDocumentsError(Exception):
    """Base class for every error this module raises."""

    code: str = "internal_error"
    status: int = 500

    def __init__(self, message: str | None = None, **details):
        super().__init__(message or self.code)
        self.message = message or self.code
        self.details = details

    def to_envelope(self) -> dict:
        return {
            "success": False,
            "error": self.code,
            "message": self.message,
            "details": self.details,
        }


class ValidationError(IncomingDocumentsError):
    code = "validation_error"
    status = 400


class RepoNotFound(IncomingDocumentsError):
    code = "repo_not_found"
    status = 404


class RepoAlreadyExists(IncomingDocumentsError):
    code = "repo_already_exists"
    status = 409


class SchemaDrift(IncomingDocumentsError):
    code = "schema_drift"
    status = 409


class BatchTooLarge(IncomingDocumentsError):
    code = "batch_too_large"
    status = 413


class PrimaryKeyMissing(IncomingDocumentsError):
    code = "primary_key_missing"
    status = 422


class NotImplementedYet(IncomingDocumentsError):
    code = "not_implemented"
    status = 501


class BackendUnavailable(IncomingDocumentsError):
    code = "backend_unavailable"
    status = 502


class KafkaUnavailable(IncomingDocumentsError):
    """Backend write succeeded but Kafka publish failed.

    The route MUST set ``written=True`` in the response details so the
    caller knows the data is persisted.
    """

    code = "kafka_unavailable"
    status = 503


class ProvisioningFailed(IncomingDocumentsError):
    code = "provisioning_failed"
    status = 503
