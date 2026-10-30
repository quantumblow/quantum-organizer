"""Tests for the scanning pipeline."""

import shutil
from pathlib import Path

import pytest

from quantum_organizer.organize import PlanOptions
from quantum_organizer.pipeline import Pipeline

FX = Path("tests/fixtures/media")


@pytest.fixture
def media(tmp_path):
    d = tmp_path / "src"
    d.mkdir()
    for name in ("photo_gps.jpg", "photo_nogps.jpg", "plain.mp4", "broken.jpg"):
        shutil.copy(FX / name, d / name)
    return d


def test_scan_fills_geocode_and_plan(media, tmp_path):
    p = Pipeline(tmp_path / "state")
    plan = p.scan(PlanOptions(root=str(media)))
    by_name = {Path(i.item.path).name: i for i in plan.items}
    assert by_name["photo_gps.jpg"].item.province == "江苏"
    assert by_name["photo_gps.jpg"].item.city == "南京"
    assert by_name["photo_gps.jpg"].decision == "rename"
    assert by_name["photo_nogps.jpg"].decision == "keep"
    assert by_name["plain.mp4"].decision == "keep"
    assert by_name["broken.jpg"].item.status.value == "invalid"


def test_scan_reports_progress(media, tmp_path):
    seen = []
    p = Pipeline(tmp_path / "state")
    p.scan(PlanOptions(root=str(media)), progress=lambda i, n, name: seen.append((i, n)) or True)
    assert seen[-1] == (4, 4)


def test_scan_can_be_aborted(media, tmp_path):
    p = Pipeline(tmp_path / "state")
    plan = p.scan(PlanOptions(root=str(media)), progress=lambda i, n, name: i < 1)
    assert len(plan.items) == 1


def test_scan_cache_skips_reextraction(media, tmp_path):
    p = Pipeline(tmp_path / "state")
    p.scan(PlanOptions(root=str(media)))
    calls = []
    real = p.extractor.extract
    p.extractor.extract = lambda path: calls.append(path) or real(path)
    p.scan(PlanOptions(root=str(media)))
    assert calls == []


def test_scan_refuses_above_limit(media, tmp_path):
    p = Pipeline(tmp_path / "state", max_files=2)
    with pytest.raises(ValueError, match="max_files"):
        p.scan(PlanOptions(root=str(media)))


def test_scan_ignores_non_media(media, tmp_path):
    (media / "notes.txt").write_text("x")
    plan = Pipeline(tmp_path / "state").scan(PlanOptions(root=str(media)))
    assert all(Path(i.item.path).suffix != ".txt" for i in plan.items)


def test_scan_is_recursive(media, tmp_path):
    sub = media / "2024" / "day1"
    sub.mkdir(parents=True)
    shutil.copy(FX / "photo_gps.jpg", sub / "nested.jpg")
    plan = Pipeline(tmp_path / "state").scan(PlanOptions(root=str(media)))
    assert any(Path(i.item.path).name == "nested.jpg" for i in plan.items)
