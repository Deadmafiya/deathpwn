# DeathPWN

> Natural-language bug bounty / pentest runner — describe the attack in English, watch it run.

```bash
deathpwn "find subdomains for https://example.com"
# → streams subdomains live + saves to ./example.com-subdomains.txt
```

Extensible by design — one file per tool via a registry. v0.1 ships one capability; the rest plug in the same way.

---

## What it does (v0.1)

One capability: **subdomain discovery via `subfinder`**, fronted by **FunctionGemma on Ollama**.

You type English. FunctionGemma emits a `subfinder` tool call. DeathPWN normalizes the domain and runs `subfinder` with a streaming tee — each subdomain prints as it arrives and is flushed to disk.

```
deathpwn "find subdomains for https://example.com"
# [*] Finding subdomains for example.com...
# admin.example.com
# api.example.com
# ...
# [+] Found 42 subdomains → ./example.com-subdomains.txt
```

No daemon, no state between runs. One-shot CLI.

---

## Prerequisites

| Requirement | Install |
|---|---|
| **Python 3.10+** | `python --version` |
| **Ollama** | https://ollama.com → `ollama serve` (keep running) |
| **FunctionGemma** | `ollama pull functiongemma:latest` (~268 MB) |
| **subfinder** | `sudo pacman -S subfinder` · or `go install -v github.com/projectdiscovery/subfinder/v2/cmd/subfinder@latest` |

Verify:

```bash
ollama list              # functiongemma:latest should appear
which subfinder          # should print a path
subfinder -d example.com -silent | head
```

---

## Install

```bash
git clone https://github.com/DeathPWN/deathpwn DeathPWN && cd DeathPWN
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
deathpwn --help
```

> `pip install -e .` is enough if you don't need tests. `.[dev]` adds `pytest`.

---

## Usage

### Basic

```bash
deathpwn "find subdomains for https://example.com"
deathpwn "enumerate subdomains of example.com"
```

### Without quotes

Positional args are joined with spaces — quotes are optional:

```bash
deathpwn find subdomains for example.com
```

### Custom output

```bash
deathpwn "find subs for example.com" -o out.txt
deathpwn "find subs for example.com" --output-dir ./results
# → ./results/example.com-subdomains.txt
```

### Thorough scan

```bash
deathpwn "find subs for example.com" --all
# passes -all to subfinder — more sources, slower
```

### Dry run & verbose

```bash
deathpwn "find subs for example.com" --dry-run
# [DRY-RUN] Would run: subfinder -d example.com -silent
# Output: /cwd/example.com-subdomains.txt

deathpwn "find subs for example.com" --verbose
# shows interpreted query, LLM tool call, normalized domain, and subfinder command

deathpwn "find subs for example.com" --dry-run --verbose
```

### Flags

| Flag | Description |
|---|---|
| `query` (positional) | Natural-language request — joined with spaces |
| `-o, --output <path>` | Output file path (default: `./<domain>-subdomains.txt`) |
| `--output-dir <dir>` | Output directory (`<dir>/<domain>-subdomains.txt`) |
| `--all` | Pass `-all` to subfinder (more thorough, slower) |
| `--json` | Accepted, not yet implemented in v0.1 — warns and writes txt only |
| `--dry-run` | Show what would run, do not execute |
| `--verbose, -v` | Verbose output (LLM call, normalized domain, command) |
| `--model <tag>` | Override Ollama model (default: `functiongemma:latest`) |
| `--version` | Show version |
| `-h, --help` | Show help + examples |

Exit codes: `0` success · `1` no results / no matching tool · `2` bad usage / bad domain · `3` tool failure · `4` Ollama/model error · `130` interrupted.

---

## How it works

3-step pipeline:

```
1. English ──► 2. FunctionGemma tool call ──► 3. subfinder streaming tee
                (Ollama /api/chat)              normalize → run → save
```

```
"find subdomains         POST {OLLAMA_HOST}/api/chat         normalize_domain()
 for https://             model: functiongemma:latest         strip https://, path,
   example.com"  ─────►   tools: [subfinder]  ─────►  {     port, case, whitespace
                         returns: {name:               domain: "example.com"}
                                   "subfinder",  ─────►  subfinder -d example.com -silent
                                   arguments:              │
                                     {domain:               ├──► stdout (live)
                                      "example.com"}}        └──► ./example.com-subdomains.txt
```

- **LLM layer** — `deathpwn/llm/client.py` POSTs raw English + `TOOL_DEFINITIONS` to Ollama (no prompt engineering, `stream: false`).
- **Normalize** — `deathpwn/utils/domain.py` handles FunctionGemma quirks (leading space), strips scheme/path/port, validates against strict regex.
- **Execute** — `deathpwn/tools/subfinder.py` `Popen`s subfinder, tees each line to stdout + file with `flush()`.

Adding a tool = one file in `deathpwn/tools/` with `@register("name")` + one schema entry in `deathpwn/llm/tools.py`. No changes to CLI or LLM client.

---

## Output

- **Default:** `./<domain>-subdomains.txt` in the current directory.
- **`-o / --output <path>`** — explicit file path. If `<path>` ends with `/` or is an existing directory, the default filename is appended: `deathpwn "find subs for example.com" -o /tmp/` → `/tmp/example.com-subdomains.txt`.
- **`--output-dir <dir>`** — directory for the default-named file: `deathpwn "find subs for example.com" --output-dir ./results` → `./results/example.com-subdomains.txt`.
- `~` is expanded, paths are resolved absolute. Parent directories are created automatically.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Ollama not reachable` / connection refused | `ollama serve` in another terminal; check `DEATHPWN_OLLAMA_HOST` (default `http://127.0.0.1:11434`) |
| `Model ... not found` | `ollama pull functiongemma:latest` · override with `--model` or `DEATHPWN_MODEL` |
| `Ollama timed out` | Model still loading — retry; bump `DEATHPWN_TIMEOUT` (default `30`) |
| `subfinder not found` | Install via `pacman` / `go install`; ensure `which subfinder` succeeds |
| `No subdomains found` | Try `--all`; run `subfinder -d <domain> -silent` directly to sanity-check |
| `No matching tool for that request` | Rephrase to include *find / enumerate / discover* + *subdomains* + domain — v0.1 only knows `subfinder` |
| `Could not extract valid domain` | Check spelling; scheme/path/port are stripped automatically, but the host must be a valid domain |
| `Unknown tool "..."` | LLM hallucinated a tool — registry guards it; rephrase and retry |

Env overrides: `DEATHPWN_OLLAMA_HOST`, `DEATHPWN_MODEL`, `DEATHPWN_TIMEOUT`.

---

## Roadmap

- **v0.1** — `subfinder` (this release)
- **Next** — `httpx`, `nuclei`, `naabu`, and chaining — each as one file per tool via `deathpwn/tools/registry.py`

---

## License

MIT
