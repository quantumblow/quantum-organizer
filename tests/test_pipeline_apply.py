"""Tests for plan persistence and the apply/undo facade."""

import shutil
from pathlib import Path

import pytest

from quantum_organizer.organize import PlanOptions
from quantum_organizer.pipeline import Pipeline

FX = Path("tests/fixtures/media")


@pytest.fixture
def media(tmp_path):
    d = tmp_path / "src"
    d.mkdir()
    shutil.copy(FX / "photo_gps.jpg", d / "photo_gps.jpg")
    shutil.copy(FX / "photo_nogps.jpg", d / "photo_nogps.jpg")
    return d


def test_save_and_load_plan(media, tmp_path):
    p = Pipeline(tmp_path / "state")
    plan = p.scan(PlanOptions(root=str(media)))
    pid = p.save_plan(plan)
    loaded = p.load_plan(pid, str(media))
    assert loaded.plan_id == pid and len(loaded.items) == len(plan.items)


def test_load_latest_plan_by_root(media, tmp_path):
    p = Pipeline(tmp_path / "state")
    p.save_plan(p.scan(PlanOptions(root=str(media))))
    assert p.load_plan(None, str(media)).root == str(media)


def test_fingerprint_mismatch_raises(media, tmp_path):
    p = Pipeline(tmp_path / "state")
    p.save_plan(p.scan(PlanOptions(root=str(media))))
    with pytest.raises(ValueError, match="fingerprint"):
        p.load_plan(None, str(media), options=PlanOptions(root=str(media), copy=True))


def test_apply_then_undo_restores_tree(media, tmp_path):
    p = Pipeline(tmp_path / "state")
    plan = p.scan(PlanOptions(root=str(media)))
    p.save_plan(plan)
    rec = p.apply(plan, options=PlanOptions(root=str(media)))
    assert rec.status == "done"
    assert (media / "江苏" / "南京").is_dir()
    res = p.undo(op_id=rec.op_id)
    assert res.ok
    assert (media / "photo_gps.jpg").exists()
    assert not (media / "江苏").exists()


def test_apply_selection_by_paths(media, tmp_path):
    p = Pipeline(tmp_path / "state")
    plan = p.scan(PlanOptions(root=str(media)))
    rec = p.apply(
        plan,
        options=PlanOptions(root=str(media)),
        selection=[str(media / "photo_gps.jpg")],
    )
    assert (media / "江苏" / "南京").is_dir()
    assert all(s.src.endswith("photo_gps.jpg") or "photo_gps" in s.src for s in rec.steps)


def test_undo_without_op_uses_latest(media, tmp_path):
    p = Pipeline(tmp_path / "state")
    plan = p.scan(PlanOptions(root=str(media)))
    p.apply(plan, options=PlanOptions(root=str(media)))
    assert p.undo(root=str(media)).ok
