"""Tests for workspace.py — OrgWorkspace multi-file container."""

import shutil
from pathlib import Path

import pytest
from org_workspace._vendor.orgparse import load

from org_workspace._compat import dumps
from org_workspace._types import StateConfig
from org_workspace.node_view import NodeView, StaleNodeError
from org_workspace.workspace import InvalidTransitionError, OrgWorkspace


@pytest.fixture
def ws_two_files(tmp_path, minimal_org, nightshift_org):
    """Workspace with two files copied to tmp dir."""
    f1 = tmp_path / "minimal.org"
    f2 = tmp_path / "nightshift.org"
    shutil.copy(minimal_org, f1)
    shutil.copy(nightshift_org, f2)
    ws = OrgWorkspace(roots=[f1, f2])
    return ws, f1, f2


@pytest.fixture
def ws_multi(tmp_path, multi_file_dir):
    """Workspace from multi_file fixture dir."""
    dst = tmp_path / "multi"
    shutil.copytree(multi_file_dir, dst)
    ws = OrgWorkspace(roots=[dst])
    return ws, dst


class TestLoading:
    def test_load_two_files(self, ws_two_files):
        ws, f1, f2 = ws_two_files
        assert len(ws.files()) == 2
        assert f1 in ws.files()
        assert f2 in ws.files()

    def test_load_directory(self, ws_multi):
        ws, dst = ws_multi
        assert len(ws.files()) == 4  # next_actions, inbox, nightshift, archive

    def test_all_nodes_iterates_across_files(self, ws_two_files):
        ws, _, _ = ws_two_files
        nodes = list(ws.all_nodes())
        assert len(nodes) > 0
        assert all(isinstance(n, NodeView) for n in nodes)


class TestFindMethods:
    def test_find_by_id(self, ws_two_files):
        ws, _, _ = ws_two_files
        node = ws.find_by_id("550e8400-e29b-41d4-a716-446655440001")
        assert node is not None
        assert node.heading == "Simple task"

    def test_find_by_id_cross_file(self, ws_two_files):
        ws, _, _ = ws_two_files
        node = ws.find_by_id("ns-001")
        assert node is not None
        assert "Research" in node.heading

    def test_find_by_id_missing(self, ws_two_files):
        ws, _, _ = ws_two_files
        assert ws.find_by_id("nonexistent") is None

    def test_find_by_state(self, ws_two_files):
        ws, _, _ = ws_two_files
        todos = ws.find_by_state("TODO")
        assert len(todos) >= 1
        assert all(n.todo == "TODO" for n in todos)

    def test_find_by_multiple_states(self, ws_two_files):
        ws, _, _ = ws_two_files
        results = ws.find_by_state("TODO", "DONE")
        states = {n.todo for n in results}
        assert states <= {"TODO", "DONE"}

    def test_find_by_tag(self, ws_multi):
        ws, _ = ws_multi
        results = ws.find_by_tag("writing")
        assert len(results) >= 1

    def test_find_ai_tasks(self, ws_two_files):
        ws, _, _ = ws_two_files
        ai_tasks = ws.find_ai_tasks()
        assert len(ai_tasks) >= 1
        # All should have AI-related tags
        for task in ai_tasks:
            tags = task.tags
            assert any("AI" in t for t in tags)

    def test_find_ai_tasks_with_state_filter(self, ws_two_files):
        ws, _, _ = ws_two_files
        queued = ws.find_ai_tasks(states=["QUEUED"])
        for task in queued:
            assert task.todo == "QUEUED"


