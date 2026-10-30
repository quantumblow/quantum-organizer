"""Plan building and (later) plan execution.

A plan is computed before anything touches the filesystem: every item gets a
decision (``rename`` / ``move`` / ``keep`` / ``skip``), a target path, and a
conflict-free name. Execution lives in :func:`apply_plan`.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from quantum_organizer import naming
from quantum_organizer.models import MediaItem, Plan, PlanItem, Status

UNLOCATED_DIR = "未定位"


@dataclass
class PlanOptions:
    root: str
    output_dir: str | None = None
    copy: bool = False
    move_unlocated: bool = False
    recursive: bool = True
    extensions: list[str] | None = None
    allow_estimate: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_dict(cls, data: dict) -> "PlanOptions":
        allowed = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in allowed})


def options_fingerprint(opts: PlanOptions) -> str:
    return hashlib.sha256(opts.to_json().encode("utf-8")).hexdigest()[:12]


def plan_id() -> str:
    return uuid.uuid4().hex[:12]


def _writable(path: Path) -> bool:
    """Pre-flight check used before touching anything."""
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return os.access(probe, os.W_OK)


def _dedupe_target(target: Path, taken: set[str]) -> tuple[Path, str | None]:
    """Return a free path, appending ``_2``, ``_3`` … before the extension."""
    key = str(target)
    if not target.exists() and key not in taken:
        taken.add(key)
        return target, None

    stem, ext = target.stem, target.suffix
    index = 2
    while True:
        candidate = target.with_name(f"{stem}_{index}{ext}")
        if not candidate.exists() and str(candidate) not in taken:
            taken.add(str(candidate))
            return candidate, f"{target.name} exists, renamed to {candidate.name}"
        index += 1


def build_plan(items: list[MediaItem], opts: PlanOptions) -> Plan:
    root = Path(opts.root).resolve()
    base = Path(opts.output_dir).resolve() if opts.output_dir else root

    plan_items: list[PlanItem] = []
    taken: set[str] = set()
    counts: dict[str, int] = {}

    for item in items:
        source = Path(item.path)
        decision = "keep"
        target: Path | None = None
        conflict: str | None = None

        if source.is_symlink():
            item.status = Status.SKIPPED
            item.reason = "symlink"
            decision = "skip"
        elif item.status not in (Status.READY, Status.SKIPPED):
            decision = "keep"
        elif item.province is None or item.city is None:
            if opts.move_unlocated:
                decision = "move"
                target, conflict = _dedupe_target(source.parent / UNLOCATED_DIR / source.name, taken)
            else:
                decision = "keep"
        else:
            target_name = naming.build_name(
                source.stem, item.province, item.city, item.shoot_time or "", source.suffix
            )
            target_name = naming.sanitize(target_name)
            candidate = base / item.province / item.city / target_name
            if candidate.resolve() == source.resolve():
                decision = "keep"
            else:
                target, conflict = _dedupe_target(candidate, taken)
                decision = "rename"

        if target is not None and target.resolve() == source.resolve():
            decision = "keep"
            target = None

        counts[decision] = counts.get(decision, 0) + 1
        plan_items.append(
            PlanItem(
                item=item,
                target_name=target.name if target is not None else None,
                target_path=str(target) if target is not None else None,
                decision=decision,
                conflict=conflict,
            )
        )

    return Plan(
        plan_id=plan_id(),
        root=str(root),
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        options_fingerprint=options_fingerprint(opts),
        items=plan_items,
        counts=counts,
    )
