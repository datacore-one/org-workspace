"""Tests for workspace.py — OrgWorkspace multi-file container."""

import shutil
from datetime import date, datetime
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

    def test_set_scheduled(self, ws_two_files):
        ws, f1, _ = ws_two_files
        node = ws.find_by_id("550e8400-e29b-41d4-a716-446655440001")
        assert node.scheduled is None or not node.scheduled.start
        ws.set_scheduled(node, date(2026, 5, 1))
        assert f1 in ws.dirty_files()
        ws.save()
        # Reload and verify
        ws.reload(f1)
        node = ws.find_by_id("550e8400-e29b-41d4-a716-446655440001")
        assert node.scheduled is not None
        assert node.scheduled.start.year == 2026
        assert node.scheduled.start.month == 5
        assert node.scheduled.start.day == 1

    def test_set_deadline(self, ws_two_files):
        ws, f1, _ = ws_two_files
        node = ws.find_by_id("550e8400-e29b-41d4-a716-446655440001")
        ws.set_deadline(node, date(2026, 6, 15))
        ws.save()
        ws.reload(f1)
        node = ws.find_by_id("550e8400-e29b-41d4-a716-446655440001")
        assert node.deadline is not None
        assert node.deadline.start.day == 15

    def test_clear_scheduled(self, ws_two_files):
        ws, f1, _ = ws_two_files
        node = ws.find_by_id("550e8400-e29b-41d4-a716-446655440001")
        ws.set_scheduled(node, date(2026, 5, 1))
        ws.save()
        ws.reload(f1)
        node = ws.find_by_id("550e8400-e29b-41d4-a716-446655440001")
        ws.set_scheduled(node, None)
        ws.save()
        ws.reload(f1)
        node = ws.find_by_id("550e8400-e29b-41d4-a716-446655440001")
        assert not node.scheduled or not node.scheduled.start

    def test_set_closed_manual(self, ws_two_files):
        ws, f1, _ = ws_two_files
        node = ws.find_by_id("550e8400-e29b-41d4-a716-446655440001")
        now = datetime.now()
        ws.set_closed(node, now)
        assert f1 in ws.dirty_files()

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

    def test_transition_recurring_advances_scheduled(self, tmp_path):
        """Recurring tasks (+Nd/+Nw/+Nm/+Ny repeaters) auto-advance on DONE.

        Standard org-mode behaviour: when a task with a +Nw repeater is
        flipped to DONE, SCHEDULED advances by the repeater interval and
        state reverts to TODO so the task stays alive for its next cycle.

        Bug surfaced 2026-05-21: prior to fix, transition() set state=DONE
        and left SCHEDULED unchanged — recurring tasks effectively died
        on first completion.
        """
        from org_workspace import OrgWorkspace
        text = (
            "#+SEQ_TODO: TODO(t) NEXT(n!) | DONE(d!)\n"
            "* TODO Weekly review\n"
            "SCHEDULED: <2026-05-23 Sat +1w>\n"
            ":PROPERTIES:\n"
            ":ID: org-recur-weekly\n"
            ":END:\n"
            "\n"
            "* TODO Monthly report\n"
            "SCHEDULED: <2026-05-20 Wed +1m>\n"
            ":PROPERTIES:\n"
            ":ID: org-recur-monthly\n"
            ":END:\n"
            "\n"
            "* TODO Habit thing\n"
            "SCHEDULED: <2026-05-10 Sun .+1w>\n"
            ":PROPERTIES:\n"
            ":ID: org-recur-habit\n"
            ":END:\n"
            "\n"
            "* TODO Non-recurring\n"
            "SCHEDULED: <2026-05-25 Mon>\n"
            ":PROPERTIES:\n"
            ":ID: org-once\n"
            ":END:\n"
        )
        f = tmp_path / "recur.org"
        f.write_text(text)
        ws = OrgWorkspace()
        ws.load(f)

        # +1w: advance from original by 1 week
        node = ws.find_by_id("org-recur-weekly")
        ws.transition(node, "DONE")
        node = ws.find_by_id("org-recur-weekly")
        assert node.todo == "TODO", "Recurring task must revert state, not stay DONE"
        assert "2026-05-30" in str(node.scheduled), f"+1w from 2026-05-23 should be 2026-05-30, got {node.scheduled}"
        assert "+1w" in str(node.scheduled), "Repeater must be preserved on advanced date"
        assert node.get_property("LAST_REPEAT"), "LAST_REPEAT must be stamped"

        # +1m: month math
        node = ws.find_by_id("org-recur-monthly")
        ws.transition(node, "DONE")
        node = ws.find_by_id("org-recur-monthly")
        assert "2026-06-20" in str(node.scheduled), f"+1m from 2026-05-20 should be 2026-06-20, got {node.scheduled}"
        assert "+1m" in str(node.scheduled)

        # .+1w (habit): shift to today + 1w, ignoring old date
        import datetime as _dt
        node = ws.find_by_id("org-recur-habit")
        ws.transition(node, "DONE")
        node = ws.find_by_id("org-recur-habit")
        expected = (_dt.date.today() + _dt.timedelta(weeks=1)).isoformat()
        assert expected in str(node.scheduled), f".+1w should restart from today, got {node.scheduled}"
        assert ".+1w" in str(node.scheduled), "Habit-style repeater must be preserved"

        # Non-recurring: normal terminal behaviour
        node = ws.find_by_id("org-once")
        ws.transition(node, "DONE")
        node = ws.find_by_id("org-once")
        assert node.todo == "DONE", "Non-recurring should stay DONE"
        assert node.closed is not None, "Non-recurring DONE should have CLOSED stamp"


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

    def test_set_property_with_interleaved_logbook_drawer(self, tmp_path):
        """Regression: malformed source with LOGBOOK enclosing PROPERTIES
        used to crash the properties setter with
        'PropertyDrawerEndLine not in list'.

        Real-world incident 2026-05-16: nodes in next_actions.org had
        LOGBOOK lines before PROPERTIES; the parser bound drawer.end_line
        to a synthetic PropertyDrawerEndLine that wasn't in _line_items
        (the actual :END: line had been parsed as TextLine). The setter
        then failed at _line_items.index(drawer.end_line). See
        org-20260517-orgworkspace-truncation-bug.
        """
        from org_workspace import OrgWorkspace
        text = (
            "* PROJECT Dubai Gold Pilot\n"
            ":LOGBOOK:\n"
            '- State "PROJECT"    from              [2025-11-26 Wed 15:08]\n'
            ":PROPERTIES:\n"
            ":NIGHTSHIFT_STATUS: approved\n"
            ":END:\n"
            ":END:\n"
            "\n"
            "    body text after the drawers\n"
        )
        f = tmp_path / "interleaved.org"
        f.write_text(text)
        ws = OrgWorkspace()
        ws.load(f)
        node = next(ws.all_nodes())
        # Must not raise. Should add the ID into the existing drawer.
        ws.set_property(node, "ID", "org-test-recovery")
        assert node.properties.get("ID") == "org-test-recovery"
        ws.save(f)
        result = f.read_text()
        # Original body must survive (no truncation)
        assert "body text after the drawers" in result
        # New ID must be present
        assert "org-test-recovery" in result

    def test_set_property_with_logbook_nested_inside_properties(self, tmp_path):
        """Regression: malformed task with :LOGBOOK: drawer nested INSIDE
        the :PROPERTIES: drawer.

        Real-world incident 2026-05-18: the live next_actions.org had a
        DONE task whose :PROPERTIES: drawer contained both regular
        properties and an interleaved :LOGBOOK: drawer with its own
        :ID:, followed by a second :ID: outside the LOGBOOK but inside
        the outer :END:. Setting a property on a neighbouring task
        caused the save pipeline to truncate ~2000 lines from the file.

        The parser treats `LOGBOOK` as a property key (with `:CLOCK:`
        as its value) on the outer drawer, which leaves the inner
        :END: lines in an ambiguous state during render.

        The test ensures:
          1. Loading the malformed task does not raise.
          2. Setting a property on a DIFFERENT task does not lose lines.
          3. The malformed task itself is preserved verbatim.
        """
        from org_workspace import OrgWorkspace
        text = (
            "*** DONE Malformed task\n"
            "SCHEDULED: <2026-05-14 Thu> CLOSED: [2026-05-14 Thu 11:48]\n"
            ":PROPERTIES:\n"
            ":CREATED: [2026-05-14 Thu 09:11]\n"
            ":EFFORT: 2:30\n"
            ":CONTEXT: Long context line\n"
            ":LOGBOOK:\n"
            "CLOCK: [2026-05-14 Thu 09:11]--[2026-05-14 Thu 11:48] =>  2:37\n"
            ":ID: org-inner-logbook-id\n"
            ":END:\n"
            ":ID: org-outer-real-id\n"
            ":END:\n"
            "\n"
            "*** TODO Next task — must survive intact\n"
            "SCHEDULED: <2026-05-20 Wed>\n"
            ":PROPERTIES:\n"
            ":ID: org-after-task\n"
            ":END:\n"
            "Body line 1\n"
            "Body line 2\n"
            "Body line 3\n"
        )
        f = tmp_path / "nested_logbook.org"
        f.write_text(text)

        before_lines = text.count("\n")

        ws = OrgWorkspace()
        ws.load(f)

        # Touch a property on the SECOND task — the one after the
        # malformed structure. The 2026-05-18 incident's exact pattern.
        after = ws.find_by_id("org-after-task")
        assert after is not None, "Parser must still find the next task"
        ws.set_property(after, "TEST_PROP", "test")
        ws.save(f)

        result = f.read_text()
        after_lines = result.count("\n")

        # Critical: must not silently lose >10% of the file.
        assert after_lines >= before_lines - 1, (
            f"File shrunk catastrophically: {before_lines} → {after_lines} lines"
        )
        # The next task's body must survive.
        assert "Body line 1" in result
        assert "Body line 2" in result
        assert "Body line 3" in result
        # The malformed task's content must still be there.
        assert "CLOCK: [2026-05-14 Thu 09:11]" in result
        assert "Long context line" in result
        # The new property landed somewhere.
        assert "TEST_PROP" in result

    def test_parser_normalizes_logbook_nested_in_properties(self, tmp_path):
        """When :LOGBOOK: appears inside :PROPERTIES:, the parser must
        treat it as the implicit close of the PROPERTIES drawer (LOGBOOK
        is a sibling drawer in org-mode, never nested in PROPERTIES).

        Verifies the 2026-05-18 fix at parse time, not just at save time:
        properties before LOGBOOK are correctly indexed, LOGBOOK is
        parsed as a separate drawer, and the file round-trips without
        corruption.
        """
        from org_workspace._vendor.orgparse import loads, dumps

        text = (
            "*** DONE Malformed task\n"
            ":PROPERTIES:\n"
            ":CREATED: [2026-05-14 Thu]\n"
            ":EFFORT: 2:30\n"
            ":LOGBOOK:\n"
            "CLOCK: [2026-05-14 Thu 09:11]--[2026-05-14 Thu 11:48] =>  2:37\n"
            ":END:\n"
            "Body line\n"
        )
        root = loads(text)
        task = root.children[0]

        # PROPERTIES must contain only CREATED + EFFORT, NOT LOGBOOK.
        # (Pre-fix, `:LOGBOOK:` was consumed as a no-value property.)
        assert "CREATED" in task.properties
        assert "EFFORT" in task.properties
        assert "LOGBOOK" not in task.properties, (
            "LOGBOOK was incorrectly read as a property"
        )

        # The CLOCK entry must be recognized as a LOGBOOK clock.
        assert len(task.clock) == 1, "CLOCK line must be parsed inside LOGBOOK"

        # Round-trip via dumps must not lose the body line.
        result = dumps(root)
        assert "Body line" in result, "Body content lost in round-trip"

    def test_save_aborts_on_catastrophic_shrink(self, tmp_path, monkeypatch):
        """Defense-in-depth: if dumps() ever returns a result that would
        shrink the file by more than the safety threshold, save() must
        raise instead of silently writing the truncated content.

        This is the safety net for any future serializer bug — without
        it, parser regressions cause silent data loss like the
        2026-05-16 and 2026-05-18 incidents.
        """
        from org_workspace import OrgWorkspace
        from org_workspace.workspace import CatastrophicShrinkError

        text = "\n".join(f"* TODO Task {i}\n  Body for task {i}\n" for i in range(50))
        f = tmp_path / "many.org"
        f.write_text(text)

        ws = OrgWorkspace()
        ws.load(f)
        node = next(iter(ws.all_nodes()))
        ws.set_property(node, "FOO", "bar")  # mark dirty

        # Sabotage dumps to return a truncated string.
        import org_workspace.workspace as wsmod
        monkeypatch.setattr(wsmod, "dumps", lambda root: "* Tiny\n")

        with pytest.raises(CatastrophicShrinkError):
            ws.save(f)

        # And on disk, the original content must still be intact.
        assert "Task 49" in f.read_text(), "Original file must be preserved on guard trip"


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
