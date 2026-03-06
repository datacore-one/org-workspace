"""Plans as DAGs with dependency resolution and execution ordering.

DEPENDS_ON semantics:
- BLOCKS target_id: This task must complete before target can start
- AFTER target_id: This task cannot start until target completes
- WAITING target_id: Like AFTER but implies external blocker

All three produce the same DAG edge for execution ordering.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

from org_workspace._compat import get_multiline_property
from org_workspace._types import parse_depends_on

if TYPE_CHECKING:
    from org_workspace.node_view import NodeView
    from org_workspace.workspace import OrgWorkspace


@dataclass
class PlanProgress:
    total: int
    done: int
    in_progress: int
    blocked: int
    ready: int

    @property
    def percent(self) -> float:
        if self.total == 0:
            return 100.0
        return round(self.done / self.total * 100, 1)


class Plan:
    """A plan represented as a subtree with dependency DAG.

    The root node is the plan heading; its children are steps.
    Dependencies are expressed via DEPENDS_ON properties.
    """

    def __init__(self, root_node: NodeView, workspace: OrgWorkspace):
        self._root = root_node
        self._workspace = workspace
        self._steps_cache: list[NodeView] | None = None

    @property
    def root(self) -> NodeView:
        return self._root

    def steps(self) -> list[NodeView]:
        """All step nodes (children of root, recursively)."""
        if self._steps_cache is not None:
            return self._steps_cache
        result = []
        self._collect_steps(self._root, result)
        self._steps_cache = result
        return result

    def _collect_steps(self, node: NodeView, result: list[NodeView]) -> None:
        for child in node.children:
            result.append(child)
            self._collect_steps(child, result)

    def _build_graph(self) -> tuple[dict[str, set[str]], dict[str, NodeView]]:
        """Build adjacency graph from DEPENDS_ON properties.

        Returns (edges: {node_id -> set of node_ids it depends on}, node_map).
        """
        nodes = {}
        edges: dict[str, set[str]] = defaultdict(set)

        for step in self.steps():
            node_id = step.id()
            if node_id:
                nodes[node_id] = step

        for step in self.steps():
            node_id = step.id()
            if not node_id:
                continue

            depends_on = get_multiline_property(step.node, "DEPENDS_ON")
            if not depends_on:
                # Try single-line
                depends_on = step.properties.get("DEPENDS_ON")
            if not depends_on or depends_on == "|":
                continue

            deps = parse_depends_on(depends_on)
            for dep in deps:
                if dep.dep_type == "BLOCKS" and dep.target_id:
                    # This node blocks target -> target depends on this
                    edges[dep.target_id].add(node_id)
                elif dep.dep_type in ("AFTER", "WAITING") and dep.target_id:
                    # This node depends on target
                    edges[node_id].add(dep.target_id)

        return dict(edges), nodes

    def execution_order(self) -> list[NodeView]:
        """Topological sort of steps respecting dependencies.

        Steps without dependencies come first.
        Raises ValueError if cycles exist.
        """
        edges, nodes = self._build_graph()

        # Kahn's algorithm
        all_ids = set(nodes.keys())
        in_degree: dict[str, int] = {nid: 0 for nid in all_ids}
        for nid, deps in edges.items():
            if nid in in_degree:
                in_degree[nid] = len(deps)

        queue = deque(nid for nid, deg in in_degree.items() if deg == 0)
        result = []
        visited = set()

        while queue:
            nid = queue.popleft()
            if nid in visited:
                continue
            visited.add(nid)
            if nid in nodes:
                result.append(nodes[nid])

            # Find nodes that depend on this one
            for other_id, deps in edges.items():
                if nid in deps:
                    in_degree[other_id] -= 1
                    if in_degree[other_id] == 0:
                        queue.append(other_id)

        # Add any nodes without IDs or without deps
        id_set = {n.id() for n in result if n.id()}
        for step in self.steps():
            sid = step.id()
            if sid and sid not in id_set:
                # Part of a cycle — detected below
                pass
            elif not sid:
                result.append(step)

        if len(visited) < len(all_ids):
            cycles = self.cycle_check()
            if cycles:
                raise ValueError(f"Dependency cycle detected: {cycles}")

        return result

    def ready_tasks(self) -> list[NodeView]:
        """Return steps that are ready for execution.

        Ready = not claimed, not blocked by unfinished deps, not in terminal state.
        """
        edges, nodes = self._build_graph()
        state_config = self._workspace.state_config

        ready = []
        for step in self.steps():
            node_id = step.id()
            todo = step.todo

            # Skip terminal states
            if todo and state_config.is_terminal(todo):
                continue

            # Skip claimed tasks
            if step.properties.get("CLAIMED_BY"):
                continue

            # Check if all dependencies are satisfied (terminal)
            if node_id and node_id in edges:
                deps_satisfied = True
                for dep_id in edges[node_id]:
                    dep_node = nodes.get(dep_id)
                    if dep_node:
                        dep_state = dep_node.todo
                        if not dep_state or not state_config.is_terminal(dep_state):
                            deps_satisfied = False
                            break
                if not deps_satisfied:
                    continue

            ready.append(step)

        return ready

    def blocked_tasks(self) -> list[tuple[NodeView, str]]:
        """Return steps that are blocked, with reason strings."""
        edges, nodes = self._build_graph()
        state_config = self._workspace.state_config

        blocked = []
        for step in self.steps():
            node_id = step.id()
            todo = step.todo

            if todo and state_config.is_terminal(todo):
                continue

            if node_id and node_id in edges:
                for dep_id in edges[node_id]:
                    dep_node = nodes.get(dep_id)
                    if dep_node:
                        dep_state = dep_node.todo
                        if not dep_state or not state_config.is_terminal(dep_state):
                            reason = f"Blocked by {dep_id} ({dep_node.heading})"
                            blocked.append((step, reason))
                            break

        return blocked

    def progress(self) -> PlanProgress:
        """Compute plan progress."""
        state_config = self._workspace.state_config
        steps = self.steps()
        total = len(steps)
        done = 0
        in_progress = 0
        blocked_set = {s.id() for s, _ in self.blocked_tasks() if s.id()}
        ready_set = {s.id() for s in self.ready_tasks() if s.id()}

        for step in steps:
            todo = step.todo
            if todo and state_config.is_terminal(todo):
                done += 1
            elif step.properties.get("CLAIMED_BY"):
                in_progress += 1

        blocked = len(blocked_set)
        ready = len(ready_set)

        return PlanProgress(
            total=total,
            done=done,
            in_progress=in_progress,
            blocked=blocked,
            ready=ready,
        )

    def cycle_check(self) -> list[list[str]]:
        """Detect dependency cycles. Returns list of cycles (each = list of IDs)."""
        edges, nodes = self._build_graph()
        all_ids = set(nodes.keys())

        # DFS-based cycle detection
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {nid: WHITE for nid in all_ids}
        parent = {nid: None for nid in all_ids}
        cycles = []

        def dfs(nid):
            color[nid] = GRAY
            if nid in edges:
                for dep_id in edges[nid]:
                    if dep_id not in color:
                        continue
                    if color[dep_id] == GRAY:
                        # Found cycle — trace back
                        cycle = [dep_id, nid]
                        cycles.append(cycle)
                    elif color[dep_id] == WHITE:
                        parent[dep_id] = nid
                        dfs(dep_id)
            color[nid] = BLACK

        for nid in all_ids:
            if color[nid] == WHITE:
                dfs(nid)

        return cycles
