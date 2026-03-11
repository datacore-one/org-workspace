"""Tests for _compat.py — orgparse compatibility layer."""

from org_workspace._vendor.orgparse import load, loads

from org_workspace._compat import dumps, get_multiline_property, set_multiline_property


class TestCompatAssertions:
    """Verify orgparse PR #77 internals are available."""

    def test_line_items_exists(self):
        node = loads("* probe\n").children[0]
        assert hasattr(node, "_line_items")

    def test_insert_line_item_exists(self):
        node = loads("* probe\n").children[0]
        assert hasattr(node, "_insert_line_item")

    def test_remove_line_item_exists(self):
        node = loads("* probe\n").children[0]
        assert hasattr(node, "_remove_line_item")


class TestOrgparseParsing:
    """Verify orgparse parses standard org constructs."""

    def test_parse_minimal(self, minimal_org):
        root = load(str(minimal_org))
        assert len(root.children) == 2

        task = root.children[0]
        assert task.heading == "Simple task"
        assert task.todo == "TODO"
        assert task.properties["ID"] == "550e8400-e29b-41d4-a716-446655440001"

        done = root.children[1]
        assert done.todo == "DONE"

    def test_parse_tags(self, rich_task_org):
        root = load(str(rich_task_org))
        task = root.children[0]
        assert "project" in task.tags
        assert "backend" in task.tags

    def test_parse_properties(self, rich_task_org):
        root = load(str(rich_task_org))
        task = root.children[0]
        assert task.properties["ID"] == "550e8400-e29b-41d4-a716-446655440010"
        # orgparse auto-converts Effort to minutes
        assert task.properties["Effort"] == 480


class TestRoundTrip:
    """INV-1: dumps(load(path)) == open(path).read() for unmutated files."""

    def test_round_trip_minimal(self, minimal_org):
        root = load(str(minimal_org))
        result = dumps(root)
        original = minimal_org.read_text()
        assert result == original, f"Round-trip failed:\n{repr(result)}\n!=\n{repr(original)}"

    def test_round_trip_rich_task(self, rich_task_org):
        root = load(str(rich_task_org))
        result = dumps(root)
        original = rich_task_org.read_text()
        assert result == original

    def test_round_trip_nightshift(self, nightshift_org):
        root = load(str(nightshift_org))
        result = dumps(root)
        original = nightshift_org.read_text()
        assert result == original

    def test_round_trip_multiline_props(self, multiline_props_org):
        root = load(str(multiline_props_org))
        result = dumps(root)
        original = multiline_props_org.read_text()
        assert result == original

    def test_round_trip_dependencies(self, dependencies_org):
        root = load(str(dependencies_org))
        result = dumps(root)
        original = dependencies_org.read_text()
        assert result == original

    def test_round_trip_loads(self):
        """Round-trip via loads/dumps."""
        text = "* TODO Hello\n  :PROPERTIES:\n  :ID: abc\n  :END:\n"
        root = loads(text)
        assert dumps(root) == text


class TestMultilinePropertyGet:
    """Test multiline property reading."""

    def test_simple_property(self, multiline_props_org):
        root = load(str(multiline_props_org))
        node = root.children[0]
        assert get_multiline_property(node, "SIMPLE_PROP") == "just a value"

    def test_multiline_context(self, multiline_props_org):
        root = load(str(multiline_props_org))
        node = root.children[0]
        result = get_multiline_property(node, "CONTEXT")
        assert result is not None
        lines = result.split("\n")
        assert len(lines) == 3
        assert "First line of context" in lines[0]
        assert "Third line of context" in lines[2]

    def test_multiline_key_files(self, multiline_props_org):
        root = load(str(multiline_props_org))
        node = root.children[0]
        result = get_multiline_property(node, "KEY_FILES")
        assert result is not None
        assert "src/auth.py" in result
        assert "tests/test_auth.py" in result

    def test_missing_property(self, multiline_props_org):
        root = load(str(multiline_props_org))
        node = root.children[0]
        assert get_multiline_property(node, "NONEXISTENT") is None

    def test_rich_task_context(self, rich_task_org):
        root = load(str(rich_task_org))
        node = root.children[0]
        result = get_multiline_property(node, "CONTEXT")
        assert result is not None
        assert "authentication system" in result


class TestMultilinePropertySet:
    """Test multiline property writing."""

    def test_set_single_line(self, tmp_org):
        root = load(str(tmp_org))
        node = root.children[0]
        set_multiline_property(node, "STATUS", "active")
        assert node.properties["STATUS"] == "active"

    def test_set_multiline(self, tmp_org):
        root = load(str(tmp_org))
        node = root.children[0]
        set_multiline_property(node, "CONTEXT", "Line one\nLine two\nLine three")
        # Verify it's readable back
        result = get_multiline_property(node, "CONTEXT")
        assert result is not None
        assert "Line one" in result
        assert "Line three" in result
