"""qorg CLI — thin shell over :mod:`quantum_organizer.pipeline`."""

from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import sqlite3
from pathlib import Path

import typer

from quantum_organizer import naming
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


def media_roots(cli_roots: list[Path] | None) -> list[Path]:
    """Decide which media roots the WebUI may touch.

    Order of precedence: ``--data`` flags, ``QORG_DATA_ROOTS`` (``os.pathsep``-separated),
    then the photographer defaults (~/Pictures, ~/Videos), then ``/data`` (the image workdir),
    and finally the home directory.
    """
    if cli_roots:
        return [Path(p).expanduser() for p in cli_roots]

    env = os.environ.get("QORG_DATA_ROOTS")
    if env:
        return [Path(p).expanduser() for p in env.split(os.pathsep) if p.strip()]

    home = Path.home()
    defaults = [home / "Pictures", home / "Videos"]
    existing = [p for p in defaults if p.is_dir()]
    if existing:
        return existing
    if Path("/data").is_dir():
        return [Path("/data")]
    return [home]


def state_writable_probe(path: Path) -> str | None:
    """Return None when ``path`` is writable, else a short reason.

    Opens a throwaway SQLite database, because a plain file write can succeed while SQLite still
    refuses to write (journals, ownership, read-only mounts) — that is the failure users hit.
    """
    db = path / ".qorg-probe.db"
    try:
        path.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db)
        try:
            conn.execute("CREATE TABLE probe (x INTEGER)")
            conn.commit()
        finally:
            conn.close()
        db.unlink()
    except (OSError, sqlite3.Error) as exc:
        return str(exc)
    return None


def _readonly_hint(path: Path) -> str:
    """Explain the classic Docker bind/volume ownership trap in one place."""
    return (
        f"状态目录不可写：{path}\n"
        "通常是旧的 Docker 卷由 root 创建（老镜像以 root 运行），而现在镜像以 uid 1000 运行。\n"
        "修复（保留历史记录）：\n"
        "  docker run --rm -v <你的卷>:/state python:3.12-slim chown -R 1000:1000 /state\n"
        "或者换一个新卷；绑挂载目录则 chown 一次即可。"
    )


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
    probe_error = state_writable_probe(state_dir())
    report["state_writable"] = "yes" if probe_error is None else f"no ({probe_error})"
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
    copy: bool = typer.Option(False, "--copy", help="copy instead of move"),
    move_unlocated: bool = typer.Option(False, "--move-unlocated", help="collect unlocated files"),
    allow_estimate: bool = typer.Option(
        False, "--allow-estimate", help="allow city-centre estimate"
    ),
    rename: bool = typer.Option(
        True, "--rename/--no-rename", help="append a suffix to source files (default: on)"
    ),
    name_parts: str = typer.Option(
        "province,city,time",
        "--name-parts",
        help="suffix segments, any combination of: province,city,time",
    ),
) -> None:
    """Scan a directory and build a plan (never modifies files)."""
    try:
        parts = naming.normalize_parts(name_parts)
    except ValueError as exc:
        typer.echo(f"invalid --name-parts: {exc}")
        raise typer.Exit(EXIT_BLOCKED) from exc
    opts = PlanOptions(
        root=str(root),
        output_dir=str(output) if output else None,
        recursive=recursive,
        copy=copy,
        move_unlocated=move_unlocated,
        allow_estimate=allow_estimate,
        rename=rename,
        name_parts=parts,
    )
    pipeline = _pipeline(allow_estimate=allow_estimate)
    plan = pipeline.scan(opts)
    pipeline.save_plan(plan, options=opts)

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
    allow_estimate: bool = typer.Option(False, "--allow-estimate"),
) -> None:
    """Execute the latest plan for *root* as one undoable operation.

    执行语义来自 `qorg scan` 时存下的选项（--copy/--output/--move-unlocated 在 scan 上传）。
    """
    if not dry_run and not yes:
        typer.echo("preview only; re-run with --yes to confirm")
        raise typer.Exit(EXIT_BLOCKED)

    pipeline = _pipeline(allow_estimate=allow_estimate)
    try:
        plan = pipeline.load_plan(plan_id, str(root.resolve()))
        opts = pipeline.load_plan_options(plan.plan_id)
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
    data: list[Path] | None = typer.Option(
        None,
        "--data",
        help="media root the WebUI may touch; repeat for several (default: ~/Pictures, ~/Videos)",
    ),
    port: int = typer.Option(8080, "--port"),
    host: str = typer.Option("0.0.0.0", "--host"),
) -> None:
    """Start the WebUI."""
    import uvicorn

    from quantum_organizer.web.app import create_app

    probe_error = state_writable_probe(state_dir())
    if probe_error is not None:
        typer.echo(_readonly_hint(state_dir()))
        raise typer.Exit(EXIT_BLOCKED)

    roots = media_roots(data)
    for root in roots:
        typer.echo(f"root: {root}")
    uvicorn.run(
        create_app(state_dir(), data_roots=[str(r) for r in roots]),
        host=host,
        port=port,
        workers=1,
    )


if __name__ == "__main__":  # pragma: no cover
    app()
