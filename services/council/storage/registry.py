"""Storage backend lookup by name."""

from __future__ import annotations

import os

from storage.base import StorageBackend
from storage.sqlite_repo import SQLiteBackend
from storage.dynamodb_repo import DynamoDBBackend

_BACKENDS: dict[str, type[StorageBackend]] = {
    "sqlite": SQLiteBackend,
    "dynamodb": DynamoDBBackend,
}

_INSTANCE: StorageBackend | None = None


def get_storage(name: str | None = None) -> StorageBackend:
    """Return a singleton storage backend instance."""
    global _INSTANCE
    if _INSTANCE is not None:
        return _INSTANCE

    name = name or os.getenv("STORAGE_PROVIDER", "sqlite")
    if name not in _BACKENDS:
        raise ValueError(
            f"Unknown storage backend: {name}. Available: {list(_BACKENDS)}"
        )
    _INSTANCE = _BACKENDS[name]()
    return _INSTANCE
