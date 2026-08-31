# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

DeathPWN — natural-language bug bounty runner. The hunter types English; MiniCPM5 on Ollama translates it to a tool call and streams results live. Two capabilities: **subdomain discovery via `subfinder`** and **directory bruteforce via `dirb` (`dirb https://<host>`)**. Extensible by design — one file per tool via a registry + one schema entry in `deathpwn/llm/tools.py`. MiniCPM5 is a chat/thinking model, so all prompt/tool management lives in code and runs **non-thinking** by default (`think:false`, `num_predict:128`, `temperature:0`, `keep_alive:30m`).

No daemon, no state between runs. One-shot CLI: `deathpwn "find subdomains for https://example.com"` → streams live + saves to `ctf-flagboard/output/<domain>-subdomains.txt`; `deathpwn "start directory bruteforce on example.com"` → `dirb https://example.com` → `…-dirb.txt`. `https://` for dirb is built by the CLI from a bare host — never by the model.

## Commands

All from the repo root (`/home/poteto/Projects/DeathPWN`):

```bash
./install.sh                         # one-shot: Ollama + model + venv + ~/.local/bin/deathpwn
./install.sh --yes                   # non-interactive (also: --help, --dev, --skip-ollama/--skip-model/--skip-subfinder, --no-venv)
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"              # manual alternative — or pip install -e . (no tests)
deathpwn --help                      # also: python -m deathpwn --help
deathpwn "find subdomains for https://example.com" --dry-run          # preview, no execution
deathpwn "find subdomains for https://example.com" --verbose          # LLM + normalize trace
deathpwn "start directory bruteforce on example.com" --dry-run        # -> dirb https://example.com
deathpwn "find subs for example.com" -o out.txt                       # custom file
deathpwn "find subs for example.com" --output-dir ./results           # dir -> ./results/<domain>-subdomains.txt
deathpwn "find subs for example.com" --all                            # subfinder -all (slower, more thorough)

# Tests — must run from repo root, via the venv
.venv/bin/python -m pytest -q                            # 72 tests (bare `pytest` with no path finds 0 — use .venv)
.venv/bin/python -m pytest tests/test_domain.py -q       # single file
```

Config: `deathpwn/config.py` loads `.env` (repo root, `DEATHPWN_ENV_FILE` override) with `override=false` (shell env wins), zero-dep parser (uses `python-dotenv` when installed). Vars: `DEATHPWN_OLLAMA_HOST`/`BASE_URL`/`DEATHPWN_BASE_URL` → base URL (default `http://127.0.0.1:11434`), `DEATHPWN_API_KEY`/`API_KEY`/`DEATHPWN_API_TOKEN` → Bearer token (default `""` — local Ollama, no header), `DEATHPWN_MODEL`/`MODEL_NAME` → model (default `openbmb/minicpm5:latest`). `.env` is gitignored; committed template is `.env.example`.

Env overrides (also CLI flags): `DEATHPWN_OLLAMA_HOST` (default `http://127.0.0.1:11434`), `DEATHPWN_API_KEY` (default `""` — empty = local, no `Authorization` header), `DEATHPWN_MODEL` (`openbmb/minicpm5:latest`), `DEATHPWN_TIMEOUT` (12s), `DEATHPWN_THINK` (`false` — set `1`/`true` to re-enable thinking), `DEATHPWN_SYSTEM_PROMPT`, `DEATHPWN_OUTPUT_DIR`, `DEATHPWN_FLAGBOARD_ROOT`. Flag `--model` overrides `DEATHPWN_MODEL`.

Prerequisites (not installed by pip): Python 3.10+, Ollama (`ollama serve` + `ollama pull openbmb/minicpm5:latest` ~688 MB), `subfinder` (`pacman -S subfinder` or `go install …/subfinder/v2/…`), `dirb` (`pacman -S dirb` or `apt install -y dirb`).

