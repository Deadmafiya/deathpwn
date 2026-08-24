"""Output path resolution for DeathPWN results.

Resolves where subfinder results are saved. Supports an explicit
file/directory path, an output directory, or the default cwd location.
All returned paths are expanded (``~``) and normalized to absolute
form. Directory creation is deferred to :func:`ensure_parent_exists`.

Streaming tee integration (see plan § Subfinder execution — streaming tee):
    subfinder is run via ``Popen(..., stdout=PIPE, text=True, bufsize=1)``
    and each line is teed to stdout + file. The file path comes from
    :func:`resolve_output_path`; the caller creates parent dirs via
    :func:`ensure_parent_exists` before opening the file. ``-o`` in
    subfinder itself is not used so output streams live.
"""

from __future__ import annotations

from pathlib import Path


def resolve_output_path(
    domain: str,
    output: str | None = None,
    output_dir: str | None = None,
) -> Path:
    """Resolve the output file path for a domain's subdomains.

    Priority:
        1. ``output`` — explicit file path or directory.
        2. ``output_dir`` — directory in which to place the default-named file.
        3. Fallback — current working directory.

    The default filename is ``f"{domain}-subdomains.txt"``.

    Normalization:
        * ``~`` is expanded via :meth:`pathlib.Path.expanduser`.
        * Result is made absolute via :meth:`pathlib.Path.resolve`
          (strict=False — does not require existence). Returned path is
          always absolute, with ``~`` resolved.

    Directory handling for ``output``:
        If ``output`` looks like a directory — the raw string ends with
        ``/`` or ``\\`` *or* the expanded path exists and
        :meth:`Path.is_dir` is true — the default filename is appended
        (``Path(output) / f"{domain}-subdomains.txt"``).

    No filesystem mutation is performed here. If ``output_dir`` does not
    exist it is *not* created — the caller must call
    :func:`ensure_parent_exists` before writing. Parent creation for the
    ``output`` case is likewise deferred to the caller.

    Args:
        domain: Target domain, e.g. ``"example.com"``. Used only for the
            default filename.
        output: Explicit output path. May be a file path
            (``"/tmp/out.txt"``, ``"./results.txt"``, ``"~/out.txt"``) or a
            directory (``"/tmp/"``, ``"results/"``, or an existing directory
            path). ``None`` or empty string is treated as not provided.
        output_dir: Directory in which to create the default-named file.
            Ignored when ``output`` is provided. ``None`` or empty string
            is treated as not provided.

    Returns:
        Absolute :class:`pathlib.Path` to the file that should be written.
        Parent directories may not yet exist.

    Example:
        >>> resolve_output_path("example.com", output="~/out.txt")
        PosixPath('/home/user/out.txt')
        >>> resolve_output_path("example.com", output="/tmp/")
        PosixPath('/tmp/example.com-subdomains.txt')
        >>> resolve_output_path("example.com", output_dir="~/results")
        PosixPath('/home/user/results/example.com-subdomains.txt')
        >>> resolve_output_path("example.com")
        PosixPath('/cwd/example.com-subdomains.txt')
    """
    default_name = f"{domain}-subdomains.txt"

    def _normalize(p: Path) -> Path:
        """Expand ``~`` and make absolute without requiring existence."""
        return p.expanduser().resolve()

    if output:
        raw = output
        p = Path(raw).expanduser()
        is_dir_hint = raw.endswith("/") or raw.endswith("\\")
        if is_dir_hint or (p.exists() and p.is_dir()):
            return _normalize(p) / default_name
        return _normalize(p)

    if output_dir:
        return _normalize(Path(output_dir)) / default_name

    return Path.cwd() / default_name


def ensure_parent_exists(path: Path) -> None:
    """Ensure the parent directory of *path* exists.

    Creates ``path.parent`` and any missing ancestors
    (``mkdir(parents=True, exist_ok=True)``).

    Args:
        path: File path whose parent should exist. The file itself is
            not created.

    Example:
        >>> ensure_parent_exists(Path("/tmp/a/b/out.txt"))
        # creates /tmp/a/b if needed
    """
    path.parent.mkdir(parents=True, exist_ok=True)
