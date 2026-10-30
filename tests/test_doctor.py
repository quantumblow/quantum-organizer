"""Tests for ``qorg doctor``."""

from quantum_organizer.cli import doctor_report


def test_reports_missing_tools(monkeypatch):
    monkeypatch.setattr(
        "quantum_organizer.cli.shutil.which", lambda n: {"ffmpeg": "/usr/bin/ffmpeg"}.get(n)
    )
    r = doctor_report()
    assert r["ffmpeg"] == "/usr/bin/ffmpeg"
    assert r["exiftool"] == "missing"
    assert "libimage-exiftool-perl" in r["hint"]


def test_reports_all_present(monkeypatch):
    monkeypatch.setattr("quantum_organizer.cli.shutil.which", lambda n: f"/usr/bin/{n}")
    r = doctor_report()
    assert "missing" not in r["ffmpeg"] + r["exiftool"]
    assert r["quantum_locator"] != "missing"


def test_reports_state_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("QORG_STATE_DIR", str(tmp_path / "state"))
    assert doctor_report()["state_dir"] == str(tmp_path / "state")
