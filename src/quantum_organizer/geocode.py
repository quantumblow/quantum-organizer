"""Province/city resolution: embedded locator first, optional remote service, optional estimate.

Coordinates move through this module as ``(lat, lon)``; ``quantum_locator`` speaks
``(lon, lat)``, so the swap happens here and nowhere else.
"""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

_CENTERS: list[dict[str, Any]] = []


@dataclass(frozen=True)
class GeoResult:
    province: str | None
    city: str | None
    source: str  # exact | remote | estimate | none
    reason: str | None = None
    boundary: bool = False


def _load_centers() -> list[dict[str, Any]]:
    global _CENTERS
    if _CENTERS:
        return _CENTERS
    path = Path(__file__).with_name("data") / "city_centers.json"
    if path.exists():
        _CENTERS = json.loads(path.read_text("utf-8"))
    return _CENTERS


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class Geocoder:
    """Resolve ``(lat, lon)`` to a province/city pair."""

    def __init__(
        self,
        remote_url: str | None = None,
        allow_estimate: bool = False,
        locator: Any = None,
    ) -> None:
        self.remote_url = remote_url.rstrip("/") if remote_url else None
        self.allow_estimate = allow_estimate
        self._locator = locator
        self._cache: dict[tuple[float, float], GeoResult] = {}

    # ------------------------------------------------------------------ public

    def resolve(self, lat: float, lon: float) -> GeoResult:
        key = (round(lat, 5), round(lon, 5))
        if key in self._cache:
            return self._cache[key]
        result = self._resolve_uncached(key[0], key[1])
        self._cache[key] = result
        return result

    def resolve_many(
        self, coords: Iterable[tuple[float, float]]
    ) -> dict[tuple[float, float], GeoResult]:
        out: dict[tuple[float, float], GeoResult] = {}
        for lat, lon in coords:
            key = (round(lat, 5), round(lon, 5))
            if key not in out:
                out[key] = self.resolve(lat, lon)
        return out

    # ------------------------------------------------------------------ internals

    def _resolve_uncached(self, lat: float, lon: float) -> GeoResult:
        if self.remote_url:
            remote = self._remote(lat, lon)
            if remote is not None:
                return remote

        loc = self._locator_or_default().query(lon, lat, True)
        reason = getattr(loc, "reason", None)
        province = getattr(loc, "province", None)
        city = getattr(loc, "city", None)
        boundary = bool(getattr(loc, "boundary", False))

        if reason is None and province is not None:
            return GeoResult(province, city, "exact", None, boundary)

        if reason == "outside_polygons" and self.allow_estimate:
            estimated = self._estimate(lat, lon)
            if estimated is not None:
                return GeoResult(estimated[0], estimated[1], "estimate", None, boundary)

        return GeoResult(province, city, "none", reason or "outside_polygons", boundary)

    def _locator_or_default(self) -> Any:
        if self._locator is None:
            from quantum_locator import CityLocator

            self._locator = CityLocator()
        return self._locator

    def _remote(self, lat: float, lon: float) -> GeoResult | None:
        query = urllib.parse.urlencode(
            {"lon": lon, "lat": lat, "need_gcj02_convert": "true"}
        )
        url = f"{self.remote_url}/api/v1/location?{query}"
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            return None

        province = data.get("province")
        city = data.get("city")
        if province is None:
            return GeoResult(None, None, "remote", data.get("reason") or "outside_polygons")
        return GeoResult(province, city, "remote", None, bool(data.get("boundary", False)))

    def _estimate(self, lat: float, lon: float) -> tuple[str, str] | None:
        centers = _load_centers()
        if not centers:
            return None
        best: tuple[float, str, str] = (float("inf"), "", "")
        for entry in centers:
            try:
                clat = float(entry["latitude"])
                clon = float(entry["longitude"])
            except (KeyError, TypeError, ValueError):
                continue
            dist = _haversine(lat, lon, clat, clon)
            if dist < best[0]:
                best = (dist, str(entry.get("province", "")), str(entry.get("city", "")))
        if not best[1]:
            return None
        from quantum_organizer.naming import clean_city, clean_province

        return clean_province(best[1]), clean_city(best[2])
