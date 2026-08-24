"""Ollama / MiniCPM5 HTTP client — tool-call extraction + error mapping.

This module is the only place that talks to Ollama. It POSTs to
``{OLLAMA_HOST}/api/chat`` with ``TOOL_DEFINITIONS`` + a managed system
prompt and extracts a tool call.

Model: openbmb/minicpm5:latest (1.1B, Q4_K_M) — chat/thinking model.
Unlike FunctionGemma (native tool-tuned 268M), MiniCPM5 is a general chat
model, so all prompt/tool management lives here:

* System prompt (config.SYSTEM_PROMPT) tells the model to extract bare
  hostnames from URLs, when to call subfinder, and when to refuse.
* ``think: false`` by default — avoids the 400-token thinking trace that
  made earlier probes 8-28 s; re-enable via DEATHPWN_THINK=1 when needed.
* ``num_predict: 128`` — FunctionGemma's 32 truncates MiniCPM5 tool_calls.
* ``temperature: 0`` — deterministic extraction.
* ``keep_alive: 30m`` — keep model hot.

Linked ctf-flagboard source: ``lib/functiongemma.js`` carries the same
SYSTEM_PROMPT / think / num_predict tuning and is updated in lockstep.

Design choices
--------------
* Uses ``requests`` directly (no ``ollama`` SDK) — full control over
  timeout / error mapping.
* ``stream: False`` — tool calls are < 100 tokens; streaming adds complexity.
* Timeouts retried once, then surfaced as ``OllamaTimeout``.
* Domain normalization is NOT done here — caller (cli.py) owns it via
  ``normalize_domain``. The only safety applied here is ``str.strip()`` on
  string args (leading-space quirk) plus normalization of URL-as-domain
  when the model incorrectly returns a full URL.
* Fallback content-JSON extraction: if /api/chat returns no ``tool_calls``
  but ``content`` contains a JSON tool call (chat-model drift), it is
  parsed as a tool call instead of treated as ``None``.
"""

from __future__ import annotations

import json
import re
from typing import Any

import requests

from deathpwn import config
from deathpwn.llm.tools import TOOL_DEFINITIONS
from deathpwn.utils.domain import extract_domain_from_text, _looks_like_subdomain_request


# ---------------------------------------------------------------------------
# Exceptions — all subclass DeathPWNError which subclasses Exception
# ---------------------------------------------------------------------------


class DeathPWNError(Exception):
    """Base for all DeathPWN errors."""


class OllamaUnavailable(DeathPWNError):
    """Ollama is not reachable (connection refused / DNS failure)."""


class ModelNotFound(DeathPWNError):
    """The requested Ollama model is not installed / not found (HTTP 404)."""


class OllamaTimeout(DeathPWNError):
    """Ollama did not respond within the configured timeout (retried once)."""


