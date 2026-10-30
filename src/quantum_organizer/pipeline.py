"""The pipeline facade: scan → plan → apply → undo.

Scanning extracts metadata concurrently (external tools dominate the runtime) and
caches results by ``(path, size, mtime)`` so re-running a plan never re-probes a file.
Province/city resolution is always re-run, because it is cheap and because
``--allow-estimate`` can change the answer.
"""

from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from quantum_organizer.geocode import Geocoder
from quantum_organizer.metadata import ALL_EXTS, MediaExtractor
from quantum_organizer.models import MediaItem, OpRecord, Plan, Status, UndoResult
from quantum_organizer.organize import PlanOptions, apply_plan, build_plan

ProgressFn = Callable[[int, int, str], bool]

_CACHE_SCHEMA = """
CREATE TABLE IF NOT EXISTS scan_cache (
    path TEXT PRIMARY KEY,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    item_json TEXT NOT NULL
);
"""


class Pipeline:
    def __init__(
        self,
        state_dir: Path | str,
        geocoder: Geocoder | None = None,
        extractor: MediaExtractor | None = None,
        concurrency: int = 8,
        max_files: int = 100_000,
    ) -> None:
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.geocoder = geocoder or Geocoder()
        self.extractor = extractor or MediaExtractor()
        self.concurrency = concurrency
        self.max_files = max_files

        self.cache_path = self.state_dir / "scan_cache.db"
        with sqlite3.connect(self.cache_path) as conn:
            conn.executescript(_CACHE_SCHEMA)
        self.history_path = self.state_dir / "history.db"
        self.plans_path = self.state_dir / "plans.db"

    # ------------------------------------------------------------------ scanning

    def enumerate_files(self, opts: PlanOptions) -> list[Path]:
        root = Path(opts.root)
        if not root.exists():
            raise FileNotFoundError(f"directory not found: {root}")
        exts = {e.lower() for e in opts.extensions} if opts.extensions else ALL_EXTS
        iterator = root.rglob("*") if opts.recursive else root.glob("*")
        files = [p for p in iterator if p.is_file() and p.suffix.lower() in exts]
        if len(files) > self.max_files:
            raise ValueError(f"found {len(files)} files, exceeds max_files={self.max_files}")
        return files

    def scan(self, opts: PlanOptions, progress: ProgressFn | None = None) -> Plan:
        files = self.enumerate_files(opts)
        total = len(files)
        items: list[MediaItem] = []
        aborted = False

        with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
            futures = [pool.submit(self._item_for, path) for path in files]
            for index, future in enumerate(futures, 1):
                items.append(future.result())
                if progress is not None and progress(index, total, files[index - 1].name) is False:
                    aborted = True
                    break

        if aborted:
            items = items[: len(items)]

        self._resolve_places(items)
        return build_plan(items, opts)

    def _item_for(self, path: Path) -> MediaItem:
        try:
            stat = path.stat()
        except OSError:
            return MediaItem(
                path=str(path), size=0, mtime=0.0, kind="image", status=Status.INVALID,
                reason="unreadable",
            )
        cached = self._cache_get(path, stat.st_size, stat.st_mtime)
        if cached is not None:
            return cached
        try:
            item = self.extractor.extract(path)
        except OSError:
            item = MediaItem(
                path=str(path), size=stat.st_size, mtime=stat.st_mtime, kind="image",
                status=Status.INVALID, reason="unreadable",
            )
        self._cache_put(item)
        return item

    def _resolve_places(self, items: list[MediaItem]) -> None:
        coords = [(i.lat, i.lon) for i in items if i.lat is not None and i.lon is not None]
        results = self.geocoder.resolve_many(coords) if coords else {}
        for item in items:
            if item.lat is None or item.lon is None:
                continue
            key = (round(item.lat, 5), round(item.lon, 5))
            geo = results.get(key)
            if geo is None:
                continue
            item.province = geo.province
            item.city = geo.city
            item.geo_source = geo.source
            item.geo_boundary = geo.boundary
            if geo.province is None:
                item.reason = geo.reason or "outside_polygons"

    # ------------------------------------------------------------------ cache

    def _cache_get(self, path: Path, size: int, mtime: float) -> MediaItem | None:
        with sqlite3.connect(self.cache_path) as conn:
            row = conn.execute(
                "SELECT item_json FROM scan_cache WHERE path = ? AND size = ? AND mtime = ?",
                (str(path), size, mtime),
            ).fetchone()
        if not row:
            return None
        try:
            return MediaItem.from_dict(json.loads(row[0]))
        except (ValueError, TypeError):
            return None

    def _cache_put(self, item: MediaItem) -> None:
        payload = item.to_dict()
        with sqlite3.connect(self.cache_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO scan_cache (path, size, mtime, item_json)"
                " VALUES (?, ?, ?, ?)",
                (item.path, item.size, item.mtime, json.dumps(payload, ensure_ascii=False)),
            )
