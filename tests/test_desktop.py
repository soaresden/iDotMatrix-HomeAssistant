"""The desktop Pixel Studio (desktop/pixel_studio.py), in a process of its own:
it replaces Home Assistant with desktop/homeassistant, which must not meet the
real one these tests run on."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_desktop_pixel_studio():
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "desktop/desktop_checks.py"],
        cwd=ROOT, capture_output=True, text=True, timeout=600,
    )
    assert result.returncode == 0, result.stdout[-6000:] + result.stderr[-3000:]
