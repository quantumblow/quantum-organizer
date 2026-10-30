"""Tests for the qorg CLI."""

import json
import shutil
from pathlib import Path

from typer.testing import CliRunner

from quantum_organizer.cli import app

FX = Path("tests/fixtures/media")
runner = CliRunner()


def _media(tmp_path):
    media = tmp_path / "src"
    media.mkdir()
    shutil.copy(FX / "photo_gps.jpg", media / "photo_gps.jpg")
    return media


def test_scan_writes_json(tmp_path, monkeypatch):
    media = _media(tmp_path)
    monkeypatch.setenv("QORG_STATE_DIR", str(tmp_path / "state"))
    out = tmp_path / "plan.json"
    r = runner.invoke(app, ["scan", str(media), "--json", str(out)])
    assert r.exit_code == 0, r.stdout
    data = json.loads(out.read_text("utf-8"))
    assert data["items"][0]["item"]["province"] == "江苏"


def test_apply_requires_yes(tmp_path, monkeypatch):
    media = _media(tmp_path)
    monkeypatch.setenv("QORG_STATE_DIR", str(tmp_path / "state"))
    r = runner.invoke(app, ["apply", str(media)])
    assert r.exit_code == 2 and "confirm" in r.stdout.lower()
    assert (media / "photo_gps.jpg").exists()


def test_apply_then_undo(tmp_path, monkeypatch):
    media = _media(tmp_path)
    monkeypatch.setenv("QORG_STATE_DIR", str(tmp_path / "state"))
    assert runner.invoke(app, ["scan", str(media)]).exit_code == 0
    assert runner.invoke(app, ["apply", str(media), "--yes"]).exit_code == 0
    assert (media / "江苏" / "南京").is_dir()
    assert runner.invoke(app, ["undo", "--root", str(media)]).exit_code == 0
    assert (media / "photo_gps.jpg").exists()


def test_scan_nothing_to_do_exits_1(tmp_path, monkeypatch):
    media = tmp_path / "empty"
    media.mkdir()
    monkeypatch.setenv("QORG_STATE_DIR", str(tmp_path / "state"))
    assert runner.invoke(app, ["scan", str(media)]).exit_code == 1


def test_apply_dry_run_touches_nothing(tmp_path, monkeypatch):
    media = _media(tmp_path)
    monkeypatch.setenv("QORG_STATE_DIR", str(tmp_path / "state"))
    runner.invoke(app, ["scan", str(media)])
    assert runner.invoke(app, ["apply", str(media), "--dry-run"]).exit_code == 0
    assert (media / "photo_gps.jpg").exists()
