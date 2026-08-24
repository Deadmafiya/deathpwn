"""Tests for subfinder runner — subprocess mocked."""
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open
import pytest

from deathpwn.tools.registry import TOOL_REGISTRY
from deathpwn.tools.subfinder import ToolNotFound, ToolExecutionError


def _popen_mock(lines, returncode=0, stderr=""):
    m = MagicMock()
    m.stdout = iter([l + "\n" for l in lines])
    m.stderr = MagicMock()
    m.stderr.read.return_value = stderr
    m.returncode = returncode
    m.wait.return_value = returncode
    return m


def test_streams_and_saves(tmp_path, capsys):
    out = tmp_path / "example.com-subdomains.txt"
    popen = _popen_mock(["a.example.com", "b.example.com"])
    with patch("deathpwn.tools.subfinder.shutil.which", return_value="/usr/bin/subfinder"), \
         patch("deathpwn.tools.subfinder.subprocess.Popen", return_value=popen):
        from deathpwn.tools.subfinder import run_subfinder
        count = run_subfinder("example.com", output=out)
    assert count == 2
    assert out.read_text().splitlines() == ["a.example.com", "b.example.com"]
    captured = capsys.readouterr()
    assert "a.example.com" in captured.out

def test_zero_results(tmp_path, capsys):
    out = tmp_path / "example.com-subdomains.txt"
    popen = _popen_mock([])
    with patch("deathpwn.tools.subfinder.shutil.which", return_value="/usr/bin/subfinder"), \
         patch("deathpwn.tools.subfinder.subprocess.Popen", return_value=popen):
        from deathpwn.tools.subfinder import run_subfinder
        count = run_subfinder("example.com", output=out)
    assert count == 0
    assert out.read_text() == ""
    assert "No subdomains" in capsys.readouterr().out

def test_nonzero_no_results_raises(tmp_path):
    out = tmp_path / "out.txt"
    popen = _popen_mock([], returncode=1, stderr="api error")
    with patch("deathpwn.tools.subfinder.shutil.which", return_value="/usr/bin/subfinder"), \
         patch("deathpwn.tools.subfinder.subprocess.Popen", return_value=popen):
        from deathpwn.tools.subfinder import run_subfinder
        with pytest.raises(ToolExecutionError, match="api error"):
            run_subfinder("example.com", output=out)

def test_nonzero_with_results_does_not_raise(tmp_path):
    out = tmp_path / "out.txt"
    popen = _popen_mock(["a.example.com"], returncode=1, stderr="some warning")
    with patch("deathpwn.tools.subfinder.shutil.which", return_value="/usr/bin/subfinder"), \
         patch("deathpwn.tools.subfinder.subprocess.Popen", return_value=popen):
        from deathpwn.tools.subfinder import run_subfinder
        count = run_subfinder("example.com", output=out)
    assert count == 1

def test_binary_missing():
    with patch("deathpwn.tools.subfinder.shutil.which", return_value=None):
        from deathpwn.tools.subfinder import run_subfinder
        with pytest.raises(ToolNotFound, match="subfinder not found"):
            run_subfinder("example.com", output=Path("/tmp/x.txt"))

def test_registry_has_subfinder():
    import deathpwn.tools  # noqa: F401
    assert "subfinder" in TOOL_REGISTRY

def test_all_flag_passed(tmp_path):
    out = tmp_path / "out.txt"
    popen = _popen_mock(["a.example.com"])
    with patch("deathpwn.tools.subfinder.shutil.which", return_value="/usr/bin/subfinder"), \
         patch("deathpwn.tools.subfinder.subprocess.Popen", return_value=popen) as mock_popen:
        from deathpwn.tools.subfinder import run_subfinder
        run_subfinder("example.com", output=out, all_sources=True)
        args = mock_popen.call_args[0][0]
        assert "-all" in args

def test_parent_dir_created(tmp_path):
    out = tmp_path / "newdir" / "sub" / "out.txt"
    popen = _popen_mock(["a.example.com"])
    with patch("deathpwn.tools.subfinder.shutil.which", return_value="/usr/bin/subfinder"), \
         patch("deathpwn.tools.subfinder.subprocess.Popen", return_value=popen):
        from deathpwn.tools.subfinder import run_subfinder
        run_subfinder("example.com", output=out)
    assert out.exists()
