"""Tests for the Web API."""

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from quantum_organizer.web.app import create_app

FX = Path("tests/fixtures/media")


@pytest.fixture
def client(tmp_path):
    media = tmp_path / "src"
    media.mkdir()
    shutil.copy(FX / "photo_gps.jpg", media / "photo_gps.jpg")
    shutil.copy(FX / "photo_nogps.jpg", media / "photo_nogps.jpg")
    app = create_app(state_dir=tmp_path / "state", data_root=str(tmp_path))
    return TestClient(app), media


def test_health(client):
    c, _ = client
    assert c.get("/healthz").json() == {"status": "ok"}


def test_plan_items_are_paginated(client):
    c, media = client
    pid = c.post("/api/v1/plans", json={"root": str(media)}).json()["plan_id"]
    body = c.get(f"/api/v1/plans/{pid}/items", params={"page": 1, "size": 1}).json()
    assert body["total"] == 2 and len(body["items"]) == 1


def test_apply_and_undo(client):
    c, media = client
    pid = c.post("/api/v1/plans", json={"root": str(media)}).json()["plan_id"]
    op = c.post(f"/api/v1/plans/{pid}/apply", json={"dry_run": False}).json()["op_id"]
    assert c.get(f"/api/v1/ops/{op}").json()["status"] == "done"
    assert (media / "江苏" / "南京").is_dir()
    assert c.post(f"/api/v1/ops/{op}/undo").json()["ok"] is True
    assert (media / "photo_gps.jpg").exists()


def test_apply_rejects_foreign_path(client):
    c, media = client
    pid = c.post("/api/v1/plans", json={"root": str(media)}).json()["plan_id"]
    r = c.post(f"/api/v1/plans/{pid}/apply", json={"paths": ["/etc/passwd"]})
    assert r.status_code == 400


def test_root_must_be_under_data_root(client):
    c, _tmp_path = client
    r = c.post("/api/v1/plans", json={"root": "/etc"})
    assert r.status_code == 400


def test_items_filter_by_reason(client):
    c, media = client
    pid = c.post("/api/v1/plans", json={"root": str(media)}).json()["plan_id"]
    body = c.get(f"/api/v1/plans/{pid}/items", params={"reason": "no_gps"}).json()
    assert body["total"] == 1
