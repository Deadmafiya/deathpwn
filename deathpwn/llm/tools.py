"""Tool definitions for MiniCPM5 — single source of truth."""
from __future__ import annotations

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "subfinder",
            "description": (
                "Discover subdomains for a target domain using passive sources. "
                "Use when the user asks to find, enumerate, or discover subdomains "
                "for a domain, host, website, or URL. "
                "When the user gives a URL (e.g. https://example.com/path), "
                "extract the bare hostname (example.com) as the domain."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Bare target domain/hostname, e.g. example.com — no scheme, path, port, query, or fragment. Extract bare host if user gave a URL.",
                    },
                    "all_sources": {
                        "type": "boolean",
                        "description": "Use all sources (slower, more thorough). Default false.",
                    },
                },
                "required": ["domain"],
            },
        },
    }
]

TOOL_NAMES = ["subfinder"]