Global command: symlink at `~/.local/bin/deathpwn` → `.venv/bin/deathpwn` (PATH already includes `~/.local/bin`; Arch PEP 668 blocks system pip install, hence the symlink).

Linked resource: `DeathPWN/output` is a symlink to `../ctf-flagboard/output` — both repos share one output dir. Flagboard's `ctf-flagboard/lib/functiongemma.js` is the JS mirror of the Python LLM stack (same `openbmb/minicpm5:latest`, `think:false`, `num_predict:128`, `SYSTEM_PROMPT`).

## Architecture

```
English ──► MiniCPM5 tool call (Ollama /api/chat) ──► normalize → streaming tee → save
                                              think:false, 128, system prompt
```

- **`deathpwn/cli.py`** — entry point (`deathpwn.cli:main`, also `deathpwn/__main__.py` for `python -m deathpwn`). Argparse with `query` as `nargs="*"` (joined with spaces, quotes optional), flags `-o/--output`, `--output-dir`, `--all`, `--json` (accepted, warns, txt-only), `--dry-run`, `--verbose/-v`, `--model`, `--version`. Calls `call_llm()` with fallback on `OllamaTimeout`/`OllamaUnavailable`/`LLMParseError` → `fallback_tool_call()`, applies hallucination guard (`_looks_like_any_tool_request` — covers subdomains + dirb with typo-tolerant fuzzy match), handles `tool_call is None` with a second fallback retry, then dispatches per-tool: `subfinder` (extract/validate `domain` → `resolve_output_path(…)` with `suffix="-subdomains.txt"`) vs `dirb` (extract/validate bare host as `target` → CLI builds `https://` → `suffix="-dirb.txt"`). Dry-run previews without executing; otherwise prints Rich header and calls the registered runner.

- **`deathpwn/llm/client.py`** — only place that talks to Ollama. POSTs `TOOL_DEFINITIONS` + managed `SYSTEM_PROMPT` to `{OLLAMA_HOST}/api/chat` with `stream:false`, `think` (from `config.OLLAMA_THINK`), `keep_alive:30m`, `options:{temperature:0, num_predict:128}`. Handles both `arguments` shapes (dict or JSON string) and the leading-space quirk (`str.strip()` on string args). Normalizes URL-as-host if the model slips `https://…` as `domain`/`target`. Also parses JSON-in-`content` fallback when the chat model drifts and emits `{"name":…,"arguments":…}` in content instead of `tool_calls`. Maps errors to `OllamaUnavailable`/`OllamaTimeout` (retried once)/`ModelNotFound`/`LLMParseError`. Exports `fallback_tool_call()` — regex fallback gated on tool intent, dirb-prioritized when both hints match.

- **`deathpwn/llm/tools.py`** — single source of truth for `TOOL_DEFINITIONS` (two entries: `subfinder` with `domain` + optional `all_sources`; `dirb` with `target` bare host — descriptions are strict with `ONLY`/`NEVER` and URL→bare-host instructions to keep MiniCPM5 from misrouting). `TOOL_NAMES` mirrors it.

- **`deathpwn/tools/registry.py`** — `TOOL_REGISTRY: dict` + `@register(name)` decorator. Adding a tool = one file in `deathpwn/tools/` with `@register` + one schema in `tools.py`. No CLI/LLM changes.

- **`deathpwn/tools/subfinder.py` / `deathpwn/tools/dirb.py`** — `@register("subfinder") def run_subfinder(domain, *, output: Path, …)` and `@register("dirb") def run_dirb(target, *, output: Path, …)`. Each checks `shutil.which`, builds its command (`subfinder -d <domain> -silent [-all]` vs `dirb https://<host>` — for dirb the URL is built in `dirb.py:_target_to_url` and again in `cli.py` for dry-run, always forced to `https`), `Popen(stdout=PIPE, text=True, bufsize=1)` and tees. Subfinder uses a Rich `Live` table in TTY; dirb streams raw lines and counts hits (`+ https://…`/`==> DIRECTORY:`). Both handle zero results, `KeyboardInterrupt` (terminate → kill after 3s), and `ToolNotFound`/`ToolExecutionError`.

