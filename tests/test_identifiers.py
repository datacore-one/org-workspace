"""Tests for identifiers.py — auto-ID and resolution."""

import re
from datetime import datetime
from pathlib import Path

import pytest
from org_workspace._vendor.orgparse import load, loads

from org_workspace.identifiers import (
    DuplicateIdError,
    IdIndex,
    dedup_ids,
    ensure_id,
    generate_id,
    heading_hash,
)

_ID_PATTERN = re.compile(r"^org-\d{8}-\d{6}-[0-9a-f]{8}$")


class TestGenerateId:
    def test_format(self):
        result = generate_id("Buy groceries")
        assert _ID_PATTERN.match(result), f"Bad format: {result}"

    def test_contains_date(self):
        ts = datetime(2026, 3, 6, 14, 30, 22)
        result = generate_id("Buy groceries", timestamp=ts)
        assert "20260306-143022" in result

    def test_same_heading_same_hash(self):
        ts = datetime(2026, 3, 6, 14, 30, 22)
        a = generate_id("Buy groceries", timestamp=ts)
        b = generate_id("Buy groceries", timestamp=ts)
        assert a == b

    def test_different_heading_different_hash(self):
        ts = datetime(2026, 3, 6, 14, 30, 22)
        a = generate_id("Buy groceries", timestamp=ts)
        b = generate_id("Write report", timestamp=ts)
        assert a != b

    def test_different_time_different_id(self):
        a = generate_id("Buy groceries", datetime(2026, 1, 1, 0, 0, 0))
        b = generate_id("Buy groceries", datetime(2026, 1, 2, 0, 0, 0))
        assert a != b
        # But same hash suffix
        assert a.split("-")[-1] == b.split("-")[-1]


class TestHeadingHash:
    def test_deterministic(self):
        assert heading_hash("Buy groceries") == heading_hash("Buy groceries")

    def test_different_for_different_headings(self):
        assert heading_hash("Buy groceries") != heading_hash("Write report")

    def test_length(self):
        assert len(heading_hash("anything")) == 8


class TestEnsureId:
    def test_generates_content_addressed_id_when_missing(self):
        root = loads("* TODO Task without ID\n")
        node = root.children[0]
        result = ensure_id(node)
        assert _ID_PATTERN.match(result), f"Bad format: {result}"
        assert node.properties["ID"] == result

    def test_preserves_existing_id(self):
        root = loads("* TODO Task\n  :PROPERTIES:\n  :ID: existing-id\n  :END:\n")
        node = root.children[0]
        result = ensure_id(node)
        assert result == "existing-id"
        assert node.properties["ID"] == "existing-id"

    def test_no_modification_when_exists(self):
        root = loads("* TODO Task\n  :PROPERTIES:\n  :ID: keep-me\n  :END:\n")
        node = root.children[0]
        ensure_id(node)
        assert node.properties["ID"] == "keep-me"


class TestIdIndex:
    def test_resolve_across_files(self, minimal_org, nightshift_org):
        idx = IdIndex()
        root1 = load(str(minimal_org))
        root2 = load(str(nightshift_org))
        idx.add_file(minimal_org, root1)
        idx.add_file(nightshift_org, root2)

        # Resolve from first file
        result = idx.resolve("550e8400-e29b-41d4-a716-446655440001")
        assert result is not None
        path, node = result
        assert path == minimal_org
        assert node.heading == "Simple task"

        # Resolve from second file
        result = idx.resolve("ns-001")
        assert result is not None
        path, node = result
        assert path == nightshift_org

    def test_resolve_missing(self):
        idx = IdIndex()
        assert idx.resolve("nonexistent") is None

    def test_duplicate_detection(self):
        """INV-3: Duplicate IDs raise DuplicateIdError."""
        idx = IdIndex()
        root1 = loads("* TODO Task A\n  :PROPERTIES:\n  :ID: dupe-id\n  :END:\n")
        root2 = loads("* TODO Task B\n  :PROPERTIES:\n  :ID: dupe-id\n  :END:\n")
        idx.add_file(Path("a.org"), root1)
        with pytest.raises(DuplicateIdError, match="dupe-id"):
            idx.add_file(Path("b.org"), root2)

    def test_nested_nodes_indexed(self):
        """IDs in nested nodes are also indexed."""
        root = loads(
            "* Parent\n"
            "  :PROPERTIES:\n  :ID: parent-id\n  :END:\n"
            "** Child\n"
            "   :PROPERTIES:\n   :ID: child-id\n   :END:\n"
        )
        idx = IdIndex()
        idx.add_file(Path("test.org"), root)
        assert idx.resolve("parent-id") is not None
        assert idx.resolve("child-id") is not None

    def test_remove_file(self, minimal_org):
        idx = IdIndex()
        root = load(str(minimal_org))
        idx.add_file(minimal_org, root)
        assert len(idx) == 2
        idx.remove_file(minimal_org)
        assert len(idx) == 0

    def test_contains(self, minimal_org):
        idx = IdIndex()
        root = load(str(minimal_org))
        idx.add_file(minimal_org, root)
        assert "550e8400-e29b-41d4-a716-446655440001" in idx
        assert "nonexistent" not in idx

    def test_all_ids(self, minimal_org):
        idx = IdIndex()
        root = load(str(minimal_org))
        idx.add_file(minimal_org, root)
        ids = idx.all_ids()
        assert "550e8400-e29b-41d4-a716-446655440001" in ids
        assert len(ids) == 2


class TestDedupIds:
    """Test dedup_ids: regenerate IDs for duplicates within a tree."""

    def test_no_duplicates_no_changes(self):
        root = loads(
            "* TODO Task A\n  :PROPERTIES:\n  :ID: id-a\n  :END:\n"
            "* TODO Task B\n  :PROPERTIES:\n  :ID: id-b\n  :END:\n"
        )
        changes = dedup_ids(root)
        assert changes == []

    def test_duplicate_within_file(self):
        root = loads(
            "* TODO Task A\n  :PROPERTIES:\n  :ID: same-id\n  :END:\n"
            "* TODO Task B\n  :PROPERTIES:\n  :ID: same-id\n  :END:\n"
        )
        changes = dedup_ids(root)
        assert len(changes) == 1
        node, old_id, new_id = changes[0]
        assert old_id == "same-id"
        assert new_id != "same-id"
        # First node keeps original
        assert root.children[0].properties["ID"] == "same-id"
        # Second node gets new ID
        assert root.children[1].properties["ID"] == new_id

    def test_collision_with_existing_ids(self):
        root = loads("* TODO Task\n  :PROPERTIES:\n  :ID: taken-id\n  :END:\n")
        changes = dedup_ids(root, existing_ids={"taken-id"})
        assert len(changes) == 1
        _, old_id, new_id = changes[0]
        assert old_id == "taken-id"
        assert new_id != "taken-id"

    def test_triple_duplicate(self):
        root = loads(
            "* A\n  :PROPERTIES:\n  :ID: x\n  :END:\n"
            "* B\n  :PROPERTIES:\n  :ID: x\n  :END:\n"
            "* C\n  :PROPERTIES:\n  :ID: x\n  :END:\n"
        )
        changes = dedup_ids(root)
        assert len(changes) == 2
        # All three nodes should have unique IDs
        ids = [root.children[i].properties["ID"] for i in range(3)]
        assert len(set(ids)) == 3
