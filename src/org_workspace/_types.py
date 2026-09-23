"""Core types for org-workspace."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ChecklistItem:
    """A checkbox item parsed from org body text."""

    text: str
    checked: bool
    line_number: int | None = None  # relative to body start

    def __str__(self) -> str:
        marker = "X" if self.checked else " "
        return f"- [{marker}] {self.text}"


_CHECKLIST_RE = re.compile(r"^\s*- \[([ Xx])\]\s+(.+)$")


def parse_checklists(body: str) -> list[ChecklistItem]:
    """Parse checklist items from org body text.

    Recognizes lines matching `- [X] text` or `- [ ] text`.
    """
    items = []
    for i, line in enumerate(body.split("\n")):
        m = _CHECKLIST_RE.match(line)
        if m:
            checked = m.group(1).upper() == "X"
            items.append(ChecklistItem(text=m.group(2), checked=checked, line_number=i))
    return items


@dataclass(frozen=True)
class StateConfig:
    """Configuration for org-mode TODO state sequences.

    Defines valid states, transitions, and terminal states.
    """

    sequences: dict[str, list[str]]
    terminal_states: frozenset[str]
    # Keywords rendered right of `|` in #+SEQ_TODO (org "done" class). Distinct
    # from terminal_states: DEFERRED (DIP-0009 v2.0) is done-class for
    # parsing/rendering but non-terminal for workflow — it can wake to TODO.
    # None → falls back to terminal_states (backward compatible).
    done_class: frozenset[str] | None = None

    @property
    def all_states(self) -> frozenset[str]:
        """All valid states across all sequences."""
        states: set[str] = set()
        for seq in self.sequences.values():
            states.update(seq)
        return frozenset(states)

    def is_terminal(self, state: str) -> bool:
        """Check if a state is terminal (DONE, CANCELLED under the default)."""
        return state in self.terminal_states

    def valid_transitions(self, from_state: str) -> frozenset[str]:
        """Return states reachable from the given state.

        Within a sequence, any non-terminal state can transition to any other state.
        Terminal states cannot transition to anything.
        """
        if from_state not in self.all_states:
            return frozenset()
        if self.is_terminal(from_state):
            return frozenset()
        # Can transition to any state in the same sequence(s)
        reachable: set[str] = set()
        for seq in self.sequences.values():
            if from_state in seq:
                reachable.update(seq)
        reachable.discard(from_state)
        return frozenset(reachable)

    def can_transition(self, from_state: str, to_state: str) -> bool:
        """Check if a transition is valid."""
        return to_state in self.valid_transitions(from_state)

    def env_keys(self) -> tuple[list[str], list[str]]:
        """(todo_keys, done_keys) for seeding the orgparse environment.

        done_keys mirror the right-of-`|` header class; everything else is
        todo-class. Order follows the declared sequences.
        """
        dones_set = self.done_class if self.done_class is not None else self.terminal_states
        todos: list[str] = []
        dones: list[str] = []
        for seq in self.sequences.values():
            for state in seq:
                target = dones if state in dones_set else todos
                if state not in target:
                    target.append(state)
        return todos, dones

    @classmethod
    def default(cls) -> StateConfig:
        """Canonical DIP-0009 v2.0 vocabulary.

        ``#+SEQ_TODO: TODO NEXT WAITING REVIEW | DONE DEFERRED CANCELLED``

        v2.0 retired the execution overlay: QUEUED, WORKING and FAILED are no
        longer states (migrated to NEXT, NEXT and REVIEW). DEFERRED is
        done-class (right of ``|``) but NOT terminal: it is closed-but-wakeable
        and may return to TODO. Terminal states are DONE and CANCELLED.

        Loaded workspaces seed the parser with this set as a baseline; per-file
        headers add keywords on top, so a file that still declares a retired
        keyword in its own header keeps parsing it.
        """
        return cls(
            sequences={
                "gtd": ["TODO", "NEXT", "WAITING", "REVIEW",
                        "DONE", "DEFERRED", "CANCELLED"],
            },
            terminal_states=frozenset({"DONE", "CANCELLED"}),
            done_class=frozenset({"DONE", "DEFERRED", "CANCELLED"}),
        )

    @classmethod
    def nightshift(cls) -> StateConfig:
        """Deprecated alias for :meth:`default`.

        DIP-0009 v1.1 merged the nightshift states into the canonical
        vocabulary; v2.0 then retired the overlay (QUEUED, WORKING, FAILED).
        A caller that must still read a legacy overlay file passes its own
        StateConfig or relies on that file's #+SEQ_TODO header.
        """
        return cls.default()


@dataclass(frozen=True)
class Dependency:
    """A parsed DEPENDS_ON entry."""

    dep_type: str  # BLOCKS, AFTER, WAITING
    target_id: str | None = None
    target_label: str | None = None
    free_text: str | None = None

    def __str__(self) -> str:
        if self.target_id:
            label_part = f' "{self.target_label}"' if self.target_label else ""
            return f"{self.dep_type} {self.target_id}{label_part}"
        return f'{self.dep_type} "{self.free_text}"'


# ID pattern: any non-whitespace, non-quote sequence (covers UUIDs and short IDs like dep-002)
_ID_REF_RE = re.compile(
    r"^(BLOCKS|AFTER|WAITING)\s+"
    r"([^\s\"]+)"
    r'(?:\s+"([^"]*)")?$'
)
_FREE_TEXT_RE = re.compile(
    r'^(BLOCKS|AFTER|WAITING)\s+"([^"]*)"$'
)


def parse_depends_on(value: str) -> list[Dependency]:
    """Parse DEPENDS_ON property value into Dependency list.

    Supports both single-line and multiline values.
    Grammar (from DIP-0009):
        dep_line  ::= dep_type SPACE target
        dep_type  ::= "BLOCKS" | "AFTER" | "WAITING"
        target    ::= uuid_ref | free_text
        uuid_ref  ::= UUID [SPACE DQUOTE label DQUOTE]
        free_text ::= DQUOTE text DQUOTE
    """
    deps = []
    for line in value.strip().split("\n"):
        line = line.strip()
        if not line:
            continue

        # Try ID reference first
        m = _ID_REF_RE.match(line)
        if m:
            deps.append(Dependency(
                dep_type=m.group(1),
                target_id=m.group(2),
                target_label=m.group(3),
            ))
            continue

        # Try free text
        m = _FREE_TEXT_RE.match(line)
        if m:
            deps.append(Dependency(
                dep_type=m.group(1),
                free_text=m.group(2),
            ))
            continue

    return deps