class TestTransition:
    def test_transition_todo_to_done(self, ws_two_files):
        ws, f1, _ = ws_two_files
        node = ws.find_by_id("550e8400-e29b-41d4-a716-446655440001")
        assert node.todo == "TODO"
        ws.transition(node, "DONE")
        assert node.todo == "DONE"

    def test_transition_marks_dirty(self, ws_two_files):
        ws, f1, _ = ws_two_files
        node = ws.find_by_id("550e8400-e29b-41d4-a716-446655440001")
        assert f1 not in ws.dirty_files()
        ws.transition(node, "NEXT")
        assert f1 in ws.dirty_files()

    def test_transition_terminal_sets_closed(self, ws_two_files):
        ws, _, _ = ws_two_files
        node = ws.find_by_id("550e8400-e29b-41d4-a716-446655440001")
        ws.transition(node, "DONE")
        # Check CLOSED is set
        raw = node.node
        assert raw.closed is not None

    def test_transition_with_agent(self, ws_two_files):
        ws, _, _ = ws_two_files
        node = ws.find_by_id("550e8400-e29b-41d4-a716-446655440001")
        ws.transition(node, "DONE", agent="nightshift-agent")
        assert node.properties.get("COMPLETED_BY") == "nightshift-agent"

    def test_invalid_transition_raises(self, ws_two_files):
        ws, _, _ = ws_two_files
        # DONE -> TODO is invalid (terminal can't transition)
        node = ws.find_by_id("550e8400-e29b-41d4-a716-446655440002")
        assert node.todo == "DONE"
        with pytest.raises(InvalidTransitionError):
            ws.transition(node, "TODO")

    def test_unknown_state_raises(self, ws_two_files):
        ws, _, _ = ws_two_files
        node = ws.find_by_id("550e8400-e29b-41d4-a716-446655440001")
        with pytest.raises(InvalidTransitionError):
            ws.transition(node, "BOGUS")

    def test_transition_noop_same_state(self, ws_two_files):
        ws, f1, _ = ws_two_files
        node = ws.find_by_id("550e8400-e29b-41d4-a716-446655440001")
        ws.transition(node, "TODO")  # same state
        assert f1 not in ws.dirty_files()

    def test_transition_nightshift_states(self, tmp_path, nightshift_org):
        """Nightshift state config allows QUEUED -> EXECUTING."""
        f = tmp_path / "ns.org"
        shutil.copy(nightshift_org, f)
        ws = OrgWorkspace(roots=[f], state_config=StateConfig.nightshift())
        node = ws.find_by_id("ns-001")
        assert node.todo == "QUEUED"
        ws.transition(node, "EXECUTING")
        assert node.todo == "EXECUTING"


class TestSetProperty:
    def test_set_property(self, ws_two_files):
        ws, f1, _ = ws_two_files
        node = ws.find_by_id("550e8400-e29b-41d4-a716-446655440001")
        ws.set_property(node, "STATUS", "active")
        assert node.properties["STATUS"] == "active"
        assert f1 in ws.dirty_files()

    def test_set_property_preserves_existing(self, ws_two_files):
        ws, _, _ = ws_two_files
        node = ws.find_by_id("550e8400-e29b-41d4-a716-446655440001")
        ws.set_property(node, "NEW_KEY", "new_value")
        assert node.properties["ID"] == "550e8400-e29b-41d4-a716-446655440001"
        assert node.properties["NEW_KEY"] == "new_value"


    def test_set_multiline_property(self, ws_two_files):
        ws, f1, _ = ws_two_files
        node = ws.find_by_id("550e8400-e29b-41d4-a716-446655440001")
        ws.set_property(node, "CONTEXT", "Line one\nLine two\nLine three")
        # Verify via get_property (multiline-aware)
        result = ws.get_property(node, "CONTEXT")
        assert result is not None
        assert "Line one" in result
        assert "Line three" in result
        assert f1 in ws.dirty_files()

    def test_get_property_single_line(self, ws_two_files):
        ws, _, _ = ws_two_files
        node = ws.find_by_id("550e8400-e29b-41d4-a716-446655440001")
        ws.set_property(node, "STATUS", "active")
        assert ws.get_property(node, "STATUS") == "active"

    def test_get_property_missing(self, ws_two_files):
        ws, _, _ = ws_two_files
        node = ws.find_by_id("550e8400-e29b-41d4-a716-446655440001")
        assert ws.get_property(node, "NONEXISTENT") is None


class TestSetHeading:
    def test_set_heading(self, ws_two_files):
        ws, f1, _ = ws_two_files
        node = ws.find_by_id("550e8400-e29b-41d4-a716-446655440001")
        ws.set_heading(node, "Renamed task")
        assert node.heading == "Renamed task"
        assert f1 in ws.dirty_files()


