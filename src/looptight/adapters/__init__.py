"""Adapter registry.

One place that knows the set of agents. Adding an agent is: write a subclass,
add it here. Nothing else in looptight names a specific agent.
"""

from __future__ import annotations

from .base import Adapter
from .claude import ClaudeAdapter
from .codex import CodexAdapter
from .opencode import OpencodeAdapter

_REGISTRY: dict[str, type[Adapter]] = {
    ClaudeAdapter.name: ClaudeAdapter,
    CodexAdapter.name: CodexAdapter,
    OpencodeAdapter.name: OpencodeAdapter,
}


def available_adapter_names() -> tuple[str, ...]:
    return tuple(_REGISTRY)


def get_adapter(name: str) -> Adapter:
    """Instantiate the adapter for ``name``. Raises KeyError if unknown."""
    try:
        return _REGISTRY[name]()
    except KeyError:
        known = ", ".join(_REGISTRY)
        raise KeyError(f"unknown agent '{name}'. known agents: {known}") from None


__all__ = [
    "Adapter",
    "ClaudeAdapter",
    "CodexAdapter",
    "OpencodeAdapter",
    "available_adapter_names",
    "get_adapter",
]
