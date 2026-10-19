"""On-disk JSON registry for `RepoConfig` records.

Atomic writes via temp-file + ``os.replace``; mtime-based hot reload so
multiple Gunicorn workers see changes without an explicit reload signal.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import ValidationError as PydanticValidationError

from .errors import RepoAlreadyExists, RepoNotFound, ValidationError
from .models import RepoConfig


class RepoRegistry:
    """Thread-safe JSON-file-backed registry of `RepoConfig` records."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self._cache: dict[str, RepoConfig] = {}
        self._stamp: tuple[float, int] = (-1.0, -1)  # (mtime, size)

    # ---------- file IO ----------

    def _ensure_dir(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _read_disk(self) -> tuple[dict[str, RepoConfig], tuple[float, int]]:
        if not self.path.exists():
            return {}, (0.0, 0)
        raw = self.path.read_text(encoding="utf-8") or "[]"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValidationError(
                f"registry file is not valid JSON: {e}", path=str(self.path)
            ) from e
        if not isinstance(data, list):
            raise ValidationError(
                "registry file must be a JSON array of RepoConfig objects",
                path=str(self.path),
            )
        out: dict[str, RepoConfig] = {}
        for i, item in enumerate(data):
            try:
                cfg = RepoConfig.model_validate(item)
            except PydanticValidationError as e:
                raise ValidationError(
                    f"registry entry #{i} failed validation",
                    path=str(self.path),
                    errors=e.errors(),
                ) from e
            if cfg.name in out:
                raise ValidationError(
                    f"duplicate repo name '{cfg.name}' in registry",
                    path=str(self.path),
                )
            out[cfg.name] = cfg
        st = self.path.stat()
        return out, (st.st_mtime, st.st_size)

    def _write_disk(self, configs: dict[str, RepoConfig]) -> tuple[float, int]:
        self._ensure_dir()
        # exclude_none: pydantic refills absent optionals on load, so a None on disk carries no
        # information — and the 8 optional display fields on ColumnDef serialized as ~750 literal
        # nulls across 93 columns, committed churn in a runtime-written file. Display metadata is
        # deliberately NOT stored here (the BFF merges blueprint/schema/display.json per request);
        # keeping the nulls out also keeps a stray non-null display value from ever competing
        # with that catalog as a second source of truth.
        payload = [c.model_dump(mode="json", by_alias=True, exclude_none=True)
                   for c in configs.values()]
        # Atomic write: temp-file in same dir, then os.replace.
        fd, tmp = tempfile.mkstemp(
            prefix=".repos.", suffix=".json.tmp", dir=str(self.path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        st = self.path.stat()
        return st.st_mtime, st.st_size

    def _refresh_if_stale(self) -> None:
        """Reload from disk if the file's stamp moved (or the cache is empty)."""
        if not self.path.exists():
            self._cache = {}
            self._stamp = (0.0, 0)
            return
        st = self.path.stat()
        stamp = (st.st_mtime, st.st_size)
        if stamp != self._stamp:
            self._cache, self._stamp = self._read_disk()

    # ---------- public API ----------

    def list(self) -> list[RepoConfig]:
        with self._lock:
            self._refresh_if_stale()
            return list(self._cache.values())

    def get(self, name: str) -> RepoConfig:
        with self._lock:
            self._refresh_if_stale()
            try:
                return self._cache[name]
            except KeyError as e:
                raise RepoNotFound(f"repo '{name}' is not registered") from e

    def has(self, name: str) -> bool:
        with self._lock:
            self._refresh_if_stale()
            return name in self._cache

    def create(self, config: RepoConfig) -> RepoConfig:
        with self._lock:
            self._refresh_if_stale()
            if config.name in self._cache:
                raise RepoAlreadyExists(f"repo '{config.name}' already exists")
            now = datetime.now(timezone.utc)
            cfg = config.model_copy(update={"created_at": now, "updated_at": now})
            new = dict(self._cache)
            new[cfg.name] = cfg
            self._stamp = self._write_disk(new)
            self._cache = new
            return cfg

    def update(self, config: RepoConfig) -> RepoConfig:
        with self._lock:
            self._refresh_if_stale()
            if config.name not in self._cache:
                raise RepoNotFound(f"repo '{config.name}' is not registered")
            existing = self._cache[config.name]
            cfg = config.model_copy(
                update={
                    "created_at": existing.created_at,
                    "updated_at": datetime.now(timezone.utc),
                }
            )
            new = dict(self._cache)
            new[cfg.name] = cfg
            self._stamp = self._write_disk(new)
            self._cache = new
            return cfg

    def delete(self, name: str) -> None:
        with self._lock:
            self._refresh_if_stale()
            if name not in self._cache:
                raise RepoNotFound(f"repo '{name}' is not registered")
            new = dict(self._cache)
            new.pop(name)
            self._stamp = self._write_disk(new)
            self._cache = new

    # ---------- helpers used by routes ----------

    def upsert_unsafe(self, config: RepoConfig) -> RepoConfig:
        """Used by `provision_repo` to persist a fully-resolved config in
        one atomic write. Replaces any existing entry of the same name.
        """
        with self._lock:
            self._refresh_if_stale()
            now = datetime.now(timezone.utc)
            existing = self._cache.get(config.name)
            cfg = config.model_copy(
                update={
                    "created_at": existing.created_at if existing else now,
                    "updated_at": now,
                }
            )
            new = dict(self._cache)
            new[cfg.name] = cfg
            self._stamp = self._write_disk(new)
            self._cache = new
            return cfg


_default_registry: Optional[RepoRegistry] = None
_default_registry_lock = threading.Lock()


def get_default_registry() -> RepoRegistry:
    """Process-wide singleton, path comes from
    ``INCOMING_DOCS_REPO_REGISTRY`` (default
    ``.storage/incoming_documents/repos.json``).
    """
    global _default_registry
    with _default_registry_lock:
        if _default_registry is None:
            path = os.getenv(
                "INCOMING_DOCS_REPO_REGISTRY",
                ".storage/incoming_documents/repos.json",
            )
            _default_registry = RepoRegistry(path)
        return _default_registry
