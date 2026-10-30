"""Tests for idempotent filename building and sanitisation."""

import pytest

from quantum_organizer.naming import build_name, parse_existing, sanitize


def test_parse_existing_strips_known_suffix():
    assert parse_existing("IMG_1234_江苏_南京_240815") == ("IMG_1234", "江苏_南京_240815")


def test_parse_existing_ignores_non_place_suffix():
    assert parse_existing("IMG_20140621_161135") == ("IMG_20140621_161135", None)
    assert parse_existing("DSC_0047_140620_140620") == ("DSC_0047_140620_140620", None)


def test_build_name_keeps_existing_suffix():
    assert (
        build_name("IMG_1234_江苏_南京_240815", "江苏", "南京", "240815", ".jpg")
        == "IMG_1234_江苏_南京_240815.jpg"
    )


def test_build_name_replaces_changed_suffix():
    assert (
        build_name("DSC_0001_北京_东城区_240101", "北京", "东城区", "240102", ".JPG")
        == "DSC_0001_北京_东城区_240102.JPG"
    )


def test_build_name_keeps_camera_underscores():
    assert (
        build_name("IMG_20140531_074823_HDR", "江苏", "南京", "140531", ".jpg")
        == "IMG_20140531_074823_HDR_江苏_南京_140531.jpg"
    )


def test_sanitize_replaces_illegal_characters():
    assert sanitize('a<b>c:d"e/f\\g|h?i*j.jpg') == "a-b-c-d-e-f-g-h-i-j.jpg"


def test_sanitize_truncates_bytes_keeping_extension():
    out = sanitize("测" * 120 + ".jpg")
    assert len(out.encode()) <= 200
    assert out.endswith(".jpg")


def test_build_name_rejects_empty_place():
    with pytest.raises(ValueError):
        build_name("a", "", "南京", "240815", ".jpg")
