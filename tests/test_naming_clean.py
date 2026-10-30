"""Tests for province/city cleaning and date parsing."""

import json
import pathlib

import pytest

from quantum_organizer.naming import clean_city, clean_province, format_date


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("江苏省", "江苏"),
        ("新疆维吾尔自治区", "新疆"),
        ("内蒙古自治区", "内蒙古"),
        ("广西壮族自治区", "广西"),
        ("香港特别行政区", "香港"),
        ("北京市", "北京"),
    ],
)
def test_clean_province(raw, expected):
    assert clean_province(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("南京市", "南京"),
        ("东城区", "东城区"),
        ("黄大仙区", "黄大仙区"),
        ("湘西土家族苗族自治州", "湘西"),
        ("海西蒙古族藏族自治州", "海西"),
        ("博尔塔拉蒙古自治州", "博尔塔拉"),
        ("克孜勒苏柯尔克孜自治州", "克孜勒苏"),
        ("酉阳土家族苗族自治县", "酉阳"),
        ("大兴安岭地区", "大兴安岭"),
        ("阿拉善盟", "阿拉善"),
    ],
)
def test_clean_city(raw, expected):
    assert clean_city(raw) == expected


def test_naming_cases_fixture():
    raw = pathlib.Path("tests/fixtures/naming_cases.json").read_text("utf-8")
    for case in json.loads(raw)["cities"]:
        cleaned = clean_city(case["raw"])
        assert cleaned == case["clean"]
        assert "族" not in cleaned
        assert len(cleaned) <= 8


def test_format_date():
    assert format_date("2014:08:15 10:00:00") == "140815"
    assert format_date("2014-08-15T10:00:00Z") == "140815"
    assert format_date("140815") == "140815"
    assert format_date(None) is None
    assert format_date("not a date") is None


def test_format_date_rejects_impossible_dates():
    assert format_date("2014:13:45 10:00:00") is None
