"""DeathPWN configuration — defaults overridable via env / flags."""
import os
import shutil
from pathlib import Path

OLLAMA_HOST: str = os.environ.get("DEATHPWN_OLLAMA_HOST", "http://127.0.0.1:11434")
MODEL: str = os.environ.get("DEATHPWN_MODEL", "openbmb/minicpm5:latest")
OLLAMA_TIMEOUT: int = int(os.environ.get("DEATHPWN_TIMEOUT", "12"))
OLLAMA_KEEP_ALIVE: str = os.environ.get("DEATHPWN_KEEP_ALIVE", "30m")
OLLAMA_NUM_PREDICT: int = int(os.environ.get("DEATHPWN_NUM_PREDICT", "128"))
# MiniCPM5 is a thinking chat model — Ollama exposes `think` per-request.
# Default false: clean tool_calls in ~3s; true burns 400 tokens/8-28s for same result.
# Env truthy values ("1"/"true"/"yes"/"on") re-enable thinking.
OLLAMA_THINK: bool = os.environ.get("DEATHPWN_THINK", "false").lower() in ("1", "true", "yes", "on")
SUBFINDER_BIN: str = shutil.which("subfinder") or "subfinder"

# System prompt for the chat model (env override → default).
# Teaches URL→bare-host extraction + typo tolerance (subomains ok) +
# explicit refusal for port/http/nuclei/httpx so MiniCPM5 does not hallucinate
# a subfinder call on non-subdomain intent (validated live: 6/6 with candidate).
SYSTEM_PROMPT: str = os.environ.get(
    "DEATHPWN_SYSTEM_PROMPT",
    (
        "You are DeathPWN, a bug bounty assistant. You have one tool: "
        "subfinder(domain: string, all_sources?: boolean) — passively discovers "
        "subdomains for a target domain. The user may give a bare domain "
        "(example.com), a URL (https://example.com/path?x=1), or a host with "
        "port (example.com:8080). Always extract the bare hostname: lowercase, "
        "no scheme, path, port, query, or fragment — e.g. https://Example.COM/path -> example.com. "
        "Call subfinder ONLY when the user explicitly wants to find, enumerate, "
        "or discover subdomains (keywords: subdomain, subdomains, subs, subfinder "
        "— typos like subomains are ok). For port scanning (scan ports, nmap), "
        "HTTP probing (httpx), nuclei, directory brute-force, or greetings like "
        "hello, do NOT call a tool — respond that you lack that capability."
    ),
)

# --- Linked resource: ctf-flagboard project folder ---
# deathpwn takes its default resources (output dir, shared model tuning)
# from the ctf-flagboard project so both repos share one source of truth.
# Linked with: ctf-flagboard/lib/functiongemma.js (same openbmb/minicpm5:latest,
# keep_alive 30m, num_predict 128, think false) and ctf-flagboard/output/
def _flagboard_root() -> Path:
    # Env override first (explicit)
    env = os.environ.get("DEATHPWN_FLAGBOARD_ROOT") or os.environ.get("FLAGBOARD_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    # Sibling heuristic: DeathPWN and ctf-flagboard are siblings under ~/Projects
    # deathpwn/config.py -> deathpwn/ -> DeathPWN/ -> Projects/ -> ctf-flagboard/
    here = Path(__file__).resolve()
    candidate = here.parents[2] / "ctf-flagboard"
    if candidate.is_dir():
        return candidate
    # Fallback: env-less run from unknown location — use CWD's ctf-flagboard if present
    cwd_candidate = Path.cwd() / "ctf-flagboard"
    if cwd_candidate.is_dir():
        return cwd_candidate.resolve()
    return candidate.resolve()  # absolute path even if missing (caller handles creation)

FLAGBOARD_ROOT: Path = _flagboard_root()
DEFAULT_OUTPUT_DIR: Path = Path(
    os.environ.get("DEATHPWN_OUTPUT_DIR", str(FLAGBOARD_ROOT / "output"))
).expanduser().resolve()
