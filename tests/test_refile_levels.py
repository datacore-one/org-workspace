"""refile(): where the moved node lands, and what a level change may touch.

A node refiled without a target parent belongs at the top level of the target
file, which is what org-refile does for a file target. It used to keep the
level it had in the source, so a deeper node became a child of whatever heading
happened to be last in the target: a task moved out of an inbox section into a
flat queue file ended up nested under an unrelated finished task (2026-11-16).

A level change must touch headings only. A heading is a line that starts in
column 0 with stars followed by a space. An indented star is a list bullet and
a star followed by text is bold markup; both used to be rewritten, the bullet
into a heading of its own.
"""

from org_workspace.workspace import OrgWorkspace

BODY = (
    "   :PROPERTIES:\n"
    "   :ID: move-me\n"
    "   :END:\n"
    "   Notes:\n"
    "   * first point\n"
    "*Important*: keep this line\n"
)
NESTED = (
    "* Inbox\n"
    "** TODO Write the report\n"
    + BODY
    + "*** TODO Collect the numbers\n"
    "    :PROPERTIES:\n"
    "    :ID: move-me-child\n"
    "    :END:\n"
    "** TODO Stays here\n"
    "   :PROPERTIES:\n"
    "   :ID: stays\n"
    "   :END:\n"
)
TOP_LEVEL = (
    "* TODO Write the report\n"
    + BODY
    + "** TODO Collect the numbers\n"
    "   :PROPERTIES:\n"
    "   :ID: move-me-child\n"
    "   :END:\n"
    "* TODO Stays here\n"
    "  :PROPERTIES:\n"
    "  :ID: stays\n"
    "  :END:\n"
)
QUEUE = (
    "* DONE Earlier job\n"
    "  :PROPERTIES:\n"
    "  :ID: earlier\n"
    "  :END:\n"
)


def _workspace(tmp_path, source_text):
    source, queue = tmp_path / "source.org", tmp_path / "queue.org"
    source.write_text(source_text)
    queue.write_text(QUEUE)
    return OrgWorkspace(roots=[source, queue]), queue


def _lines_starting_with_a_star(path):
    return [line for line in path.read_text().splitlines() if line.startswith("*")]


def test_without_a_parent_the_node_lands_at_the_top_level_of_the_target(tmp_path):
    ws, queue = _workspace(tmp_path, NESTED)
    ws.refile(ws.find_by_id("move-me"), queue)
    ws.save_all()

    assert _lines_starting_with_a_star(queue) == [
        "* DONE Earlier job",
        "* TODO Write the report",
        "*Important*: keep this line",
        "** TODO Collect the numbers",
    ]
    assert "   * first point" in queue.read_text().splitlines()
    assert ws.find_by_id("earlier").children == []
    assert ws.find_by_id("move-me").level == 1
    assert ws.find_by_id("move-me-child").parent.id() == "move-me"


def test_under_a_parent_the_node_lands_one_level_below_it(tmp_path):
    ws, queue = _workspace(tmp_path, NESTED)
    ws.refile(ws.find_by_id("move-me"), queue, ws.find_by_id("earlier"))
    ws.save_all()

    assert ws.find_by_id("move-me").parent.id() == "earlier"
    assert ws.find_by_id("move-me").level == 2
    assert ws.find_by_id("move-me-child").level == 3


def test_a_level_change_touches_headings_only(tmp_path):
    ws, queue = _workspace(tmp_path, TOP_LEVEL)
    ws.refile(ws.find_by_id("move-me"), queue, ws.find_by_id("earlier"))
    ws.save_all()

    assert _lines_starting_with_a_star(queue) == [
        "* DONE Earlier job",
        "** TODO Write the report",
        "*Important*: keep this line",
        "*** TODO Collect the numbers",
    ]
    assert "   * first point" in queue.read_text().splitlines()
