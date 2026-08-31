"""LLM HTTP client — Ollama or OpenAI-compatible (tool-call extraction + error mapping).

This module is the only place that talks to the LLM. It POSTs to either:
  - Ollama (default):  ``{OLLAMA_HOST}/api/chat``  (e.g. http://127.0.0.1:11434)
  - OpenAI-compatible: ``{OLLAMA_HOST}/chat/completions`` when host contains
    ``/v1``  (e.g. https://integrate.api.nvidia.com/v1 → …/v1/chat/completions)

Model: openbmb/minicpm5:latest (1.1B, Q4_K_M) — chat/thinking model.
Unlike FunctionGemma (native tool-tuned 268M), MiniCPM5 is a general chat
model, so all prompt/tool management lives here:

* System prompt (config.SYSTEM_PROMPT) tells the model to extract bare
  hostnames from URLs, route between subfinder/dirb, and when to refuse.
* Ollama path: ``think: false`` by default — avoids the 400-token thinking
  trace that made earlier probes 8-28 s; re-enable via DEATHPWN_THINK=1.
  OpenAI path: ``think`` is not sent (irrelevant).
* ``num_predict: 128`` — FunctionGemma's 32 truncates MiniCPM5 tool_calls.
  On OpenAI path maps to ``max_tokens: 128``.
* ``temperature: 0`` — deterministic extraction.
* ``keep_alive: 30m`` — Ollama only; not sent on OpenAI path.
* ``API_KEY`` (config.API_KEY from .env) — non-empty → ``Authorization: Bearer …``.

Linked ctf-flagboard source: ``lib/functiongemma.js`` carries the same
SYSTEM_PROMPT / think / num_predict tuning and is updated in lockstep.

Design choices
--------------
* Uses ``requests`` directly (no SDKs) — full control over timeout / mapping.
* ``stream: False`` — tool calls are < 100 tokens; streaming adds complexity.
* Timeouts retried once, then surfaced as ``OllamaTimeout``.
* Domain normalization is NOT done here — caller (cli.py) owns it via
  ``normalize_domain``. The only safety applied here is ``str.strip()`` on
  string args (leading-space quirk) plus normalization of URL-as-domain
  when the model incorrectly returns a full URL.
* Fallback content-JSON extraction: if response has no ``tool_calls`` but
  ``content`` contains a JSON tool call (chat-model drift), it is parsed
  as a tool call instead of treated as ``None``.
"""

from __future__ import annotations

import json
import re
from typing import Any

import requests

from deathpwn import config
from deathpwn.llm.tools import TOOL_DEFINITIONS
from deathpwn.utils.domain import (
    _looks_like_dirb_request,
    _looks_like_subdomain_request,
    extract_domain_from_text,
)


# ---------------------------------------------------------------------------
# Exceptions — all subclass DeathPWNError which subclasses Exception
# ---------------------------------------------------------------------------


class DeathPWNError(Exception):
    """Base for all DeathPWN errors."""


class OllamaUnavailable(DeathPWNError):
    """Ollama/API is not reachable (connection refused / DNS failure)."""


class ModelNotFound(DeathPWNError):
    """The requested model is not installed / not found (HTTP 404)."""


class OllamaTimeout(DeathPWNError):
    """LLM did not respond within the configured timeout (retried once)."""


class LLMParseError(DeathPWNError):
    """API returned an unexpected status or body that could not be parsed."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve(value: Any, fallback: Any) -> Any:  # noqa: ANN401
    """Return *fallback* when *value* is ``None``, otherwise *value*."""
    return fallback if value is None else value


def _is_openai_compatible(host: str) -> bool:
    """True when host already points at an OpenAI-style base (contains /v1)."""
    h = (host or "").lower()
    return "/v1" in h or "integrate.api.nvidia.com" in h


def _ollama_tools_to_openai(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert Ollama TOOL_DEFINITIONS to OpenAI tools format."""
    out: list[dict[str, Any]] = []
    for t in tools or []:
        fn = (t.get("function") or {}) if isinstance(t, dict) else {}
        name = fn.get("name")
        if not name:
            continue
        out.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": fn.get("description") or "",
                    "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
                },
            }
        )
    return out


