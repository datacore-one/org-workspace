"""Tests for context.py — AI execution context assembly."""

import shutil

import pytest

from org_workspace.context import build_execution_context, get_context, get_refs
from org_workspace.workspace import OrgWorkspace


@pytest.fixture
def context_ws(tmp_path, rich_task_org):
    f = tmp_path / "rich.org"
    shutil.copy(rich_task_org, f)
    return OrgWorkspace(roots=[f])


class TestGetContext:
    def test_extracts_multiline_context(self, context_ws):
        node = context_ws.find_by_id("550e8400-e29b-41d4-a716-446655440010")
        ctx = get_context(node)
        assert "context" in ctx
        assert "authentication system" in ctx["context"]

    def test_extracts_role(self, context_ws):
        node = context_ws.find_by_id("550e8400-e29b-41d4-a716-446655440010")
        ctx = get_context(node)
        assert ctx["role"] == "Senior Backend Engineer"

    def test_extracts_acceptance_criteria(self, context_ws):
        node = context_ws.find_by_id("550e8400-e29b-41d4-a716-446655440010")
        ctx = get_context(node)
        assert "acceptance_criteria" in ctx
        assert "JWT" in ctx["acceptance_criteria"]

    def test_empty_node_returns_empty_dict(self, tmp_path):
        content = "* TODO Plain task\n  :PROPERTIES:\n  :ID: plain-001\n  :END:\n"
        f = tmp_path / "plain.org"
        f.write_text(content)
        ws = OrgWorkspace(roots=[f])
        node = ws.find_by_id("plain-001")
        ctx = get_context(node)
        assert ctx == {}


class TestGetRefs:
    def test_parses_key_files(self, tmp_path):
        content = (
            "* TODO Task with refs\n"
            "  :PROPERTIES:\n"
            "  :ID: ref-001\n"
            "  :KEY_FILES: |\n"
            "  :   src/auth.py\n"
            "  :   src/models.py\n"
            "  :END:\n"
        )
        f = tmp_path / "refs.org"
        f.write_text(content)
        ws = OrgWorkspace(roots=[f])
        node = ws.find_by_id("ref-001")
        refs = get_refs(node)
        assert "src/auth.py" in refs
        assert "src/models.py" in refs

    def test_single_line_refs(self, tmp_path):
        content = (
            "* TODO Task\n"
            "  :PROPERTIES:\n"
            "  :ID: ref-002\n"
            "  :REFS: src/main.py\n"
            "  :END:\n"
        )
        f = tmp_path / "single.org"
        f.write_text(content)
        ws = OrgWorkspace(roots=[f])
        node = ws.find_by_id("ref-002")
        refs = get_refs(node)
        assert refs == ["src/main.py"]

    def test_no_refs_returns_empty(self, tmp_path):
        content = "* TODO No refs\n  :PROPERTIES:\n  :ID: nr-001\n  :END:\n"
        f = tmp_path / "norefs.org"
        f.write_text(content)
        ws = OrgWorkspace(roots=[f])
        node = ws.find_by_id("nr-001")
        assert get_refs(node) == []


class TestBuildExecutionContext:
    def test_full_context(self, context_ws):
        node = context_ws.find_by_id("550e8400-e29b-41d4-a716-446655440010")
        ctx = build_execution_context(
            node,
            engrams=["User prefers TypeScript", "Always use async/await"],
            extra_context={"session_id": "test-123"},
        )
        assert "prompt" in ctx
        assert "context" in ctx
        assert "role" in ctx
        assert ctx["engrams"] == ["User prefers TypeScript", "Always use async/await"]
        assert ctx["session_id"] == "test-123"

    def test_without_engrams(self, context_ws):
        node = context_ws.find_by_id("550e8400-e29b-41d4-a716-446655440010")
        ctx = build_execution_context(node)
        assert "engrams" not in ctx
        assert "prompt" in ctx

    def test_minimal_node(self, tmp_path):
        content = "* TODO Minimal\n  :PROPERTIES:\n  :ID: min-001\n  :END:\n"
        f = tmp_path / "min.org"
        f.write_text(content)
        ws = OrgWorkspace(roots=[f])
        node = ws.find_by_id("min-001")
        ctx = build_execution_context(node)
        assert ctx == {}