- **`deathpwn/utils/domain.py`** — `normalize_domain()` (strip/lower, strip `http(s)://`, split `/` `:` `?` `#`, rstrip `.`), `validate_domain()` (anchored regex `^[a-z0-9]([a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}$`, no `..`, per-label hyphen/length checks), `extract_domain_from_text()` (URL first, then bare token), `_looks_like_subdomain_request()` / `_looks_like_dirb_request()` / `_looks_like_any_tool_request()` (hint regexes `sub\s*domains?|\bsubs\b|subfinder` and `dir\s*b\b|directory\s+(?:brute…)`, plus fuzzy Levenshtein for typo tolerance on subdomain keywords so `subomains` still routes).

- **`deathpwn/utils/output.py`** — `resolve_output_path(domain, output, output_dir, *, suffix="-subdomains.txt")` priority `output` > `output_dir` > `DEFAULT_OUTPUT_DIR` (which is `ctf-flagboard/output`), handles `~`, trailing `/` or existing dir, always returns absolute `Path`; `ensure_parent_exists()`.

- **`deathpwn/config.py`** — defaults overridable via env (`OLLAMA_HOST`, `MODEL` → `openbmb/minicpm5:latest`, `OLLAMA_TIMEOUT=12`, `OLLAMA_KEEP_ALIVE=30m`, `OLLAMA_NUM_PREDICT=128`, `OLLAMA_THINK=false`, `SYSTEM_PROMPT` that routes subfinder vs dirb and teaches bare-host extraction + `scan ports`/`hello` refusal, `SUBFINDER_BIN`/`DIRB_BIN` via `shutil.which`, `FLAGBOARD_ROOT`/`DEFAULT_OUTPUT_DIR`). The `SYSTEM_PROMPT` and `RECON_TOOLS` are kept in lockstep with `ctf-flagboard/lib/functiongemma.js`.

## Key invariants

- **Tool calls are JSON, not exit codes** — `call_llm` returns `{"name","arguments"}` or `None`; callers must handle `None` as "no matching tool" (retry fallback once before showing the hint).
- **`https://` for dirb is CLI-owned** — the model must return a bare host (`target` = `example.com`); `dirb.py`/`cli.py` builds `https://<host>` deterministically. Never let the model emit a full URL as `target`.
- **Hallucination guard gates on any-tool hint** — `fallback_tool_call` and the guard gate on `_looks_like_any_tool_request`; `scan ports on example.com` must never trigger subfinder/dirb, even if Ollama hallucinates or times out. The `None` → fallback path is the safety net when MiniCPM5 returns no `tool_calls` (e.g., dirb URL edge case).
- **Non-thinking by default** — `think:false` is explicit in the request (Ollama defaults to thinking when omitted on this model); `num_predict:128` is the safe minimum (32 truncates MiniCPM5). Re-enable with `DEATHPWN_THINK=1`.
- **Leading-space quirk** — MiniCPM5 may return `" example.com"`; `client.py` does `strip()` on string args, `domain.py` also handles it via `normalize_domain(raw.strip().lower())`.
- **Output suffix is tool-specific** — subfinder → `-subdomains.txt`, dirb → `-dirb.txt` via the `suffix` param; both share `ctf-flagboard/output`.
- **`pyproject.toml` is PEP 621 / hatchling**, `requires-python >=3.10`, deps `requests` + `rich`, entry point `deathpwn=deathpwn.cli:main`, `tool.pytest.ini_options.testpaths=["tests"]` (so run from repo root).
- **`.gitignore` ignores** `.venv/`, `__pycache__/`, `*.egg-info/`, `dist/`, `build/`, `results/`, `output/` (covers the `output` symlink), `*-subdomains.txt`, `*-dirb.txt`, `.pytest_cache/` — result files don't get committed.
