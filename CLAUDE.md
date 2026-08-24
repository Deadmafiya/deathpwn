# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

DeathPWN — natural-language bug bounty / pentest runner. The hunter describes an attack in English; the tool translates it to a real tool call via MiniCPM5 on Ollama and streams results live. v0.1 ships one capability: **subdomain discovery via `subfinder` (BlackArch)**. Extensible by design — one file per tool via a registry, one schema entry in `deathpwn/llm/tools.py`.

No daemon, no state between runs. One-shot CLI: `deathpwn "find subdomains for https://example.com"` → streams subdomains live + saves to `./<domain>-subdomains.txt`.

## Commands

All from the repo root (`/home/poteto/Projects/DeathPWN`):

```bash
./install.sh                         # one-shot: Ollama + model + venv + ~/.local/bin/deathpwn  (also: --yes / --help)
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"              # manual alternative — or pip install -e . (no tests)
deathpwn --help                      # also: python -m deathpwn --help
deathpwn "find subdomains for https://example.com"          # basic
deathpwn "find subdomains for https://example.com" --dry-run  # preview
deathpwn "find subdomains for https://example.com" --verbose  # LLM + normalize trace
deathpwn "find subs for example.com" -o out.txt              # custom file
deathpwn "find subs for example.com" --output-dir ./results  # dir → ./results/<domain>-subdomains.txt
deathpwn "find subs for example.com" --all                   # subfinder -all (slower, more thorough)

# Tests — must run from the repo root, via the venv
.venv/bin/python -m pytest -q        # 72 tests (bare `pytest` or `python -m pytest` with no path finds 0)
.venv/bin/python -m pytest tests/test_domain.py -q   # single file
```

Env overrides (also CLI flags): `DEATHPWN_OLLAMA_HOST` (default `http://127.0.0.1:11434`), `DEATHPWN_MODEL` (`openbmb/minicpm5:latest`), `DEATHPWN_TIMEOUT` (12s). Flag `--model` overrides `DEATHPWN_MODEL`.

Prerequisites (not installed by pip): Python 3.10+, Ollama (`ollama serve` + `ollama pull openbmb/minicpm5:latest (~688 MB)), `subfinder` (`pacman -S subfinder` or `go install .../subfinder/v2/...`).

Global command: symlink at `~/.local/bin/deathpwn` → `.venv/bin/deathpwn` (PATH already includes `~/.local/bin`; Arch PEP 668 blocks system pip install, hence the symlink).

## Architecture

```
English ──► MiniCPM5 tool call (Ollama /api/chat) ──► normalize → subfinder streaming tee → save
```

- **`deathpwn/cli.py`** — entry point (`deathpwn.cli:main`, also `deathpwn/__main__.py` for `python -m deathpwn`). Argparse with `query` as `nargs="*"` (joined with spaces, quotes optional), flags `-o/--output`, `--output-dir`, `--all`, `--json` (accepted, warns, txt-only in v0.1), `--dry-run`, `--verbose/-v`, `--model`, `--version`. Calls `call_llm()` with fallback on `OllamaTimeout`/`OllamaUnavailable`/`LLMParseError` → `fallback_tool_call()`, applies hallucination guard (`_looks_like_subdomain_request`), normalizes/validates domain, resolves output path, dispatches via `TOOL_REGISTRY`.
- **`deathpwn/llm/client.py`** — only place that talks to Ollama. POSTs `TOOL_DEFINITIONS` + raw English to `{OLLAMA_HOST}/api/chat` with `stream: false`, handles both `arguments` shapes (dict or JSON string) and the MiniCPM5/FunctionGemma leading-space quirk (`str.strip()` on string args only — no further normalization). Maps errors to `OllamaUnavailable`/`OllamaTimeout` (retried once)/`ModelNotFound`/`LLMParseError`. Exports `fallback_tool_call()` — regex fallback gated on subdomain hint.
- **`deathpwn/llm/tools.py`** — single source of truth for `TOOL_DEFINITIONS` (currently one entry: `subfinder` with `domain` + optional `all_sources`). `TOOL_NAMES` mirrors it.
- **`deathpwn/tools/registry.py`** — `TOOL_REGISTRY: dict` + `@register(name)` decorator. Adding a tool = one file in `deathpwn/tools/` with `@register` + one schema in `tools.py`. No CLI/LLM changes.
- **`deathpwn/tools/subfinder.py`** — `@register("subfinder") def run_subfinder(domain, *, output: Path, ...)`. Checks `shutil.which`, builds `[subfinder, -d, domain, -silent, (-all)]`, `Popen(stdout=PIPE, text=True, bufsize=1)` and tees each line to stdout + file with `flush()`. Handles zero results, `KeyboardInterrupt` (terminate → kill after 3s), and `ToolNotFound`/`ToolExecutionError`.
- **`deathpwn/utils/domain.py`** — `normalize_domain()` (strip/lower, strip `http(s)://`, split `/` `:` `?` `#`, rstrip `.`), `validate_domain()` (anchored regex `^[a-z0-9]([a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}$`, no `..`, per-label hyphen/length checks), `extract_domain_from_text()` (URL first, then bare token), `_looks_like_subdomain_request()` (hint regex `sub\s*domains?|\bsubs\b|subfinder`).
- **`deathpwn/utils/output.py`** — `resolve_output_path(domain, output, output_dir)` priority `output` > `output_dir` > cwd, handles `~`, trailing `/` or existing dir, always returns absolute Path; `ensure_parent_exists()`.
- **`deathpwn/config.py`** — defaults overridable via env (`OLLAMA_HOST`, `MODEL`, `OLLAMA_TIMEOUT=12`, `SUBFINDER_BIN=shutil.which(...)`).

## Key invariants

- **Tool calls are JSON, not exit codes** — `call_llm` returns `{"name","arguments"}` or `None`; callers must handle `None` as "no matching tool."
- **Fallback only on subdomain hint** — `fallback_tool_call` and hallucination guard both gate on `_SUBDOMAIN_HINT_RE`; `scan ports on example.com` must never trigger subfinder, even if Ollama hallucinates or times out.
- **Leading-space quirk** — FunctionGemma often returns `" example.com"`; `client.py` does `strip()` on string args, `domain.py` also handles it via `normalize_domain(raw.strip().lower())`.
- **Timeout is 12s + one retry** — URL prompts (e.g. `https://example.com`) are slow on chat model; fallback keeps the exact user example working without waiting 60s.
- **`pyproject.toml` is PEP 621 / hatchling**, `requires-python >=3.10`, single dep `requests`, entry point `deathpwn=deathpwn.cli:main`, `tool.pytest.ini_options.testpaths=["tests"]` (so run from repo root).
- **`.gitignore` ignores** `.venv/`, `__pycache__/`, `*.egg-info/`, `dist/`, `build/`, `results/`, `*-subdomains.txt`, `.pytest_cache/` — result files don't get committed.