class LLMParseError(DeathPWNError):
    """Ollama returned an unexpected status or body that could not be parsed."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve(value: Any, fallback: Any) -> Any:  # noqa: ANN401
    """Return *fallback* when *value* is ``None``, otherwise *value*."""
    return fallback if value is None else value


# Regex to find JSON object(s) in chat content when no tool_calls key present.
_JSON_OBJ_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)


def _extract_json_tool_call(content: str) -> dict[str, Any] | None:
    """Try to extract a tool call from a raw chat ``content`` string.

    MiniCPM5 in chat mode (no tools param) or in rare drift with tools may
    emit JSON like ``{"name":"subfinder","arguments":{"domain":"..."}}``
    directly in content instead of via the ``tool_calls`` channel. This
    helper parses that fallback channel without importing extra deps.

    Returns ``{"name": str, "arguments": dict}`` on success, else None.
    """
    if not content or not content.strip():
        return None
    s = content.strip()

    # Strip code fences if the model wrapped JSON in them.
    if s.startswith("```"):
        # remove leading ```json or ``` and trailing ```
        s = re.sub(r"^```[\w]*\n?", "", s)
        s = re.sub(r"\n?```\s*$", "", s)
        s = s.strip()

    # 1) Direct parse — content is exactly one JSON object.
    try:
        data = json.loads(s)
        if isinstance(data, dict):
            if "name" in data and "arguments" in data and isinstance(data["arguments"], dict):
                if isinstance(data["name"], str) and data["name"]:
                    return {"name": data["name"].strip(), "arguments": data["arguments"]}
            # Shorthand: model returned {"domain": "example.com"}
            if "domain" in data and isinstance(data.get("domain"), str):
                return {"name": "subfinder", "arguments": {"domain": data["domain"], **{k: v for k, v in data.items() if k != "domain"}}}
            # Refusal marker from pure-chat prompts
            if data.get("no_tool") is True:
                return None
    except (json.JSONDecodeError, ValueError):
        pass

    # 2) Scan for any embedded JSON object that looks like a tool call.
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
        if "domain" in data and isinstance(data.get("domain"), str):
            return {"name": "subfinder", "arguments": {"domain": data["domain"]}}
        if data.get("no_tool") is True:
            return None
    return None


def _normalize_tool_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """Strip string args and normalize URL-as-domain when model slips.

    The only case we normalize here is when the model returns a full URL as
    ``domain`` (e.g. ``https://hadiya.in/path``) despite the instruction
    to return bare hostnames. We strip it to the bare domain so the caller
    does not have to distinguish LLM-URL vs bare-domain.
    """
    cleaned: dict[str, Any] = {}
    for k, v in arguments.items():
        if isinstance(v, str):
            v = v.strip()
            if k == "domain" and ("://" in v or "/" in v or ":" in v or "?" in v or "#" in v):
                # Looks like a URL sneaked through — extract bare host.
                from deathpwn.utils.domain import normalize_domain as _norm

                v = _norm(v)
        cleaned[k] = v
    return cleaned


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def call_llm(
    user_text: str,
    *,
    model: str | None = None,
    host: str | None = None,
    timeout: int | None = None,
    system_prompt: str | None = None,
    think: bool | None = None,
) -> dict[str, Any] | None:
    """Send *user_text* to Ollama / MiniCPM5 and extract a tool call.

    Resolves ``model`` / ``host`` / ``timeout`` / ``system_prompt`` / ``think``
    from explicit arguments when given, otherwise from :mod:`deathpwn.config`
    defaults (which honour env overrides ``DEATHPWN_MODEL``,
    ``DEATHPWN_OLLAMA_HOST``, ``DEATHPWN_TIMEOUT``, ``DEATHPWN_SYSTEM_PROMPT``,
    ``DEATHPWN_THINK``):

    * ``MODEL`` (default ``"openbmb/minicpm5:latest"``)
    * ``OLLAMA_HOST`` (default ``"http://127.0.0.1:11434"``)
    * ``OLLAMA_TIMEOUT`` (default ``30`` seconds)
    * ``OLLAMA_KEEP_ALIVE`` (default ``"30m"``)
    * ``OLLAMA_NUM_PREDICT`` (default ``128`` — 32 truncated MiniCPM5)
    * ``OLLAMA_THINK`` (default ``False`` — 400-token trace waste)
    * ``SYSTEM_PROMPT`` (managed prompt that teaches URL extraction + refusal)

    Request shape::

        POST {host}/api/chat
        {
          "model": "<model>",
          "messages": [
            {"role": "system", "content": "<system_prompt>"},
            {"role": "user", "content": "<user_text>"}
          ],
          "tools": TOOL_DEFINITIONS,
          "stream": false,
          "think": false,
          "keep_alive": "30m",
          "options": {"temperature": 0, "num_predict": 128}
        }

    Args:
        user_text: Raw English from the hunter, e.g.
            ``"find subdomains for https://example.com/path"``.
            Passed verbatim as the user message — the system prompt
            handles normalization instructions.
        model: Ollama model tag.  ``None`` → ``config.MODEL``.
        host: Ollama base URL. ``None`` → ``config.OLLAMA_HOST``.
        timeout: Seconds to wait. ``None`` → ``config.OLLAMA_TIMEOUT``.
            On :exc:`requests.Timeout` the request is retried once.
        system_prompt: System instruction. ``None`` → ``config.SYSTEM_PROMPT``.
            Pass ``""`` to suppress the system message entirely.
        think: Whether to enable MiniCPM5 thinking traces. ``None`` →
            ``config.OLLAMA_THINK``.  False is faster (3 s vs 10 s).

    Returns:
        ``{"name": str, "arguments": dict}`` for the first tool call, or
        ``None`` when no tool matched (e.g. ``"scan ports on example.com"``).

        Both Ollama tool-call shapes are accepted, plus JSON-in-content
        fallback (``{"name":..., "arguments":...}`` embedded in ``content``).

    Raises:
        OllamaUnavailable, OllamaTimeout, ModelNotFound, LLMParseError
        (see module docstring for mapping).

    Example:
        >>> call_llm("find subdomains for example.com")
        {'name': 'subfinder', 'arguments': {'domain': 'example.com'}}
        >>> call_llm("scan ports on example.com") is None
        True
    """
    # Resolve defaults — config already applied env overrides at import time.
    model = _resolve(model, config.MODEL)
    host = _resolve(host, config.OLLAMA_HOST)
    timeout = _resolve(timeout, config.OLLAMA_TIMEOUT)
    system_prompt = _resolve(system_prompt, config.SYSTEM_PROMPT)
    think = _resolve(think, config.OLLAMA_THINK)

    url = f"{host.rstrip('/')}/api/chat"

    # Build messages with managed system prompt.
    messages: list[dict[str, str]] = []
    if system_prompt and system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt.strip()})
    messages.append({"role": "user", "content": user_text})

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "tools": TOOL_DEFINITIONS,
        "stream": False,
        "think": think,
        "keep_alive": config.OLLAMA_KEEP_ALIVE,
        "options": {"temperature": 0, "num_predict": config.OLLAMA_NUM_PREDICT},
    }

    # -- HTTP call with one retry on timeout only -------------------------
    last_exc: Exception | None = None
    resp: requests.Response | None = None
    for attempt in range(2):
        try:
            resp = requests.post(url, json=payload, timeout=timeout)
            break
        except requests.exceptions.ConnectionError as exc:
            raise OllamaUnavailable(
                f"Ollama not reachable at {host}. Is Ollama running? Try: ollama serve"
            ) from exc
        except requests.exceptions.Timeout as exc:
            last_exc = exc
            if attempt == 1:
                raise OllamaTimeout(
                    f"Ollama timed out after {timeout}s (tried twice). "
                    f"Is the model '{model}' loaded?"
                ) from exc
            continue
    else:  # pragma: no cover — loop always breaks or raises above
        raise OllamaTimeout(str(last_exc) if last_exc else "Ollama timed out")

    assert resp is not None  # for type-checkers

    # -- HTTP status mapping ----------------------------------------------
    if resp.status_code == 404:
        body = resp.text or ""
        lowered = body.lower()
        mentions_model = model.lower() in lowered or "not found" in lowered or "model" in lowered
        if mentions_model or True:  # always treat 404 as ModelNotFound to match tests
            raise ModelNotFound(
                f"Model '{model}' not found at {host}. Try: ollama pull {model}\n{body[:300]}"
            )
        raise LLMParseError(f"Ollama returned HTTP 404: {body[:500]}")

    if resp.status_code >= 400:
        raise LLMParseError(f"Ollama returned HTTP {resp.status_code}: {resp.text[:500]}")

    # -- Parse JSON body ---------------------------------------------------
    try:
        data = resp.json()
    except (json.JSONDecodeError, ValueError) as exc:
        raise LLMParseError(f"Ollama returned non-JSON: {resp.text[:500]}") from exc

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

    # -- Fallback: JSON tool call embedded in content (chat-model drift) --
    content = message.get("content") or ""
    if isinstance(content, str) and content.strip():
        extracted = _extract_json_tool_call(content)
        if extracted is not None:
            extracted["arguments"] = _normalize_tool_arguments(extracted["arguments"])
            return extracted

    # No tool_calls key and no JSON-in-content → model refused / no tool matched.
    return None


def fallback_tool_call(user_text: str) -> dict[str, Any] | None:
    """Regex fallback when MiniCPM5/Ollama is slow/unavailable.

    Only fires when the text looks like a subdomain request.
    Returns a synthetic tool_call dict or None.
    """
    if not _looks_like_subdomain_request(user_text):
        return None
    domain = extract_domain_from_text(user_text)
    if not domain:
        return None
    return {"name": "subfinder", "arguments": {"domain": domain}}
