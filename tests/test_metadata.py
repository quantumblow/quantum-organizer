"""Tests for metadata extraction (images and plain videos)."""

from pathlib import Path

import pytest

from quantum_organizer.metadata import MediaExtractor
from quantum_organizer.models import Status

FX = Path("tests/fixtures/media")


@pytest.fixture(scope="module")
def ex():
    return MediaExtractor()


def test_photo_with_gps(ex):
    m = ex.extract(FX / "photo_gps.jpg")
    assert (m.shoot_time, m.time_source) == ("140815", "exif")
    assert (m.lat, m.lon, m.gps_source) == (32.0603, 118.7969, "exiftool")
    assert (m.province, m.city) == (None, None)


def test_photo_without_gps_keeps_time(ex):
    m = ex.extract(FX / "photo_nogps.jpg")
    assert (m.shoot_time, m.time_source) == ("140506", "exif")
    assert m.lat is None and m.reason == "no_gps"


def test_video_without_metadata_falls_back_to_mtime(ex):
    m = ex.extract(FX / "plain.mp4")
    assert m.kind == "video" and m.lat is None
    assert m.time_source == "mtime" and m.shoot_time is not None


def test_corrupt_file_is_invalid_not_raised(ex):
    m = ex.extract(FX / "broken.jpg")
    assert m.status is Status.INVALID and m.reason == "unreadable"


def test_size_and_mtime_recorded(ex):
    m = ex.extract(FX / "photo_gps.jpg")
    stat = (FX / "photo_gps.jpg").stat()
    assert m.size == stat.st_size
    assert m.mtime == pytest.approx(stat.st_mtime)
