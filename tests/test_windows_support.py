"""Native Windows support.

Two kinds of test live here:

* platform-injected tests, which run everywhere and simulate the Windows
  branch (fake ``msvcrt``, ``fcntl`` missing, injected ``os.replace``
  failures) so the Windows code path is exercised on macOS/Linux too;
* real tests, marked ``windows_only`` / ``posix_only``, which call the real
  platform primitives and only run where those exist.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import types

import pytest

import org_workspace
from org_workspace import _fs, concurrency
from org_workspace.concurrency import FileLock, OptimisticLock
from org_workspace.log import SessionLog
from org_workspace.workspace import OrgWorkspace

windows_only = pytest.mark.skipif(os.name != "nt", reason="real Windows primitives")
posix_only = pytest.mark.skipif(os.name == "nt", reason="real POSIX primitives")

ORG = "* TODO Café task — naïve résumé\n  :PROPERTIES:\n  :ID: w-001\n  :END:\n  Body ✓\n"


# The child interpreter must import the same org_workspace under test.
_SRC = os.path.dirname(os.path.dirname(os.path.abspath(org_workspace.__file__)))


def _run_py(code: str, *flags: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = _SRC + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, *flags, "-c", textwrap.dedent(code)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )


# --- import without fcntl -------------------------------------------------


def test_concurrency_imports_without_fcntl():
    """On Windows ``fcntl`` does not exist; importing must still work."""
    result = _run_py(
        """
        import sys, types
        sys.modules["fcntl"] = None  # makes `import fcntl` raise ImportError
        fake = types.ModuleType("msvcrt")
        fake.LK_NBLCK, fake.LK_UNLCK = 2, 0
        fake.locking = lambda fd, mode, n: None
        sys.modules["msvcrt"] = fake
        import org_workspace.concurrency
        import org_workspace
        print("ok")
        """
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


# --- FileLock, Windows branch injected ------------------------------------


class _FakeMsvcrt(types.ModuleType):
    """Records msvcrt.locking calls; one shared 'held' set per path."""

    LK_UNLCK = 0
    LK_NBLCK = 2

    def __init__(self):
        super().__init__("msvcrt")
        self.calls: list[tuple[int, int, int]] = []
        self.held: set[str] = set()
        self.fd_paths: dict[int, str] = {}

    def locking(self, fd, mode, nbytes):
        self.calls.append((fd, mode, nbytes))
        assert os.lseek(fd, 0, os.SEEK_CUR) == 0, "must lock byte 0"
        key = self.fd_paths[fd]
        if mode == self.LK_NBLCK:
            if key in self.held:
                raise PermissionError(13, "locked")
            self.held.add(key)
        elif mode == self.LK_UNLCK:
            self.held.discard(key)


@pytest.fixture
def fake_windows(monkeypatch):
    fake = _FakeMsvcrt()
    monkeypatch.setattr(concurrency, "_IS_WINDOWS", True)
    monkeypatch.setattr(concurrency, "msvcrt", fake, raising=False)

    real_open = concurrency._open_lock_file

    def tracking_open(path):
        fh = real_open(path)
        fake.fd_paths[fh.fileno()] = str(path)
        return fh

    monkeypatch.setattr(concurrency, "_open_lock_file", tracking_open)
    return fake


def test_windows_filelock_uses_msvcrt_single_byte(tmp_path, fake_windows):
    f = tmp_path / "a.org"
    f.write_text("x", encoding="utf-8")
    lock = FileLock(f)
    lock.acquire()
    lock.release()
    modes = [(mode, n) for _fd, mode, n in fake_windows.calls]
    assert modes == [(_FakeMsvcrt.LK_NBLCK, 1), (_FakeMsvcrt.LK_UNLCK, 1)]


def test_windows_filelock_contention_times_out(tmp_path, fake_windows):
    f = tmp_path / "a.org"
    f.write_text("x", encoding="utf-8")
    first = FileLock(f)
    first.acquire()
    try:
        with pytest.raises(TimeoutError):
            FileLock(f).acquire(timeout=0.15)
    finally:
        first.release()
    # released -> another holder can take it
    with FileLock(f):
        pass


def test_windows_filelock_tolerates_unlink_permission_error(tmp_path, fake_windows, monkeypatch):
    """Deleting a lock file another process holds open fails on Windows."""
    f = tmp_path / "a.org"
    f.write_text("x", encoding="utf-8")
    lock = FileLock(f)
    lock.acquire()

    def deny(self, *a, **k):
        raise PermissionError(13, "in use")

    monkeypatch.setattr(type(lock._lock_path), "unlink", deny)
    lock.release()  # must not raise
    assert lock._fd is None


def test_windows_multi_lock_keeps_lexicographic_order(tmp_path, fake_windows):
    paths = [tmp_path / n for n in ("c.org", "a.org", "b.org")]
    for p in paths:
        p.write_text("x", encoding="utf-8")
    with concurrency.multi_lock(paths) as locks:
        assert [lk._path.name for lk in locks] == ["a.org", "b.org", "c.org"]


# --- os.replace retry -----------------------------------------------------


def test_replace_retries_permission_error_on_windows(tmp_path, monkeypatch):
    src, dst = tmp_path / "s", tmp_path / "d"
    src.write_text("new", encoding="utf-8")
    dst.write_text("old", encoding="utf-8")
    real_replace = os.replace
    attempts = []

    def flaky(a, b):
        attempts.append(1)
        if len(attempts) < 3:
            raise PermissionError(13, "sharing violation")
        real_replace(a, b)

    monkeypatch.setattr(_fs.os, "replace", flaky)
    _fs.replace(src, dst, is_windows=True, delay=0)
    assert len(attempts) == 3
    assert dst.read_text(encoding="utf-8") == "new"


def test_replace_does_not_retry_on_posix(tmp_path, monkeypatch):
    attempts = []

    def deny(a, b):
        attempts.append(1)
        raise PermissionError(13, "denied")

    monkeypatch.setattr(_fs.os, "replace", deny)
    with pytest.raises(PermissionError):
        _fs.replace(tmp_path / "s", tmp_path / "d", is_windows=False, delay=0)
    assert len(attempts) == 1


def test_replace_gives_up_after_retries_on_windows(tmp_path, monkeypatch):
    def deny(a, b):
        raise PermissionError(13, "denied")

    monkeypatch.setattr(_fs.os, "replace", deny)
    with pytest.raises(PermissionError):
        _fs.replace(tmp_path / "s", tmp_path / "d", is_windows=True, delay=0)


# --- encoding: no locale-dependent text IO anywhere ------------------------


def test_no_default_encoding_text_io(tmp_path):
    """Every text read/write must name its encoding (PEP 597).

    Run the library's file paths with EncodingWarning turned into an error:
    any ``open``/``read_text``/``write_text`` without ``encoding=`` fails.
    On Windows such a call would use cp1252 and corrupt non-ASCII notes.
    """
    org = tmp_path / "tasks.org"
    org.write_bytes(ORG.encode("utf-8"))
    deep = (
        "* Projects é\n** Area ü\n*** DONE Old task ✓\n"
        "    :PROPERTIES:\n    :ID: w-003\n    :END:\n"
    )
    (tmp_path / "deep.org").write_bytes(deep.encode("utf-8"))
    code = f"""
        import warnings
        from datetime import date
        from pathlib import Path
        from org_workspace.workspace import OrgWorkspace
        from org_workspace.concurrency import FileLock, OptimisticLock
        from org_workspace.log import SessionLog
        from org_workspace import archive

        org = Path({str(org)!r})
        with FileLock(org):
            pass
        ws = OrgWorkspace(roots=[org])
        node = ws.find_by_id("w-001")
        ws.set_property(node, "NOTE", "Ünïcödé")
        ws.save()
        lock = OptimisticLock(org)
        lock.snapshot()
        lock.save_with_check(org.read_text(encoding="utf-8"))
        log = SessionLog("s1")
        log.log("written ✓")
        log.flush(Path({str(tmp_path / "logs")!r}))
        deep = Path({str(tmp_path / "deep.org")!r})
        ws.load(deep)
        archive.archive_node(ws, ws.find_by_id("w-003"),
                             target=Path({str(tmp_path / "archive.org")!r}))
        ws.save()
        print("ok")
    """
    result = _run_py(code, "-X", "warn_default_encoding", "-W", "error::EncodingWarning")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("ok")


def test_save_writes_utf8_bytes(tmp_path):
    org = tmp_path / "tasks.org"
    org.write_bytes(ORG.encode("utf-8"))
    ws = OrgWorkspace(roots=[org])
    ws.set_property(ws.find_by_id("w-001"), "NOTE", "Ünïcödé ✓")
    ws.save()
    data = org.read_bytes()
    data.decode("utf-8")  # raises if not utf-8
    assert "Ünïcödé ✓".encode("utf-8") in data


# --- line endings ---------------------------------------------------------


def test_save_keeps_lf_files_lf(tmp_path):
    org = tmp_path / "tasks.org"
    org.write_bytes(ORG.encode("utf-8"))
    ws = OrgWorkspace(roots=[org])
    ws.set_property(ws.find_by_id("w-001"), "NOTE", "x")
    ws.save()
    assert b"\r\n" not in org.read_bytes()


def test_save_keeps_crlf_files_crlf(tmp_path):
    """A CRLF file (e.g. a Windows checkout) is not rewritten to LF on save."""
    org = tmp_path / "tasks.org"
    org.write_bytes(ORG.replace("\n", "\r\n").encode("utf-8"))
    ws = OrgWorkspace(roots=[org])
    ws.set_property(ws.find_by_id("w-001"), "NOTE", "x")
    ws.save()
    data = org.read_bytes()
    assert data.count(b"\n") == data.count(b"\r\n")
    assert b"\r\r" not in data
    assert b"NOTE" in data


def test_optimistic_lock_snapshot_matches_disk_after_save(tmp_path):
    """save_with_check must hash exactly the bytes it wrote."""
    org = tmp_path / "tasks.org"
    org.write_bytes(ORG.encode("utf-8"))
    lock = OptimisticLock(org)
    lock.snapshot()
    lock.save_with_check("* line one é\n* line two\n")
    assert lock.verify()
    assert org.read_bytes() == "* line one é\n* line two\n".encode("utf-8")


def test_session_log_is_utf8_lf(tmp_path):
    log = SessionLog("s1")
    log.log("Café ✓")
    path = log.flush(tmp_path)
    data = path.read_bytes()
    assert "Café ✓".encode("utf-8") in data
    assert b"\r\n" not in data


# --- real platform primitives --------------------------------------------


@windows_only
def test_real_windows_lock_contention_across_processes(tmp_path):
    f = tmp_path / "a.org"
    f.write_text("x", encoding="utf-8")
    with FileLock(f):
        result = _run_py(
            f"""
            from pathlib import Path
            from org_workspace.concurrency import FileLock
            try:
                FileLock(Path({str(f)!r})).acquire(timeout=0.3)
                print("acquired")
            except TimeoutError:
                print("timeout")
            """
        )
        assert result.stdout.strip() == "timeout", result.stderr
    with FileLock(f):
        pass


@windows_only
def test_real_windows_release_while_other_handle_open(tmp_path):
    """Lock file held open elsewhere: release must not raise on unlink."""
    f = tmp_path / "a.org"
    f.write_text("x", encoding="utf-8")
    lock = FileLock(f)
    lock.acquire()
    other = open(lock._lock_path, "a+", encoding="utf-8")
    try:
        lock.release()
    finally:
        other.close()
    with FileLock(f):
        pass


@windows_only
def test_real_windows_save_over_file_no_crlf(tmp_path):
    org = tmp_path / "tasks.org"
    org.write_bytes(ORG.encode("utf-8"))
    ws = OrgWorkspace(roots=[org])
    ws.set_property(ws.find_by_id("w-001"), "NOTE", "x")
    ws.save()
    ws.set_property(ws.find_by_id("w-001"), "NOTE", "y")
    ws.save()
    assert b"\r\n" not in org.read_bytes()


@posix_only
def test_real_posix_lock_uses_fcntl(tmp_path):
    assert concurrency._IS_WINDOWS is False
    f = tmp_path / "a.org"
    f.write_text("x", encoding="utf-8")
    result_holder = FileLock(f)
    result_holder.acquire()
    try:
        result = _run_py(
            f"""
            from pathlib import Path
            from org_workspace.concurrency import FileLock
            try:
                FileLock(Path({str(f)!r})).acquire(timeout=0.3)
                print("acquired")
            except TimeoutError:
                print("timeout")
            """
        )
        assert result.stdout.strip() == "timeout", result.stderr
    finally:
        result_holder.release()
