"""Tests for plan building: target paths, safety rules, conflict resolution."""

import os
from pathlib import Path

import pytest

from quantum_organizer.models import MediaItem, Status
from quantum_organizer.organize import PlanOptions, build_plan, options_fingerprint


def item(path, prov="江苏", city="南京", date="240815", reason=None, status=Status.READY):
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
        status=status,
        reason=reason,
    )


@pytest.fixture
def opts(tmp_path):
    return PlanOptions(root=str(tmp_path))


def test_target_path(opts, tmp_path):
    src = tmp_path / "IMG_1234.jpg"
    src.write_bytes(b"x")
    pi = build_plan([item(src)], opts).items[0]
    assert (pi.decision, pi.target_name) == ("rename", "IMG_1234_江苏_南京_240815.jpg")
    assert pi.target_path == str(tmp_path / "江苏" / "南京" / "IMG_1234_江苏_南京_240815.jpg")
    assert Path(pi.target_path).resolve().is_relative_to(tmp_path.resolve())


def test_unlocated_items_untouched(opts, tmp_path):
    src = tmp_path / "a.jpg"
    src.write_bytes(b"x")
    pi = build_plan([item(src, prov=None, city=None, reason="no_gps")], opts).items[0]
    assert pi.decision == "keep" and pi.target_path is None and pi.item.reason == "no_gps"


def test_move_unlocated_collects_without_renaming(tmp_path):
    src = tmp_path / "a.jpg"
    src.write_bytes(b"x")
    o = PlanOptions(root=str(tmp_path), move_unlocated=True)
    pi = build_plan([item(src, prov=None, city=None, reason="no_gps")], o).items[0]
    assert pi.decision == "move"
    assert pi.target_path == str(tmp_path / "未定位" / "a.jpg")


def test_already_named_file_is_moved_without_stacking(opts, tmp_path):
    # 名称已正确但没归档：仍然移动进 省/市，且绝不叠加后缀
    src = tmp_path / "a_江苏_南京_240815.jpg"
    src.write_bytes(b"x")
    pi = build_plan([item(src)], opts).items[0]
    assert pi.decision == "rename"
    assert pi.target_name == "a_江苏_南京_240815.jpg"
    assert pi.target_path == str(tmp_path / "江苏" / "南京" / "a_江苏_南京_240815.jpg")


def test_filed_and_named_file_is_kept(opts, tmp_path):
    target = tmp_path / "江苏" / "南京" / "a_江苏_南京_240815.jpg"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"x")
    assert build_plan([item(target)], opts).items[0].decision == "keep"


def test_conflict_suffix_avoids_overwrite(opts, tmp_path):
    (tmp_path / "江苏" / "南京").mkdir(parents=True)
    (tmp_path / "江苏" / "南京" / "a_江苏_南京_240815.jpg").write_bytes(b"existing")
    src = tmp_path / "a.jpg"
    src.write_bytes(b"x")
    plan = build_plan([item(src)], opts)
    assert Path(plan.items[0].target_name).name == "a_江苏_南京_240815_2.jpg"


def test_duplicate_targets_inside_one_plan(opts, tmp_path):
    a = tmp_path / "a.jpg"
    a.write_bytes(b"1")
    b = tmp_path / "a.JPG"
    b.write_bytes(b"2")
    plan = build_plan([item(a), item(b)], opts)
    names = sorted(Path(i.target_name).name for i in plan.items)
    assert names == ["a_江苏_南京_240815.JPG", "a_江苏_南京_240815.jpg"]


def test_symlink_refused(opts, tmp_path):
    real = tmp_path / "real.jpg"
    real.write_bytes(b"x")
    link = tmp_path / "link.jpg"
    os.symlink(real, link)
    pi = build_plan([item(link)], opts).items[0]
    assert pi.decision == "skip" and pi.item.reason == "symlink"


def test_invalid_items_kept(opts, tmp_path):
    pi = build_plan(
        [item(tmp_path / "broken.jpg", status=Status.INVALID, reason="unreadable")], opts
    ).items[0]
    assert pi.decision == "keep"


def test_fingerprint_is_stable(tmp_path):
    a = PlanOptions(root=str(tmp_path))
    b = PlanOptions(root=str(tmp_path))
    assert options_fingerprint(a) == options_fingerprint(b)
    assert options_fingerprint(a) != options_fingerprint(PlanOptions(root=str(tmp_path), copy=True))
