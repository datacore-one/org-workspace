"""DIP-0009 v1.1 canonical state vocabulary (2026-07-25).

The workspace seeds the orgparse environment with the canonical union set,
so execution-overlay states (QUEUED/WORKING/REVIEW/FAILED) are recognized
even in files whose #+SEQ_TODO header omits them or that have no header at
all. Per-file headers still ADD keywords on top of the baseline — reading
from the file wins, the baseline is the safety net.

Background: four disagreeing state vocabularies stalled ~80 tasks invisibly
(nightshift wrote WORKING/REVIEW/FAILED into files that didn't declare them;
node.todo came back None; writers then stacked keywords: "NEXT WORKING").
"""
from pathlib import Path

import pytest

from org_workspace import OrgWorkspace, Query
from org_workspace._types import StateConfig

UNION = {"TODO", "NEXT", "WAITING", "DEFERRED", "QUEUED", "WORKING",
         "REVIEW", "DONE", "FAILED", "CANCELLED"}


def _ws_with(tmp_path: Path, content: str) -> tuple[OrgWorkspace, Path]:
    f = tmp_path / "tasks.org"
    f.write_text(content, encoding="utf-8")
    ws = OrgWorkspace()
    ws.load(f)
    return ws, f


# --- parsing: canonical baseline ---

def test_headerless_file_recognizes_overlay_states(tmp_path):
    ws, f = _ws_with(tmp_path, (
        "* Tasks\n"
        "** WORKING Claimed by executor :AI:\n"
        "** REVIEW Awaiting decision :AI:\n"
        "** QUEUED In the queue :AI:\n"
        "** FAILED Broke overnight :AI:\n"
    ))
    states = {n.todo for n in list(ws.all_nodes()) if n.level == 2}
    assert states == {"WORKING", "REVIEW", "QUEUED", "FAILED"}


def test_headerless_file_recognizes_next(tmp_path):
    # 5-plur/org/inbox.org had no header: even NEXT was unrecognized.
    ws, f = _ws_with(tmp_path, "* Inbox\n** NEXT Do the thing\n")
    node = [n for n in list(ws.all_nodes()) if n.level == 2][0]
    assert node.todo == "NEXT"


def test_partial_header_still_recognizes_undeclared_overlay_state(tmp_path):
    # Team-space headers declared only 6 states; REVIEW written by nightshift
    # must not be swallowed while Phase 1b stamping is in flight.
    ws, f = _ws_with(tmp_path, (
        "#+SEQ_TODO: TODO(t) NEXT(n!) WAITING(w!) WORKING(W!) | DONE(d!) CANCELLED(c!)\n"
        "* Tasks\n"
        "** REVIEW Needs a human :AI:\n"
    ))
    node = [n for n in list(ws.all_nodes()) if n.level == 2][0]
    assert node.todo == "REVIEW"


def test_file_header_adds_custom_keyword(tmp_path):
    # Reading from the file: a keyword the baseline never heard of.
    ws, f = _ws_with(tmp_path, (
        "#+SEQ_TODO: TODO BLOCKED | DONE\n"
        "* Tasks\n"
        "** BLOCKED Waiting on vendor\n"
    ))
    node = [n for n in list(ws.all_nodes()) if n.level == 2][0]
    assert node.todo == "BLOCKED"


def test_query_by_state_finds_overlay_states(tmp_path):
    ws, f = _ws_with(tmp_path, (
        "* Tasks\n"
        "** WORKING One :AI:\n"
        "** TODO Two\n"
    ))
    q = Query(ws)
    found = q.by_state("WORKING")
    assert [t.heading for t in found] == ["One"]


# --- StateConfig: canonical default ---

def test_default_config_is_canonical_union():
    cfg = StateConfig.default()
    assert cfg.all_states == frozenset(UNION)


def test_default_terminal_is_done_and_cancelled_only():
    cfg = StateConfig.default()
    assert cfg.is_terminal("DONE")
    assert cfg.is_terminal("CANCELLED")
    for s in ("FAILED", "REVIEW", "WORKING", "QUEUED"):
        assert not cfg.is_terminal(s), s


def test_default_config_allows_overlay_transitions():
    cfg = StateConfig.default()
    assert cfg.can_transition("NEXT", "WORKING")
    assert cfg.can_transition("WORKING", "REVIEW")
    assert cfg.can_transition("REVIEW", "DONE")
    assert cfg.can_transition("FAILED", "NEXT")


def test_env_keys_split_todo_and_done_class():
    todos, dones = StateConfig.default().env_keys()
    assert set(dones) == {"DONE", "FAILED", "CANCELLED"}  # right of | in header
    assert set(todos) == UNION - set(dones)


def test_nightshift_factory_aligned_no_executing():
    cfg = StateConfig.nightshift()
    assert "EXECUTING" not in cfg.all_states
    assert "WORKING" in cfg.all_states
    assert not cfg.is_terminal("FAILED")


# --- round trip ---

def test_transition_and_save_roundtrip_overlay_state(tmp_path):
    ws, f = _ws_with(tmp_path, "* Tasks\n** NEXT Claim me :AI:\n")
    node = [n for n in list(ws.all_nodes()) if n.level == 2][0]
    ws.transition(node, "WORKING")
    ws.save()
    ws2 = OrgWorkspace()
    ws2.load(f)
    node2 = [n for n in list(ws2.all_nodes()) if n.level == 2][0]
    assert node2.todo == "WORKING"
    assert "WORKING WORKING" not in f.read_text()
