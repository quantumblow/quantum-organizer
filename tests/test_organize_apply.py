"""Tests for executing a plan."""

import pytest

from quantum_organizer.history import HistoryStore
from quantum_organizer.models import MediaItem
from quantum_organizer.organize import PlanOptions, apply_plan, build_plan


def _item(path, prov="江苏", city="南京", date="240815"):
    return MediaItem(
        path=str(path),
        size=1,
        mtime=1.0,
        kind="image",
        shoot_time=date,
        time_source="exif",
        lat=32.0,
        lon=118.0,
        gps_source="exiftool",
        province=prov,
        city=city,
        geo_source="exact",
    )


@pytest.fixture
def env(tmp_path):
    media = tmp_path / "src"
    media.mkdir()
    a = media / "a.jpg"
    a.write_bytes(b"1")
    b = media / "b.jpg"
    b.write_bytes(b"2")
    opts = PlanOptions(root=str(media))
    plan = build_plan([_item(a), _item(b, prov=None, city=None)], opts)
    return media, plan, HistoryStore(tmp_path / "h.db"), opts


def test_apply_renames_and_moves(env):
    media, plan, hist, opts = env
    rec = apply_plan(plan, hist, options=opts)
    assert rec.status == "done"
    target = media / "江苏" / "南京" / "a_江苏_南京_240815.jpg"
    assert target.exists() and not (media / "a.jpg").exists()
    assert [s.action for s in rec.steps] == ["move"]  # 命名与归档在一次 move 内完成
    assert (media / "b.jpg").exists()  # 无省市：原地不动，不进 steps


def test_apply_dry_run_changes_nothing(env):
    media, plan, hist, opts = env
    rec = apply_plan(plan, hist, options=opts, dry_run=True)
    assert rec.status == "planned"
    assert (media / "a.jpg").exists() and not (media / "江苏").exists()
    assert rec.steps == []


def test_apply_selection_only(env):
    media, plan, hist, opts = env
    apply_plan(plan, hist, options=opts, selection=[str(media / "b.jpg")])
    assert (media / "a.jpg").exists()
    assert (media / "b.jpg").exists()


def test_apply_is_idempotent(env):
    media, plan, hist, opts = env
    apply_plan(plan, hist, options=opts)
    again = build_plan(
        [_item(media / "江苏" / "南京" / "a_江苏_南京_240815.jpg")], PlanOptions(root=str(media))
    )
    assert again.items[0].decision == "keep"


def test_copy_mode_keeps_source(tmp_path):
    media = tmp_path / "src"
    media.mkdir()
    a = media / "a.jpg"
    a.write_bytes(b"1")
    opts = PlanOptions(root=str(media), copy=True)
    plan = build_plan([_item(a)], opts)
    hist = HistoryStore(tmp_path / "h.db")
    rec = apply_plan(plan, hist, options=opts)
    assert (media / "a.jpg").exists()
    assert (media / "江苏" / "南京" / "a_江苏_南京_240815.jpg").exists()
    assert rec.steps[-1].action == "copy"


def test_apply_aborts_before_touching_when_target_unwritable(env, monkeypatch):
    media, plan, hist, opts = env
    monkeypatch.setattr("quantum_organizer.organize._writable", lambda p: False)
    with pytest.raises(PermissionError):
        apply_plan(plan, hist, options=opts)
    assert (media / "a.jpg").exists()


def test_apply_moves_unlocated(env):
    media, plan, hist, opts = env
    a = media / "c.jpg"
    a.write_bytes(b"3")
    o = PlanOptions(root=str(media), move_unlocated=True)
    plan = build_plan([_item(a, prov=None, city=None)], o)
    apply_plan(plan, hist, options=o)
    assert (media / "未定位" / "c.jpg").exists()
