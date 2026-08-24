"""DeathPWN CLI — natural-language bug bounty runner."""

from __future__ import annotations

import argparse
import sys
import traceback

from deathpwn import __version__

# ---------------------------------------------------------------------------
# ANSI helpers
# ---------------------------------------------------------------------------

RED = "31"
GREEN = "32"
CYAN = "36"
YELLOW = "33"
DIM = "90"
RESET = "0"


def _color(text: str, code: str) -> str:
    if sys.stdout.isatty():
        return f"\033[{code}m{text}\033[0m"
    return text


def _red(s: str) -> str:
    return _color(s, RED)


def _green(s: str) -> str:
    return _color(s, GREEN)


def _cyan(s: str) -> str:
    return _color(s, CYAN)


def _yellow(s: str) -> str:
    return _color(s, YELLOW)


def _dim(s: str) -> str:
    return _color(s, DIM)


def _bold(s: str) -> str:
    return _color(s, "1")


# ---------------------------------------------------------------------------
# argparse
# ---------------------------------------------------------------------------

_EXAMPLES = """\
examples:
  deathpwn "find subdomains for https://example.com"
  deathpwn "find subs for example.com" -o out.txt
  deathpwn "enumerate subdomains of example.com" --all --verbose\
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
        help="Output file path (default: ./<domain>-subdomains.txt)",
    )
    p.add_argument(
        "--output-dir",
        dest="output_dir",
        default=None,
        help="Output directory (default: current directory)",
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
        help="Ollama model (default: functiongemma:latest)",
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
            print(f"{parser.prog}: error: the following arguments are required: query", file=sys.stderr)
            print(file=sys.stderr)
            print(_EXAMPLES, file=sys.stderr)
            print(_yellow('  hint: try  deathpwn "find subdomains for example.com"'), file=sys.stderr)
            return 2

        query_text = " ".join(args.query)

        # 3. Understanding line
        if args.verbose:
            print(_dim(f'[*] Understanding: "{query_text}"...'), flush=True)
        else:
            print(_dim("→ Interpreting request..."), flush=True)

        # 4. Call LLM
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
        except OllamaUnavailable as exc:
            fb = fallback_tool_call(query_text)
            if fb is not None:
                print(_dim(f"  [*] Ollama unreachable — using local parser: {fb}"), flush=True)
                tool_call = fb
            else:
                msg = str(exc) or f"Ollama not reachable. Is it running? Try: ollama serve"
                if "ollama serve" not in msg.lower():
                    msg = f"{msg} Is it running? Try: ollama serve"
                print(_red(msg), file=sys.stderr)
                return 4
        except ModelNotFound as exc:
            msg = str(exc)
            model_name = args.model or "functiongemma:latest"
            if "ollama pull" not in msg.lower():
                msg = f"Model {model_name} not found. Try: ollama pull {model_name}"
            print(_red(msg), file=sys.stderr)
            return 4
        except OllamaTimeout as exc:
            # Retry via fast regex fallback before failing
            fb = fallback_tool_call(query_text)
            if fb is not None:
                print(_dim(f"  [*] FunctionGemma slow — using local parser: {fb}"), flush=True)
                tool_call = fb
            else:
                msg = str(exc) or "Ollama timed out. Try again or check Ollama status."
                if "timed out" not in msg.lower():
                    msg = f"Ollama timed out: {msg}"
                print(_red(msg), file=sys.stderr)
                return 4
        except LLMParseError as exc:
            fb = fallback_tool_call(query_text)
            if fb is not None:
                print(_dim(f"  [*] LLM parse error — using local parser: {fb}"), flush=True)
                tool_call = fb
            else:
                print(_red(f"LLM error: {exc}"), file=sys.stderr)
                return 4

        # 5. Hallucination guard — drop subfinder call when English has no subdomain intent
        if tool_call is not None:
            from deathpwn.utils.domain import _looks_like_subdomain_request

            if not _looks_like_subdomain_request(query_text):
                if args.verbose:
                    print(_dim("  [*] Discarding hallucinated tool_call — query has no subdomain intent"), flush=True)
                print("No matching tool for that request.", file=sys.stderr)
                print("I currently support:", file=sys.stderr)
                print('  • find subdomains — e.g. deathpwn "find subdomains for example.com"', file=sys.stderr)
                return 1

        # 5b. No tool matched
        if tool_call is None:
            print("No matching tool for that request.", file=sys.stderr)
            print("I currently support:", file=sys.stderr)
            print('  • find subdomains — e.g. deathpwn "find subdomains for example.com"', file=sys.stderr)
            if args.verbose:
                print(_dim("  (model returned no tool_call — try rephrasing)"), file=sys.stderr)
            return 1

        if args.verbose:
            print(_dim(f"[*] Tool call: {tool_call}"), flush=True)
            if isinstance(tool_call, dict) and tool_call.get("content"):
                print(_dim(f"  model content: {tool_call['content']}"), file=sys.stderr)

        # 6. Extract domain
        arguments = tool_call.get("arguments", {}) if isinstance(tool_call, dict) else {}
        if not isinstance(arguments, dict):
            arguments = {}
        domain_raw = arguments.get("domain", "")
        if not isinstance(domain_raw, str):
            domain_raw = str(domain_raw) if domain_raw is not None else ""
        # handle missing domain
        if not domain_raw or not domain_raw.strip():
            print(_red(f'Could not extract valid domain from \'{domain_raw}\'. Try: deathpwn "find subdomains for example.com"'), file=sys.stderr)
            return 2

        # 7. Normalize + validate
        from deathpwn.utils.domain import normalize_domain, validate_domain

        domain = normalize_domain(domain_raw)

        if args.verbose:
            print(_dim(f'[*] Raw domain: "{domain_raw}" -> normalized: "{domain}"'), flush=True)

        if not validate_domain(domain):
            print(_red(f'Could not extract valid domain from \'{domain_raw}\'. Try: deathpwn "find subdomains for example.com"'), file=sys.stderr)
            return 2

        # 8. Resolve output
        from deathpwn.utils.output import resolve_output_path

        output_path = resolve_output_path(domain, args.output, args.output_dir)

        # 9. all_sources
        all_sources = bool(arguments.get("all_sources", False)) or bool(args.all)

        # handle --json flag (warn but continue)
        if args.json_output:
            print(_dim("[*] Note: --json flag is accepted but JSON output is not yet implemented in v0.1 (txt only)."), flush=True)

        # 10. Dry-run
        if args.dry_run:
            cmd_preview = f"subfinder -d {domain} -silent" + (" -all" if all_sources else "")
            print(f"[DRY-RUN] Would run: {cmd_preview}\nOutput: {output_path}")
            return 0

        # 11. Registry dispatch
        import deathpwn.tools  # noqa: F401  ensure subfinder registered
        from deathpwn.tools import registry

        tool_name = tool_call.get("name", "") if isinstance(tool_call, dict) else ""
        fn = registry.TOOL_REGISTRY.get(tool_name)
        if fn is None:
            print(_red(f'Unknown tool "{tool_name}".'), file=sys.stderr)
            known = ", ".join(sorted(registry.TOOL_REGISTRY)) or "(none)"
            print(_dim(f"  Known tools: {known}"), file=sys.stderr)
            return 3

        # 12. Header
        print(f"[*] Finding subdomains for {domain}...", flush=True)

        # 13. Call tool
        from deathpwn.tools.subfinder import ToolExecutionError, ToolNotFound

        try:
            count = fn(domain, output=output_path, all_sources=all_sources, verbose=args.verbose)
        except ToolNotFound as exc:
            print(_red(str(exc)), file=sys.stderr)
            return 3
        except ToolExecutionError as exc:
            print(_red(f"Subfinder failed: {exc}"), file=sys.stderr)
            return 3
        except KeyboardInterrupt:
            return 130

        # 14. Summary
        if count > 0:
            print(_green(f"[+] Found {count} subdomains → {output_path}"), flush=True)
            return 0
        else:
            print(f"[*] No subdomains found (saved empty file at {output_path})", flush=True)
            return 1

    except SystemExit:
        raise
    except Exception as exc:
        # top-level unexpected
        verbose = False
        try:
            verbose = bool(args.verbose)  # type: ignore[possibly-undefined]
        except Exception:
            pass
        print(_red(f"Unexpected error: {exc}"), file=sys.stderr)
        if verbose:
            traceback.print_exc()
        else:
            print(_dim("  (run with --verbose for traceback)"), file=sys.stderr)
        return 3