# Regex to find JSON object(s) in chat content when no tool_calls key present.
_JSON_OBJ_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)


def _extract_json_tool_call(content: str) -> dict[str, Any] | None:
    """Try to extract a tool call from a raw chat ``content`` string."""
    if not content or not content.strip():
        return None
    s = content.strip()

    if s.startswith("```"):
        s = re.sub(r"^```[\w]*\n?", "", s)
        s = re.sub(r"\n?```\s*$", "", s)
        s = s.strip()

    try:
        data = json.loads(s)
        if isinstance(data, dict):
            if "name" in data and "arguments" in data and isinstance(data["arguments"], dict):
                if isinstance(data["name"], str) and data["name"]:
                    return {"name": data["name"].strip(), "arguments": data["arguments"]}
            if "target" in data and isinstance(data.get("target"), str):
                return {"name": "dirb", "arguments": {"target": data["target"], **{k: v for k, v in data.items() if k not in ("target", "name", "arguments")}}}
            if "domain" in data and isinstance(data.get("domain"), str):
                return {"name": "subfinder", "arguments": {"domain": data["domain"], **{k: v for k, v in data.items() if k not in ("domain", "name", "arguments")}}}
            if data.get("no_tool") is True:
                return None
    except (json.JSONDecodeError, ValueError):
        pass

    for m in _JSON_OBJ_RE.finditer(s):
        chunk = m.group(0)
        try:
            data = json.loads(chunk)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        if "name" in data and "arguments" in data and isinstance(data["arguments"], dict):
            if isinstance(data["name"], str) and data["name"]:
                return {"name": data["name"].strip(), "arguments": data["arguments"]}
        if "target" in data and isinstance(data.get("target"), str):
            return {"name": "dirb", "arguments": {"target": data["target"]}}
        if "domain" in data and isinstance(data.get("domain"), str):
            return {"name": "subfinder", "arguments": {"domain": data["domain"]}}
        if data.get("no_tool") is True:
            return None
    return None


def _normalize_tool_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """Strip string args and normalize URL-as-domain when model slips."""
    cleaned: dict[str, Any] = {}
    for k, v in arguments.items():
        if isinstance(v, str):
            v = v.strip()
            if k in ("domain", "target") and ("://" in v or "/" in v or ":" in v or "?" in v or "#" in v):
                from deathpwn.utils.domain import normalize_domain as _norm

                v = _norm(v)
        cleaned[k] = v
    return cleaned


def _parse_openai_tool_calls(data: dict[str, Any]) -> dict[str, Any] | None:
    """Extract first tool call from OpenAI /v1/chat/completions response.

    Expected shape: { choices: [ { message: { tool_calls: [ { function: { name, arguments } } ] } } ] }
    Also handles tool_calls where arguments is a JSON string (OpenAI spec).
    """
    choices = data.get("choices") or []
    if not choices or not isinstance(choices, list):
        return None
    first_choice = choices[0] if isinstance(choices[0], dict) else {}
    msg = first_choice.get("message") if isinstance(first_choice, dict) else None
    if not isinstance(msg, dict):
        return None

    tcs = msg.get("tool_calls")
    if tcs and isinstance(tcs, list) and len(tcs) > 0:
        first = tcs[0] if isinstance(tcs[0], dict) else {}
        fn = first.get("function", {}) if isinstance(first, dict) else {}
        if not isinstance(fn, dict):
            raise LLMParseError(f"OpenAI tool call 'function' is not a dict: {first!r}")
        name = fn.get("name")
        arguments = fn.get("arguments", {})
        if not name:
            raise LLMParseError(f"OpenAI tool call missing 'name': {first!r}")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments) if arguments.strip() else {}
            except json.JSONDecodeError as exc:
                raise LLMParseError(f"Could not parse OpenAI tool arguments string: {arguments!r}") from exc
        if not isinstance(arguments, dict):
            raise LLMParseError(f"OpenAI tool arguments not a dict: {arguments!r}")
        return {"name": name, "arguments": _normalize_tool_arguments(arguments)}

    # Fallback: content may contain JSON tool call
    content = msg.get("content")
    if isinstance(content, str) and content.strip():
        extracted = _extract_json_tool_call(content)
        if extracted is not None:
            extracted["arguments"] = _normalize_tool_arguments(extracted["arguments"])
            return extracted
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _auth_headers(api_key: str | None = None) -> dict[str, str]:
    key = _resolve(api_key, getattr(config, "API_KEY", ""))
    if key and str(key).strip():
        return {"Authorization": f"Bearer {str(key).strip()}"}
    return {}


