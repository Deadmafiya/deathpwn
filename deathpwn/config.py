"""DeathPWN configuration — defaults overridable via env / flags."""
import os, shutil
OLLAMA_HOST: str = os.environ.get("DEATHPWN_OLLAMA_HOST", "http://127.0.0.1:11434")
MODEL: str = os.environ.get("DEATHPWN_MODEL", "functiongemma:latest")
OLLAMA_TIMEOUT: int = int(os.environ.get("DEATHPWN_TIMEOUT", "12"))
SUBFINDER_BIN: str = shutil.which("subfinder") or "subfinder"
