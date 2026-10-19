"""Core domain — pure-python, no Flask, no I/O beyond the registry file.

Public re-exports kept stable for the rest of the module to import from
``apitools.incoming_documents.core``.
"""
from .diff import compute_diff
from .errors import (
    BackendUnavailable,
    BatchTooLarge,
    IncomingDocumentsError,
    KafkaUnavailable,
    NotImplementedYet,
    PrimaryKeyMissing,
    ProvisioningFailed,
    RepoAlreadyExists,
    RepoNotFound,
    SchemaDrift,
    ValidationError,
)
from .models import (
    ColumnDef,
    ContainerReport,
    DiffResult,
    EventEnvelope,
    EventType,
    FilterClause,
    GSheetBackendConfig,
    KafkaConfig,
    PermissionsReport,
    ProvisionReport,
    Query,
    QueryOp,
    RepoConfig,
    RowUpdate,
    SchemaReport,
    SupabaseBackendConfig,
    TableReport,
)
from .registry import RepoRegistry, get_default_registry
from .repo import DocumentRepo, InMemoryRepo
from .types import LogicalType, normalize_value, values_equal

__all__ = [
    "BackendUnavailable",
    "BatchTooLarge",
    "ColumnDef",
    "ContainerReport",
    "DiffResult",
    "DocumentRepo",
    "EventEnvelope",
    "EventType",
    "FilterClause",
    "GSheetBackendConfig",
    "InMemoryRepo",
    "IncomingDocumentsError",
    "KafkaConfig",
    "KafkaUnavailable",
    "LogicalType",
    "NotImplementedYet",
    "PermissionsReport",
    "PrimaryKeyMissing",
    "ProvisionReport",
    "ProvisioningFailed",
    "Query",
    "QueryOp",
    "RepoAlreadyExists",
    "RepoConfig",
    "RepoNotFound",
    "RepoRegistry",
    "RowUpdate",
    "SchemaDrift",
    "SchemaReport",
    "SupabaseBackendConfig",
    "TableReport",
    "ValidationError",
    "compute_diff",
    "get_default_registry",
    "normalize_value",
    "values_equal",
]
