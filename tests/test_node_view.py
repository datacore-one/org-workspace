"""Tests for node_view.py — NodeView stateless read-only view."""

from datetime import timedelta
from pathlib import Path

import pytest
from org_workspace._vendor.orgparse import load, loads

from org_workspace.node_view import NodeView, StaleNodeError


def _make_view(org_text: str, state_config=None) -> NodeView:
    """Helper to create a NodeView from org text."""
    root = loads(org_text)
    node = root.children[0]
    return NodeView(node, Path("test.org"), state_config)


class TestNodeViewReadOnly:
    """NodeView wraps OrgNode and exposes read-only properties."""

    def test_heading(self):
        view = _make_view("* TODO My task\n")
        assert view.heading == "My task"

    def test_todo(self):
        view = _make_view("* TODO My task\n")
        assert view.todo == "TODO"

    def test_todo_none(self):
        view = _make_view("* Just a heading\n")
        assert view.todo is None

    def test_tags(self):
        view = _make_view("* TODO Tagged task :project:backend:\n")
        assert "project" in view.tags
        assert "backend" in view.tags

    def test_properties(self):
        view = _make_view("* TODO Task\n  :PROPERTIES:\n  :ID: abc-123\n  :END:\n")
        assert view.properties["ID"] == "abc-123"

    def test_body(self):
        view = _make_view("* TODO Task\n  Body text here.\n")
        assert "Body text here" in view.body

    def test_level(self):
        view = _make_view("* TODO Level 1\n")
        assert view.level == 1

    def test_id(self):
        view = _make_view("* TODO Task\n  :PROPERTIES:\n  :ID: my-id-123\n  :END:\n")
        assert view.id() == "my-id-123"

    def test_id_none(self):
        view = _make_view("* TODO Task without ID\n")
        assert view.id() is None

    def test_get_property_simple(self):
        view = _make_view("* TODO Task\n  :PROPERTIES:\n  :ID: abc\n  :STATUS: active\n  :END:\n")
        assert view.get_property("STATUS") == "active"
        assert view.get_property("MISSING") is None

    def test_from_file(self, rich_task_org):
        root = load(str(rich_task_org))
        node = root.children[0]
        view = NodeView(node, rich_task_org)
        assert view.heading == "[1/3] Implement authentication system"
        assert view.todo == "TODO"
        assert "project" in view.tags
        assert view.scheduled is not None
        assert view.deadline is not None

    def test_children(self):
        root = loads("* Parent\n** Child 1\n** Child 2\n")
        parent = root.children[0]
        view = NodeView(parent, Path("test.org"))
        children = view.children
        assert len(children) == 2
        assert children[0].heading == "Child 1"
        assert isinstance(children[0], NodeView)

    def test_parent(self):
        root = loads("* Parent\n** Child\n")
        child = root.children[0].children[0]
        view = NodeView(child, Path("test.org"))
        parent = view.parent
        assert parent is not None
        assert parent.heading == "Parent"


class TestEffortDuration:
    """effort_duration() parses Effort property."""

    def test_hmm_format(self):
        view = _make_view("* TODO Task\n  :PROPERTIES:\n  :Effort: 2:00\n  :END:\n")
        assert view.effort_duration() == timedelta(hours=2)

    def test_hmm_with_minutes(self):
        view = _make_view("* TODO Task\n  :PROPERTIES:\n  :Effort: 0:30\n  :END:\n")
        assert view.effort_duration() == timedelta(minutes=30)

    def test_orgparse_autoconvert(self):
        """orgparse auto-converts Effort to minutes (int)."""
        # orgparse converts "8:00" to 480 (minutes)
        view = _make_view("* TODO Task\n  :PROPERTIES:\n  :Effort: 8:00\n  :END:\n")
        result = view.effort_duration()
        assert result == timedelta(hours=8)

    def test_no_effort(self):
        view = _make_view("* TODO Task\n")
        assert view.effort_duration() is None

    def test_no_effort_property(self):
        """Task without any Effort property returns None."""
        view = _make_view("* TODO Task\n  :PROPERTIES:\n  :ID: x\n  :END:\n")
        assert view.effort_duration() is None


