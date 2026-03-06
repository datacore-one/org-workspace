"""Tests for _types.py — StateConfig, ChecklistItem, Dependency."""


from org_workspace._types import (
    ChecklistItem,
    Dependency,
    StateConfig,
    parse_checklists,
    parse_depends_on,
)


class TestChecklistItem:
    def test_parse_checked(self):
        body = "  - [X] Design token schema\n  - [ ] Implement endpoint\n"
        items = parse_checklists(body)
        assert len(items) == 2
        assert items[0].checked is True
        assert items[0].text == "Design token schema"

    def test_parse_unchecked(self):
        body = "  - [ ] Implement endpoint\n"
        items = parse_checklists(body)
        assert len(items) == 1
        assert items[0].checked is False
        assert items[0].text == "Implement endpoint"

    def test_parse_mixed_content(self):
        body = "Some text before.\n  - [X] Done item\nMore text.\n  - [ ] Todo item\n"
        items = parse_checklists(body)
        assert len(items) == 2

    def test_parse_empty(self):
        assert parse_checklists("") == []
        assert parse_checklists("Just text, no checkboxes") == []

    def test_lowercase_x(self):
        items = parse_checklists("- [x] lowercase checked")
        assert len(items) == 1
        assert items[0].checked is True

    def test_str_representation(self):
        item = ChecklistItem(text="Test", checked=True)
        assert str(item) == "- [X] Test"
        item2 = ChecklistItem(text="Todo", checked=False)
        assert str(item2) == "- [ ] Todo"


class TestStateConfig:
    def test_default_states(self):
        cfg = StateConfig.default()
        assert "TODO" in cfg.all_states
        assert "NEXT" in cfg.all_states
        assert "WAITING" in cfg.all_states
        assert "DONE" in cfg.all_states
        assert "CANCELLED" in cfg.all_states
        assert "DEFERRED" in cfg.all_states

    def test_default_terminal(self):
        cfg = StateConfig.default()
        assert cfg.is_terminal("DONE")
        assert cfg.is_terminal("CANCELLED")
        assert not cfg.is_terminal("TODO")
        assert not cfg.is_terminal("NEXT")

    def test_nightshift_states(self):
        cfg = StateConfig.nightshift()
        assert "QUEUED" in cfg.all_states
        assert "EXECUTING" in cfg.all_states
        assert "REVIEW" in cfg.all_states
        assert "FAILED" in cfg.all_states

    def test_nightshift_terminal(self):
        cfg = StateConfig.nightshift()
        assert cfg.is_terminal("DONE")
        assert cfg.is_terminal("FAILED")
        assert cfg.is_terminal("CANCELLED")
        assert not cfg.is_terminal("QUEUED")
        assert not cfg.is_terminal("EXECUTING")

    def test_valid_transitions(self):
        cfg = StateConfig.default()
        # TODO can transition to any non-terminal and terminal states
        trans = cfg.valid_transitions("TODO")
        assert "NEXT" in trans
        assert "DONE" in trans
        assert "TODO" not in trans  # can't transition to self

    def test_terminal_no_transitions(self):
        cfg = StateConfig.default()
        assert cfg.valid_transitions("DONE") == frozenset()
        assert cfg.valid_transitions("CANCELLED") == frozenset()

    def test_can_transition(self):
        cfg = StateConfig.default()
        assert cfg.can_transition("TODO", "DONE")
        assert cfg.can_transition("TODO", "NEXT")
        assert not cfg.can_transition("DONE", "TODO")
        assert not cfg.can_transition("TODO", "TODO")

    def test_unknown_state(self):
        cfg = StateConfig.default()
        assert cfg.valid_transitions("INVALID") == frozenset()
        assert not cfg.is_terminal("INVALID")


class TestDependency:
    def test_parse_blocks_with_uuid(self):
        deps = parse_depends_on('BLOCKS 550e8400-e29b-41d4-a716-446655440001 "Deploy CI pipeline"')
        assert len(deps) == 1
        assert deps[0].dep_type == "BLOCKS"
        assert deps[0].target_id == "550e8400-e29b-41d4-a716-446655440001"
        assert deps[0].target_label == "Deploy CI pipeline"

    def test_parse_after_with_uuid(self):
        deps = parse_depends_on('AFTER 550e8400-e29b-41d4-a716-446655440002 "Finalize MVP spec"')
        assert len(deps) == 1
        assert deps[0].dep_type == "AFTER"

    def test_parse_waiting_free_text(self):
        deps = parse_depends_on('WAITING "legal review of data classification"')
        assert len(deps) == 1
        assert deps[0].dep_type == "WAITING"
        assert deps[0].free_text == "legal review of data classification"
        assert deps[0].target_id is None

    def test_parse_multiline(self):
        value = (
            'BLOCKS 550e8400-e29b-41d4-a716-446655440001 "Deploy CI pipeline"\n'
            'AFTER 550e8400-e29b-41d4-a716-446655440002 "Finalize MVP spec"\n'
            'WAITING "legal review of data classification"'
        )
        deps = parse_depends_on(value)
        assert len(deps) == 3
        assert deps[0].dep_type == "BLOCKS"
        assert deps[1].dep_type == "AFTER"
        assert deps[2].dep_type == "WAITING"

    def test_parse_empty(self):
        assert parse_depends_on("") == []

    def test_parse_uuid_without_label(self):
        deps = parse_depends_on("BLOCKS abc-123")
        assert len(deps) == 1
        assert deps[0].target_id == "abc-123"
        assert deps[0].target_label is None

    def test_str_representation(self):
        dep = Dependency(dep_type="BLOCKS", target_id="abc", target_label="Test")
        assert str(dep) == 'BLOCKS abc "Test"'
        dep2 = Dependency(dep_type="WAITING", free_text="some review")
        assert str(dep2) == 'WAITING "some review"'
