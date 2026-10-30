"""Directory browsing and multi-root support for the WebUI."""

import os

import pytest
from fastapi.testclient import TestClient

from quantum_organizer.web.app import create_app


@pytest.fixture
def roots(tmp_path):
    pictures = tmp_path / "Pictures"
    videos = tmp_path / "Videos"
    (pictures / "trip").mkdir(parents=True)
    (pictures / ".hidden").mkdir()
    (pictures / "note.txt").write_text("x", encoding="utf-8")
    (videos / "dji").mkdir(parents=True)
    return pictures, videos


@pytest.fixture
def client(tmp_path, roots):
    pictures, videos = roots
    app = create_app(state_dir=tmp_path / "state", data_roots=[pictures, videos])
    return TestClient(app)


def test_roots_lists_every_configured_root(client, roots):
    pictures, videos = roots
    body = client.get("/api/v1/roots").json()
    assert body["roots"] == [str(pictures.resolve()), str(videos.resolve())]


def test_browse_defaults_to_first_root_and_hides_dot_dirs(client, roots):
    pictures, _ = roots
    body = client.get("/api/v1/browse").json()
    assert body["path"] == str(pictures.resolve())
    assert [d["name"] for d in body["dirs"]] == ["trip"]
    assert body["error"] is None
    assert body["parent"] is None  # 已经在根上，不能再往上


def test_browse_navigates_into_a_subdirectory(client, roots):
    pictures, _ = roots
    body = client.get("/api/v1/browse", params={"path": str(pictures / "trip")}).json()
    assert body["path"] == str((pictures / "trip").resolve())
    assert body["parent"] == str(pictures.resolve())


def test_browse_rejects_paths_outside_the_roots(client, tmp_path):
    resp = client.get("/api/v1/browse", params={"path": "/etc"})
    assert resp.status_code == 400
    assert "inside one of" in resp.json()["detail"]


def test_browse_skips_symlinks_pointing_outside(client, roots, tmp_path):
    pictures, _ = roots
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(outside, pictures / "escape")
    names = [d["name"] for d in client.get("/api/v1/browse").json()["dirs"]]
    assert "escape" not in names


def test_browse_reports_permission_denied_without_raising(client, roots):
    if os.geteuid() == 0:  # root 无视权限位
        pytest.skip("running as root, permission bits are ignored")
    pictures, _ = roots
    locked = pictures / "locked"
    locked.mkdir()
    locked.chmod(0o000)
    try:
        body = client.get("/api/v1/browse", params={"path": str(locked)}).json()
        assert body["error"] == "permission_denied"
        assert body["dirs"] == []
    finally:
        locked.chmod(0o755)


def test_plan_accepts_a_root_from_any_configured_root(tmp_path, roots):
    pictures, videos = roots
    (videos / "dji" / "A.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    app = create_app(state_dir=tmp_path / "state", data_roots=[pictures, videos])
    client = TestClient(app)
    resp = client.post("/api/v1/plans", json={"root": str(videos / "dji")})
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


def test_plan_still_rejects_roots_outside_the_allowed_list(client):
    resp = client.post("/api/v1/plans", json={"root": "/etc"})
    assert resp.status_code == 400
    assert "inside one of" in resp.json()["detail"]


def test_readonly_state_surfaces_a_500_with_a_hint(tmp_path, monkeypatch):
    """sqlite 写不进去时，前端要看到可操作的提示，而不是裸 traceback。"""
    import sqlite3

    from quantum_organizer.pipeline import Pipeline

    app = create_app(state_dir=tmp_path / "state", data_roots=[tmp_path])
    client = TestClient(app)

    def boom(self, plan, options=None):
        raise sqlite3.OperationalError("attempt to write a readonly database")

    monkeypatch.setattr(Pipeline, "save_plan", boom)
    root = tmp_path / "media"
    root.mkdir()
    (root / "A.jpg").write_bytes(b"\xff\xd8\xff\xd9")

    resp = client.post("/api/v1/plans", json={"root": str(root)})
    assert resp.status_code == 500
    body = resp.json()
    assert "not writable" in body["detail"]
    assert "chown" in body["hint"]
