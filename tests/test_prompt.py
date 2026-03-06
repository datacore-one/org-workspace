"""Tests for prompt.py — PROMPT property and body fallback."""

import shutil

import pytest

from org_workspace.prompt import get_prompt, get_role
from org_workspace.workspace import OrgWorkspace


@pytest.fixture
def prompt_ws(tmp_path, rich_task_org):
    f = tmp_path / "rich.org"
    shutil.copy(rich_task_org, f)
    return OrgWorkspace(roots=[f])


class TestGetPrompt:
    def test_from_prompt_property(self, prompt_ws):
        node = prompt_ws.find_by_id("550e8400-e29b-41d4-a716-446655440010")
        result = get_prompt(node)
        assert result == "Design and implement OAuth2 authentication"

    def test_fallback_to_body(self, tmp_path):
        content = (
            "* TODO Task with body\n"
            "  :PROPERTIES:\n"
            "  :ID: body-001\n"
            "  :END:\n"
            "  This is the body text used as prompt.\n"
        )
        f = tmp_path / "body.org"
        f.write_text(content)
        ws = OrgWorkspace(roots=[f])
        node = ws.find_by_id("body-001")
        result = get_prompt(node)
        assert "body text used as prompt" in result

    def test_returns_none_when_empty(self, tmp_path):
        content = (
            "* TODO Empty task\n"
            "  :PROPERTIES:\n"
            "  :ID: empty-001\n"
            "  :END:\n"
        )
        f = tmp_path / "empty.org"
        f.write_text(content)
        ws = OrgWorkspace(roots=[f])
        node = ws.find_by_id("empty-001")
        result = get_prompt(node)
        assert result is None


class TestGetRole:
    def test_from_role_property(self, prompt_ws):
        node = prompt_ws.find_by_id("550e8400-e29b-41d4-a716-446655440010")
        result = get_role(node)
        assert result == "Senior Backend Engineer"

    def test_returns_none_when_missing(self, tmp_path):
        content = "* TODO No role\n  :PROPERTIES:\n  :ID: nr-001\n  :END:\n"
        f = tmp_path / "norole.org"
        f.write_text(content)
        ws = OrgWorkspace(roots=[f])
        node = ws.find_by_id("nr-001")
        assert get_role(node) is None
