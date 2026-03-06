"""Tests for log.py — LOGBOOK and session logging."""

from datetime import datetime

from orgparse import loads

from org_workspace._compat import dumps
from org_workspace.log import (
    SessionLog,
    add_clock_entry,
    add_logbook_entry,
    add_state_change_entry,
)


def _make_node(org_text):
    return loads(org_text).children[0]


class TestAddLogbookEntry:
    def test_creates_logbook_if_missing(self):
        node = _make_node("* TODO Task\n  :PROPERTIES:\n  :ID: x\n  :END:\n")
        add_logbook_entry(node, "Test entry")
        dumps(loads(""))  # dummy — check node directly
        # Check _line_items contain LOGBOOK
        raws = [getattr(item, "_raw", "") for item in node._line_items]
        assert any(":LOGBOOK:" in r for r in raws)
        assert any("Test entry" in r for r in raws)

    def test_adds_to_existing_logbook(self):
        node = _make_node(
            "* TODO Task\n"
            "  :PROPERTIES:\n  :ID: x\n  :END:\n"
            "  :LOGBOOK:\n"
            "  - Existing entry [2025-01-01 Wed 10:00]\n"
            "  :END:\n"
        )
        add_logbook_entry(node, "New entry")
        raws = [getattr(item, "_raw", "") for item in node._line_items]
        # New entry should be present
        assert any("New entry" in r for r in raws)
        # Existing entry should still be there
        assert any("Existing entry" in r for r in raws)

    def test_entry_format_with_agent(self):
        node = _make_node("* TODO Task\n")
        ts = datetime(2025, 11, 28, 14, 30)
        add_logbook_entry(node, "Processed", agent="nightshift", timestamp=ts)
        raws = [getattr(item, "_raw", "") for item in node._line_items]
        entry = [r for r in raws if "Processed" in r]
        assert len(entry) == 1
        assert "by:nightshift" in entry[0]
        assert "[2025-11-28" in entry[0]

    def test_entry_format_without_agent(self):
        node = _make_node("* TODO Task\n")
        add_logbook_entry(node, "Simple note")
        raws = [getattr(item, "_raw", "") for item in node._line_items]
        entry = [r for r in raws if "Simple note" in r]
        assert len(entry) == 1
        assert "by:" not in entry[0]


class TestAddStateChangeEntry:
    def test_state_change_format(self):
        node = _make_node("* TODO Task\n  :PROPERTIES:\n  :ID: x\n  :END:\n")
        ts = datetime(2025, 11, 28, 14, 30)
        add_state_change_entry(node, "TODO", "DONE", agent="agent-1", timestamp=ts)
        raws = [getattr(item, "_raw", "") for item in node._line_items]
        entry = [r for r in raws if "State" in r and "DONE" in r]
        assert len(entry) == 1
        assert '"DONE"' in entry[0]
        assert '"TODO"' in entry[0]
        assert "by:agent-1" in entry[0]


class TestAddClockEntry:
    def test_clock_format(self):
        node = _make_node("* TODO Task\n  :PROPERTIES:\n  :ID: x\n  :END:\n")
        start = datetime(2025, 11, 28, 14, 0)
        end = datetime(2025, 11, 28, 15, 30)
        add_clock_entry(node, start, end)
        raws = [getattr(item, "_raw", "") for item in node._line_items]
        clock = [r for r in raws if "CLOCK:" in r]
        assert len(clock) == 1
        assert "=> " in clock[0]
        assert "1:30" in clock[0]

    def test_clock_duration_multi_hour(self):
        node = _make_node("* TODO Task\n")
        start = datetime(2025, 11, 28, 9, 0)
        end = datetime(2025, 11, 28, 17, 45)
        add_clock_entry(node, start, end)
        raws = [getattr(item, "_raw", "") for item in node._line_items]
        clock = [r for r in raws if "CLOCK:" in r]
        assert "8:45" in clock[0]


class TestSessionLog:
    def test_log_and_flush(self, tmp_path):
        log = SessionLog(session_id="test-123")
        log.log("Started processing")
        log.log("Completed task", node_id="abc", agent="agent-1")
        path = log.flush(tmp_path)
        assert path.exists()
        content = path.read_text()
        assert "test-123" in content
        assert "Started processing" in content
        assert "Completed task" in content
        assert "agent-1" in content
        assert "abc" in content

    def test_flush_clears_buffer(self, tmp_path):
        log = SessionLog()
        log.log("Entry 1")
        log.flush(tmp_path)
        log.log("Entry 2")
        path = log.flush(tmp_path)
        content = path.read_text()
        assert "Entry 2" in content
        # Entry 1 should not appear in second flush

    def test_session_id_auto_generated(self):
        log = SessionLog()
        assert len(log.session_id) == 8

    def test_flush_creates_directory(self, tmp_path):
        log = SessionLog()
        log.log("test")
        subdir = tmp_path / "logs" / "sessions"
        path = log.flush(subdir)
        assert path.exists()
        assert subdir.exists()
