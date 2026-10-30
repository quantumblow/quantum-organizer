"""SQLite operation history: one row per operation, one row per filesystem step.

The database lives in ``QORG_STATE_DIR`` — never inside the user's media folders.
Undo replays the steps in reverse order and stops at the first inconsistency.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from quantum_organizer.models import OpRecord, StepRecord, UndoResult

_SCHEMA = """
CREATE TABLE IF NOT EXISTS operations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    kind TEXT NOT NULL,
    root TEXT NOT NULL,
    options_json TEXT NOT NULL,
    status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS steps (
    op_id INTEGER NOT NULL,
    seq INTEGER NOT NULL,
    action TEXT NOT NULL,
    src TEXT NOT NULL,
    dst TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    PRIMARY KEY (op_id, seq),
    FOREIGN KEY (op_id) REFERENCES operations(id)
);
CREATE INDEX IF NOT EXISTS idx_ops_root ON operations(root, id DESC);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class HistoryStore:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # ------------------------------------------------------------------ writes

    def begin(self, kind: str, root: str, options_json: str) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO operations (started_at, kind, root, options_json, status)"
                " VALUES (?, ?, ?, ?, ?)",
                (_now(), kind, root, options_json, "running"),
            )
            return int(cur.lastrowid or 0)

    def record_step(
        self,
        op_id: int,
        seq: int,
        action: str,
        src: str,
        dst: str,
        status: str,
        error: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO steps (op_id, seq, action, src, dst, status, error)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (op_id, seq, action, src, dst, status, error),
            )

    def finish(self, op_id: int, status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE operations SET status = ?, finished_at = ? WHERE id = ?",
                (status, _now(), op_id),
            )

    def mark_undone(self, op_id: int) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE operations SET status = 'undone' WHERE id = ?", (op_id,))

    def set_step_status(self, op_id: int, seq: int, status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE steps SET status = ? WHERE op_id = ? AND seq = ?", (status, op_id, seq)
            )

    # ------------------------------------------------------------------ reads

    def get(self, op_id: int) -> OpRecord:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, started_at, finished_at, kind, root, options_json, status"
                " FROM operations WHERE id = ?",
                (op_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"operation {op_id} not found")
            steps = conn.execute(
                "SELECT seq, action, src, dst, status, error FROM steps"
                " WHERE op_id = ? ORDER BY seq",
                (op_id,),
            ).fetchall()
        return OpRecord(
            op_id=row[0],
            started_at=row[1],
            finished_at=row[2],
            kind=row[3],
            root=row[4],
            options_json=row[5],
            status=row[6],
            steps=[
                StepRecord(seq=s[0], action=s[1], src=s[2], dst=s[3], status=s[4], error=s[5])
                for s in steps
            ],
        )

    def last(self, root: str | None = None) -> OpRecord | None:
        with self._connect() as conn:
            if root is None:
                row = conn.execute("SELECT id FROM operations ORDER BY id DESC LIMIT 1").fetchone()
            else:
                row = conn.execute(
                    "SELECT id FROM operations WHERE root = ? ORDER BY id DESC LIMIT 1", (root,)
                ).fetchone()
        return self.get(int(row[0])) if row else None

    # ------------------------------------------------------------------ undo

    @staticmethod
    def _prune_empty_dirs(start: Path, root: Path) -> None:
        """Remove directories this operation created, never outside the operation root.

        ``--output`` 可能把文件放到 root 之外，撤销时绝不能往上删到别人的目录。
        """
        try:
            root_resolved = root.resolve()
        except OSError:
            return
        current = start
        while True:
            try:
                resolved = current.resolve()
            except OSError:
                return
            if resolved == root_resolved or root_resolved not in resolved.parents:
                return
            try:
                current.rmdir()  # only succeeds when empty
            except OSError:
                return
            current = current.parent

    def undo(self, op_id: int, dry_run: bool = False) -> UndoResult:
        record = self.get(op_id)
        if record.status == "undone":
            raise RuntimeError(f"operation {op_id} was already undone")

        reverted = 0
        conflicts: list[str] = []

        for step in sorted(record.steps, key=lambda s: s.seq, reverse=True):
            dst, src = Path(step.dst), Path(step.src)
            if step.status != "done":
                continue
            if step.action == "copy":
                # 复制步骤的源本来就在；只要副本还在就能回滚
                if not dst.exists():
                    conflicts.append(str(dst))
                    if not dry_run:
                        self.set_step_status(op_id, step.seq, "conflict")
                    break
            elif not dst.exists() or src.exists():
                conflicts.append(str(dst))
                if not dry_run:
                    self.set_step_status(op_id, step.seq, "conflict")
                break
            if dry_run:
                reverted += 1
                continue

            try:
                src.parent.mkdir(parents=True, exist_ok=True)
                if step.action == "copy":
                    if not src.exists():
                        shutil.copy2(dst, src)
                    os.unlink(dst)
                else:
                    shutil.move(str(dst), str(src))
                self.set_step_status(op_id, step.seq, "reverted")
                self._prune_empty_dirs(dst.parent, Path(record.root))
                reverted += 1
            except OSError as exc:
                conflicts.append(f"{dst}: {exc}")
                self.set_step_status(op_id, step.seq, "conflict")
                break

        ok = not conflicts
        if ok and not dry_run:
            self.mark_undone(op_id)
        return UndoResult(op_id=op_id, ok=ok, reverted=reverted, conflicts=conflicts)
