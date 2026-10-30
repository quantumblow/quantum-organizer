"""State-directory writability: the Docker volume-ownership trap must fail loudly."""

import os

import pytest
from typer.testing import CliRunner

from quantum_organizer.cli import app, state_writable_probe

runner = CliRunner()


def test_probe_creates_and_reports_ok(tmp_path):
    target = tmp_path / "state"
    assert state_writable_probe(target) is None
    assert target.is_dir()
    assert not (target / ".qorg-write-probe").exists()


def test_probe_reports_reason_when_not_writable(tmp_path):
    if os.geteuid() == 0:  # root 无视权限位
        pytest.skip("running as root")
    locked = tmp_path / "ro"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        reason = state_writable_probe(locked)
        assert reason is not None
        lowered = reason.lower()
        assert any(word in lowered for word in ("denied", "permission", "unable to open"))
    finally:
        locked.chmod(0o700)


def test_serve_refuses_to_start_on_readonly_state(tmp_path, monkeypatch):
    if os.geteuid() == 0:
        pytest.skip("running as root")
    locked = tmp_path / "ro"
    locked.mkdir()
    locked.chmod(0o500)
    monkeypatch.setenv("QORG_STATE_DIR", str(locked))
    try:
        result = runner.invoke(app, ["serve", "--port", "0"])
        assert result.exit_code == 2
        assert "状态目录不可写" in result.output
        assert "chown -R 1000:1000" in result.output
    finally:
        locked.chmod(0o700)


def test_doctor_reports_state_writable(tmp_path, monkeypatch):
    monkeypatch.setenv("QORG_STATE_DIR", str(tmp_path / "state"))
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "state_writable" in result.output
    assert "yes" in result.output
