"""Web API + static UI host for qorg.

Single process, single worker: the plan registry is in memory, plans and history are
on disk in ``QORG_STATE_DIR``. Every filesystem path coming from the browser must be
inside ``data_root``.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from quantum_organizer.geocode import Geocoder
from quantum_organizer.organize import PlanOptions
from quantum_organizer.pipeline import Pipeline

STATIC_DIR = Path(__file__).with_name("static")


class PlanRequest(BaseModel):
    model_config = {"populate_by_name": True}

    root: str
    output_dir: str | None = None
    copy_files: bool = Field(False, alias="copy")
    move_unlocated: bool = False
    allow_estimate: bool = False


class ApplyRequest(BaseModel):
    paths: list[str] | None = None
    dry_run: bool = True


class BatchBody(BaseModel):
    coordinates: list[dict[str, Any]] = Field(default_factory=list)


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


def create_app(state_dir: Path | str, data_root: str | None = None) -> FastAPI:
    state = Path(state_dir)
    state.mkdir(parents=True, exist_ok=True)
    app = FastAPI(title="quantum-organizer", version="0.1.0")

    app.state.options = {}
    app.state.jobs = {}

    def pipeline_for(allow_estimate: bool) -> Pipeline:
        return Pipeline(
            state,
            geocoder=Geocoder(allow_estimate=allow_estimate),
        )

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/v1/plans")
    def create_plan(req: PlanRequest) -> dict[str, Any]:
        root = Path(req.root)
        if data_root is not None and not _inside(root, Path(data_root)):
            raise HTTPException(status_code=400, detail="root must be inside the data directory")
        if not root.exists():
            raise HTTPException(status_code=400, detail=f"root not found: {root}")
        if req.output_dir is not None:
            out = Path(req.output_dir)
            if data_root is not None and not _inside(out, Path(data_root)):
                raise HTTPException(
                    status_code=400, detail="output_dir must be inside the data directory"
                )
            if not out.is_dir():
                raise HTTPException(status_code=400, detail=f"output_dir not found: {out}")

        opts = PlanOptions(
            root=str(root),
            output_dir=req.output_dir,
            copy=req.copy_files,
            move_unlocated=req.move_unlocated,
            allow_estimate=req.allow_estimate,
        )
        pipeline = pipeline_for(req.allow_estimate)

        job_id = f"job-{len(app.state.jobs) + 1}"
        events: list[dict[str, Any]] = []
        app.state.jobs[job_id] = events

        def progress(done: int, total: int, name: str) -> bool:
            events.append({"done": done, "total": total, "current": name})
            return True

        plan = pipeline.scan(opts, progress=progress)
        pipeline.save_plan(plan, options=opts)
        app.state.options[plan.plan_id] = opts
        return {
            "plan_id": plan.plan_id,
            "counts": plan.counts,
            "job_id": job_id,
            "total": len(plan.items),
        }

    @app.get("/api/v1/plans/{plan_id}/items")
    def plan_items(
        plan_id: str,
        page: int = Query(1, ge=1),
        size: int = Query(200, ge=1, le=2000),
        decision: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        try:
            plan = pipeline_for(False).load_plan(plan_id, root="")
        except KeyError:
            raise HTTPException(status_code=404, detail="plan not found") from None

        items = plan.items
        if decision:
            items = [i for i in items if i.decision == decision]
        if reason:
            items = [i for i in items if i.item.reason == reason]
        start = (page - 1) * size
        return {
            "total": len(items),
            "page": page,
            "size": size,
            "counts": plan.counts,
            "items": [i.to_dict() for i in items[start : start + size]],
        }

    @app.post("/api/v1/plans/{plan_id}/apply")
    def apply_plan_endpoint(plan_id: str, req: ApplyRequest) -> dict[str, Any]:
        pipeline = pipeline_for(False)
        try:
            plan = pipeline.load_plan(plan_id, root="")
        except KeyError:
            raise HTTPException(status_code=404, detail="plan not found") from None

        # 执行语义只认计划里存的选项；读不到就拒绝，绝不退回默认 move 语义
        try:
            opts: PlanOptions = pipeline.load_plan_options(plan.plan_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        known = {i.item.path for i in plan.items}
        if req.paths is not None:
            unknown = [p for p in req.paths if p not in known]
            if unknown:
                raise HTTPException(status_code=400, detail=f"paths not in plan: {unknown[:3]}")

        record = pipeline.apply(plan, selection=req.paths, dry_run=req.dry_run, options=opts)
        return {
            "op_id": record.op_id,
            "status": record.status,
            "steps": len(record.steps),
        }

    @app.get("/api/v1/ops/{op_id}")
    def get_op(op_id: int) -> dict[str, Any]:
        try:
            record = pipeline_for(False).history().get(op_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="operation not found") from None
        return {
            "op_id": record.op_id,
            "status": record.status,
            "root": record.root,
            "steps": [
                {"seq": s.seq, "action": s.action, "src": s.src, "dst": s.dst, "status": s.status}
                for s in record.steps
            ],
        }

    @app.post("/api/v1/ops/{op_id}/undo")
    def undo_op(op_id: int) -> dict[str, Any]:
        try:
            result = pipeline_for(False).undo(op_id=op_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="operation not found") from None
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        return {"ok": result.ok, "reverted": result.reverted, "conflicts": result.conflicts}

    @app.get("/api/v1/progress/{job_id}")
    async def progress_stream(job_id: str) -> StreamingResponse:
        events = app.state.jobs.get(job_id)
        if events is None:
            raise HTTPException(status_code=404, detail="job not found")

        async def generator():
            sent = 0
            while True:
                while sent < len(events):
                    payload = json.dumps(events[sent], ensure_ascii=False)
                    yield f"event: progress\ndata: {payload}\n\n"
                    sent += 1
                if sent and events[sent - 1]["done"] >= events[sent - 1]["total"]:
                    yield "event: done\ndata: {}\n\n"
                    return
                await asyncio.sleep(0.2)

        return StreamingResponse(generator(), media_type="text/event-stream")

    @app.get("/api/v1/roots")
    def list_roots() -> dict[str, Any]:
        if data_root is None:
            return {"roots": []}
        base = Path(data_root)
        if not base.exists():
            return {"roots": []}
        return {
            "roots": sorted(
                str(p) for p in base.iterdir() if p.is_dir() and not p.name.startswith(".")
            )
        }

    if STATIC_DIR.exists():
        app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

    return app
