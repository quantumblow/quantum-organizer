"""qorg CLI — thin shell over :mod:`quantum_organizer.pipeline`."""

from __future__ import annotations

import importlib.util
import os
import platform
import shutil
from pathlib import Path

import typer

from quantum_organizer.organize import PlanOptions
from quantum_organizer.pipeline import Pipeline

app = typer.Typer(
    add_completion=False, help="qorg — organize photo/video folders by Chinese province/city"
)

DEFAULT_STATE_DIR = Path.home() / ".local" / "state" / "quantum-organizer"

_EXTERNAL_TOOLS = ("ffmpeg", "ffprobe", "exiftool")

EXIT_OK = 0
EXIT_NOTHING = 1
EXIT_BLOCKED = 2
EXIT_PARTIAL = 3


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


def _pipeline(allow_estimate: bool = False) -> Pipeline:
    from quantum_organizer.geocode import Geocoder

    geocoder = Geocoder(
        remote_url=os.environ.get("QORG_GEOCODER_URL") or None,
        allow_estimate=allow_estimate,
    )
    return Pipeline(state_dir(), geocoder=geocoder)


def _print_preview(plan) -> None:
    if not plan.items:
        typer.echo("没有找到媒体文件")
        return
    typer.echo(f"{'original':34s} {'decision':8s} target / reason")
    for pi in plan.items[:30]:
        target = pi.target_path or f"[{pi.decision}] {pi.item.reason or '-'}"
        typer.echo(f"{Path(pi.item.path).name:34s} {pi.decision:8s} {target}")
    if len(plan.items) > 30:
        typer.echo(f"... {len(plan.items)} items total, {len(plan.items) - 30} hidden")


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


@app.command()
def scan(
    root: Path = typer.Argument(..., help="material directory to scan"),
    output: Path | None = typer.Option(None, "--output", "-o", help="unified output root"),
    recursive: bool = typer.Option(True, "--recursive/--no-recursive", help="scan subdirectories"),
    json_out: Path | None = typer.Option(None, "--json", help="write the plan as JSON"),
    allow_estimate: bool = typer.Option(
        False, "--allow-estimate", help="allow city-centre estimate"
    ),
) -> None:
    """Scan a directory and build a plan (never modifies files)."""
    opts = PlanOptions(
        root=str(root),
        output_dir=str(output) if output else None,
        recursive=recursive,
        allow_estimate=allow_estimate,
    )
    pipeline = _pipeline(allow_estimate=allow_estimate)
    plan = pipeline.scan(opts)
    pipeline.save_plan(plan)

    _print_preview(plan)
    typer.echo(f"plan: {plan.plan_id}  counts: {plan.counts}")

    if json_out is not None:
        json_out.write_text(plan.to_json(), encoding="utf-8")
        typer.echo(f"plan written to {json_out}")

    if plan.counts.get("rename", 0) + plan.counts.get("move", 0) == 0:
        raise typer.Exit(EXIT_NOTHING)
    raise typer.Exit(EXIT_OK)


@app.command()
def apply(
    root: Path = typer.Argument(..., help="material directory (same as scan)"),
    plan_id: str | None = typer.Option(None, "--plan", help="plan id, defaults to the latest"),
    select: Path | None = typer.Option(None, "--select", help="file with one path per line"),
    dry_run: bool = typer.Option(False, "--dry-run", help="show what would happen"),
    yes: bool = typer.Option(False, "--yes", help="confirm execution"),
    copy: bool = typer.Option(False, "--copy", help="copy instead of move"),
    move_unlocated: bool = typer.Option(False, "--move-unlocated", help="collect unlocated files"),
    output: Path | None = typer.Option(None, "--output", "-o", help="unified output root"),
    allow_estimate: bool = typer.Option(False, "--allow-estimate"),
) -> None:
    """Execute the latest plan for *root* as one undoable operation."""
    opts = PlanOptions(
        root=str(root),
        output_dir=str(output) if output else None,
        copy=copy,
        move_unlocated=move_unlocated,
        allow_estimate=allow_estimate,
    )
    pipeline = _pipeline(allow_estimate=allow_estimate)

    if not dry_run and not yes:
        typer.echo("preview only; re-run with --yes to confirm")
        raise typer.Exit(EXIT_BLOCKED)

    try:
        plan = pipeline.load_plan(plan_id, str(root.resolve()), options=opts)
    except KeyError:
        typer.echo("no plan found, run `qorg scan` first")
        raise typer.Exit(EXIT_BLOCKED) from None
    except ValueError as exc:
        typer.echo(f"{exc} (re-run `qorg scan`)")
        raise typer.Exit(EXIT_BLOCKED) from None

    selection = None
    if select is not None:
        selection = [
            line.strip() for line in select.read_text("utf-8").splitlines() if line.strip()
        ]

    record = pipeline.apply(plan, selection=selection, dry_run=dry_run, options=opts)
    typer.echo(f"op: {record.op_id}  status: {record.status}  steps: {len(record.steps)}")
    raise typer.Exit(EXIT_PARTIAL if record.status == "partial" else EXIT_OK)


@app.command()
def undo(
    op: int | None = typer.Option(None, "--op", help="operation id, defaults to the latest"),
    root: Path | None = typer.Option(None, "--root", help="latest operation under this root"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Undo one operation in reverse order; stop and report on the first inconsistency."""
    pipeline = _pipeline()
    try:
        result = pipeline.undo(
            op_id=op, root=str(root.resolve()) if root else None, dry_run=dry_run
        )
    except KeyError:
        typer.echo("nothing to undo")
        raise typer.Exit(EXIT_NOTHING) from None
    except RuntimeError as exc:
        typer.echo(str(exc))
        raise typer.Exit(EXIT_BLOCKED) from None

    typer.echo(f"op: {result.op_id}  reverted: {result.reverted}  ok: {result.ok}")
    for conflict in result.conflicts:
        typer.echo(f"conflict: {conflict}")
    raise typer.Exit(EXIT_OK if result.ok else EXIT_PARTIAL)


@app.command()
def serve(
    data: Path = typer.Option(Path("/data"), "--data", help="media root the WebUI may touch"),
    port: int = typer.Option(8080, "--port"),
    host: str = typer.Option("0.0.0.0", "--host"),
) -> None:
    """Start the WebUI."""
    import uvicorn

    from quantum_organizer.web.app import create_app

    uvicorn.run(create_app(state_dir(), data_root=str(data)), host=host, port=port, workers=1)


if __name__ == "__main__":  # pragma: no cover
    app()