class TestSetTags:
    def test_set_tags(self, ws_two_files):
        ws, f1, _ = ws_two_files
        node = ws.find_by_id("550e8400-e29b-41d4-a716-446655440001")
        ws.set_tags(node, ["urgent", "backend"])
        assert "urgent" in node.tags
        assert "backend" in node.tags
        assert f1 in ws.dirty_files()


class TestUpdateProgressCookie:
    def test_update_existing_cookie(self, tmp_path, rich_task_org):
        f = tmp_path / "rich.org"
        shutil.copy(rich_task_org, f)
        ws = OrgWorkspace(roots=[f])
        node = ws.find_by_id("550e8400-e29b-41d4-a716-446655440010")
        ws.update_progress_cookie(node)
        assert "[1/3]" in node.heading

    def test_no_cookie_when_no_checklist(self, ws_two_files):
        ws, _, _ = ws_two_files
        node = ws.find_by_id("550e8400-e29b-41d4-a716-446655440002")
        ws.update_progress_cookie(node)
        # No change expected
        assert "[" not in node.heading


class TestCreateNode:
    def test_create_at_root(self, ws_two_files):
        ws, f1, _ = ws_two_files
        before_count = len(list(ws.all_nodes()))
        new = ws.create_node(f1, "New task", state="TODO")
        assert new.heading == "New task"
        assert new.todo == "TODO"
        assert f1 in ws.dirty_files()
        after_count = len(list(ws.all_nodes()))
        assert after_count == before_count + 1

    def test_create_with_properties(self, ws_two_files):
        ws, f1, _ = ws_two_files
        new = ws.create_node(f1, "Task with props", state="TODO", ID="new-id-001")
        assert new.properties.get("ID") == "new-id-001"

    def test_create_under_parent(self, ws_multi):
        ws, dst = ws_multi
        parent = ws.find_by_id("mf-001")
        assert parent is not None
        parent_level = parent.level
        parent_path = parent.path
        new = ws.create_node(
            parent_path, "Subtask", state="TODO", parent=parent
        )
        # parent NodeView is stale after reload, use saved level
        assert new.level == parent_level + 1

    def test_create_under_parent_lands_under_correct_parent(self, tmp_path):
        """Bug test: create_node with parent= appends to EOF, so the new node
        ends up under the LAST level-1 heading instead of the specified parent."""
        org_content = (
            "* Section A\n"
            "** A child 1\n"
            "** A child 2\n"
            "* Section B\n"
            "** B child 1\n"
        )
        f = tmp_path / "two_sections.org"
        f.write_text(org_content)
        ws = OrgWorkspace(roots=[f])

        # Find Section A as parent
        section_a = None
        for n in ws.all_nodes():
            if n.heading == "Section A":
                section_a = n
                break
        assert section_a is not None, "Section A not found"

        # Create a new child under Section A
        new_node = ws.create_node(f, "New A child", state="TODO", parent=section_a)

        # The new node should be under Section A, not Section B
        assert new_node.parent is not None, "New node has no parent"
        assert new_node.parent.heading == "Section A", (
            f"Expected parent 'Section A', got '{new_node.parent.heading}'. "
            f"The node was appended to EOF and landed under the last matching-level heading."
        )

    def test_create_with_tags(self, ws_two_files):
        ws, f1, _ = ws_two_files
        new = ws.create_node(f1, "Tagged task", state="TODO", tags=["urgent", "AI"])
        assert "urgent" in new.tags

    def test_create_in_unloaded_file_raises(self, ws_two_files):
        ws, _, _ = ws_two_files
        with pytest.raises(ValueError, match="not loaded"):
            ws.create_node(Path("/fake/path.org"), "Task")

    def test_auto_id_assigned(self, ws_two_files):
        """create_node auto-assigns a content-addressed :ID:."""
        import re

        ws, f1, _ = ws_two_files
        new = ws.create_node(f1, "Auto ID task", state="TODO")
        node_id = new.id()
        assert node_id is not None
        assert re.match(r"^org-\d{8}-\d{6}-[0-9a-f]{8}$", node_id)

    def test_auto_created_timestamp(self, ws_two_files):
        """create_node auto-assigns :CREATED: timestamp."""
        ws, f1, _ = ws_two_files
        new = ws.create_node(f1, "Timestamped task", state="TODO")
        created = new.properties.get("CREATED")
        assert created is not None
        assert created.startswith("[20")
        assert created.endswith("]")

    def test_explicit_id_preserved(self, ws_two_files):
        """Explicit ID= kwarg is not overwritten by auto-ID."""
        ws, f1, _ = ws_two_files
        new = ws.create_node(f1, "Custom ID", state="TODO", ID="my-custom-id")
        assert new.id() == "my-custom-id"

    def test_dedup_returns_existing(self, ws_two_files):
        """dedup=True returns existing node if heading hash matches."""
        ws, f1, _ = ws_two_files
        first = ws.create_node(f1, "Unique task", state="TODO")
        first_id = first.id()
        second = ws.create_node(f1, "Unique task", state="TODO", dedup=True)
        assert second.id() == first_id

    def test_dedup_false_creates_duplicate(self, ws_two_files):
        """dedup=False (default) creates a new node even with same heading."""
        ws, f1, _ = ws_two_files
        first = ws.create_node(f1, "Repeated task", state="TODO")
        first_id = first.id()  # capture before second create stales it
        second = ws.create_node(f1, "Repeated task", state="TODO")
        assert first_id != second.id()

    def test_id_contains_heading_hash(self, ws_two_files):
        """The auto-ID suffix matches heading_hash()."""
        from org_workspace.identifiers import heading_hash

        ws, f1, _ = ws_two_files
        new = ws.create_node(f1, "Hash check task", state="TODO")
        expected_hash = heading_hash("Hash check task")
        assert new.id().endswith(f"-{expected_hash}")