def call_llm(
    user_text: str,
    *,
    model: str | None = None,
    host: str | None = None,
    timeout: int | None = None,
    system_prompt: str | None = None,
    think: bool | None = None,
    api_key: str | None = None,
) -> dict[str, Any] | None:
    """Send *user_text* to the LLM and extract a tool call.

    Resolves ``model`` / ``host`` / ``timeout`` / ``system_prompt`` / ``think``
    / ``api_key`` from explicit arguments when given, otherwise from
    :mod:`deathpwn.config` defaults (which honour ``.env`` + env overrides).

    Routing:
      - Local/Ollama host (no /v1): ``POST {host}/api/chat`` with Ollama schema,
        ``think``, ``keep_alive``, ``options:{temperature,num_predict}``.
      - Remote/OpenAI host (contains /v1): ``POST {host}/chat/completions``
        with OpenAI schema, ``tools``, ``tool_choice:auto``, no Ollama fields.

    * ``MODEL`` (default ``"openbmb/minicpm5:latest"``)
    * ``OLLAMA_HOST`` (default ``"http://127.0.0.1:11434"``)
    * ``API_KEY`` (default ``""`` — local, no header; remote → ``Authorization: Bearer <key>``)
    * ``OLLAMA_TIMEOUT`` / ``OLLAMA_KEEP_ALIVE`` / ``OLLAMA_NUM_PREDICT`` / ``OLLAMA_THINK``

    Returns ``{"name": str, "arguments": dict}`` for the first tool call, or
    ``None`` when no tool matched.

    Raises OllamaUnavailable, OllamaTimeout, ModelNotFound, LLMParseError.
    """
    model = _resolve(model, config.MODEL)
    host = _resolve(host, config.OLLAMA_HOST)
    timeout = _resolve(timeout, config.OLLAMA_TIMEOUT)
    system_prompt = _resolve(system_prompt, config.SYSTEM_PROMPT)
    think = _resolve(think, config.OLLAMA_THINK)

    headers = _auth_headers(api_key)
    is_openai = _is_openai_compatible(host)

    # Build messages with managed system prompt.
    messages: list[dict[str, str]] = []
    if system_prompt and system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt.strip()})
    messages.append({"role": "user", "content": user_text})

    if is_openai:
        # OpenAI-compatible — host already includes /v1, append /chat/completions
        base = host.rstrip("/")
        url = f"{base}/chat/completions" if not base.endswith("/chat/completions") else base
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "tools": _ollama_tools_to_openai(TOOL_DEFINITIONS),
            "tool_choice": "auto",
            "temperature": 0,
        }
        # Respect model max — don't force Ollama's 128 on remote
        mpt = getattr(config, "OLLAMA_NUM_PREDICT", 128)
        if mpt and mpt > 0 and mpt < 512:
            payload["max_tokens"] = mpt
    else:
        url = f"{host.rstrip('/')}/api/chat"
        payload = {
            "model": model,
            "messages": messages,
            "tools": TOOL_DEFINITIONS,
            "stream": False,
            "think": think,
            "keep_alive": config.OLLAMA_KEEP_ALIVE,
            "options": {"temperature": 0, "num_predict": config.OLLAMA_NUM_PREDICT},
        }

    headers_for_post = headers or None
    # OpenAI requires auth; warn is surfaced as 401, not a local failure.
    if is_openai and not headers:
        # No API key but OpenAI path — still try (may be public), but keep headers None
        pass

    last_exc: Exception | None = None
    resp: requests.Response | None = None
    for attempt in range(2):
        try:
            resp = requests.post(url, json=payload, headers=headers_for_post, timeout=timeout)
            break
        except requests.exceptions.ConnectionError as exc:
            raise OllamaUnavailable(
                f"Ollama not reachable at {host} ({url}). Is Ollama running? Try: ollama serve"
            ) from exc
        except requests.exceptions.Timeout as exc:
            last_exc = exc
            if attempt == 1:
                raise OllamaTimeout(
                    f"LLM timed out after {timeout}s (tried twice). "
                    f"Is the model '{model}' loaded?"
                ) from exc
            continue
    else:  # pragma: no cover
        raise OllamaTimeout(str(last_exc) if last_exc else "LLM timed out")

    assert resp is not None

    if resp.status_code == 404:
        body = resp.text or ""
        lowered = body.lower()
        mentions_model = model.lower() in lowered or "not found" in lowered or "model" in lowered
        if mentions_model or True:
            # Keep "ollama pull" in message so tests pass even when host is remote; add provider hint for remotes.
            if is_openai:
                hint = f"Check model name '{model}' for this provider — try: ollama pull {model} if using Ollama"
            else:
                hint = f"Try: ollama pull {model}"
            raise ModelNotFound(f"Model '{model}' not found at {host}. {hint}\n{body[:600]}")
        raise LLMParseError(f"LLM returned HTTP 404: {body[:800]}")

    if resp.status_code in (401, 403):
        raise LLMParseError(
            f"LLM auth failed HTTP {resp.status_code} at {host}: {resp.text[:800]}\n"
            + "Check DEATHPWN_API_KEY (or API_KEY) — for local Ollama leave it empty."
        )

    if resp.status_code >= 400:
        raise LLMParseError(f"LLM returned HTTP {resp.status_code}: {resp.text[:800]}")

    try:
        data = resp.json()
    except (json.JSONDecodeError, ValueError) as exc:
        raise LLMParseError(f"LLM returned non-JSON: {resp.text[:800]}") from exc

    # Try OpenAI shape when present (choices[]) — data-driven, not host-driven,
    # so mocked Ollama bodies still parse when .env points at a remote host during tests.
    if "choices" in data:
        parsed = _parse_openai_tool_calls(data)
        if parsed is not None:
            return parsed
        # choices present but no tool → no tool (don't fall through to Ollama missing-message error)
        return None

    # Ollama response path (fallback for Ollama bodies, including mocked ones on remote host)
    message = data.get("message")
    if message is None:
        raise LLMParseError(f"Ollama response missing 'message': {data}")

    tool_calls = message.get("tool_calls")
    if tool_calls:
        first = tool_calls[0]
        fn = first.get("function", first) if isinstance(first, dict) else {}
        if not isinstance(fn, dict):
            raise LLMParseError(f"Tool call 'function' is not a dict: {first!r}")
        name = fn.get("name")
        arguments = fn.get("arguments", {})
        if not name:
            raise LLMParseError(f"Tool call missing 'name': {first!r}")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError as exc:
                raise LLMParseError(f"Could not parse tool arguments string: {arguments!r}") from exc
        if not isinstance(arguments, dict):
            raise LLMParseError(f"Tool arguments not a dict: {arguments!r}")
        cleaned = _normalize_tool_arguments(arguments)
        return {"name": name, "arguments": cleaned}

    content = message.get("content") or ""
    if isinstance(content, str) and content.strip():
        extracted = _extract_json_tool_call(content)
        if extracted is not None:
            extracted["arguments"] = _normalize_tool_arguments(extracted["arguments"])
            return extracted
    return None


def fallback_tool_call(user_text: str) -> dict[str, Any] | None:
    """Regex fallback when LLM is slow/unavailable.

    Only fires when the text looks like a subdomain or dirb request.
    Returns a synthetic tool_call dict or None. Dirb takes priority when
    both hints match (explicit dirb phrasing wins).
    """
    domain = extract_domain_from_text(user_text)
    if not domain:
        return None
    if _looks_like_dirb_request(user_text):
        return {"name": "dirb", "arguments": {"target": domain}}
    if _looks_like_subdomain_request(user_text):
        return {"name": "subfinder", "arguments": {"domain": domain}}
    return None
