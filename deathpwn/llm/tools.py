"""Tool definitions for MiniCPM5 — single source of truth."""
from __future__ import annotations

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "subfinder",
            "description": (
                "Discover subdomains for a target domain using passive sources. "
                "Use ONLY when the user asks to find, enumerate, or discover subdomains "
                "for a domain, host, website, or URL. Do NOT use for directory "
                "bruteforce or port scanning. "
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
    },
    {
        "type": "function",
        "function": {
            "name": "dirb",
            "description": (
                "Bruteforce directories and files on a website (runs dirb https://<host>). "
                "Use ONLY when the user asks for directory bruteforce — keywords: dirb, "
                "directory bruteforce, directory brute force, directory scan, bruteforce "
                "directories, directory enumeration, discover directories. Do NOT use for "
                "subdomains or for port scanning (scan ports, nmap, port scan) — those are "
                "NOT directory bruteforce. When the user gives a URL like https://example.com/path, "
                "extract the bare host (example.com) as target."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "Bare hostname e.g. example.com — no scheme, path, port. CLI adds https://. Extract bare host if URL.",
                    },
                },
                "required": ["target"],
            },
        },
    },
]

TOOL_NAMES = ["subfinder", "dirb"]
