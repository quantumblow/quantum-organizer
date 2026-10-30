"""Regression tests for the pre-release review findings."""

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from quantum_organizer.naming import build_name, parse_existing
from quantum_organizer.organize import PlanOptions
from quantum_organizer.pipeline import Pipeline
from quantum_organizer.web.app import create_app

FX = Path("tests/fixtures/media")


def _media(tmp_path):
    media = tmp_path / "src"
    media.mkdir()
    shutil.copy(FX / "photo_gps.jpg", media / "IMG_0001.jpg")
    return media


# 1. 撤销只允许清理 root 内的空目录
def test_undo_does_not_prune_outside_root(tmp_path):
    media = _media(tmp_path)
    out = tmp_path / "导出"  # 空的输出目录：撤销绝不能把它删掉
    out.mkdir()

    p = Pipeline(tmp_path / "state")
    opts = PlanOptions(root=str(media), output_dir=str(out), copy=True)
    plan = p.scan(opts)
    record = p.apply(plan, options=opts)
    assert p.undo(op_id=record.op_id).ok
    assert out.is_dir()


# 2. 计划必须自带执行语义：换进程/换实例也不改 copy/move
def test_plan_options_survive_a_new_pipeline(tmp_path):
    media = _media(tmp_path)
    first = Pipeline(tmp_path / "state")
    opts = PlanOptions(root=str(media), copy=True)
    plan = first.scan(opts)
    first.save_plan(plan, options=opts)

    second = Pipeline(tmp_path / "state")
    loaded = second.load_plan(plan.plan_id, root=str(media))
    stored = second.load_plan_options(plan.plan_id)
    assert stored.copy is True
    second.apply(loaded, options=stored)
    assert (media / "IMG_0001.jpg").exists()  # copy 语义：原件还在
    assert list((media / "江苏" / "南京").glob("IMG_0001_江苏_南京_*.jpg"))


def test_apply_without_stored_options_fails_closed(tmp_path):
    media = _media(tmp_path)
    p = Pipeline(tmp_path / "state")
    plan = p.scan(PlanOptions(root=str(media)))
    p.save_plan(plan)  # 没写 options
    with pytest.raises(ValueError, match="options"):
        p.load_plan_options(plan.plan_id)


# 3. Web：output_dir 也必须在 data_root 内
def test_cli_copy_plan_keeps_sources(tmp_path):
    """`qorg scan --copy` 的语义必须跟着计划走到 apply（以前 apply 会退回 move）。"""
    from typer.testing import CliRunner

    from quantum_organizer.cli import app

    media = _media(tmp_path)
    runner = CliRunner()
    env = {"QORG_STATE_DIR": str(tmp_path / "state")}

    assert runner.invoke(app, ["scan", str(media), "--copy"], env=env).exit_code == 0
    result = runner.invoke(app, ["apply", str(media), "--yes"], env=env)
    assert result.exit_code == 0, result.output
    assert (media / "IMG_0001.jpg").exists()
    assert list((media / "江苏" / "南京").glob("IMG_0001_江苏_南京_*.jpg"))


def test_web_output_dir_must_be_inside_data_root(tmp_path):
    app = create_app(state_dir=tmp_path / "state", data_root=str(tmp_path))
    c = TestClient(app)
    media = _media(tmp_path)
    r = c.post("/api/v1/plans", json={"root": str(media), "output_dir": "/tmp/qorg-escape"})
    assert r.status_code == 400


# 5. 冲突后缀 _2 不会在二次扫描时被再次拼进 stem
def test_conflict_suffix_does_not_break_idempotency():
    base, _suffix = parse_existing("IMG_0001_江苏_南京_240815_2")
    assert base == "IMG_0001"
    assert build_name("IMG_0001_江苏_南京_240815_2", "江苏", "南京", "240815", ".jpg") == (
        "IMG_0001_江苏_南京_240815.jpg"
    )


# 6. 超长名只截 stem，省市与日期必须保留
def test_long_name_keeps_province_city_and_date():
    stem = "很长的中文文件名" * 12
    name = build_name(stem, "内蒙古", "鄂尔多斯", "240815", ".jpg")
    assert name.endswith("_内蒙古_鄂尔多斯_240815.jpg")
    assert len(name.encode("utf-8")) <= 200
