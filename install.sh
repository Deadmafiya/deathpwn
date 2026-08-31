#!/usr/bin/env bash
# install.sh — DeathPWN one-shot installer
# Checks/installs: Ollama, current model (openbmb/minicpm5:latest), venv + deathpwn command.
# Portable: no hardcoded /home paths — resolves repo dir dynamically, works from any cwd on any Linux.
#
# Usage:
#   ./install.sh              # interactive, installs what is missing
#   ./install.sh --yes        # non-interactive (auto-yes where prompted)
#   ./install.sh --help
#
# Flags:
#   --yes / -y          assume yes (skip confirmations)
#   --skip-ollama       do not install/start Ollama
#   --skip-model        do not pull model
#   --skip-subfinder    do not check/install subfinder
#   --dev               pip install -e ".[dev]" (includes pytest)
#   --no-venv           reuse system python / skip venv (not recommended)
#   --help / -h

set -euo pipefail

# ── args ─────────────────────────────────────────────────────────────────────
ASSUME_YES=0
SKIP_OLLAMA=0
SKIP_MODEL=0
SKIP_SUBFINDER=0
WITH_DEV=0
NO_VENV=0

for arg in "$@"; do
  case "$arg" in
    --yes|-y) ASSUME_YES=1 ;;
    --skip-ollama) SKIP_OLLAMA=1 ;;
    --skip-model) SKIP_MODEL=1 ;;
    --skip-subfinder) SKIP_SUBFINDER=1 ;;
    --dev) WITH_DEV=1 ;;
    --no-venv) NO_VENV=1 ;;
    --help|-h)
      cat <<'USAGE'
install.sh — DeathPWN one-shot installer
  Checks/installs: Ollama, model (from deathpwn/config.py), venv + deathpwn command.
  Portable: resolves repo dir dynamically, works from any cwd on any Linux.

Usage:
  ./install.sh              # interactive
  ./install.sh --yes        # non-interactive
  ./install.sh --help

Flags:
  --yes / -y          assume yes (skip confirmations)
  --skip-ollama       do not install/start Ollama
  --skip-model        do not pull model
  --skip-subfinder    do not check/install subfinder
  --dev               pip install -e ".[dev]" (includes pytest)
  --no-venv           reuse system python / skip venv (not recommended)
  --help / -h
USAGE
      exit 0
      ;;
    *) echo "Unknown flag: $arg  (try --help)" >&2; exit 2 ;;
  esac
done

# ── pretty ───────────────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
  GREEN=$'\033[1;32m'; CYAN=$'\033[36m'; YELLOW=$'\033[1;33m'; RED=$'\033[1;31m'; DIM=$'\033[2m'; RST=$'\033[0m'
else
  GREEN=""; CYAN=""; YELLOW=""; RED=""; DIM=""; RST=""
fi
info()  { printf "${CYAN}▸ %s${RST}\n" "$*"; }
ok()    { printf "${GREEN}✓ %s${RST}\n" "$*"; }
warn()  { printf "${YELLOW}⚠ %s${RST}\n" "$*"; }
err()   { printf "${RED}✗ %s${RST}\n" "$*" >&2; }
step()  { printf "\n${GREEN}━━ %s ━━${RST}\n" "$*"; }

# ── resolve repo dir (dynamic, no hardcoded /home) ───────────────────────────
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_DIR="$SCRIPT_DIR"
if [[ ! -f "$REPO_DIR/pyproject.toml" || ! -d "$REPO_DIR/deathpwn" ]]; then
  err "Run this from the DeathPWN repo (expected pyproject.toml + deathpwn/ in $REPO_DIR)"
  exit 1
fi
cd "$REPO_DIR"

