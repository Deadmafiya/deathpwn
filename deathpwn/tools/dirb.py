"""dirb runner — directory bruteforce via dirb (Rich TTY + plain fallback)."""
from __future__ import annotations

import shutil
import subprocess
import sys
import urllib.parse
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from deathpwn import config
from deathpwn.tools.registry import register
from deathpwn.utils.domain import normalize_domain


class ToolNotFound(Exception):
    pass


class ToolExecutionError(Exception):
    pass


def _is_tty() -> bool:
    try:
        return sys.stdout.isatty()
    except Exception:
        return False


def _target_to_url(target: str) -> str:
    """Convert bare hostname/domain to https URL (CLI-owned, not LLM).

    The model is instructed to return bare host only; this function adds
    https:// so dirb receives a valid URL. If user already supplied a URL
    that slipped through as target, it is normalized to https and stripped
    to scheme+host only.
    """
    s = (target or "").strip()
    if not s:
        return ""
    # If it looks like a URL, parse it; otherwise treat as bare host
    if "://" in s:
        parsed = urllib.parse.urlparse(s if "://" in s else f"https://{s}")
        host = (parsed.hostname or "").strip().lower()
        if not host:
            host = normalize_domain(s)
        if not host:
            return ""
        # Always force https, drop path/query/fragment, keep port if present
        port = f":{parsed.port}" if parsed.port else ""
        return f"https://{host}{port}"
    # bare host — normalize then force https
    host = normalize_domain(s)
    if not host:
        return ""
    return f"https://{host}"


@register("dirb")
def run_dirb(target: str, *, output: Path, verbose: bool = False) -> int:
    """Run dirb against target (bare host -> https URL built here).

    Streams dirb output live (like subfinder) and saves raw lines to output.
    Returns count of discovered entries (lines starting with + or URL-like).
    """
    if shutil.which(config.DIRB_BIN) is None and shutil.which("dirb") is None:
        raise ToolNotFound(
            "dirb not found. Install: sudo pacman -S dirb / sudo apt install -y dirb — https://tools.kali.org/web-applications/dirb"
        )

    binary = config.DIRB_BIN if shutil.which(config.DIRB_BIN) else "dirb"

    url = _target_to_url(target)
    if not url:
        raise ToolExecutionError(f"Could not build URL from target {target!r}")

    cmd = [binary, url]

    console = Console()
    err_console = Console(stderr=True)

    if verbose:
        err_console.print(f"[dim]● Running:[/] [cyan]{' '.join(cmd)}[/]")

    output.parent.mkdir(parents=True, exist_ok=True)

    count = 0
    proc = None

    # Patterns dirb uses for a hit: "+ https://..." and sometimes "==> DIRECTORY: https://..."
    def _is_hit(line: str) -> bool:
        s = line.strip()
        if not s:
            return False
        if s.startswith("+ "):
            return True
        if s.startswith("==> DIRECTORY:") or s.startswith("==>"):
            return True
        # Also treat any printed URL under the target host as a hit
        low = s.lower()
        host = normalize_domain(target)
        if host and host in low and "http" in low:
            return True
        return False

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)

        # Stream live — plain path so capsys/pipes see raw lines; TTY just prints too
        with output.open("w", encoding="utf-8") as outfile:
            assert proc.stdout is not None
            for raw_line in proc.stdout:
                line = raw_line.rstrip("\n")
                # Save raw line
                outfile.write(line + "\n")
                outfile.flush()
                # Print live
                if _is_hit(line):
                    count += 1
                    print(line, flush=True)
                else:
                    # Keep output visible but dim in TTY
                    if verbose:
                        print(line, flush=True)
                    elif _is_tty():
                        # dirb is verbose; in non-verbose TTY still show hits only
                        pass
                    else:
                        # non-TTY, non-verbose: show hits only; skip banner/noise for callers
                        pass

            proc.wait()
            stderr_text = ""
            if proc.stderr is not None:
                try:
                    stderr_text = proc.stderr.read() or ""
                except Exception:
                    stderr_text = ""

            # dirb exit codes: 0 found, 1 not found; treat 0/1 as ok if we have hits
            # Only fail when dirb errors out and found nothing
            if proc.returncode not in (0, 1, None) and count == 0:
                msg = stderr_text.strip() or f"dirb exited with code {proc.returncode}"
                err_console.print(Panel(msg, title="[red]dirb failed[/]", border_style="red"))
                raise ToolExecutionError(msg)
            if stderr_text and verbose and count == 0:
                # dirb often prints to stderr for progress; surface on verbose when nothing found
                print(stderr_text, flush=True)

            if count == 0:
                hint = f"No directories/files found for {url}"
                if _is_tty():
                    console.print(Panel(f"[yellow]{hint}[/] [dim](saved raw output at {output})[/]", border_style="yellow"))
                else:
                    print(f"[!] {hint}", flush=True)

    except KeyboardInterrupt:
        if proc is not None:
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
            except Exception:
                pass
        msg_ki = f"Interrupted — kept {count} results at {output}"
        if _is_tty():
            err_console.print(Panel(msg_ki, title="[yellow]interrupted[/]", border_style="yellow"))
        else:
            print(f"\n[!] {msg_ki}", flush=True)
        return count

    return count
