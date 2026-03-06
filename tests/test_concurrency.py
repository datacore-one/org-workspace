"""Tests for concurrency.py — locks, claims, conflict detection."""


import pytest

from org_workspace.concurrency import (
    ConflictError,
    FileLock,
    OptimisticLock,
    TaskClaim,
    multi_lock,
)
from org_workspace.workspace import OrgWorkspace


@pytest.fixture
def ws_with_task(tmp_path):
    """Workspace with a single claimable task."""
    content = (
        "* TODO Claimable task\n"
        "  :PROPERTIES:\n"
        "  :ID: claim-001\n"
        "  :END:\n"
    )
    f = tmp_path / "tasks.org"
    f.write_text(content)
    ws = OrgWorkspace(roots=[f])
    return ws, f


class TestFileLock:
    def test_acquire_and_release(self, tmp_path):
        f = tmp_path / "test.org"
        f.write_text("content")
        lock = FileLock(f)
        lock.acquire()
        lock.release()

    def test_context_manager(self, tmp_path):
        f = tmp_path / "test.org"
        f.write_text("content")
        with FileLock(f):
            pass  # lock held

    def test_second_acquire_times_out(self, tmp_path):
        f = tmp_path / "test.org"
        f.write_text("content")
        lock1 = FileLock(f)
        lock1.acquire()
        try:
            lock2 = FileLock(f)
            with pytest.raises(TimeoutError):
                lock2.acquire(timeout=0.2)
        finally:
            lock1.release()

    def test_release_allows_reacquire(self, tmp_path):
        f = tmp_path / "test.org"
        f.write_text("content")
        lock = FileLock(f)
        lock.acquire()
        lock.release()
        lock.acquire()  # should work
        lock.release()


class TestMultiLock:
    def test_sorted_order(self, tmp_path):
        """INV-6: locks acquired in lexicographic order."""
        b = tmp_path / "b.org"
        a = tmp_path / "a.org"
        b.write_text("b")
        a.write_text("a")
        # Pass in reverse order — should still acquire a first
        with multi_lock([b, a]) as locks:
            assert len(locks) == 2

    def test_deduplicates(self, tmp_path):
        f = tmp_path / "a.org"
        f.write_text("a")
        with multi_lock([f, f]) as locks:
            assert len(locks) == 1


class TestOptimisticLock:
    def test_snapshot_and_verify_unchanged(self, tmp_path):
        f = tmp_path / "test.org"
        f.write_text("original content")
        lock = OptimisticLock(f)
        lock.snapshot()
        assert lock.verify() is True

    def test_verify_detects_change(self, tmp_path):
        f = tmp_path / "test.org"
        f.write_text("original content")
        lock = OptimisticLock(f)
        lock.snapshot()
        f.write_text("modified content")
        assert lock.verify() is False

    def test_save_with_check_succeeds(self, tmp_path):
        f = tmp_path / "test.org"
        f.write_text("original")
        lock = OptimisticLock(f)
        lock.snapshot()
        lock.save_with_check("new content")
        assert f.read_text() == "new content"

    def test_save_with_check_raises_on_conflict(self, tmp_path):
        f = tmp_path / "test.org"
        f.write_text("original")
        lock = OptimisticLock(f)
        lock.snapshot()
        f.write_text("external change")
        with pytest.raises(ConflictError):
            lock.save_with_check("my change")
        # File should still have external change
        assert f.read_text() == "external change"

    def test_no_snapshot_raises(self, tmp_path):
        f = tmp_path / "test.org"
        f.write_text("content")
        lock = OptimisticLock(f)
        with pytest.raises(RuntimeError, match="No snapshot"):
            lock.verify()


class TestTaskClaim:
    def test_claim_succeeds(self, ws_with_task):
        ws, _ = ws_with_task
        node = ws.find_by_id("claim-001")
        tc = TaskClaim(ws)
        assert tc.claim(node, "agent-1") is True
        assert tc.is_claimed(node)
        assert node.properties["CLAIMED_BY"] == "agent-1"

    def test_claim_fails_if_already_claimed(self, ws_with_task):
        ws, _ = ws_with_task
        node = ws.find_by_id("claim-001")
        tc = TaskClaim(ws)
        tc.claim(node, "agent-1")
        assert tc.claim(node, "agent-2") is False

    def test_release_succeeds(self, ws_with_task):
        ws, _ = ws_with_task
        node = ws.find_by_id("claim-001")
        tc = TaskClaim(ws)
        tc.claim(node, "agent-1")
        assert tc.release(node, "agent-1") is True
        assert not tc.is_claimed(node)

    def test_release_fails_wrong_agent(self, ws_with_task):
        ws, _ = ws_with_task
        node = ws.find_by_id("claim-001")
        tc = TaskClaim(ws)
        tc.claim(node, "agent-1")
        assert tc.release(node, "agent-2") is False

    def test_is_stale(self, ws_with_task):
        ws, _ = ws_with_task
        node = ws.find_by_id("claim-001")
        tc = TaskClaim(ws)
        tc.claim(node, "agent-1")
        # With timeout=0, any claim is stale
        assert tc.is_stale(node, timeout_minutes=0) is True

    def test_is_not_stale_fresh(self, ws_with_task):
        ws, _ = ws_with_task
        node = ws.find_by_id("claim-001")
        tc = TaskClaim(ws)
        tc.claim(node, "agent-1")
        # Very large timeout means not stale
        assert tc.is_stale(node, timeout_minutes=9999) is False

    def test_not_claimed_not_stale(self, ws_with_task):
        ws, _ = ws_with_task
        node = ws.find_by_id("claim-001")
        tc = TaskClaim(ws)
        assert tc.is_stale(node) is False

    def test_claim_marks_dirty(self, ws_with_task):
        ws, f = ws_with_task
        node = ws.find_by_id("claim-001")
        tc = TaskClaim(ws)
        tc.claim(node, "agent-1")
        assert f in ws.dirty_files()
