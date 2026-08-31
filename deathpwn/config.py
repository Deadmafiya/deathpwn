"""DeathPWN configuration — defaults overridable via .env / env / flags.

Resolution order (highest wins):
  1. Real env vars already set in the shell (and --model flag at runtime)
  2. .env file in the repo (DeathPWN/.env) — loaded with override=False
  3. Hard defaults below

The .env file provides: base URL (host), API key, model name.
For local Ollama the API key stays empty (no Authorization header sent).
For remote providers set DEATHPWN_API_KEY to a real token.

Aliases are also read so a single .env can service other tools:
  DEATHPWN_OLLAMA_HOST <- also BASE_URL / DEATHPWN_BASE_URL
  DEATHPWN_API_KEY     <- also API_KEY / DEATHPWN_API_TOKEN
  DEATHPWN_MODEL       <- also MODEL_NAME / DEATHPWN_MODEL_NAME
"""
import os
import shutil
from pathlib import Path


def _load_dotenv() -> None:
    """Load .env from repo or DEATHPWN_ENV_FILE, without overwriting existing env.

    Zero-dep: parses KEY=VALUE lines in stdlib only. If python-dotenv is
    installed it is preferred, but not required. Quotes, 'export ' prefix,
    inline comments (unquoted #), and empty lines are handled.
    """
    # Let an explicit DEATHPWN_ENV_FILE override the path
    env_file = os.environ.get("DEATHPWN_ENV_FILE")
    if env_file:
        p = Path(env_file).expanduser()
    else:
        # Default: DeathPWN/.env next to this file's repo (deathpwn/config.py -> DeathPWN/)
        try:
            p = Path(__file__).resolve().parents[1] / ".env"
        except Exception:
            # Fallback: CWD
            p = Path.cwd() / ".env"

    if not p.is_file():
        return

    # Prefer python-dotenv when available (handles edge cases best)
    try:
        import dotenv  # type: ignore

        dotenv.load_dotenv(p, override=False)
        return
    except Exception:
        pass

    # Stdlib fallback
    try:
        for raw in p.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export ") :].lstrip()
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip()
            if not k or k in os.environ:
                continue  # real env wins (override=False)
            # Strip surrounding quotes (single or double), handle escaped chars minimally
            if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
                v = v[1:-1]
            else:
                # Unquoted: strip trailing inline comment (space + #)
                # Only when # is preceded by space so values like https://...#frag keep #
                if " #" in v:
                    v = v.split(" #", 1)[0].rstrip()
            # Expand ~ not needed for host/key/model, but handle $VAR references lightly
            os.environ[k] = v
    except Exception:
        return


_load_dotenv()

# --- Aliases: let BASE_URL / API_KEY / MODEL_NAME also populate the DEATHPWN_* vars ---
# (only when the canonical DEATHPWN_* is not already set)
if not os.environ.get("DEATHPWN_OLLAMA_HOST"):
    for alias in ("DEATHPWN_BASE_URL", "BASE_URL"):
        if os.environ.get(alias):
            os.environ["DEATHPWN_OLLAMA_HOST"] = os.environ[alias].strip()
            break

if not os.environ.get("DEATHPWN_API_KEY"):
    for alias in ("DEATHPWN_API_TOKEN", "API_KEY"):
        if os.environ.get(alias):
            os.environ["DEATHPWN_API_KEY"] = os.environ[alias].strip()
            break

if not os.environ.get("DEATHPWN_MODEL"):
    for alias in ("DEATHPWN_MODEL_NAME", "MODEL_NAME"):
        if os.environ.get(alias):
            os.environ["DEATHPWN_MODEL"] = os.environ[alias].strip()
            break

OLLAMA_HOST: str = os.environ.get("DEATHPWN_OLLAMA_HOST", "http://127.0.0.1:11434")
MODEL: str = os.environ.get("DEATHPWN_MODEL", "openbmb/minicpm5:latest")
# Empty string means local Ollama — no Authorization header is sent.
# For remote OpenAI-compatible APIs (e.g. https://integrate.api.nvidia.com/v1)
# set DEATHPWN_API_KEY to a real token; client then hits /v1/chat/completions.
API_KEY: str = os.environ.get("DEATHPWN_API_KEY", "").strip()
OLLAMA_TIMEOUT: int = int(os.environ.get("DEATHPWN_TIMEOUT", "12"))
OLLAMA_KEEP_ALIVE: str = os.environ.get("DEATHPWN_KEEP_ALIVE", "30m")
OLLAMA_NUM_PREDICT: int = int(os.environ.get("DEATHPWN_NUM_PREDICT", "128"))
# MiniCPM5 is a thinking chat model — Ollama exposes `think` per-request.
# Default false: clean tool_calls in ~3s; true burns 400 tokens/8-28s for same result.
# Env truthy values ("1"/"true"/"yes"/"on") re-enable thinking.
OLLAMA_THINK: bool = os.environ.get("DEATHPWN_THINK", "false").lower() in ("1", "true", "yes", "on")
SUBFINDER_BIN: str = shutil.which("subfinder") or "subfinder"
DIRB_BIN: str = shutil.which("dirb") or "dirb"

# System prompt for the chat model (env override → default).
# Routes subfinder vs dirb + teaches bare-host extraction + typo tolerance.
# Validated live with MiniCPM5 non-thinking: 10/10 probes (dirb+subfinder+negatives), scan ports correctly refused.
SYSTEM_PROMPT: str = os.environ.get(
    "DEATHPWN_SYSTEM_PROMPT",
    (
        "You are DeathPWN, a bug bounty assistant. You have two tools: "
        "1) subfinder(domain: string, all_sources?: boolean) — passively discovers "
        "subdomains for a target domain. "
        "2) dirb(target: string) — bruteforces directories/files on a website. "
        "The user may give a bare domain (example.com), a URL (https://example.com/path), "
        "or a host with port (example.com:8080). For BOTH tools, always extract the bare "
        "hostname: lowercase, no scheme, path, port, query, or fragment — e.g. "
        "https://Example.COM/path -> example.com. "
        "Use subfinder when user wants subdomains (keywords: subdomain, subdomains, subs, "
        "subfinder — typos like subomains ok). Use dirb when user wants directory "
        "bruteforce (keywords: dirb, directory bruteforce/brute force, directory scan, "
        "directory enumeration, discover directories, bruteforce directories). "
        "For port scanning (keywords: scan ports, nmap, port scan), HTTP probing (httpx), "
        "nuclei, or greetings like hello — do NOT call any tool; respond that you cannot do that."
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
