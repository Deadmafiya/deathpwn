"""Tests for output path resolution."""
from pathlib import Path
from deathpwn.utils.output import resolve_output_path, ensure_parent_exists

def test_default_is_cwd():
    p = resolve_output_path("example.com")
    # Default is the linked ctf-flagboard/output resource folder, not CWD.
    from deathpwn.config import DEFAULT_OUTPUT_DIR
    assert p == DEFAULT_OUTPUT_DIR / "example.com-subdomains.txt"
    assert "ctf-flagboard" in str(p) or "output" in str(p)

def test_output_file():
    p = resolve_output_path("example.com", output="/tmp/out.txt")
    assert p == Path("/tmp/out.txt")

def test_output_dir_with_trailing_slash():
    p = resolve_output_path("example.com", output="/tmp/mydir/")
    assert p == Path("/tmp/mydir") / "example.com-subdomains.txt"

def test_output_dir_flag():
    p = resolve_output_path("example.com", output_dir="/tmp/results")
    assert p == Path("/tmp/results/example.com-subdomains.txt")

def test_tilde_expansion():
    p = resolve_output_path("example.com", output="~/out.txt")
    assert "~" not in str(p)
    assert p.name == "out.txt"

def test_output_dir_tilde():
    p = resolve_output_path("example.com", output_dir="~/results")
    assert "~" not in str(p)

def test_ensure_parent(tmp_path):
    target = tmp_path / "a" / "b" / "out.txt"
    ensure_parent_exists(target)
    assert (tmp_path / "a" / "b").is_dir()

def test_existing_dir_as_output(tmp_path):
    d = tmp_path / "mydir"
    d.mkdir()
    p = resolve_output_path("example.com", output=str(d))
    assert p == d / "example.com-subdomains.txt"
