"""演练必须回报「会做几步」，并且不影响之后的真实执行。"""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from quantum_organizer.web.app import create_app

FIXTURE = Path(__file__).parent / "fixtures" / "media"


def _client(tmp_path: Path) -> tuple[TestClient, Path]:
    media = tmp_path / "media"
    media.mkdir()
    shutil.copy2(FIXTURE / "photo_gps.jpg", media / "photo_gps.jpg")
    return TestClient(create_app(state_dir=tmp_path / "state", data_roots=[media])), media


def test_dry_run_reports_the_planned_step_count(tmp_path):
    client, media = _client(tmp_path)
    plan_id = client.post("/api/v1/plans", json={"root": str(media)}).json()["plan_id"]

    body = client.post(f"/api/v1/plans/{plan_id}/apply", json={"dry_run": True}).json()
    assert body["status"] == "planned"
    assert body["steps"] == 1

    # 文件一个都没动，计划还能照常执行
    assert (media / "photo_gps.jpg").exists()
    real = client.post(f"/api/v1/plans/{plan_id}/apply", json={"dry_run": False}).json()
    assert real["status"] == "done"
    assert real["steps"] == 1
    assert (media / "江苏" / "南京" / "photo_gps_江苏_南京_140815.jpg").exists()


def test_dry_run_on_a_selection_counts_only_the_selection(tmp_path):
    client, media = _client(tmp_path)
    shutil.copy2(FIXTURE / "photo_nogps.jpg", media / "photo_nogps.jpg")
    plan_id = client.post("/api/v1/plans", json={"root": str(media)}).json()["plan_id"]

    items = client.get(f"/api/v1/plans/{plan_id}/items").json()["items"]
    chosen = [i["item"]["path"] for i in items if i["decision"] == "rename"]
    assert len(chosen) == 1

    body = client.post(
        f"/api/v1/plans/{plan_id}/apply", json={"dry_run": True, "paths": chosen}
    ).json()
    assert body["steps"] == 1
