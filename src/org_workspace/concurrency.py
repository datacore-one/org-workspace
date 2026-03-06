"""Concurrency primitives: file locks, optimistic locks, task claims.

INV-6: File locks acquired in lexicographic path order to prevent deadlocks.
"""

from __future__ import annotations

import fcntl
import hashlib
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from org_workspace.node_view import NodeView
    from org_workspace.workspace import OrgWorkspace


class ConflictError(Exception):
    """Raised when optimistic lock detects file changed since snapshot."""


class FileLock:
    """File-level exclusive lock using fcntl.flock.

    Usage:
        lock = FileLock(path)
        with lock:
            # exclusive access to file
    """

    def __init__(self, path: Path):
        self._path = Path(path)
        self._lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        self._fd = None

    def acquire(self, timeout: float = 5.0) -> None:
        """Acquire exclusive lock. Raises TimeoutError if not acquired."""
        self._fd = open(self._lock_path, "w")
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except (OSError, BlockingIOError):
                if time.monotonic() >= deadline:
                    self._fd.close()
                    self._fd = None
                    raise TimeoutError(
                        f"Could not acquire lock on {self._path} "
                        f"within {timeout}s"
                    )
                time.sleep(0.05)

    def release(self) -> None:
        """Release the lock."""
        if self._fd is not None:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            self._fd.close()
            self._fd = None
            try:
                self._lock_path.unlink()
            except OSError:
                pass

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.release()


@contextmanager
def multi_lock(paths: list[Path], timeout: float = 5.0):
    """Acquire file locks in lexicographic order (INV-6).

    Prevents deadlocks by always acquiring locks in a consistent order.
    """
    sorted_paths = sorted(set(Path(p) for p in paths))
    locks = []
    try:
        for path in sorted_paths:
            lock = FileLock(path)
            lock.acquire(timeout)
            locks.append(lock)
        yield locks
    finally:
        # Release in reverse order
        for lock in reversed(locks):
            lock.release()


class OptimisticLock:
    """Optimistic concurrency control using file content hashing.

    Take a snapshot, do work, then verify before saving.
    """

    def __init__(self, path: Path):
        self._path = Path(path)
        self._snapshot_hash: str | None = None

    def snapshot(self) -> str:
        """Take a snapshot of the current file state. Returns hash."""
        content = self._path.read_bytes()
        self._snapshot_hash = hashlib.sha256(content).hexdigest()
        return self._snapshot_hash

    def verify(self) -> bool:
        """Check if file is unchanged since snapshot."""
        if self._snapshot_hash is None:
            raise RuntimeError("No snapshot taken")
        current = hashlib.sha256(self._path.read_bytes()).hexdigest()
        return current == self._snapshot_hash

    def save_with_check(self, content: str) -> None:
        """Write content only if file unchanged since snapshot.

        Raises ConflictError if file was modified externally.
        """
        if not self.verify():
            raise ConflictError(
                f"File {self._path} was modified since snapshot"
            )
        self._path.write_text(content)
        # Update snapshot to reflect new state
        self._snapshot_hash = hashlib.sha256(content.encode()).hexdigest()


class TaskClaim:
    """Task claiming for distributed execution.

    Uses workspace mutation methods (not direct OrgNode mutation).
    For distributed use (nightshift), the caller wraps in git commit/push.
    """

    def __init__(self, workspace: OrgWorkspace):
        self._workspace = workspace

    def claim(self, node: NodeView, agent_id: str) -> bool:
        """Claim a task for execution.

        Sets CLAIMED_BY and CLAIMED_AT properties.
        Returns True if claim succeeded, False if already claimed.
        """
        if self.is_claimed(node):
            return False

        now = datetime.now().strftime("[%Y-%m-%d %a %H:%M]")
        self._workspace.set_property(node, "CLAIMED_BY", agent_id)
        self._workspace.set_property(node, "CLAIMED_AT", now)
        return True

    def release(self, node: NodeView, agent_id: str) -> bool:
        """Release a claim. Only the claiming agent can release.

        Returns True if released, False if not claimed by this agent.
        """
        current_claimer = node.properties.get("CLAIMED_BY")
        if current_claimer != agent_id:
            return False

        # Clear claim properties
        self._workspace.set_property(node, "CLAIMED_BY", "")
        self._workspace.set_property(node, "CLAIMED_AT", "")
        return True

    def is_claimed(self, node: NodeView) -> bool:
        """Check if task is currently claimed."""
        claimer = node.properties.get("CLAIMED_BY")
        return bool(claimer)

    def is_stale(self, node: NodeView, timeout_minutes: int = 30) -> bool:
        """Check if a claim is older than the timeout.

        Returns False if not claimed or if claim is fresh.
        """
        if not self.is_claimed(node):
            return False

        claimed_at = node.properties.get("CLAIMED_AT", "")
        if not claimed_at:
            return True  # Claimed but no timestamp = stale

        # Parse org timestamp: [YYYY-MM-DD Day HH:MM]
        try:
            # Strip brackets and day name
            clean = claimed_at.strip("[]")
            parts = clean.split()
            date_str = parts[0]
            time_str = parts[-1] if ":" in parts[-1] else "00:00"
            dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            return datetime.now() - dt > timedelta(minutes=timeout_minutes)
        except (ValueError, IndexError):
            return True  # Unparseable = treat as stale
