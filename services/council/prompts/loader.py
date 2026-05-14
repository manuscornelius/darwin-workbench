"""Load versioned system prompts from YAML files.

Each YAML file defines one or more named prompts. A prompt has a name, version,
and body. The loader exposes a single get_prompt(name) function that returns
the active version's body plus its versioned identifier (e.g. "council@0.2.0").

YAML schema:
    name: council
    description: System prompt for the single-agent council loop.
    active: "0.2.0"
    versions:
      "0.2.0":
        body: |
          You are the Darwin Council...
      "0.1.0":
        body: |
          Older version kept for history.

Prompts are cached in-process on first read. Call reload_prompts() to pick up
edits without restarting the service.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_PROMPTS_DIR = Path(__file__).parent / "system_prompts"
_CACHE: dict[str, "Prompt"] = {}


class PromptNotFoundError(KeyError):
    """Raised when a prompt name has no matching YAML file."""


@dataclass(frozen=True)
class Prompt:
    """A resolved prompt — the active version's body plus its versioned id."""

    name: str
    version: str
    body: str

    @property
    def versioned_id(self) -> str:
        """Versioned identifier like 'council@0.2.0' for audit/audit-trail use."""
        return f"{self.name}@{self.version}"


def _load_file(path: Path) -> Prompt:
    """Parse one YAML file and return the active version's prompt."""
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))

    name = data.get("name") or path.stem
    active = data.get("active")
    versions = data.get("versions", {})

    if not active:
        raise ValueError(f"{path.name}: missing 'active' field")
    if active not in versions:
        raise ValueError(
            f"{path.name}: active version '{active}' not in versions "
            f"{list(versions)}"
        )

    body = versions[active].get("body")
    if not body:
        raise ValueError(f"{path.name}: version {active} has no 'body'")

    return Prompt(name=name, version=active, body=body.strip())


def _ensure_loaded() -> None:
    """Load all YAML files in system_prompts/ into the cache on first access."""
    if _CACHE:
        return
    if not _PROMPTS_DIR.exists():
        raise PromptNotFoundError(
            f"Prompts directory does not exist: {_PROMPTS_DIR}"
        )
    for path in sorted(_PROMPTS_DIR.glob("*.yaml")):
        prompt = _load_file(path)
        _CACHE[prompt.name] = prompt


def get_prompt(name: str) -> Prompt:
    """Return the active version of the named prompt."""
    _ensure_loaded()
    if name not in _CACHE:
        raise PromptNotFoundError(
            f"Prompt '{name}' not found. Available: {list(_CACHE)}"
        )
    return _CACHE[name]


def list_prompts() -> list[Prompt]:
    """Return all loaded prompts (active versions)."""
    _ensure_loaded()
    return list(_CACHE.values())


def reload_prompts() -> None:
    """Clear the cache so the next access re-reads from disk."""
    _CACHE.clear()
