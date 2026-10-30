"""Data models shared by every pipeline stage."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class Status(str, Enum):
    READY = "ready"
    SKIPPED = "skipped"
    INVALID = "invalid"
    CONFLICT = "conflict"
    DONE = "done"
    FAILED = "failed"


@dataclass
class MediaItem:
    path: str
    size: int
    mtime: float
    kind: str
    shoot_time: str | None = None
    time_source: str | None = None
    lat: float | None = None
    lon: float | None = None
    gps_source: str | None = None
    province: str | None = None
    city: str | None = None
    geo_source: str | None = None
    geo_boundary: bool = False
    status: Status = Status.READY
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MediaItem":
        payload = dict(data)
        payload["status"] = Status(payload.get("status", Status.READY))
        return cls(**payload)


@dataclass
class PlanItem:
    item: MediaItem
    target_name: str | None
    target_path: str | None
    decision: str  # rename | move | keep | skip
    conflict: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "item": self.item.to_dict(),
            "target_name": self.target_name,
            "target_path": self.target_path,
            "decision": self.decision,
            "conflict": self.conflict,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PlanItem":
        return cls(
            item=MediaItem.from_dict(data["item"]),
            target_name=data.get("target_name"),
            target_path=data.get("target_path"),
            decision=data["decision"],
            conflict=data.get("conflict"),
        )


@dataclass
class Plan:
    plan_id: str
    root: str
    created_at: str
    options_fingerprint: str
    items: list[PlanItem] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "root": self.root,
            "created_at": self.created_at,
            "options_fingerprint": self.options_fingerprint,
            "items": [i.to_dict() for i in self.items],
            "counts": self.counts,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Plan":
        return cls(
            plan_id=data["plan_id"],
            root=data["root"],
            created_at=data["created_at"],
            options_fingerprint=data["options_fingerprint"],
            items=[PlanItem.from_dict(i) for i in data.get("items", [])],
            counts=dict(data.get("counts", {})),
        )

    @classmethod
    def from_json(cls, raw: str) -> "Plan":
        return cls.from_dict(json.loads(raw))


@dataclass
class StepRecord:
    seq: int
    action: str  # rename | move | copy
    src: str
    dst: str
    status: str  # done | failed | reverted | conflict
    error: str | None = None


@dataclass
class OpRecord:
    op_id: int
    started_at: str
    finished_at: str | None
    kind: str
    root: str
    options_json: str
    status: str
    steps: list[StepRecord] = field(default_factory=list)


@dataclass
class UndoResult:
    op_id: int
    ok: bool
    reverted: int
    conflicts: list[str] = field(default_factory=list)
