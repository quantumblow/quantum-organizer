"""CLI flags and the WebAPI must expose the same naming choices."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from quantum_organizer.cli import app
from quantum_organizer.web.app import create_app

FIXTURE = Path(__file__).parent / "fixtures" / "media"
runner = CliRunner()


def _media(tmp_path: Path) -> Path:
    media = tmp_path / "media"
    media.mkdir()
    for name in ("photo_gps.jpg", "photo_nogps.jpg"):
        shutil.copy2(FIXTURE / name, media / name)
    return media


def test_scan_can_skip_renaming(tmp_path):
    media = _media(tmp_path)
    out = tmp_path / "plan.json"
    result = runner.invoke(
        app,
        ["scan", str(media), "--no-rename", "--name-parts", "province,city", "--json", str(out)],
        env={"QORG_STATE_DIR": str(tmp_path / "state")},
    )
    assert result.exit_code == 0, result.output
    targets = [i["target_name"] for i in json.loads(out.read_text())["items"] if i["target_name"]]
    assert targets and all(t.startswith("photo_gps") and "_江苏_南京" not in t for t in targets)


def test_scan_rejects_unknown_name_parts(tmp_path):
    media = _media(tmp_path)
    result = runner.invoke(
        app,
        ["scan", str(media), "--name-parts", "gps"],
        env={"QORG_STATE_DIR": str(tmp_path / "state")},
    )
    assert result.exit_code == 2
    assert "unknown name part" in result.output


def test_web_plan_accepts_name_parts_and_reports_targets(tmp_path):
    media = _media(tmp_path)
    client = TestClient(create_app(state_dir=tmp_path / "state", data_roots=[media]))

    resp = client.post(
        "/api/v1/plans",
        json={"root": str(media), "name_parts": ["time"]},
    )
    assert resp.status_code == 200, resp.text
    plan_id = resp.json()["plan_id"]

    items = client.get(f"/api/v1/plans/{plan_id}/items").json()["items"]
    renamed = [i for i in items if i["target_name"]]
    assert renamed, items
    assert all("_江苏" not in i["target_name"] for i in renamed)


def test_web_plan_rejects_unknown_name_parts(tmp_path):
    media = _media(tmp_path)
    client = TestClient(create_app(state_dir=tmp_path / "state", data_roots=[media]))
    resp = client.post("/api/v1/plans", json={"root": str(media), "name_parts": ["gps"]})
    assert resp.status_code == 400
    assert "unknown name part" in resp.json()["detail"]
