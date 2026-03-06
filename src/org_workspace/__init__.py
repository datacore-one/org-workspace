"""org-workspace: Python library for AI agent org-mode workflows."""

from org_workspace._compat import dumps, get_multiline_property, set_multiline_property
from org_workspace._types import (
    ChecklistItem,
    Dependency,
    StateConfig,
    parse_checklists,
    parse_depends_on,
)
from org_workspace.archive import (
    archive_done,
    archive_node,
    archive_plan,
    default_archive_path,
)
from org_workspace.concurrency import (
    ConflictError,
    FileLock,
    OptimisticLock,
    TaskClaim,
    multi_lock,
)
from org_workspace.context import build_execution_context, get_context, get_refs
from org_workspace.identifiers import (
    DuplicateIdError,
    IdIndex,
    ensure_id,
    generate_id,
    heading_hash,
)
from org_workspace.log import SessionLog, add_clock_entry, add_logbook_entry, add_state_change_entry
from org_workspace.node_view import NodeView, StaleNodeError
from org_workspace.plan import Plan, PlanProgress
from org_workspace.prompt import get_prompt, get_role
from org_workspace.query import Query
from org_workspace.workspace import InvalidTransitionError, OrgWorkspace

__version__ = "0.3.0"

__all__ = [
    # Core types
    "ChecklistItem",
    "Dependency",
    "StateConfig",
    "parse_checklists",
    "parse_depends_on",
    # Compat
    "dumps",
    "get_multiline_property",
    "set_multiline_property",
    # Node view
    "NodeView",
    "StaleNodeError",
    # Identifiers
    "DuplicateIdError",
    "IdIndex",
    "ensure_id",
    "generate_id",
    "heading_hash",
    # Workspace
    "OrgWorkspace",
    "InvalidTransitionError",
    # Concurrency
    "ConflictError",
    "FileLock",
    "OptimisticLock",
    "TaskClaim",
    "multi_lock",
    # Logging
    "SessionLog",
    "add_clock_entry",
    "add_logbook_entry",
    "add_state_change_entry",
    # Plans
    "Plan",
    "PlanProgress",
    # Query
    "Query",
    # Archive
    "archive_done",
    "archive_node",
    "archive_plan",
    "default_archive_path",
    # Context & Prompt
    "build_execution_context",
    "get_context",
    "get_prompt",
    "get_refs",
    "get_role",
]
