"""qorg CLI entry point.

Sub-commands are added by later tasks; ``doctor`` is the first one because every
other command depends on ffmpeg/exiftool being present.
"""

from __future__ import annotations

import importlib.util
import os
import platform
import shutil
from pathlib import Path

import typer

app = typer.Typer(add_completion=False, help="qorg — organize photo/video folders by province/city")

DEFAULT_STATE_DIR = Path.home() / ".local" / "state" / "quantum-organizer"

_EXTERNAL_TOOLS = ("ffmpeg", "ffprobe", "exiftool")


def state_dir() -> Path:
    """Resolve the state directory (never inside the user's media folders)."""
    return Path(os.environ.get("QORG_STATE_DIR", DEFAULT_STATE_DIR))


def _install_hint() -> str:
    if platform.system() == "Darwin":
        return "brew install ffmpeg exiftool"
    return "apt install ffmpeg libimage-exiftool-perl"


def doctor_report() -> dict[str, str]:
    """Report external tool + dependency status as a flat dict."""
    report = {name: (shutil.which(name) or "missing") for name in _EXTERNAL_TOOLS}
    has_locator = importlib.util.find_spec("quantum_locator") is not None
    report["quantum_locator"] = "installed" if has_locator else "missing"
    report["state_dir"] = str(state_dir())
    missing = [n for n in _EXTERNAL_TOOLS if report[n] == "missing"]
    report["hint"] = _install_hint() if missing else "all external tools present"
    return report


@app.callback()
def main() -> None:
    """Root command: keeps Typer in multi-command mode."""


@app.command()
def doctor() -> None:
    """Check external tools, the locator dependency and the state directory."""
    report = doctor_report()
    for key, value in report.items():
        if key == "hint":
            continue
        typer.echo(f"{key:16s} {value}")
    typer.echo(f"hint             {report['hint']}")


if __name__ == "__main__":  # pragma: no cover
    app()
