"""Tests for plan.py — DAG execution and dependency resolution."""

import shutil

import pytest

from org_workspace._types import parse_depends_on
from org_workspace.plan import Plan
from org_workspace.workspace import OrgWorkspace


class TestParseDependsOn:
    """Dependency parsing (also tested in test_types.py, extended here)."""

    def test_blocks_produces_forward_edge(self):
        deps = parse_depends_on('BLOCKS dep-002 "Implement endpoints"')
        assert deps[0].dep_type == "BLOCKS"
        assert deps[0].target_id == "dep-002"

    def test_after_produces_backward_edge(self):
        deps = parse_depends_on('AFTER dep-001 "Design API schema"')
        assert deps[0].dep_type == "AFTER"
        assert deps[0].target_id == "dep-001"


@pytest.fixture
def plan_ws(tmp_path, dependencies_org):
    """Workspace with dependency fixture."""
    f = tmp_path / "deps.org"
    shutil.copy(dependencies_org, f)
    ws = OrgWorkspace(roots=[f])
    return ws, f


@pytest.fixture
def plan(plan_ws):
    ws, f = plan_ws
    root = ws.find_by_id("dep-001")
    # Find the parent (Project Alpha)
    parent = root.parent
    assert parent is not None
    return Plan(parent, ws)


class TestPlan:
    def test_steps(self, plan):
        steps = plan.steps()
        assert len(steps) == 5
        ids = {s.id() for s in steps}
        assert "dep-001" in ids
        assert "dep-005" in ids

    def test_execution_order(self, plan):
        order = plan.execution_order()
        ids = [s.id() for s in order]
        # dep-001 must come before dep-002 and dep-003
        assert ids.index("dep-001") < ids.index("dep-002")
        assert ids.index("dep-001") < ids.index("dep-003")
        # dep-002 and dep-003 must come before dep-004
        assert ids.index("dep-002") < ids.index("dep-004")
        assert ids.index("dep-003") < ids.index("dep-004")
        # dep-004 must come before dep-005
        assert ids.index("dep-004") < ids.index("dep-005")

    def test_ready_tasks_initial(self, plan):
        """Initially, only dep-001 (no deps) should be ready."""
        ready = plan.ready_tasks()
        ready_ids = {s.id() for s in ready}
        assert "dep-001" in ready_ids
        # dep-002 depends on dep-001, so not ready
        assert "dep-002" not in ready_ids

    def test_blocked_tasks(self, plan):
        blocked = plan.blocked_tasks()
        blocked_ids = {s.id() for s, _ in blocked}
        assert "dep-002" in blocked_ids
        assert "dep-005" in blocked_ids

    def test_progress_initial(self, plan):
        prog = plan.progress()
        assert prog.total == 5
        assert prog.done == 0
        assert prog.percent == 0.0

    def test_ready_after_completing_dep(self, plan_ws):
        ws, f = plan_ws
        # Complete dep-001
        node = ws.find_by_id("dep-001")
        ws.transition(node, "DONE")

        root_parent = ws.find_by_id("dep-002").parent
        p = Plan(root_parent, ws)
        ready = p.ready_tasks()
        ready_ids = {s.id() for s in ready}
        # dep-002 and dep-003 should now be ready
        assert "dep-002" in ready_ids
        assert "dep-003" in ready_ids
        # dep-004 still blocked (needs both dep-002 and dep-003)
        assert "dep-004" not in ready_ids

    def test_parallel_eligible_steps(self, plan_ws):
        """dep-002 and dep-003 have no deps between them — both should be ready."""
        ws, f = plan_ws
        ws.transition(ws.find_by_id("dep-001"), "DONE")
        root_parent = ws.find_by_id("dep-002").parent
        p = Plan(root_parent, ws)
        ready = p.ready_tasks()
        ready_ids = {s.id() for s in ready}
        assert "dep-002" in ready_ids
        assert "dep-003" in ready_ids


class TestCycleDetection:
    def test_no_cycles(self, plan):
        cycles = plan.cycle_check()
        assert cycles == []

    def test_cycle_detected(self, tmp_path):
        """A BLOCKS B, B BLOCKS A should detect a cycle."""
        content = (
            "* Plan\n"
            "** TODO Step A\n"
            "   :PROPERTIES:\n"
            "   :ID: cyc-a\n"
            "   :DEPENDS_ON: BLOCKS cyc-b\n"
            "   :END:\n"
            "** TODO Step B\n"
            "   :PROPERTIES:\n"
            "   :ID: cyc-b\n"
            "   :DEPENDS_ON: BLOCKS cyc-a\n"
            "   :END:\n"
        )
        f = tmp_path / "cycle.org"
        f.write_text(content)
        ws = OrgWorkspace(roots=[f])
        root = list(ws.all_nodes())[0]  # Plan heading
        p = Plan(root, ws)
        cycles = p.cycle_check()
        assert len(cycles) > 0

    def test_execution_order_raises_on_cycle(self, tmp_path):
        content = (
            "* Plan\n"
            "** TODO Step A\n"
            "   :PROPERTIES:\n"
            "   :ID: cyc-a\n"
            "   :DEPENDS_ON: BLOCKS cyc-b\n"
            "   :END:\n"
            "** TODO Step B\n"
            "   :PROPERTIES:\n"
            "   :ID: cyc-b\n"
            "   :DEPENDS_ON: BLOCKS cyc-a\n"
            "   :END:\n"
        )
        f = tmp_path / "cycle.org"
        f.write_text(content)
        ws = OrgWorkspace(roots=[f])
        root = list(ws.all_nodes())[0]
        p = Plan(root, ws)
        with pytest.raises(ValueError, match="cycle"):
            p.execution_order()
