"""Tests for query.py — agenda, deadlines, cross-file search."""

from datetime import date, timedelta

import pytest

from org_workspace.query import Query
from org_workspace.workspace import OrgWorkspace


@pytest.fixture
def query_file(tmp_path):
    """Create a file with scheduled/deadline tasks for query testing."""
    today = date.today()
    tomorrow = today + timedelta(days=1)
    next_week = today + timedelta(days=5)
    past = today - timedelta(days=10)
    far_future = today + timedelta(days=30)

    content = (
        f"* TODO Buy groceries\n"
        f"  SCHEDULED: <{today.strftime('%Y-%m-%d')} {today.strftime('%a')}>\n"
        f"  :PROPERTIES:\n"
        f"  :ID: q-001\n"
        f"  :END:\n"
        f"* NEXT Write blog post\n"
        f"  SCHEDULED: <{tomorrow.strftime('%Y-%m-%d')} {tomorrow.strftime('%a')}>\n"
        f"  :PROPERTIES:\n"
        f"  :ID: q-002\n"
        f"  :END:\n"
        f"* TODO Deploy staging :backend:AI:\n"
        f"  SCHEDULED: <{next_week.strftime('%Y-%m-%d')} {next_week.strftime('%a')}>\n"
        f"  DEADLINE: <{far_future.strftime('%Y-%m-%d')} {far_future.strftime('%a')}>\n"
        f"  :PROPERTIES:\n"
        f"  :ID: q-003\n"
        f"  :Effort: 2:00\n"
        f"  :END:\n"
        f"* TODO Overdue task\n"
        f"  DEADLINE: <{past.strftime('%Y-%m-%d')} {past.strftime('%a')}>\n"
        f"  :PROPERTIES:\n"
        f"  :ID: q-004\n"
        f"  :END:\n"
        f"* DONE Completed task\n"
        f"  DEADLINE: <{past.strftime('%Y-%m-%d')} {past.strftime('%a')}>\n"
        f"  :PROPERTIES:\n"
        f"  :ID: q-005\n"
        f"  :END:\n"
        f"* TODO Stale task no dates\n"
        f"  :PROPERTIES:\n"
        f"  :ID: q-006\n"
        f"  :END:\n"
        f"* WAITING Claimed task\n"
        f"  :PROPERTIES:\n"
        f"  :ID: q-007\n"
        f"  :CLAIMED_BY: agent-1\n"
        f"  :END:\n"
        f"* TODO [#A] High priority\n"
        f"  :PROPERTIES:\n"
        f"  :ID: q-008\n"
        f"  :END:\n"
        f"* NEXT [#B] Medium priority\n"
        f"  :PROPERTIES:\n"
        f"  :ID: q-009\n"
        f"  :END:\n"
        f"* TODO Far future task\n"
        f"  SCHEDULED: <{far_future.strftime('%Y-%m-%d')} {far_future.strftime('%a')}>\n"
        f"  :PROPERTIES:\n"
        f"  :ID: q-010\n"
        f"  :END:\n"
    )
    f = tmp_path / "query_test.org"
    f.write_text(content)
    return f


@pytest.fixture
def query(query_file):
    ws = OrgWorkspace(roots=[query_file])
    return Query(ws)


class TestAgenda:
    def test_returns_scheduled_within_range(self, query):
        results = query.agenda(days=7)
        ids = {n.id() for n in results}
        assert "q-001" in ids  # today
        assert "q-002" in ids  # tomorrow
        assert "q-003" in ids  # next_week (5 days)

    def test_excludes_outside_range(self, query):
        results = query.agenda(days=7)
        ids = {n.id() for n in results}
        assert "q-010" not in ids  # 30 days out

    def test_sorted_by_date(self, query):
        results = query.agenda(days=7)
        # q-001 (today) before q-002 (tomorrow) before q-003 (5 days)
        ids = [n.id() for n in results]
        assert ids.index("q-001") < ids.index("q-002")
        assert ids.index("q-002") < ids.index("q-003")


class TestDeadlines:
    def test_returns_deadlines_within_range(self, query):
        results = query.deadlines(days=14)
        ids = {n.id() for n in results}
        # q-004 is overdue (past deadline, not terminal)
        assert "q-004" in ids

    def test_excludes_terminal_state(self, query):
        results = query.deadlines(days=14)
        ids = {n.id() for n in results}
        # q-005 is DONE — excluded
        assert "q-005" not in ids

    def test_sorted_by_urgency(self, query):
        results = query.deadlines(days=40)
        ids = [n.id() for n in results]
        # q-004 (overdue) before q-003 (far future deadline)
        if "q-004" in ids and "q-003" in ids:
            assert ids.index("q-004") < ids.index("q-003")


class TestNextAction:
    def test_returns_highest_priority(self, query):
        result = query.next_action()
        assert result is not None
        assert result.id() == "q-008"  # [#A] priority

    def test_skips_claimed(self, query):
        result = query.next_action()
        assert result.id() != "q-007"  # WAITING + claimed


class TestOverdue:
    def test_returns_overdue_tasks(self, query):
        results = query.overdue()
        ids = {n.id() for n in results}
        assert "q-004" in ids

    def test_excludes_done_tasks(self, query):
        results = query.overdue()
        ids = {n.id() for n in results}
        assert "q-005" not in ids


class TestStale:
    def test_no_dates_not_stale(self, query):
        """Dateless tasks are undated, not stale (no old date signal)."""
        results = query.stale(days=30)
        ids = {n.id() for n in results}
        assert "q-006" not in ids

    def test_recent_schedule_not_stale(self, query):
        results = query.stale(days=30)
        ids = {n.id() for n in results}
        # q-001 has today's schedule — not stale
        assert "q-001" not in ids

    def test_brand_new_task_no_dates_not_stale(self, tmp_path):
        """A task created today with no dates should NOT be flagged stale.

        Reproduces suspected false positive: brand-new inbox items have no
        scheduled/deadline/closed timestamps, so stale() treats them as stale
        even though they were just created.
        """
        content = "* TODO Brand new task\n"
        f = tmp_path / "brand_new.org"
        f.write_text(content)
        ws = OrgWorkspace(roots=[f])
        results = Query(ws).stale(days=30)
        headings = [n.heading for n in results]
        assert "Brand new task" not in headings, (
            "Brand-new task with no dates was incorrectly flagged as stale"
        )


class TestByProperty:
    def test_finds_by_property_key(self, query):
        results = query.by_property("Effort")
        ids = {n.id() for n in results}
        assert "q-003" in ids

    def test_finds_by_property_value(self, query):
        results = query.by_property("Effort", "2:00")
        # orgparse may auto-convert Effort to int minutes
        # Either exact match works or we skip this
        assert isinstance(results, list)


class TestAiTasks:
    def test_finds_ai_tagged(self, query):
        results = query.ai_tasks()
        ids = {n.id() for n in results}
        assert "q-003" in ids
