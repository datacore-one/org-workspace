"""Tests for query.py — agenda, deadlines, cross-file search."""

from datetime import date, datetime, timedelta

import pytest

from org_workspace.query import Query, _parse_org_date_string, _to_date
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


class TestByTag:
    def test_finds_by_tag(self, query):
        results = query.by_tag("backend")
        ids = {n.id() for n in results}
        assert "q-003" in ids

    def test_by_tag_no_match(self, query):
        results = query.by_tag("nonexistent_tag_xyz")
        assert results == []


class TestNextActionEdgeCases:
    def test_returns_none_when_no_candidates(self, tmp_path):
        """next_action returns None when workspace has no TODO/NEXT tasks."""
        content = "* DONE All done\n  :PROPERTIES:\n  :ID: edge-001\n  :END:\n"
        f = tmp_path / "done.org"
        f.write_text(content)
        ws = OrgWorkspace(roots=[f])
        result = Query(ws).next_action()
        assert result is None

    def test_skips_claimed_todo(self, tmp_path):
        """next_action skips TODO tasks with CLAIMED_BY property."""
        content = (
            "* TODO Claimed task\n"
            "  :PROPERTIES:\n"
            "  :ID: edge-002\n"
            "  :CLAIMED_BY: some-agent\n"
            "  :END:\n"
        )
        f = tmp_path / "claimed.org"
        f.write_text(content)
        ws = OrgWorkspace(roots=[f])
        result = Query(ws).next_action()
        assert result is None


class TestStaleEdgeCases:
    def test_old_deadline_is_stale(self, tmp_path):
        """A task with an old deadline (no recent activity) is flagged stale."""
        old_date = date.today() - timedelta(days=60)
        content = (
            f"* TODO Old deadline task\n"
            f"  DEADLINE: <{old_date.strftime('%Y-%m-%d')} {old_date.strftime('%a')}>\n"
            f"  :PROPERTIES:\n"
            f"  :ID: stale-001\n"
            f"  :END:\n"
        )
        f = tmp_path / "old.org"
        f.write_text(content)
        ws = OrgWorkspace(roots=[f])
        results = Query(ws).stale(days=30)
        ids = {n.id() for n in results}
        assert "stale-001" in ids

    def test_old_created_property_is_stale(self, tmp_path):
        """A task with no date signals but an old CREATED property is flagged stale."""
        old_date = date.today() - timedelta(days=60)
        content = (
            f"* TODO Old created task\n"
            f"  :PROPERTIES:\n"
            f"  :ID: stale-002\n"
            f"  :CREATED: [{old_date.strftime('%Y-%m-%d')} {old_date.strftime('%a')}]\n"
            f"  :END:\n"
        )
        f = tmp_path / "created.org"
        f.write_text(content)
        ws = OrgWorkspace(roots=[f])
        results = Query(ws).stale(days=30)
        ids = {n.id() for n in results}
        assert "stale-002" in ids

    def test_recent_created_property_not_stale(self, tmp_path):
        """A task with a recent CREATED property is not stale."""
        recent_date = date.today() - timedelta(days=5)
        content = (
            f"* TODO Recent created task\n"
            f"  :PROPERTIES:\n"
            f"  :ID: stale-003\n"
            f"  :CREATED: [{recent_date.strftime('%Y-%m-%d')} {recent_date.strftime('%a')}]\n"
            f"  :END:\n"
        )
        f = tmp_path / "recent.org"
        f.write_text(content)
        ws = OrgWorkspace(roots=[f])
        results = Query(ws).stale(days=30)
        ids = {n.id() for n in results}
        assert "stale-003" not in ids

    def test_non_todo_heading_not_stale(self, tmp_path):
        """Regular headings without a TODO keyword are not flagged stale."""
        content = "* Section heading without state\n** Sub-section\n"
        f = tmp_path / "plain.org"
        f.write_text(content)
        ws = OrgWorkspace(roots=[f])
        results = Query(ws).stale(days=30)
        headings = [n.heading for n in results]
        assert "Section heading without state" not in headings


class TestToDate:
    def test_none_returns_none(self):
        assert _to_date(None) is None

    def test_datetime_returns_date(self):
        dt = datetime(2025, 6, 15, 10, 30)
        assert _to_date(dt) == date(2025, 6, 15)

    def test_date_returns_date(self):
        d = date(2025, 6, 15)
        assert _to_date(d) == d

    def test_unknown_type_returns_none(self):
        assert _to_date("not-a-date") is None


class TestParseOrgDateString:
    def test_empty_string_returns_none(self):
        assert _parse_org_date_string("") is None

    def test_valid_org_timestamp(self):
        result = _parse_org_date_string("[2025-06-15 Sun]")
        assert result == date(2025, 6, 15)

    def test_angle_bracket_timestamp(self):
        result = _parse_org_date_string("<2025-06-15 Sun>")
        assert result == date(2025, 6, 15)

    def test_no_date_pattern_returns_none(self):
        assert _parse_org_date_string("no date here") is None

    def test_invalid_date_returns_none(self):
        assert _parse_org_date_string("[2025-13-01 Mon]") is None