class TestChecklists:
    """checklists() and progress() parse body checkboxes."""

    def test_checklists(self, rich_task_org):
        root = load(str(rich_task_org))
        view = NodeView(root.children[0], rich_task_org)
        items = view.checklists()
        assert len(items) == 3
        assert items[0].checked is True  # Design token schema
        assert items[1].checked is False  # Implement login endpoint

    def test_progress(self, rich_task_org):
        root = load(str(rich_task_org))
        view = NodeView(root.children[0], rich_task_org)
        checked, total = view.progress()
        assert checked == 1
        assert total == 3

    def test_progress_empty(self):
        view = _make_view("* TODO No checklist\n  Just text.\n")
        assert view.progress() == (0, 0)


class TestEquality:
    """NodeView equality and hashing."""

    def test_same_node_equal(self):
        root = loads("* TODO Task\n  :PROPERTIES:\n  :ID: abc\n  :END:\n")
        node = root.children[0]
        v1 = NodeView(node, Path("test.org"))
        v2 = NodeView(node, Path("test.org"))
        assert v1 == v2

    def test_same_id_equal(self):
        r1 = loads("* TODO Task\n  :PROPERTIES:\n  :ID: abc\n  :END:\n")
        r2 = loads("* DONE Task\n  :PROPERTIES:\n  :ID: abc\n  :END:\n")
        v1 = NodeView(r1.children[0], Path("a.org"))
        v2 = NodeView(r2.children[0], Path("b.org"))
        assert v1 == v2

    def test_different_id_not_equal(self):
        r1 = loads("* TODO Task\n  :PROPERTIES:\n  :ID: abc\n  :END:\n")
        r2 = loads("* TODO Task\n  :PROPERTIES:\n  :ID: xyz\n  :END:\n")
        v1 = NodeView(r1.children[0], Path("test.org"))
        v2 = NodeView(r2.children[0], Path("test.org"))
        assert v1 != v2

    def test_hashable(self):
        view = _make_view("* TODO Task\n  :PROPERTIES:\n  :ID: abc\n  :END:\n")
        s = {view}
        assert view in s


class TestNoMutationMethods:
    """NodeView does NOT have mutation methods — that's by design."""

    def test_no_transition(self):
        view = _make_view("* TODO Task\n")
        assert not hasattr(view, "transition")

    def test_no_set_heading(self):
        view = _make_view("* TODO Task\n")
        assert not hasattr(view, "set_heading")

    def test_no_set_tags(self):
        view = _make_view("* TODO Task\n")
        assert not hasattr(view, "set_tags")

    def test_no_set_property(self):
        view = _make_view("* TODO Task\n")
        assert not hasattr(view, "set_property")


class TestStaleness:
    """NodeView detects staleness via generation counter."""

    def test_stale_raises(self):
        gen = [0]
        view = NodeView(
            loads("* TODO Task\n").children[0],
            Path("test.org"),
            generation=0,
            gen_check=lambda: gen[0],
        )
        assert view.heading == "Task"  # works at gen 0

        gen[0] = 1  # simulate reload
        with pytest.raises(StaleNodeError):
            _ = view.heading

    def test_not_stale(self):
        gen = [0]
        view = NodeView(
            loads("* TODO Task\n").children[0],
            Path("test.org"),
            generation=0,
            gen_check=lambda: gen[0],
        )
        assert view.heading == "Task"  # gen matches, no error

    def test_no_gen_check_never_stale(self):
        """Without gen_check, staleness is not checked."""
        view = _make_view("* TODO Task\n")
        assert view.heading == "Task"  # always works


class TestRepr:
    def test_repr(self):
        view = _make_view("* TODO My task\n  :PROPERTIES:\n  :ID: abc\n  :END:\n")
        r = repr(view)
        assert "TODO" in r
        assert "My task" in r
        assert "abc" in r
