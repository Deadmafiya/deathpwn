"""Subfinder runner — streams results live and saves to file (Rich TTY + plain fallback)."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from deathpwn import config
from deathpwn.tools.registry import register


class ToolNotFound(Exception):
    pass


class ToolExecutionError(Exception):
    pass


def _is_tty() -> bool:
    """True only in a real interactive terminal — tests/pipes stay plain."""
    try:
        return sys.stdout.isatty()
    except Exception:
        return False


@register("subfinder")
def run_subfinder(domain: str, *, output: Path, all_sources: bool = False, verbose: bool = False) -> int:
    if shutil.which(config.SUBFINDER_BIN) is None and shutil.which("subfinder") is None:
        raise ToolNotFound(
            "subfinder not found. Install: pacman -S subfinder / go install -v github.com/projectdiscovery/subfinder/v2/cmd/subfinder@latest"
        )

    binary = config.SUBFINDER_BIN if shutil.which(config.SUBFINDER_BIN) else "subfinder"
    cmd = [binary, "-d", domain, "-silent"] + (["-all"] if all_sources else [])

    # Rich console for this call (stderr for status so stdout stays capturable in tests/pipes)
    console = Console()
    err_console = Console(stderr=True)

    if verbose:
        err_console.print(f"[dim]● Running:[/] [cyan]{' '.join(cmd)}[/]")

    output.parent.mkdir(parents=True, exist_ok=True)

    count = 0
    proc = None

    # Collect for the live table — plain path skips Live entirely so capsys/tests see raw lines
    use_live = _is_tty() and not verbose  # verbose users want raw lines; keep logs clean

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)

        if use_live:
            # Rich live table — updates in-place, still saves to file
            table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 1), expand=False)
            table.add_column("#", style="dim", width=4, justify="right", no_wrap=True)
            table.add_column("subdomain", style="white")
            found: list[str] = []

            def _make_panel() -> Panel:
                # Rebuild table snapshot each frame (keeps header + rows)
                t = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 1), expand=False)
                t.add_column("#", style="dim", width=4, justify="right", no_wrap=True)
                t.add_column("subdomain", style="white")
                for i, s in enumerate(found, 1):
                    t.add_row(str(i), s)
                if not found:
                    t.add_row("—", "[dim]waiting for results…[/dim]")
                status = "[yellow]running[/]" if not found else f"[bold]{len(found)}[/] found"
                return Panel(t, title=f"[cyan]subfinder[/] [dim]→ {domain}[/]  {status}", border_style="cyan", padding=(0, 1))

            with Live(_make_panel(), console=console, refresh_per_second=12, transient=False) as live:
                with output.open("w", encoding="utf-8") as outfile:
                    assert proc.stdout is not None
                    for raw_line in proc.stdout:
                        line = raw_line.strip()
                        if not line:
                            continue
                        found.append(line)
                        count += 1
                        outfile.write(line + "\n")
                        outfile.flush()
                        live.update(_make_panel())
                proc.wait()

            # After live completes, emit plain lines so piping / logs still work — but only if needed
            # (In a TTY we already showed the table; no extra clutter.)
            stderr_text = ""
            if proc.stderr is not None:
                try:
                    stderr_text = proc.stderr.read() or ""
                except Exception:
                    stderr_text = ""
            if proc.returncode != 0 and count == 0:
                msg = stderr_text.strip() or f"subfinder exited with code {proc.returncode}"
                err_console.print(Panel(msg, title="[red]subfinder failed[/]", border_style="red"))
                raise ToolExecutionError(msg)
            if count == 0:
                console.print(Panel(f"[yellow]No subdomains found[/] [dim]for {domain}[/]", border_style="yellow"))
            return count

        # --- Plain / test / piped path — identical to legacy, capsys-safe ---
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
        msg_ki = f"Interrupted — kept {count} results at {output}"
        if _is_tty():
            err_console.print(Panel(msg_ki, title="[yellow]interrupted[/]", border_style="yellow"))
        else:
            print(f"\n[!] {msg_ki}", flush=True)
        return count
    return count
