"""Storage layer — repository pattern over CIM entities.

The agent loop talks to repositories through the abstract interfaces in
base.py. Concrete impls (sqlite_repo, dynamodb_repo) plug in via the
registry, swapped by the STORAGE_PROVIDER env var.
"""

from storage.models import (
    AuditEvent,
    ContentBlock,
    Message,
    PromptVersion,
    Session,
    ToolCall,
)
from storage.registry import get_storage

__all__ = [
    "AuditEvent",
    "ContentBlock",
    "Message",
    "PromptVersion",
    "Session",
    "ToolCall",
    "get_storage",
]
