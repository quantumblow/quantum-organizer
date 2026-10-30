"""Choose which segments a renamed file gets: province / city / time, any combination."""

from __future__ import annotations

import pytest

from quantum_organizer import naming
from quantum_organizer.models import MediaItem, Status
from quantum_organizer.organize import PlanOptions, build_plan


def _item(path, province="江苏", city="南京", shoot_time: str | None = "240815"):
    return MediaItem(
        path=str(path),
        kind="photo",
        size=1,
        mtime=0.0,
        province=province,
        city=city,
        shoot_time=shoot_time,
        status=Status.READY,
    )


@pytest.mark.parametrize(
    ("parts", "expected"),
    [
        (("province", "city", "time"), "IMG_1234_江苏_南京_240815.jpg"),
        (("province", "city"), "IMG_1234_江苏_南京.jpg"),
        (("city",), "IMG_1234_南京.jpg"),
        (("time",), "IMG_1234_240815.jpg"),
        ((), "IMG_1234.jpg"),
    ],
)
def test_build_name_honours_the_selection(parts, expected):
    assert naming.build_name("IMG_1234", "江苏", "南京", "240815", ".jpg", parts=parts) == expected


@pytest.mark.parametrize("parts", [("province", "city", "time"), ("province", "city"), ("time",)])
def test_renaming_is_idempotent_for_every_combination(parts):
    once = naming.build_name("IMG_1234", "江苏", "南京", "240815", ".jpg", parts=parts)
    again = naming.build_name(
        once.removesuffix(".jpg"), "江苏", "南京", "240815", ".jpg", parts=parts
    )
    assert again == once


def test_switching_from_three_parts_to_two_drops_the_time_segment():
    old = "IMG_1234_江苏_南京_240815"
    new = naming.build_name(old, "江苏", "南京", "240816", ".jpg", parts=("province", "city"))
    assert new == "IMG_1234_江苏_南京.jpg"


def test_numeric_tails_are_not_mistaken_for_a_date_suffix():
    assert naming.build_name("DSC_0047_140620", "江苏", "南京", "240815", ".jpg", parts=()) == (
        "DSC_0047_140620.jpg"
    )
    # 时间模式会追加，但原来的数字尾巴保留
    assert naming.build_name("DSC_0047", "江苏", "南京", "240815", ".jpg", parts=("time",)) == (
        "DSC_0047_240815.jpg"
    )


def test_normalize_parts_accepts_chinese_and_commonspellings():
    assert naming.normalize_parts("省,市") == ("province", "city")
    assert naming.normalize_parts(["time", "province"]) == ("province", "time")
    with pytest.raises(ValueError):
        naming.normalize_parts(["gps"])


def test_plan_without_rename_only_files_the_originals(tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    src = media / "IMG_1234.jpg"
    src.write_bytes(b"x")

    opts = PlanOptions(root=str(media), rename=False)
    item = build_plan([_item(src)], opts).items[0]
    assert item.decision in ("move", "rename")  # 归档照做，只是不改名
    assert item.target_name == "IMG_1234.jpg"
    assert item.target_path == str((media / "江苏" / "南京" / "IMG_1234.jpg").resolve())


def test_plan_with_time_only_parts(tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    src = media / "IMG_1234.jpg"
    src.write_bytes(b"x")

    opts = PlanOptions(root=str(media), name_parts=("time",))
    item = build_plan([_item(src)], opts).items[0]
    assert item.target_name == "IMG_1234_240815.jpg"


def test_missing_shoot_time_degrades_to_place_only(tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    src = media / "IMG_1234.jpg"
    src.write_bytes(b"x")

    opts = PlanOptions(root=str(media), name_parts=("province", "city", "time"))
    item = build_plan([_item(src, shoot_time=None)], opts).items[0]
    assert item.target_name == "IMG_1234_江苏_南京.jpg"


def test_rename_off_still_keeps_plan_idempotent_on_rerun(tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    src = media / "江苏" / "南京"
    src.mkdir(parents=True)
    moved = src / "IMG_1234.jpg"
    moved.write_bytes(b"x")

    opts = PlanOptions(root=str(media), rename=False)
    item = build_plan([_item(moved)], opts).items[0]
    assert item.decision == "keep"