class TestRemoveNode:
    def test_remove_node(self, ws_two_files):
        ws, f1, _ = ws_two_files
        node = ws.find_by_id("550e8400-e29b-41d4-a716-446655440001")
        before_count = len(list(ws.all_nodes()))
        ws.remove_node(node)
        after_count = len(list(ws.all_nodes()))
        assert after_count == before_count - 1
        assert f1 in ws.dirty_files()

    def test_remove_updates_id_index(self, ws_two_files):
        ws, _, _ = ws_two_files
        ws.remove_node(ws.find_by_id("550e8400-e29b-41d4-a716-446655440001"))
        assert ws.find_by_id("550e8400-e29b-41d4-a716-446655440001") is None


class TestRefile:
    def test_refile_between_files(self, ws_two_files):
        ws, f1, f2 = ws_two_files
        node = ws.find_by_id("550e8400-e29b-41d4-a716-446655440001")
        assert node.path == f1
        new_view = ws.refile(node, f2)
        assert new_view.path == f2
        assert new_view.heading == "Simple task"
        # Old location should be gone
        assert ws.find_by_id("550e8400-e29b-41d4-a716-446655440001").path == f2
        # Both files dirty
        assert f1 in ws.dirty_files()
        assert f2 in ws.dirty_files()

    def test_refile_to_unloaded_raises(self, ws_two_files):
        ws, f1, _ = ws_two_files
        node = ws.find_by_id("550e8400-e29b-41d4-a716-446655440001")
        with pytest.raises(ValueError, match="not loaded"):
            ws.refile(node, Path("/fake.org"))


class TestSave:
    def test_save_writes_to_disk(self, ws_two_files):
        ws, f1, _ = ws_two_files
        node = ws.find_by_id("550e8400-e29b-41d4-a716-446655440001")
        ws.transition(node, "NEXT")
        ws.save(f1)
        # Read back and verify
        content = f1.read_text()
        assert "NEXT" in content
        assert f1 not in ws.dirty_files()

    def test_save_all(self, ws_two_files):
        ws, f1, f2 = ws_two_files
        node1 = ws.find_by_id("550e8400-e29b-41d4-a716-446655440001")
        ws.set_property(node1, "TOUCHED", "yes")
        node2 = ws.find_by_id("ns-001")
        ws.set_property(node2, "TOUCHED", "yes")
        assert len(ws.dirty_files()) == 2
        ws.save_all()
        assert len(ws.dirty_files()) == 0

    def test_dirty_tracking(self, ws_two_files):
        ws, f1, _ = ws_two_files
        assert len(ws.dirty_files()) == 0
        node = ws.find_by_id("550e8400-e29b-41d4-a716-446655440001")
        ws.set_heading(node, "Changed")
        assert f1 in ws.dirty_files()
        ws.save(f1)
        assert f1 not in ws.dirty_files()


