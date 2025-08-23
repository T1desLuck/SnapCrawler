import subprocess
import sys
import pathlib

def test_runner_help():
    root = pathlib.Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "test_runner.py"), "--help"],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0
    assert "Usage" in result.stdout or "help" in result.stdout.lower()
