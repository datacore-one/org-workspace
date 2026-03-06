"""Tests for identifiers.py — auto-ID and resolution."""

import uuid
from pathlib import Path

import pytest
from orgparse import load, loads

from org_workspace.identifiers import DuplicateIdError, IdIndex, ensure_id


class TestEnsureId:
    def test_generates_uuid_when_missing(self):
        root = loads("* TODO Task without ID\n")
        node = root.children[0]
        result = ensure_id(node)
        # Should be a valid UUID
        uuid.UUID(result)  # raises if invalid
        # Should be set on the node
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
