"""The UI is served from the built static bundle."""

from pathlib import Path

from fastapi.testclient import TestClient

from quantum_organizer.web.app import create_app


def test_serves_built_index(tmp_path):
    static = Path("src/quantum_organizer/web/static")
    assert (static / "index.html").exists(), "run `npm run build` in frontend/ first"
    client = TestClient(create_app(state_dir=tmp_path / "state"))
    resp = client.get("/")
    assert resp.status_code == 200 and "qorg" in resp.text.lower()
