"""Insurance Homepage LangGraph Orchestrator.

A LangGraph-based orchestrator that coordinates Claude Code CLI subprocesses
for parallel feature development with git worktrees and automated code review.
"""

from .models import (
    Story,
    StoryStatus,
    Priority,
    DependencyGraph,
    DependencyNode,
    WorktreeInfo,
)
from .orchestrator import InsuranceOrchestrator, build_orchestrator_graph, OrchestratorState
from .claude_code import ClaudeCodeCLI, ClaudeCodeManager, ClaudeResult
from .worktree_manager import GitWorktreeManager, init_insurance_project
from .code_reviewer import CodeReviewer, ReviewResult

__all__ = [
    # Models
    "Story",
    "StoryStatus",
    "Priority",
    "DependencyGraph",
    "DependencyNode",
    "WorktreeInfo",
    # Orchestrator
    "OrchestratorState",
    "InsuranceOrchestrator",
    "build_orchestrator_graph",
    # Claude Code
    "ClaudeCodeCLI",
    "ClaudeCodeManager",
    "ClaudeResult",
    # Worktree
    "GitWorktreeManager",
    "init_insurance_project",
    # Reviewer
    "CodeReviewer",
    "ReviewResult",
]

__version__ = "0.1.0"