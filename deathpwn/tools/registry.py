"""Minimal tool registry — makes adding the next tool a one-file change."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

TOOL_REGISTRY: dict[str, Callable[..., Any]] = {}


def register(name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        TOOL_REGISTRY[name] = fn
        return fn

    return decorator


def get_tool(name: str) -> Callable[..., Any] | None:
    return TOOL_REGISTRY.get(name)
