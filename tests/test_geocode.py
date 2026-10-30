"""Tests for the province/city resolution layer."""

import json
import urllib.request

import pytest

from quantum_organizer.geocode import Geocoder


@pytest.fixture(scope="module")
def g():
    return Geocoder()


def test_exact_resolution(g):
    r = g.resolve(32.0603, 118.7969)
    assert (r.province, r.city, r.source, r.reason) == ("江苏", "南京", "exact", None)


def test_works_for_municipality_district(g):
    r = g.resolve(39.9087, 116.3975)
    assert (r.province, r.city) == ("北京", "东城区")


def test_abroad(g):
    r = g.resolve(35.6895, 139.6917)
    assert (r.source, r.reason, r.province) == ("none", "abroad", None)


def test_taiwan_needs_city_level_data(g):
    r = g.resolve(25.0330, 121.5654)
    assert (r.reason, r.city, r.source) == ("needs_city_level_data", None, "none")


def test_estimate_off_by_default(g):
    assert g.resolve(35.6895, 139.6917).source == "none"


def test_estimate_never_guesses_for_taiwan_or_abroad():
    g = Geocoder(allow_estimate=True)
    assert g.resolve(25.0330, 121.5654).source == "none"
    assert g.resolve(35.6895, 139.6917).source == "none"


def test_estimate_applies_only_to_outside_polygons():
    class FakeLocator:
        def query(self, lon, lat, need_gcj02_convert=True):
            return type(
                "Loc",
                (),
                {
                    "province": None,
                    "city": None,
                    "level": None,
                    "adcode": None,
                    "boundary": False,
                    "reason": "outside_polygons",
                },
            )()

    g = Geocoder(allow_estimate=True, locator=FakeLocator())
    r = g.resolve(32.0603, 118.7969)
    assert (r.source, r.province, r.city) == ("estimate", "江苏", "南京")


def test_remote_mode(monkeypatch):
    body = json.dumps(
        {"province": "江苏", "city": "南京", "level": "city", "adcode": "320100", "reason": None}
    ).encode()

    class Resp:
        def read(self):
            return body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: Resp())
    r = Geocoder(remote_url="http://localhost:8899").resolve(32.0603, 118.7969)
    assert (r.province, r.city, r.source) == ("江苏", "南京", "remote")


def test_resolve_many_dedupes(monkeypatch):
    g = Geocoder()
    calls = []
    real = g.resolve
    monkeypatch.setattr(g, "resolve", lambda lat, lon: calls.append((lat, lon)) or real(lat, lon))
    out = g.resolve_many([(32.0603, 118.7969), (32.0603, 118.7969), (32.0, 118.0)])
    assert len(calls) == 2 and len(out) == 2
