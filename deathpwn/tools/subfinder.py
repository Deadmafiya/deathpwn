"""Subfinder runner — streams results live and saves to file."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from deathpwn import config
from deathpwn.tools.registry import register


class ToolNotFound(Exception):
    pass


class ToolExecutionError(Exception):
    pass


@register("subfinder")
def run_subfinder(domain: str, *, output: Path, all_sources: bool = False, verbose: bool = False) -> int:
    if shutil.which(config.SUBFINDER_BIN) is None and shutil.which("subfinder") is None:
        raise ToolNotFound(
            "subfinder not found. Install: pacman -S subfinder / go install -v github.com/projectdiscovery/subfinder/v2/cmd/subfinder@latest"
        )

    binary = config.SUBFINDER_BIN if shutil.which(config.SUBFINDER_BIN) else "subfinder"
    cmd = [binary, "-d", domain, "-silent"] + (["-all"] if all_sources else [])

    if verbose:
        print(f"[+] Running: {' '.join(cmd)}", flush=True)

    output.parent.mkdir(parents=True, exist_ok=True)

    count = 0
    proc = None
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        with output.open("w", encoding="utf-8") as outfile:
            assert proc.stdout is not None
            for raw_line in proc.stdout:
                line = raw_line.strip()
                if not line:
                    continue
                print(line, flush=True)
                outfile.write(line + "\n")
                count += 1
                outfile.flush()
            proc.wait()
            stderr_text = ""
            if proc.stderr is not None:
                try:
                    stderr_text = proc.stderr.read() or ""
                except Exception:
                    stderr_text = ""
            if proc.returncode != 0 and count == 0:
                msg = stderr_text.strip() or f"subfinder exited with code {proc.returncode}"
                raise ToolExecutionError(msg)
            if count == 0:
                print(f"[!] No subdomains found for {domain}", flush=True)
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
        print(f"\n[!] Interrupted — kept {count} results at {output}", flush=True)
        return count
    return count
