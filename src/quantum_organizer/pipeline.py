"""The pipeline facade: scan → plan → apply → undo.

Scanning extracts metadata concurrently (external tools dominate the runtime) and
caches results by ``(path, size, mtime)`` so re-running a plan never re-probes a file.
Province/city resolution is always re-run, because it is cheap and because
``--allow-estimate`` can change the answer.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from quantum_organizer.geocode import Geocoder
from quantum_organizer.history import HistoryStore
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
                try:
                    items.append(future.result())
                except Exception:  # 单个文件失败不能中断整批
                    path = files[index - 1]
                    items.append(
                        MediaItem(
                            path=str(path),
                            size=0,
                            mtime=0.0,
                            kind="image",
                            status=Status.INVALID,
                            reason="unreadable",
                        )
                    )
                if progress is not None and progress(index, total, files[index - 1].name) is False:
                    aborted = True
                    break

        # 进度回调返回 False 时只停止继续汇报：已提交的任务仍会跑完，绝不丢弃已扫结果
        del aborted

        self._resolve_places(items)
        return build_plan(items, opts)

    def _item_for(self, path: Path) -> MediaItem:
        try:
            stat = path.stat()
        except OSError:
            return MediaItem(
                path=str(path),
                size=0,
                mtime=0.0,
                kind="image",
                status=Status.INVALID,
                reason="unreadable",
            )
        cached = self._cache_get(path, stat.st_size, stat.st_mtime)
        if cached is not None:
            return cached
        try:
            item = self.extractor.extract(path)
        except OSError:
            item = MediaItem(
                path=str(path),
                size=stat.st_size,
                mtime=stat.st_mtime,
                kind="image",
                status=Status.INVALID,
                reason="unreadable",
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
            if geo.province is None or geo.city is None:
                # 只有省级数据（台湾）也要在报告里写原因，否则用户不知道为什么没归类
                item.reason = geo.reason or "outside_city_data"

    # ------------------------------------------------------------------ cache

    def _cache_get(self, path: Path, size: int, mtime: float) -> MediaItem | None:
        with sqlite3.connect(self.cache_path) as conn:
            row = conn.execute(
                "SELECT item_json FROM scan_cache WHERE path = ? AND size = ? AND mtime = ?",
                (str(path.resolve()), size, mtime),
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

    # ------------------------------------------------------------------ plans

    def _plans_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.plans_path)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS plans ("
            " plan_id TEXT PRIMARY KEY, root TEXT NOT NULL, created_at TEXT NOT NULL,"
            " options_fingerprint TEXT NOT NULL, json TEXT NOT NULL,"
            " options_json TEXT)"
        )
        with contextlib.suppress(sqlite3.OperationalError):  # 已有该列
            conn.execute("ALTER TABLE plans ADD COLUMN options_json TEXT")
        return conn

    def save_plan(self, plan: Plan, options: PlanOptions | None = None) -> str:
        """Persist the plan *and* the options it was built with.

        执行语义（copy / output / move_unlocated）必须跟着计划走：否则换个进程执行时
        会退回默认值，把 copy 计划变成 move，原件消失且不可恢复。
        """
        options_json = json.dumps(options.to_dict(), ensure_ascii=False) if options else None
        with self._plans_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO plans"
                " (plan_id, root, created_at, options_fingerprint, json, options_json)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    plan.plan_id,
                    plan.root,
                    plan.created_at,
                    plan.options_fingerprint,
                    plan.to_json(),
                    options_json,
                ),
            )
        return plan.plan_id

    def load_plan_options(self, plan_id: str) -> PlanOptions:
        """Read back the options a plan was created with; fail closed when missing."""
        with self._plans_conn() as conn:
            row = conn.execute(
                "SELECT options_json FROM plans WHERE plan_id = ?", (plan_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"no plan found for {plan_id}")
        if not row[0]:
            raise ValueError("plan has no stored options (re-run `qorg scan`)")
        return PlanOptions.from_dict(json.loads(row[0]))

    def load_plan(
        self,
        plan_id: str | None,
        root: str,
        options: PlanOptions | None = None,
    ) -> Plan:
        with self._plans_conn() as conn:
            if plan_id is None:
                row = conn.execute(
                    "SELECT json, options_fingerprint FROM plans WHERE root = ?"
                    " ORDER BY rowid DESC LIMIT 1",
                    (root,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT json, options_fingerprint FROM plans WHERE plan_id = ?", (plan_id,)
                ).fetchone()
        if row is None:
            raise KeyError(f"no plan found for {plan_id or root}")

        if options is not None:
            from quantum_organizer.organize import options_fingerprint

            if options_fingerprint(options) != row[1]:
                raise ValueError("plan fingerprint mismatch for these options, rescan required")
        return Plan.from_json(row[0])

    # ------------------------------------------------------------------ history

    def history(self) -> HistoryStore:
        return HistoryStore(self.history_path)

    def apply(
        self,
        plan: Plan,
        selection: list[str] | None = None,
        dry_run: bool = False,
        options: PlanOptions | None = None,
    ) -> OpRecord:
        return apply_plan(
            plan, self.history(), options=options, dry_run=dry_run, selection=selection
        )

    def undo(
        self,
        op_id: int | None = None,
        root: str | None = None,
        dry_run: bool = False,
    ) -> UndoResult:
        hist = self.history()
        if op_id is None:
            latest = hist.last(root)
            if latest is None:
                raise KeyError("no operation to undo")
            op_id = latest.op_id
        return hist.undo(op_id, dry_run=dry_run)
