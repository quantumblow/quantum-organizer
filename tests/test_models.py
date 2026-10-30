"""Tests for the core data models."""

from quantum_organizer.models import MediaItem, Plan, PlanItem, Status


def _item(**kw):
    base = dict(
        path="/a.jpg",
        size=1,
        mtime=1.0,
        kind="image",
        shoot_time="240815",
        time_source="exif",
        lat=32.06,
        lon=118.79,
        gps_source="exiftool",
        province="江苏",
        city="南京",
        geo_source="exact",
    )
    base.update(kw)
    return MediaItem(**base)


def test_media_item_roundtrip():
    item = _item()
    assert MediaItem.from_dict(item.to_dict()) == item


def test_status_serialises_as_string():
    item = _item(status=Status.INVALID, reason="unreadable")
    assert item.to_dict()["status"] == "invalid"
    assert MediaItem.from_dict(item.to_dict()).status is Status.INVALID


def test_plan_json_roundtrip():
    plan = Plan(
        plan_id="p1",
        root="/r",
        created_at="2026-10-30T00:00:00",
        options_fingerprint="abc123",
        items=[
            PlanItem(
                item=_item(),
                target_name="a_江苏_南京_240815.jpg",
                target_path="/r/江苏/南京/a_江苏_南京_240815.jpg",
                decision="rename",
                conflict=None,
            )
        ],
        counts={"rename": 1},
    )
    assert Plan.from_json(plan.to_json()) == plan
