"""Data models for the insurance homepage orchestrator."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class StoryStatus(str, Enum):
    """Status of a user story in the pipeline."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    REVIEWING = "reviewing"
    APPROVED = "approved"
    REJECTED = "rejected"
    MERGED = "merged"


class Priority(str, Enum):
    """Story priority levels."""
    MUST_HAVE = "Must Have"
    SHOULD_HAVE = "Should Have"
    COULD_HAVE = "Could Have"
    WONT_HAVE = "Won't Have"


@dataclass
class Story:
    """A user story with all its metadata."""
    id: str
    title: str
    category: str
    priority: Priority
    as_a: str
    i_want: str
    so_that: str
    dependencies: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    notes: Optional[str] = None
    status: StoryStatus = StoryStatus.PENDING
    worktree_name: Optional[str] = None
    branch_name: Optional[str] = None
    review_comments: list[str] = field(default_factory=list)

    def to_claude_prompt(self, all_stories: dict[str, Story]) -> str:
        """Generate a comprehensive prompt for Claude Code CLI."""
        deps_content = ""
        if self.dependencies:
            dep_stories = [all_stories[dep_id] for dep_id in self.dependencies if dep_id in all_stories]
            deps_content = "\n\n## Dependent Stories (already implemented)\n"
            for dep in dep_stories:
                if dep.status == StoryStatus.MERGED:
                    deps_content += f"- {dep.id}: {dep.title} ✓ (merged to main)\n"
                elif dep.status == StoryStatus.APPROVED:
                    deps_content += f"- {dep.id}: {dep.title} ✓ (approved, pending merge)\n"

        return f"""# User Story: {self.id} - {self.title}

## Story Details
- **As a**: {self.as_a}
- **I want**: {self.i_want}
- **So that**: {self.so_that}
- **Category**: {self.category}
- **Priority**: {self.priority.value}
{deps_content}

## Acceptance Criteria
{chr(10).join(f'{i+1}. {c}' for i, c in enumerate(self.acceptance_criteria))}

## Task
Implement this feature for the Insurance Company Home Page using Framer + Tailwind CSS.
The implementation should be in a single React component file.
Use cards and carousels as specified.
Ensure the code is production-ready, accessible, and follows best practices.

## Technical Context
- This is a TAILWIND CSS + Framer Motion project
- Use framer-motion for animations
- Use Tailwind CSS classes for styling
- Create responsive components
- Ensure WCAG accessibility compliance
"""


@dataclass
class DependencyNode:
    """A node in the dependency graph."""
    id: str
    label: str
    category: str
    edges_from: list[str] = field(default_factory=list)
    edges_to: list[str] = field(default_factory=list)


@dataclass
class DependencyGraph:
    """The full dependency graph structure."""
    nodes: list[DependencyNode] = field(default_factory=list)
    edges: list[tuple[str, str]] = field(default_factory=list)  # (from, to)
    root_nodes: list[str] = field(default_factory=list)
    category_colors: dict[str, str] = field(default_factory=dict)


@dataclass
class WorktreeInfo:
    """Information about a git worktree."""
    name: str
    path: str
    branch: str
    story_id: str
    is_active: bool = True