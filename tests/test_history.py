"""Tests for the SQLite operation history."""

import pytest

from quantum_organizer.history import HistoryStore


@pytest.fixture
def store(tmp_path):
    return HistoryStore(tmp_path / "h.db")


def test_record_and_read_back(store):
    op = store.begin("apply", "/photos", "{}")
    store.record_step(op, 1, "rename", "/photos/a.jpg", "/photos/a_江苏_南京_240815.jpg", "done")
    store.record_step(
        op, 2, "move", "/photos/a_江苏_南京_240815.jpg",
        "/photos/江苏/南京/a_江苏_南京_240815.jpg", "done",
    )
    store.finish(op, "done")
    rec = store.get(op)
    assert [s.action for s in rec.steps] == ["rename", "move"]
    assert rec.status == "done" and rec.finished_at


def test_last_by_root(store):
    a = store.begin("apply", "/photos", "{}")
    b = store.begin("apply", "/other", "{}")
    store.finish(b, "done")
    assert store.last("/photos").op_id == a
    assert store.last().op_id == b


def test_failed_step_keeps_error(store):
    op = store.begin("apply", "/photos", "{}")
    store.record_step(op, 1, "move", "/x", "/y", "failed", "Permission denied")
    assert store.get(op).steps[0].error == "Permission denied"
