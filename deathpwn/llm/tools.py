"""Tool definitions for FunctionGemma — single source of truth."""
from __future__ import annotations

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "subfinder",
            "description": "Discover subdomains for a target domain using passive sources. Use when the user asks to find, enumerate, or discover subdomains.",
            "parameters": {
                "type": "object",
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Target domain to enumerate, e.g. example.com — without protocol, path, or port",
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
