"""Tests for archive.py — task and bulk archive operations."""

from datetime import datetime

import pytest

from org_workspace.archive import (
    archive_done,
    archive_node,
    archive_plan,
    default_archive_path,
)
from org_workspace.plan import Plan
from org_workspace.workspace import OrgWorkspace


class TestDefaultArchivePath:
    def test_standard_naming(self, tmp_path):
        p = tmp_path / "next_actions.org"
        assert default_archive_path(p).name == "next_actions_archive.org"

    def test_simple_name(self, tmp_path):
        p = tmp_path / "tasks.org"
        assert default_archive_path(p).name == "tasks_archive.org"


@pytest.fixture
def archive_ws(tmp_path):
    """Workspace with tasks at various levels and states."""
    content = (
        "* Personal\n"
        "** Health\n"
        "*** DONE Buy vitamins\n"
        "   CLOSED: [2025-01-01 Wed 10:00]\n"
        "   :PROPERTIES:\n"
        "   :ID: arc-001\n"
        "   :END:\n"
        "*** TODO Schedule checkup\n"
        "   :PROPERTIES:\n"
        "   :ID: arc-002\n"
        "   :END:\n"
        "** Work\n"
        "*** DONE Deploy v1.0\n"
        "   CLOSED: [2025-01-15 Wed 14:00]\n"
        "   :PROPERTIES:\n"
        "   :ID: arc-003\n"
        "   :END:\n"
        "   Deploy notes and details.\n"
    )
    f = tmp_path / "next_actions.org"
    f.write_text(content)
    ws = OrgWorkspace(roots=[f])
    return ws, f


class TestArchiveNode:
    def test_archives_to_sibling_file(self, archive_ws, tmp_path):
        ws, f = archive_ws
        node = ws.find_by_id("arc-001")
        identifier = archive_node(ws, node)
        assert identifier == "arc-001"

        # Node should now be in archive file
        archive_path = default_archive_path(f)
        assert archive_path.resolve() in ws.files()
        archived = ws.find_by_id("arc-001")
        assert archived is not None
        assert archived.path == archive_path.resolve()

    def test_sets_archive_properties(self, archive_ws, tmp_path):
        ws, f = archive_ws
        node = ws.find_by_id("arc-001")
        archive_node(ws, node, reason="test archive")
        archived = ws.find_by_id("arc-001")
        props = archived.properties
        assert "ARCHIVE_TIME" in props
        assert props["ARCHIVE_REASON"] == "test archive"

    def test_refuses_structural_heading(self, archive_ws):
        ws, f = archive_ws
        # Find a level-1 heading
        for node in ws.all_nodes():
            if node.level == 1:
                with pytest.raises(ValueError, match="structural"):
                    archive_node(ws, node)
                break

    def test_refuses_level2_heading(self, archive_ws):
        ws, f = archive_ws
        for node in ws.all_nodes():
            if node.level == 2:
                with pytest.raises(ValueError, match="structural"):
                    archive_node(ws, node)
                break

    def test_preserves_body(self, archive_ws, tmp_path):
        ws, f = archive_ws
        node = ws.find_by_id("arc-003")
        archive_node(ws, node)
        archived = ws.find_by_id("arc-003")
        assert "Deploy notes" in archived.body


class TestArchivePlan:
    def test_archives_entire_plan(self, tmp_path):
        content = (
            "* Plan Alpha\n"
            "  :PROPERTIES:\n"
            "  :ID: plan-root\n"
            "  :END:\n"
            "** DONE Step 1\n"
            "   :PROPERTIES:\n"
            "   :ID: plan-s1\n"
            "   :END:\n"
            "** DONE Step 2\n"
            "   :PROPERTIES:\n"
            "   :ID: plan-s2\n"
            "   :END:\n"
        )
        f = tmp_path / "plans.org"
        f.write_text(content)
        ws = OrgWorkspace(roots=[f])
        root = ws.find_by_id("plan-root")
        plan = Plan(root, ws)

        identifiers = archive_plan(ws, plan)
        assert "plan-root" in identifiers


class TestArchiveHierarchyPreservation:
    """DIP-0009: Archive mirrors heading hierarchy — same tier/focus-area structure."""

    def test_archive_preserves_parent_heading_hierarchy(self, tmp_path):
        """Archived node should land under matching parent headings in archive file.

        Source:  * Personal > ** Health > *** DONE Buy vitamins
        Expected archive: * Personal > ** Health > *** DONE Buy vitamins
        Actual (gap): *** DONE Buy vitamins dumped at file root
        """
        content = (
            "* Personal\n"
            "** Health\n"
            "*** DONE Buy vitamins\n"
            "   CLOSED: [2025-01-01 Wed 10:00]\n"
            "   :PROPERTIES:\n"
            "   :ID: hier-001\n"
            "   :END:\n"
        )
        f = tmp_path / "next_actions.org"
        f.write_text(content)
        ws = OrgWorkspace(roots=[f])

        node = ws.find_by_id("hier-001")
        archive_node(ws, node)

        archive_path = default_archive_path(f)
        archive_text = archive_path.read_text()

        # Print actual archive content for diagnosis
        print("=== ARCHIVE FILE CONTENT ===")
        print(archive_text)
        print("=== END ARCHIVE ===")

        # DIP-0009 says archive should mirror heading hierarchy.
        # The archived node should be nested under * Personal > ** Health,
        # not dumped at the root level.
        assert "* Personal" in archive_text, (
            "Archive should contain '* Personal' parent heading"
        )
        assert "** Health" in archive_text, (
            "Archive should contain '** Health' parent heading"
        )

        # Verify structural nesting: "* Personal" appears before "** Health"
        # which appears before "*** DONE Buy vitamins"
        personal_pos = archive_text.index("* Personal")
        health_pos = archive_text.index("** Health")
        task_pos = archive_text.index("*** DONE Buy vitamins")
        assert personal_pos < health_pos < task_pos, (
            "Hierarchy should be preserved: Personal > Health > task"
        )


class TestArchiveDone:
    def test_archives_old_done_tasks(self, archive_ws):
        ws, f = archive_ws
        # Both arc-001 and arc-003 are DONE with old CLOSED dates
        archived = archive_done(ws, older_than_days=30)
        assert len(archived) >= 1
        # Check at least one was archived
        assert "arc-001" in archived or "arc-003" in archived

    def test_skips_structural_headings(self, archive_ws):
        ws, f = archive_ws
        archived = archive_done(ws, older_than_days=30, min_level=3)
        # Should not include level-1 or level-2 headings
        for ident in archived:
            node = ws.find_by_id(ident)
            if node:
                assert node.level >= 3

    def test_skips_recent(self, tmp_path):
        """Tasks closed recently should not be archived."""
        today = datetime.now()
        content = (
            "* Area\n"
            "** Section\n"
            f"*** DONE Recent task\n"
            f"   CLOSED: [{today.strftime('%Y-%m-%d %a %H:%M')}]\n"
            "   :PROPERTIES:\n"
            "   :ID: recent-001\n"
            "   :END:\n"
        )
        f = tmp_path / "recent.org"
        f.write_text(content)
        ws = OrgWorkspace(roots=[f])
        archived = archive_done(ws, older_than_days=30)
        assert "recent-001" not in archived
