"""Shared test fixtures for org-workspace."""

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir():
    return FIXTURES_DIR


@pytest.fixture
def minimal_org():
    return FIXTURES_DIR / "minimal.org"


@pytest.fixture
def rich_task_org():
    return FIXTURES_DIR / "rich_task.org"


@pytest.fixture
def nightshift_org():
    return FIXTURES_DIR / "nightshift_queue.org"


@pytest.fixture
def multiline_props_org():
    return FIXTURES_DIR / "multiline_props.org"


@pytest.fixture
def dependencies_org():
    return FIXTURES_DIR / "dependencies.org"


@pytest.fixture
def multi_file_dir():
    return FIXTURES_DIR / "multi_file"


@pytest.fixture
def tmp_org(tmp_path):
    """Create a temporary org file for mutation tests."""
    content = "* TODO Test task\n  :PROPERTIES:\n  :ID: test-001\n  :END:\n  Body text.\n"
    path = tmp_path / "test.org"
    path.write_text(content)
    return path
