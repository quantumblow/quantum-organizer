"""Tests for reverse-order undo."""

import pytest

from quantum_organizer.history import HistoryStore


@pytest.fixture
def store(tmp_path):
    return HistoryStore(tmp_path / "h.db")


def _op(store, root):
    return store.begin("apply", str(root), "{}")


def test_undo_reverts_rename_and_move(store, tmp_path):
    src = tmp_path / "a.jpg"
    src.write_bytes(b"x")
    named = tmp_path / "a_江苏_南京_240815.jpg"
    dst = tmp_path / "江苏" / "南京" / named.name
    dst.parent.mkdir(parents=True)
    src.rename(named)
    named.rename(dst)

    op = _op(store, tmp_path)
    store.record_step(op, 1, "rename", str(src), str(named), "done")
    store.record_step(op, 2, "move", str(named), str(dst), "done")
    store.finish(op, "done")

    res = store.undo(op)
    assert res.ok and res.reverted == 2
    assert src.exists() and not dst.exists()
    assert store.get(op).status == "undone"


def test_undo_stops_on_missing_target(store, tmp_path):
    src = tmp_path / "a.jpg"
    src.write_bytes(b"x")
    missing = tmp_path / "gone.jpg"
    op = _op(store, tmp_path)
    store.record_step(op, 1, "rename", str(src), str(missing), "done")
    store.finish(op, "done")
    res = store.undo(op)
    assert not res.ok and res.reverted == 0
    assert str(missing) in res.conflicts
    assert src.exists()


def test_undo_dry_run_touches_nothing(store, tmp_path):
    src = tmp_path / "a.jpg"
    src.write_bytes(b"x")
    dst = tmp_path / "b.jpg"
    src.rename(dst)
    op = _op(store, tmp_path)
    store.record_step(op, 1, "rename", str(src), str(dst), "done")
    store.finish(op, "done")
    res = store.undo(op, dry_run=True)
    assert res.ok and res.reverted == 1
    assert dst.exists() and not src.exists()


def test_undo_twice_is_refused(store, tmp_path):
    src = tmp_path / "a.jpg"
    src.write_bytes(b"x")
    dst = tmp_path / "b.jpg"
    src.rename(dst)
    op = _op(store, tmp_path)
    store.record_step(op, 1, "rename", str(src), str(dst), "done")
    store.finish(op, "done")
    store.undo(op)
    with pytest.raises(RuntimeError):
        store.undo(op)


def test_undo_reverts_copy_steps(store, tmp_path):
    src = tmp_path / "orig.jpg"
    src.write_bytes(b"payload")
    dst = tmp_path / "copy.jpg"
    dst.write_bytes(b"payload")

    op = _op(store, tmp_path)
    store.record_step(op, 1, "copy", str(src), str(dst), "done")
    store.finish(op, "done")

    assert store.undo(op).ok
    assert dst.exists() is False
    assert src.read_bytes() == b"payload"