class TestRoundTrip:
    """INV-1: Unmodified files round-trip perfectly."""

    def test_unmodified_round_trip(self, ws_two_files):
        ws, f1, _ = ws_two_files
        original = f1.read_text()
        result = dumps(ws.files()[f1])
        assert result == original

    def test_save_round_trip(self, ws_two_files):
        """After save, file content matches dumps()."""
        ws, f1, _ = ws_two_files
        node = ws.find_by_id("550e8400-e29b-41d4-a716-446655440001")
        ws.set_heading(node, "Modified task")
        ws.save(f1)
        content = f1.read_text()
        assert "Modified task" in content
        # Reload and verify
        root = load(str(f1))
        assert root.children[0].heading == "Modified task"


class TestReloadStaleness:
    def test_reload_increments_generation(self, ws_two_files):
        ws, f1, _ = ws_two_files
        ws.find_by_id("550e8400-e29b-41d4-a716-446655440001")
        old_gen = ws._generations[f1]
        ws.reload(f1)
        assert ws._generations[f1] == old_gen + 1

    def test_stale_nodeview_after_reload(self, ws_two_files):
        ws, f1, _ = ws_two_files
        node = ws.find_by_id("550e8400-e29b-41d4-a716-446655440001")
        _ = node.heading  # works fine
        ws.reload(f1)
        with pytest.raises(StaleNodeError):
            _ = node.heading


class TestDuplicateIdDedup:
    """Workspace deduplicates IDs on load instead of crashing."""

    def test_dedup_within_file(self, tmp_path):
        f = tmp_path / "dupes.org"
        f.write_text(
            "* TODO Task A\n"
            "  :PROPERTIES:\n"
            "  :ID: same-id\n"
            "  :END:\n"
            "* TODO Task B\n"
            "  :PROPERTIES:\n"
            "  :ID: same-id\n"
            "  :END:\n"
        )
        ws = OrgWorkspace(roots=[f])  # should not raise
        # First node keeps original ID
        node_a = ws.find_by_id("same-id")
        assert node_a is not None
        assert node_a.heading == "Task A"
        # Both nodes should be findable (second got a new ID)
        nodes = list(ws.all_nodes())
        assert len(nodes) == 2
        ids = {n.id() for n in nodes}
        assert "same-id" in ids
        assert len(ids) == 2  # two distinct IDs

    def test_dedup_across_files(self, tmp_path):
        f1 = tmp_path / "a.org"
        f2 = tmp_path / "b.org"
        f1.write_text("* TODO Task A\n  :PROPERTIES:\n  :ID: shared-id\n  :END:\n")
        f2.write_text("* TODO Task B\n  :PROPERTIES:\n  :ID: shared-id\n  :END:\n")
        ws = OrgWorkspace(roots=[f1, f2])  # should not raise
        # First loaded file keeps original
        node_a = ws.find_by_id("shared-id")
        assert node_a is not None
        assert node_a.heading == "Task A"
        # Second file's node got regenerated ID
        nodes = list(ws.all_nodes())
        ids = {n.id() for n in nodes}
        assert len(ids) == 2

    def test_dedup_persisted_to_disk(self, tmp_path):
        f = tmp_path / "dupes.org"
        f.write_text(
            "* TODO Task A\n  :PROPERTIES:\n  :ID: dup\n  :END:\n"
            "* TODO Task B\n  :PROPERTIES:\n  :ID: dup\n  :END:\n"
        )
        OrgWorkspace(roots=[f])
        # File should have been rewritten with unique IDs
        content = f.read_text()
        assert content.count(":ID: dup") == 1  # only first kept original
