"""DeathPWN CLI — natural-language bug bounty runner (Rich-powered UI)."""

from __future__ import annotations

import argparse
import sys
import traceback

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from deathpwn import __version__

# ---------------------------------------------------------------------------
# Rich consoles — linked with: ctf-flagboard/lib/functiongemma.js (now MiniCPM5) output
# ---------------------------------------------------------------------------

_THEME = Theme({
    "info": "cyan",
    "success": "bold green",
    "warning": "yellow",
    "error": "bold red",
    "dim": "dim",
    "hint": "dim",
    "accent": "bold magenta",
})

console = Console(theme=_THEME, highlight=False)
err_console = Console(stderr=True, theme=_THEME, highlight=False)

# Legacy helpers — now thin wrappers over Rich (kept for compat)
def _color(text: str, code: str) -> str:
    return text  # Rich handles color

def _red(s: str) -> str: return s
def _green(s: str) -> str: return s
def _cyan(s: str) -> str: return s
def _yellow(s: str) -> str: return s
def _dim(s: str) -> str: return s
def _bold(s: str) -> str: return s


# ---------------------------------------------------------------------------
# argparse
# ---------------------------------------------------------------------------

_EXAMPLES = """\
examples:
  deathpwn "find subdomains for https://example.com"
  deathpwn "find subs for example.com" -o out.txt
  deathpwn "enumerate subdomains of example.com" --all --verbose
  deathpwn "start directory bruteforce on example.com"           # -> dirb https://example.com
  deathpwn "bruteforce directories on https://example.com/path"   # dirb (https added by CLI)\
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="deathpwn",
        description="DeathPWN — natural-language bug bounty runner",
        epilog=_EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "query",
        nargs="*",
        help='Natural language request, e.g. \'find subdomains for https://example.com\'',
    )
    p.add_argument(
        "-o",
        "--output",
        dest="output",
        default=None,
        help="Output file path (default: ctf-flagboard/output/<domain>-<suffix>.txt — linked resource)",
    )
    p.add_argument(
        "--output-dir",
        dest="output_dir",
        default=None,
        help="Output directory (default: ctf-flagboard/output/ — linked from this project; override with --output-dir)",
    )
    p.add_argument(
        "--all",
        dest="all",
        action="store_true",
        help="Use all subfinder sources (slower, more thorough)",
    )
    p.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Also write JSONL alongside txt (not yet implemented note - just handle flag, can ignore in v0.1 or warn)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would run, do not execute",
    )
    p.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose output",
    )
    p.add_argument(
        "--model",
        default=None,
        help="Ollama model (default: openbmb/minicpm5:latest)",
    )
    p.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    try:
        parser = build_parser()
        args = parser.parse_args(argv)

        # 1. No query — parser.error style
        if not args.query:
            parser.print_usage(sys.stderr)
            err_console.print(f"{parser.prog}: error: the following arguments are required: query", style="error")
            err_console.print()
            err_console.print(Panel(_EXAMPLES, title="usage", border_style="dim", padding=(0, 1)))
            err_console.print('[hint]  try  deathpwn "find subdomains for example.com"', style="hint")
            return 2

        query_text = " ".join(args.query)

        # 3. Understanding — Rich status spinner ( linked with minicpm5 hot: keep_alive 30m )
        status = None
        if args.verbose:
            console.print(f'[dim]● Understanding: "{query_text}"...[/dim]')
        else:
            status = console.status("[dim]→ Interpreting request...[/dim]", spinner="dots")
            status.start()

        def _stop_status() -> None:
            if status is not None:
                try: status.stop()
                except Exception: pass

        # 4. Call LLM (openbmb/minicpm5:latest via Ollama — same source as ctf-flagboard/lib/functiongemma.js)
        from deathpwn.llm.client import (
            LLMParseError,
            ModelNotFound,
            OllamaTimeout,
            OllamaUnavailable,
            call_llm,
            fallback_tool_call,
        )

        try:
            tool_call = call_llm(query_text, model=args.model)
            _stop_status()
        except OllamaUnavailable as exc:
            _stop_status()
            fb = fallback_tool_call(query_text)
            if fb is not None:
                console.print(f"  [dim]● Ollama unreachable — using local parser: {fb}[/dim]")
                tool_call = fb
            else:
                msg = str(exc) or f"Ollama not reachable. Is it running? Try: ollama serve"
                if "ollama serve" not in msg.lower():
                    msg = f"{msg} Is it running? Try: ollama serve"
                err_console.print(Panel(msg, title="[error]Ollama unavailable[/]", border_style="red"))
                return 4
        except ModelNotFound as exc:
            _stop_status()
            msg = str(exc)
            model_name = args.model or "openbmb/minicpm5:latest"
            if "ollama pull" not in msg.lower():
                msg = f"Model {model_name} not found. Try: ollama pull {model_name}"
            err_console.print(Panel(msg, title="[error]Model not found[/]", border_style="red"))
            return 4
        except OllamaTimeout as exc:
            _stop_status()
            fb = fallback_tool_call(query_text)
            if fb is not None:
                console.print(f"  [dim]● MiniCPM5 slow — using local parser: {fb}[/dim]")
                tool_call = fb
            else:
                msg = str(exc) or "Ollama timed out. Try again or check Ollama status."
                if "timed out" not in msg.lower():
                    msg = f"Ollama timed out: {msg}"
                err_console.print(Panel(msg, title="[error]Timeout[/]", border_style="red"))
                return 4
        except LLMParseError as exc:
            _stop_status()
            fb = fallback_tool_call(query_text)
            if fb is not None:
                console.print(f"  [dim]● LLM parse error — using local parser: {fb}[/dim]")
                tool_call = fb
            else:
                err_console.print(Panel(str(exc), title="[error]LLM error[/]", border_style="red"))
                return 4

        # 5. Hallucination guard — allow only known tool intents (typo-tolerant fuzzy)
        if tool_call is not None:
            from deathpwn.utils.domain import _looks_like_any_tool_request

            if not _looks_like_any_tool_request(query_text):
                if args.verbose:
                    console.print("  [dim]● Discarding hallucinated tool_call — query has no supported intent[/dim]")
                err_console.print(Panel(
                    "[error]No matching tool for that request.[/]\n\n"
                    "I currently support:\n"
                    '  • [info]find subdomains[/] — e.g. deathpwn "find subdomains for example.com"\n'
                    '  • [info]directory bruteforce[/] — e.g. deathpwn "start directory bruteforce on example.com"  [dim](-> dirb https://example.com)[/]',
                    title="hint", border_style="yellow", padding=(0, 1)
                ))
                return 1

        # 5b. No tool matched — try deterministic fallback before giving up (covers dirb + subfinder)
        if tool_call is None:
            fb2 = fallback_tool_call(query_text)
            if fb2 is not None:
                if args.verbose:
                    console.print(f"  [dim]● Model returned no tool — fallback parser: {fb2}[/dim]")
                else:
                    console.print(f"  [dim]● Model returned no tool — using local parser: {fb2}[/dim]")
                tool_call = fb2
            else:
                err_console.print(Panel(
                    "[error]No matching tool for that request.[/]\n\n"
                    "I currently support:\n"
                    '  • [info]find subdomains[/] — e.g. deathpwn "find subdomains for example.com"\n'
                    '  • [info]directory bruteforce[/] — e.g. deathpwn "start directory bruteforce on example.com"  [dim](-> dirb https://example.com)[/]',
                    title="hint", border_style="yellow", padding=(0, 1)
                ))
                if args.verbose:
                    err_console.print("  [dim](model returned no tool_call — try rephrasing)[/dim]")
                return 1

        if args.verbose:
            console.print(f"[dim]● Tool call: {tool_call}[/dim]")
            if isinstance(tool_call, dict) and tool_call.get("content"):
                err_console.print(f"  [dim]model content: {tool_call['content']}[/dim]")

        # 6. Extract domain/target — dirb uses 'target', subfinder uses 'domain'
        arguments = tool_call.get("arguments", {}) if isinstance(tool_call, dict) else {}
        if not isinstance(arguments, dict):
            arguments = {}
        tool_name_raw = tool_call.get("name", "") if isinstance(tool_call, dict) else ""
        is_dirb = tool_name_raw == "dirb"

        if is_dirb:
            raw_value = arguments.get("target", "") or arguments.get("domain", "") or arguments.get("url", "")
            if not isinstance(raw_value, str):
                raw_value = str(raw_value) if raw_value is not None else ""
            if not raw_value or not raw_value.strip():
                err_console.print(Panel(
                    f"[error]Could not extract valid target from '{raw_value}'.[/]\n"
                    'Try: deathpwn "start directory bruteforce on example.com"',
                    border_style="red"
                ))
                return 2
            from deathpwn.utils.domain import normalize_domain, validate_domain
            # Normalize target as bare host (CLI will add https://)
            target_host = normalize_domain(raw_value)
            if args.verbose:
                console.print(f'[dim]● Raw target: "{raw_value}" -> normalized host: "{target_host}" -> url: "https://{target_host}"[/dim]')
            if not validate_domain(target_host):
                err_console.print(Panel(
                    f"[error]Could not extract valid target from '{raw_value}'.[/]\n"
                    'Try: deathpwn "start directory bruteforce on example.com"',
                    border_style="red"
                ))
                return 2

            # 8. Resolve output (linked: ctf-flagboard/output by default) — dirb suffix
            from deathpwn.utils.output import resolve_output_path
            output_path = resolve_output_path(target_host, args.output, args.output_dir, suffix="-dirb.txt")

            if args.json_output:
                console.print("[dim]● Note: --json flag is accepted but JSON output is not yet implemented (txt only).[/dim]")

            # 10. Dry-run — Rich panel
            if args.dry_run:
                url = f"https://{target_host}"
                cmd_preview = f"dirb {url}"
                grid = Table.grid(padding=(0, 1))
                grid.add_column(style="dim", justify="right")
                grid.add_column(style="info")
                grid.add_row("Would run:", f"[bold]{cmd_preview}[/]")
                grid.add_row("URL:", url + "  [dim](https added by CLI)[/dim]")
                grid.add_row("Output:", str(output_path))
                grid.add_row("Resources:", "ctf-flagboard/output/ [dim](linked)[/dim]")
                console.print(Panel(grid, title="[info]DRY-RUN[/]  [cyan]dirb[/]", border_style="cyan", padding=(1, 2)))
                return 0

            # 11. Registry dispatch — dirb
            import deathpwn.tools  # noqa: F401  ensure dirb + subfinder registered
            from deathpwn.tools import registry
            fn = registry.TOOL_REGISTRY.get("dirb")
            if fn is None:
                err_console.print(Panel('[error]Tool "dirb" not registered.[/]', border_style="red"))
                return 3
            # dirb tool handles https building internally; pass bare host as target
            console.print(Panel(
                f"[info]Directory bruteforce for[/] [bold]https://{target_host}[/]  [dim]via dirb → {output_path}[/dim]",
                border_style="cyan", padding=(0, 1)
            ))
            from deathpwn.tools.dirb import ToolExecutionError as DirbExecError, ToolNotFound as DirbNotFound
            try:
                count = fn(target_host, output=output_path, verbose=args.verbose)
            except DirbNotFound as exc:
                err_console.print(Panel(str(exc), title="[error]Tool not found[/]", border_style="red"))
                return 3
            except DirbExecError as exc:
                err_console.print(Panel(f"dirb failed: {exc}", title="[error]Execution failed[/]", border_style="red"))
                return 3
            except KeyboardInterrupt:
                return 130
            if count > 0:
                summary = Table.grid(padding=(0, 1))
                summary.add_column(style="success", justify="right")
                summary.add_column()
                summary.add_row("Found", f"[bold]{count}[/] paths")
                summary.add_row("Saved", str(output_path))
                summary.add_row("Source", "ctf-flagboard/output/ [dim](linked)[/dim]")
                console.print(Panel(summary, title="[success]Done[/]  [cyan]dirb[/]", border_style="green", padding=(0, 1)))
                return 0
            else:
                console.print(Panel(
                    f"[warning]No directories/files found[/] [dim](saved raw output at {output_path})[/dim]",
                    border_style="yellow"
                ))
                return 1

        # --- subfinder path (default) ---
        domain_raw = arguments.get("domain", "") or arguments.get("target", "") or arguments.get("url", "")
        if not isinstance(domain_raw, str):
            domain_raw = str(domain_raw) if domain_raw is not None else ""
        if not domain_raw or not domain_raw.strip():
            err_console.print(Panel(
                f"[error]Could not extract valid domain from '{domain_raw}'.[/]\n"
                'Try: deathpwn "find subdomains for example.com"',
                border_style="red"
            ))
            return 2

        # 7. Normalize + validate
        from deathpwn.utils.domain import normalize_domain, validate_domain

        domain = normalize_domain(domain_raw)

        if args.verbose:
            console.print(f'[dim]● Raw domain: "{domain_raw}" -> normalized: "{domain}"[/dim]')

        if not validate_domain(domain):
            err_console.print(Panel(
                f"[error]Could not extract valid domain from '{domain_raw}'.[/]\n"
                'Try: deathpwn "find subdomains for example.com"',
                border_style="red"
            ))
            return 2

        # 8. Resolve output (linked: ctf-flagboard/output by default)
        from deathpwn.utils.output import resolve_output_path

        output_path = resolve_output_path(domain, args.output, args.output_dir)

        # 9. all_sources
        all_sources = bool(arguments.get("all_sources", False)) or bool(args.all)

        if args.json_output:
            console.print("[dim]● Note: --json flag is accepted but JSON output is not yet implemented in v0.1 (txt only).[/dim]")

        # 10. Dry-run — Rich panel
        if args.dry_run:
            cmd_preview = f"subfinder -d {domain} -silent" + (" -all" if all_sources else "")
            grid = Table.grid(padding=(0, 1))
            grid.add_column(style="dim", justify="right")
            grid.add_column(style="info")
            grid.add_row("Would run:", f"[bold]{cmd_preview}[/]")
            grid.add_row("Output:", str(output_path))
            grid.add_row("Resources:", "ctf-flagboard/output/ [dim](linked)[/dim]")
            console.print(Panel(grid, title="[info]DRY-RUN[/]", border_style="cyan", padding=(1, 2)))
            return 0

        # 11. Registry dispatch
        import deathpwn.tools  # noqa: F401  ensure subfinder registered
        from deathpwn.tools import registry

        tool_name = tool_call.get("name", "") if isinstance(tool_call, dict) else ""
        fn = registry.TOOL_REGISTRY.get(tool_name)
        if fn is None:
            err_console.print(Panel(f'[error]Unknown tool "{tool_name}".[/]', border_style="red"))
            known = ", ".join(sorted(registry.TOOL_REGISTRY)) or "(none)"
            err_console.print(f"  [dim]Known tools: {known}[/dim]")
            return 3

        # 12. Header — Rich
        console.print(Panel(
            f"[info]Finding subdomains for[/] [bold]{domain}[/]  [dim]via subfinder → {output_path}[/dim]",
            border_style="cyan", padding=(0, 1)
        ))

        # 13. Call tool (Rich streaming — Live table inside subfinder.py)
        from deathpwn.tools.subfinder import ToolExecutionError, ToolNotFound

        try:
            count = fn(domain, output=output_path, all_sources=all_sources, verbose=args.verbose)
        except ToolNotFound as exc:
            err_console.print(Panel(str(exc), title="[error]Tool not found[/]", border_style="red"))
            return 3
        except ToolExecutionError as exc:
            err_console.print(Panel(f"Subfinder failed: {exc}", title="[error]Execution failed[/]", border_style="red"))
            return 3
        except KeyboardInterrupt:
            return 130

        # 14. Summary — Rich panels
        if count > 0:
            summary = Table.grid(padding=(0, 1))
            summary.add_column(style="success", justify="right")
            summary.add_column()
            summary.add_row("Found", f"[bold]{count}[/] subdomains")
            summary.add_row("Saved", str(output_path))
            summary.add_row("Source", "ctf-flagboard/output/ [dim](linked)[/dim]")
            console.print(Panel(summary, title="[success]Done[/]", border_style="green", padding=(0, 1)))
            return 0
        else:
            console.print(Panel(
                f"[warning]No subdomains found[/] [dim](saved empty file at {output_path})[/dim]",
                border_style="yellow"
            ))
            return 1

    except SystemExit:
        raise
    except Exception as exc:
        verbose = False
        try:
            verbose = bool(args.verbose)  # type: ignore[possibly-undefined]
        except Exception:
            pass
        err_console.print(Panel(f"[error]Unexpected error: {exc}[/]", title="error", border_style="red"))
        if verbose:
            traceback.print_exc()
        else:
            err_console.print("  [dim](run with --verbose for traceback)[/dim]")
        return 3
