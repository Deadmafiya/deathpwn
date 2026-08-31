"""Domain normalization and validation utilities.

Handles quirks from LLM-extracted domains (leading whitespace from
MiniCPM5/FunctionGemma, mixed case, scheme/path/port/query/fragment) and
provides strict validation before passing to subfinder.
"""

from __future__ import annotations

import re

_DOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}$")


def normalize_domain(raw: str) -> str:
    """Normalize a raw domain string to a bare lowercase hostname.

    Steps (in order):
    1. Strip surrounding whitespace and lowercase.
    2. Strip leading ``http://`` or ``https://`` (case-insensitive via
       lowercasing first).
    3. Strip path (``/``), query (``?``), fragment (``#``), and port
       (``:``) components.
    4. Strip any trailing ``.`` (FQDN dot).

    Args:
        raw: Raw domain string, possibly containing scheme, path,
            port, query, fragment, mixed case, or surrounding
            whitespace. e.g. ``" https://Example.COM/path "`` or
            ``" example.com "`` (leading-space quirk from MiniCPM5/FunctionGemma)
            or ``"example.com:8080"``.

    Returns:
        Normalized bare domain (e.g. ``"example.com"``). Returns ``""``
        if the input is empty/whitespace-only.
    """
    s = raw.strip().lower()
    if not s:
        return ""

    # Strip scheme — only http/https; lowercasing already applied.
    if s.startswith("https://"):
        s = s[len("https://"):]
    elif s.startswith("http://"):
        s = s[len("http://"):]

    # Strip path, then port, then query/fragment. Order matches spec:
    # path → port → query/fragment. Splitting on '/' first removes
    # everything after the host; subsequent splits handle the
    # no-path cases like "example.com:8080?x=1#y".
    s = s.split("/")[0]
    s = s.split(":")[0]
    # Query and fragment could still remain if port was absent;
    # splitting again is harmless and keeps implementation simple.
    s = s.split("?")[0].split("#")[0]

    # Strip trailing dot(s) — FQDN style "example.com." → "example.com".
    # Also strips surrounding whitespace that could reappear (defensive).
    s = s.strip().rstrip(".")

    return s


_URL_RE = re.compile(r"https?://([a-z0-9.-]+\.[a-z]{2,})", re.I)
_DOMAIN_TOKEN_RE = re.compile(r"\b([a-z0-9]([a-z0-9.-]*[a-z0-9])?\.[a-z]{2,})\b", re.I)
_SUBDOMAIN_HINT_RE = re.compile(r"sub\s*domains?|\bsubs\b|subfinder", re.I)
_DIRB_HINT_RE = re.compile(
    r"dir\s*b\b|directory\s+(?:brute\s*force|bruteforce|brute|enum|scan|discover)",
    re.I,
)


def _lev(a: str, b: str) -> int:
    """Levenshtein distance (iterative, no deps) — for fuzzy hint matching."""
    if a == b:
        return 0
    n, m = len(a), len(b)
    if n == 0:
        return m
    if m == 0:
        return n
    prev = list(range(m + 1))
    cur = [0] * (m + 1)
    for i in range(1, n + 1):
        cur[0] = i
        ca = a[i - 1]
        for j in range(1, m + 1):
            cost = 0 if ca == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev, cur = cur, prev
    return prev[m]


def extract_domain_from_text(text: str) -> str | None:
    """Fallback: extract a domain from raw text without hitting the LLM.

    Looks for https:// URLs first, then bare domain tokens.
    Returns the first match normalized, or None.
    """
    m = _URL_RE.search(text)
    if m:
        return normalize_domain(m.group(1))
    m2 = _DOMAIN_TOKEN_RE.search(text)
    if m2:
        return normalize_domain(m2.group(1))
    return None


def _looks_like_subdomain_request(text: str) -> bool:
    """Return True if text mentions subdomains/subs (fuzzy, typo-tolerant).

    Fast path: exact regex (covers ``sub domains``, ``subs``, ``subfinder``).
    Slow path: fuzzy word-level Levenshtein against ``subdomain``/``subdomains``/
    ``subfinder``/``subs`` so typos like ``subomains`` or ``subdoamins`` still
    route to subfinder instead of the misleading ``No matching tool`` hint.

    Negatives like ``scan ports`` or ``hello`` stay False — distance to any
    target word is > threshold (ports↔subs = 4, hello↔subdomain = 7+).
    """
    if _SUBDOMAIN_HINT_RE.search(text):
        return True
    # Fuzzy fallback — tolerates 1-2 char typos that MiniCPM5 already handles
    # at the LLM level but the exact regex would block at the hallucination guard.
    words = re.findall(r"[a-z]+", text.lower())
    for w in words:
        # Skip tiny noise words — avoids false positives on "is"/"in"/"a"
        if len(w) < 3:
            continue
        if _lev(w, "subdomain") <= 2:
            return True
        if _lev(w, "subdomains") <= 2:
            return True
        if _lev(w, "subfinder") <= 2:
            return True
        if _lev(w, "subs") <= 1:
            return True
    return False


def _looks_like_dirb_request(text: str) -> bool:
    """Return True if text mentions directory bruteforce (dirb)."""
    if _DIRB_HINT_RE.search(text):
        return True
    low = text.lower()
    # Phrase with any spacing/punctuation between words
    if "directory" in low and "brute" in low:
        return True
    return False


def _looks_like_any_tool_request(text: str) -> bool:
    """True if the English looks like any supported tool intent."""
    return _looks_like_subdomain_request(text) or _looks_like_dirb_request(text)


def validate_domain(domain: str) -> bool:
    """Validate a normalized domain string.

    Checks:
    * Total length <= 253 characters and non-empty.
    * No consecutive dots (``".."``).
    * Matches anchored regex ``^[a-z0-9]([a-z0-9.-]*[a-z0-9])?\\.[a-z]{2,}$``.
    * No label starts or ends with ``-`` and no empty label.
    * (Extra) Each label <= 63 characters.

    The regex enforces: starts with alphanumeric, ends with
    alphanumeric before the final dot, TLD is at least 2 lowercase
    letters, and only ``a-z``, ``0-9``, ``.``, ``-`` appear.

    Args:
        domain: Normalized domain from :func:`normalize_domain`
            (expected lowercase, no scheme/path/port).

    Returns:
        True if the domain passes all checks, False otherwise.
    """
    if not domain or len(domain) > 253:
        return False

    if ".." in domain:
        return False

    if not _DOMAIN_RE.match(domain):
        return False

    for label in domain.split("."):
        if not label or label.startswith("-") or label.endswith("-"):
            return False
        if len(label) > 63:
            return False

    return True