# ── current model (dynamic — read from deathpwn/config.py, fallback) ─────────
detect_model() {
  local m=""
  if command -v python3 >/dev/null 2>&1; then
    m="$(python3 -c "
import re, pathlib
p = pathlib.Path('deathpwn/config.py')
t = p.read_text() if p.exists() else ''
# capture MODEL default: os.environ.get(... , \"openbmb/minicpm5:latest\")
import re
mm = re.search(r'MODEL[^=]*=\s*os\.environ\.get\([^,]+,\s*\"([^\"]+)\"', t)
alt = re.search(r'MODEL\s*=\s*\"([^\"]+)\"', t)
print((mm.group(1) if mm else (alt.group(1) if alt else '')))
" 2>/dev/null || true)"
  fi
  if [[ -z "$m" ]]; then
    # grep fallback (no python)
    m="$(grep -oP 'MODEL[^=]*=\s*os\.environ\.get\([^,]+,\s*"\K[^"]+' deathpwn/config.py 2>/dev/null | head -n1 || true)"
  fi
  if [[ -z "$m" ]]; then m="openbmb/minicpm5:latest"; fi
  printf '%s' "$m"
}
MODEL="$(detect_model)"
MODEL_SIZE_HINT="~688 MB"
info "Repo:   $REPO_DIR"
info "Model:  $MODEL ($MODEL_SIZE_HINT)"

confirm() {
  if [[ $ASSUME_YES -eq 1 ]]; then return 0; fi
  local prompt="$1"
  read -r -p "$prompt [Y/n] " ans </dev/tty 2>/dev/null || ans="y"
  [[ "$ans" =~ ^[Yy]$ || -z "$ans" ]]
}

# ── 0) python check ──────────────────────────────────────────────────────────
step "0/5  Python"

if ! command -v python3 >/dev/null 2>&1; then
  err "python3 not found — install Python 3.10+ first:"
  echo "  Ubuntu/Debian: sudo apt update && sudo apt install -y python3 python3-venv python3-pip"
  echo "  Arch:          sudo pacman -S python python-pip"
  echo "  Fedora:        sudo dnf install -y python3 python3-pip"
  exit 1
fi

PY_VER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")' 2>/dev/null || echo "?")"
PY_OK="$(python3 -c 'import sys; print(1 if sys.version_info >= (3,10) else 0)' 2>/dev/null || echo 0)"
if [[ "$PY_OK" != "1" ]]; then
  err "Python $PY_VER found — need 3.10+. Upgrade python3 first."
  exit 1
fi
ok "python3 $PY_VER"

if [[ $NO_VENV -eq 0 ]] && ! python3 -m venv --help >/dev/null 2>&1; then
  warn "python3-venv missing — installing hint:"
  echo "  Ubuntu/Debian: sudo apt install -y python3-venv"
  echo "  Arch:          sudo pacman -S python-virtualenv  (or python)"
  echo "  Fedora:        sudo dnf install -y python3-virtualenv"
  # try to continue — pip venv may still work via virtualenv fallback
fi

# ── 1) Ollama ────────────────────────────────────────────────────────────────
step "1/5  Ollama"

install_ollama() {
  info "Installing Ollama (https://ollama.com/install.sh) — requires sudo/curl or wget..."
  local tmp=""
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL https://ollama.com/install.sh | sh
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- https://ollama.com/install.sh | sh
  else
    err "Need curl or wget to install Ollama. Install one and re-run:"
    echo "  sudo apt install -y curl   # or sudo pacman -S curl"
    return 1
  fi
}

ensure_ollama() {
  if command -v ollama >/dev/null 2>&1; then
    ok "ollama $(ollama --version 2>/dev/null || echo "found") at $(command -v ollama)"
    return 0
  fi
  warn "ollama not found"
  if [[ $SKIP_OLLAMA -eq 1 ]]; then
    warn "Skipping Ollama install (--skip-ollama)"
    return 1
  fi
  if ! confirm "Install Ollama now?"; then
    warn "Skipped Ollama install — deathpwn will need it at runtime (ollama serve + ollama pull $MODEL)"
    return 1
  fi
  install_ollama
  if ! command -v ollama >/dev/null 2>&1; then
    # install.sh may have placed it in /usr/local/bin not yet on PATH for this shell
    if [[ -x /usr/local/bin/ollama ]]; then
      export PATH="/usr/local/bin:$PATH"
    fi
  fi
  if command -v ollama >/dev/null 2>&1; then
    ok "ollama installed at $(command -v ollama)"
    return 0
  else
    err "Ollama install did not produce an 'ollama' binary on PATH"
    return 1
  fi
}

OLLAMA_OK=0
if ensure_ollama; then OLLAMA_OK=1; fi

# Ensure ollama daemon reachable (start if needed, non-fatal)
ensure_ollama_running() {
  if [[ $OLLAMA_OK -ne 1 ]]; then return 1; fi
  if ollama list >/dev/null 2>&1; then
    ok "ollama daemon reachable"
    return 0
  fi
  info "ollama daemon not reachable — attempting to start..."
  # systemd if available
  if command -v systemctl >/dev/null 2>&1; then
    sudo systemctl enable --now ollama 2>/dev/null || true
    sleep 2
    if ollama list >/dev/null 2>&1; then ok "ollama started via systemctl"; return 0; fi
  fi
  # fallback: background serve (works in containers / no systemd)
  if command -v nohup >/dev/null 2>&1; then
    nohup ollama serve >/tmp/ollama.log 2>&1 &
    disown 2>/dev/null || true
    info "started 'ollama serve' in background (log: /tmp/ollama.log) — waiting..."
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      sleep 1
      if ollama list >/dev/null 2>&1; then ok "ollama daemon reachable (background)"; return 0; fi
    done
  fi
  warn "ollama daemon still not reachable — start it manually:  ollama serve  (in another terminal)"
  return 1
}
ensure_ollama_running || true

# ── 2) Model ─────────────────────────────────────────────────────────────────
step "2/5  Model  ($MODEL)"

ensure_model() {
  if [[ $SKIP_MODEL -eq 1 ]]; then warn "Skipping model pull (--skip-model)"; return 0; fi
  if [[ $OLLAMA_OK -ne 1 ]]; then
    warn "Skipping model pull — ollama not available (install it, then: ollama pull $MODEL)"
    return 0
  fi
  if ! ollama list >/dev/null 2>&1; then
    warn "ollama daemon not reachable — cannot check/pull model now. After 'ollama serve', run: ollama pull $MODEL"
    return 0
  fi
  # ollama list format: NAME  ID  SIZE  MODIFIED  — match by first column prefix
  if ollama list 2>/dev/null | awk 'NR>1{print $1}' | grep -Fxq "$MODEL"; then
    ok "model $MODEL already present"
    return 0
  fi
  # also accept without :latest tag variant
  local base="${MODEL%%:*}"
  if ollama list 2>/dev/null | grep -qF "$base"; then
    ok "model $base present (variant of $MODEL)"
    return 0
  fi
  info "pulling $MODEL ($MODEL_SIZE_HINT) — this may take a minute on first run..."
  if ollama pull "$MODEL"; then
    ok "model $MODEL ready"
  else
    err "ollama pull $MODEL failed — retry manually: ollama pull $MODEL"
    return 1
  fi
}
ensure_model || true

# ── 3) tools: subfinder + dirb ───────────────────────────────────────────────
step "3/5  tools (subfinder + dirb)"

ensure_subfinder() {
  if command -v subfinder >/dev/null 2>&1; then
    ok "subfinder at $(command -v subfinder)"
    return 0
  fi
  warn "subfinder not found"
  if [[ $SKIP_SUBFINDER -eq 1 ]]; then warn "Skipping subfinder (--skip-subfinder)"; return 0; fi
  info "Try one of:"
  echo "  ${DIM}sudo pacman -S subfinder${RST}  (Arch/BlackArch)"
  echo "  ${DIM}sudo apt update && sudo apt install -y subfinder${RST}  (if packaged)"
  echo "  ${DIM}go install -v github.com/projectdiscovery/subfinder/v2/cmd/subfinder@latest${RST}  (Go)"
  echo "    then: ${DIM}export PATH=\"\$HOME/go/bin:\$PATH\"${RST}"
  if command -v go >/dev/null 2>&1; then
    if confirm "Install subfinder via 'go install' now?"; then
      if go install -v github.com/projectdiscovery/subfinder/v2/cmd/subfinder@latest; then
        # ensure ~/go/bin on PATH for this session
        if [[ -x "$HOME/go/bin/subfinder" ]]; then
          export PATH="$HOME/go/bin:$PATH"
        fi
        if command -v subfinder >/dev/null 2>&1; then
          ok "subfinder installed at $(command -v subfinder)"
          return 0
        fi
      fi
      warn "go install finished but 'subfinder' still not on PATH — add ~/go/bin to PATH"
    fi
  else
    warn "Go not found — install subfinder via your package manager when ready"
  fi
  return 0
}

ensure_dirb() {
  if command -v dirb >/dev/null 2>&1; then
    ok "dirb at $(command -v dirb)"
    return 0
  fi
  warn "dirb not found (needed for: deathpwn \"start directory bruteforce on example.com\" -> dirb https://example.com)"
  info "Install:"
  echo "  ${DIM}sudo pacman -S dirb${RST}  (Arch)"
  echo "  ${DIM}sudo apt update && sudo apt install -y dirb${RST}  (Debian/Ubuntu)"
  return 0
}
ensure_subfinder || true
ensure_dirb || true

# ── 4) venv + install ────────────────────────────────────────────────────────
step "4/5  Python package"

VENV_DIR="$REPO_DIR/.venv"
VENV_PY="$VENV_DIR/bin/python"
VENV_DEATHPWN="$VENV_DIR/bin/deathpwn"

if [[ $NO_VENV -eq 1 ]]; then
  info "Installing to system python (--no-venv)..."
  PIP_CMD=(python3 -m pip)
  if [[ $WITH_DEV -eq 1 ]]; then
    "${PIP_CMD[@]}" install -e ".[dev]" --break-system-packages 2>/dev/null || "${PIP_CMD[@]}" install -e ".[dev]"
  else
    "${PIP_CMD[@]}" install -e . --break-system-packages 2>/dev/null || "${PIP_CMD[@]}" install -e .
  fi
  ok "installed to system python"
else
  if [[ ! -d "$VENV_DIR" ]]; then
    info "creating venv at $VENV_DIR"
    python3 -m venv "$VENV_DIR"
    ok "venv created"
  else
    ok "venv exists at $VENV_DIR"
  fi
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
  info "upgrading pip..."
  python -m pip install --upgrade pip -q 2>&1 | tail -n 5 || true
  if [[ $WITH_DEV -eq 1 ]]; then
    info "pip install -e \".[dev]\"..."
    pip install -e ".[dev]"
  else
    info "pip install -e . ..."
    pip install -e .
  fi
  ok "deathpwn installed in venv"
  if [[ -x "$VENV_DEATHPWN" ]]; then
    ok "entry point: $VENV_DEATHPWN"
  fi
fi

# ensure output symlink target exists (linked resource ctf-flagboard/output)
if [[ -L "$REPO_DIR/output" ]]; then
  # symlink like DeathPWN/output -> ../ctf-flagboard/output
  target="$(readlink "$REPO_DIR/output" 2>/dev/null || true)"
  # resolve relative to repo
  if [[ "$target" == ../* || "$target" == ./* ]]; then
    abs_target="$(cd "$REPO_DIR" && realpath -m "$target" 2>/dev/null || echo "$REPO_DIR/$target")"
    mkdir -p "$abs_target" 2>/dev/null || true
  fi
fi

# ── 5) deathpwn command ──────────────────────────────────────────────────────
step "5/5  deathpwn command"

BIN_DIR="${HOME}/.local/bin"
mkdir -p "$BIN_DIR"

# source binary depends on venv vs system mode
if [[ $NO_VENV -eq 1 ]]; then
  # system install: deathpwn should already be on PATH if pip's bin is
  SRC_BIN="$(command -v deathpwn 2>/dev/null || python3 -c 'import sysconfig; print(sysconfig.get_path("scripts"))' 2>/dev/null)/deathpwn"
  # fallback: find via pip show
  if [[ ! -x "$SRC_BIN" ]]; then SRC_BIN="$(command -v deathpwn 2>/dev/null || echo "")"; fi
else
  SRC_BIN="$VENV_DEATHPWN"
fi

if [[ -z "${SRC_BIN:-}" || ! -e "$SRC_BIN" ]]; then
  # last resort: locate deathpwn entry point
  SRC_BIN="$(find "$REPO_DIR" -name deathpwn -type f 2>/dev/null | head -n1 || true)"
  if [[ -z "$SRC_BIN" ]]; then SRC_BIN="$VENV_DEATHPWN"; fi
fi

LINK_PATH="$BIN_DIR/deathpwn"

# Arch PEP 668 blocks system pip — we always prefer the venv symlink when available
if [[ -x "$VENV_DEATHPWN" ]]; then
  SRC_BIN="$VENV_DEATHPWN"
fi

if [[ -e "$SRC_BIN" || -x "$SRC_BIN" ]]; then
  ln -sf "$SRC_BIN" "$LINK_PATH"
  ok "linked $LINK_PATH -> $SRC_BIN"
else
  warn "Could not locate deathpwn binary to link (expected $VENV_DEATHPWN)"
  echo "  Try: ls -la $VENV_DIR/bin/  and  $VENV_PY -m deathpwn --help"
fi

# Ensure ~/.local/bin on PATH (advise, don't mutate shell rc automatically)
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
  warn "~/.local/bin not on PATH — add it:"
  echo "  ${DIM}export PATH=\"\$HOME/.local/bin:\$PATH\"${RST}  (or add to ~/.bashrc / ~/.zshrc)"
  echo "  ${DIM}echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc && source ~/.bashrc${RST}"
fi

# ── verify ───────────────────────────────────────────────────────────────────
step "Verify"

# Prefer the linked command, fallback to venv
DEATHPWN_BIN=""
if [[ -x "$LINK_PATH" ]]; then DEATHPWN_BIN="$LINK_PATH"
elif [[ -x "$VENV_DEATHPWN" ]]; then DEATHPWN_BIN="$VENV_DEATHPWN"
elif command -v deathpwn >/dev/null 2>&1; then DEATHPWN_BIN="$(command -v deathpwn)"
fi

if [[ -n "$DEATHPWN_BIN" && -x "$DEATHPWN_BIN" ]]; then
  if "$DEATHPWN_BIN" --help >/dev/null 2>&1; then
    ok "deathpwn --help works ($DEATHPWN_BIN)"
  else
    warn "deathpwn binary exists but --help failed: $DEATHPWN_BIN"
  fi
else
  warn "deathpwn not yet runnable — try: $VENV_PY -m deathpwn --help"
fi

if [[ $OLLAMA_OK -eq 1 ]] && ollama list >/dev/null 2>&1; then
  if ollama list 2>/dev/null | grep -qF "${MODEL%%:*}"; then
    ok "model $MODEL present (ollama list)"
  else
    warn "model $MODEL not yet present — run: ollama pull $MODEL"
  fi
fi

if command -v subfinder >/dev/null 2>&1; then
  ok "subfinder ready ($(subfinder --version 2>&1 | head -n1 || echo ok))"
else
  warn "subfinder still missing — install per step 3/5 hint above"
fi
if command -v dirb >/dev/null 2>&1; then
  ok "dirb ready ($(dirb 2>&1 | head -n1 || echo ok))"
else
  warn "dirb still missing — needed for directory bruteforce (install per step 3/5 hint above)"
  echo "  ${DIM}sudo pacman -S dirb${RST}  or  ${DIM}sudo apt install -y dirb${RST}"
fi

echo ""
printf "${GREEN}Done.${RST}  Try:\n"
echo "  deathpwn --help"
echo "  deathpwn \"find subdomains for hadiya.in\" --dry-run --verbose"
echo "  deathpwn \"start directory bruteforce on example.com\" --dry-run  # -> dirb https://example.com"
echo "  deathpwn \"find subomains in hadiya.in\" --dry-run   # typo-tolerant"
echo ""
printf "${DIM}Env overrides: DEATHPWN_MODEL, DEATHPWN_TIMEOUT, DEATHPWN_THINK=1 (re-enable thinking), DEATHPWN_SYSTEM_PROMPT${RST}\n"
printf "${DIM}Re-run: ./install.sh --yes  |  ./install.sh --dev  |  ./install.sh --help${RST}\n"
