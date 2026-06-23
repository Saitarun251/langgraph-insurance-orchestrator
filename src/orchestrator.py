"""Main LangGraph orchestrator for insurance homepage development.

Fixed version with proper LangGraph patterns:
- Pydantic BaseModel for state
- Proper async/sync node handling
- Immutable state updates
- Checkpointing for persistence
- Cross-platform support
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from .models import (
    Story,
    StoryStatus,
    Priority,
    DependencyGraph,
    DependencyNode,
    WorktreeInfo,
)
from .claude_code import ClaudeCodeManager, ClaudeResult
from .worktree_manager import GitWorktreeManager, init_insurance_project
from .code_reviewer import CodeReviewer, ReviewResult
from .platform_utils import (
    is_claude_code_available,
    get_claude_code_path,
    is_git_available,
    get_platform_info,
)


# ============================================================================
# LangGraph State (Pydantic BaseModel for immutable updates)
# ============================================================================

class OrchestratorState(BaseModel):
    """Immutable state for LangGraph orchestrator using Pydantic."""

    # Core data
    stories: dict[str, Story] = Field(default_factory=dict)
    dependency_graph: Optional[DependencyGraph] = None

    # Worktree tracking
    worktrees: dict[str, WorktreeInfo] = Field(default_factory=dict)

    # Current processing
    current_story_id: Optional[str] = None
    pending_queue: list[str] = Field(default_factory=list)

    # Results
    completed_stories: list[str] = Field(default_factory=list)
    failed_stories: list[str] = Field(default_factory=list)

    # Execution tracking
    processing_logs: list[str] = Field(default_factory=list)
    error: Optional[str] = None

    # Claude Code results (for passing between nodes)
    last_claude_result: Optional[dict] = None

    def add_log(self, message: str):
        """Add a log entry (creates new state)."""
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.processing_logs.append(f"[{timestamp}] {message}")

    def get_ready_stories(self) -> list[str]:
        """Get stories that are ready to be worked on (all deps merged)."""
        ready = []
        for story_id, story in self.stories.items():
            if story.status != StoryStatus.PENDING:
                continue
            # Check if all dependencies are merged
            all_deps_merged = all(
                self.stories.get(dep_id, Story(
                    id=dep_id, title="", category="",
                    priority=Priority.MUST_HAVE, as_a="", i_want="", so_that=""
                )).status == StoryStatus.MERGED
                for dep_id in story.dependencies
            )
            if all_deps_merged:
                ready.append(story_id)
        return ready

    def get_next_story(self) -> Optional[str]:
        """Get the next story to work on based on priority."""
        ready = self.get_ready_stories()
        if not ready:
            return None

        # Sort by priority
        priority_order = {
            Priority.MUST_HAVE: 0,
            Priority.SHOULD_HAVE: 1,
            Priority.COULD_HAVE: 2,
            Priority.WONT_HAVE: 3,
        }

        ready_stories = [(sid, self.stories[sid]) for sid in ready]
        ready_stories.sort(key=lambda x: priority_order.get(x[1].priority, 99))

        return ready_stories[0][0]


# ============================================================================
# LangGraph Node Functions (all sync for LangGraph)
# ============================================================================

def load_data_node(state: OrchestratorState) -> OrchestratorState:
    """Load stories and dependency graph from JSON files."""
    new_logs = list(state.processing_logs)
    new_logs.append("Loading user stories and dependency graph...")

    # Log platform info for debugging
    platform = get_platform_info()
    new_logs.append(f"Platform: {platform['system']} | Git: {platform['has_git']} | Claude: {platform['has_claude']}")

    stories_path = Path(__file__).parent.parent / "data" / "insurance-homepage-stories.json"
    graph_path = Path(__file__).parent.parent / "data" / "insurance-homepage-dependency-graph.json"

    new_stories = {}
    if stories_path.exists():
        with open(stories_path) as f:
            data = json.load(f)
            for story_data in data.get("stories", []):
                story = Story(
                    id=story_data["id"],
                    title=story_data["title"],
                    category=story_data["category"],
                    priority=Priority(story_data["priority"]),
                    as_a=story_data["asA"],
                    i_want=story_data["iWant"],
                    so_that=story_data["soThat"],
                    dependencies=story_data.get("dependencies", []),
                    acceptance_criteria=story_data.get("acceptanceCriteria", []),
                    notes=story_data.get("notes"),
                )
                new_stories[story.id] = story
    else:
        new_logs.append(f"WARNING: Stories file not found at {stories_path}")

    new_graph = None
    if graph_path.exists():
        with open(graph_path) as f:
            data = json.load(f)
            new_graph = DependencyGraph(
                nodes=[DependencyNode(**n) for n in data.get("nodes", [])],
                edges=[(e["from"], e["to"]) for e in data.get("edges", [])],
                root_nodes=data.get("rootNodes", []),
                category_colors=data.get("categoryColors", {}),
            )
    else:
        new_logs.append(f"WARNING: Graph file not found at {graph_path}")

    new_logs.append(f"Loaded {len(new_stories)} stories")

    return state.model_copy(update={
        "stories": new_stories,
        "dependency_graph": new_graph,
        "processing_logs": new_logs,
    })


def init_project_node(state: OrchestratorState) -> OrchestratorState:
    """Initialize the insurance homepage project if not exists."""
    new_logs = list(state.processing_logs)
    new_logs.append("Initializing project structure...")

    base_path = Path(__file__).parent.parent.parent / "insurance-homepage"
    if not base_path.exists():
        init_insurance_project(str(base_path))
        new_logs.append(f"Project initialized at {base_path}")
    else:
        new_logs.append("Project already exists")

    return state.model_copy(update={"processing_logs": new_logs})


def check_ready_stories_node(state: OrchestratorState) -> OrchestratorState:
    """Check which stories are ready to be worked on."""
    ready = state.get_ready_stories()

    # Filter out Won't Have stories for MVP
    mvp_stories = [
        sid for sid in ready
        if state.stories[sid].priority != Priority.WONT_HAVE
    ]

    new_logs = list(state.processing_logs)
    new_logs.append(f"Ready stories: {mvp_stories}")

    return state.model_copy(update={
        "pending_queue": mvp_stories,
        "processing_logs": new_logs,
    })


def should_continue_node(state: OrchestratorState) -> Literal["select_story", "end"]:
    """Determine if there are more stories to process."""
    # Only check pending queue, not get_ready_stories() to avoid infinite loop
    if state.pending_queue:
        return "select_story"
    return "end"


def select_story_node(state: OrchestratorState) -> OrchestratorState:
    """Select the next story to work on."""
    if not state.pending_queue:
        return state

    next_story_id = state.pending_queue[0]  # Pop from queue
    remaining_queue = state.pending_queue[1:]

    new_stories = dict(state.stories)
    if next_story_id in new_stories:
        new_stories[next_story_id] = Story(
            **{**new_stories[next_story_id].__dict__, "status": StoryStatus.IN_PROGRESS}
        )

    new_logs = list(state.processing_logs)
    new_logs.append(f"Selected story: {next_story_id} - {new_stories.get(next_story_id, Story(id=next_story_id, title='', category='', priority=Priority.MUST_HAVE, as_a='', i_want='', so_that='')).title}")

    return state.model_copy(update={
        "current_story_id": next_story_id,
        "pending_queue": remaining_queue,
        "stories": new_stories,
        "processing_logs": new_logs,
    })


def create_worktree_node(state: OrchestratorState) -> OrchestratorState:
    """Create a git worktree for the current story."""
    if not state.current_story_id:
        return state

    story = state.stories.get(state.current_story_id)
    if not story:
        return state

    base_path = Path(__file__).parent.parent.parent / "insurance-homepage"

    new_logs = list(state.processing_logs)
    new_logs.append(f"Creating worktree for {story.id}...")

    new_worktrees = dict(state.worktrees)

    try:
        worktree_mgr = GitWorktreeManager(str(base_path))
        worktree_info = worktree_mgr.create_worktree(
            story_id=story.id,
            story_title=story.title,
        )

        new_worktrees[story.id] = worktree_info

        # Update story with worktree info
        new_stories = dict(state.stories)
        updated_story = Story(
            id=story.id,
            title=story.title,
            category=story.category,
            priority=story.priority,
            as_a=story.as_a,
            i_want=story.i_want,
            so_that=story.so_that,
            dependencies=story.dependencies,
            acceptance_criteria=story.acceptance_criteria,
            notes=story.notes,
            status=story.status,
            worktree_name=worktree_info.name,
            branch_name=worktree_info.branch,
            review_comments=story.review_comments,
        )
        new_stories[story.id] = updated_story

        new_logs.append(f"Worktree created: {worktree_info.name}")

        return state.model_copy(update={
            "worktrees": new_worktrees,
            "stories": new_stories,
            "processing_logs": new_logs,
        })

    except Exception as e:
        new_logs.append(f"ERROR: Failed to create worktree: {str(e)}")
        return state.model_copy(update={
            "error": f"Failed to create worktree: {str(e)}",
            "processing_logs": new_logs,
        })


def code_feature_node(state: OrchestratorState) -> OrchestratorState:
    """Execute Claude Code CLI to implement the feature."""
    if not state.current_story_id:
        return state

    story = state.stories.get(state.current_story_id)
    worktree_info = state.worktrees.get(state.current_story_id)

    if not story or not worktree_info:
        return state

    new_logs = list(state.processing_logs)
    new_logs.append(f"Executing Claude Code for: {story.id}")

    try:
        # Check prerequisites
        if not is_git_available():
            raise FileNotFoundError("Git is not installed or not in PATH")

        if not is_claude_code_available():
            raise FileNotFoundError(
                "Claude Code CLI not found. Install with:\n"
                "  npm install -g @anthropic-ai/claude-code"
            )

        # Run synchronous Claude Code execution
        import subprocess
        base_path = Path(__file__).parent.parent.parent / "insurance-homepage"

        # Generate prompt
        prompt = story.to_claude_prompt(state.stories)

        # Create prompt file
        prompt_file = base_path / "worktrees" / worktree_info.name / f".claude_prompt_{story.id}.txt"
        prompt_file.write_text(prompt)

        try:
            # Execute Claude Code CLI (cross-platform: uses shutil.which internally via platform_utils)
            claude_path = get_claude_code_path()
            result = subprocess.run(
                [claude_path, "--print", "--max-turns=10", "--approval-mode=bypass"],
                input=prompt,
                cwd=str(base_path / "worktrees" / worktree_info.name),
                capture_output=True,
                text=True,
                timeout=300,
            )

            success = result.returncode == 0
            files_created = []
            files_modified = []

            # Parse file changes from output
            output = result.stdout + result.stderr
            for line in output.split("\n"):
                if "Created file:" in line or "Wrote file:" in line:
                    files_created.append(line.split(":", 1)[1].strip())
                elif "Modified file:" in line:
                    files_modified.append(line.split(":", 1)[1].strip())

            new_logs.append(f"Claude Code completed: {len(files_created)} files created, {len(files_modified)} modified")

            new_failed = list(state.failed_stories)
            if not success:
                new_failed.append(story.id)
                new_logs.append(f"ERROR: Claude Code failed: {result.stderr[:200]}")

            # Update story status
            new_stories = dict(state.stories)
            new_stories[story.id] = Story(
                id=story.id,
                title=story.title,
                category=story.category,
                priority=story.priority,
                as_a=story.as_a,
                i_want=story.i_want,
                so_that=story.so_that,
                dependencies=story.dependencies,
                acceptance_criteria=story.acceptance_criteria,
                notes=story.notes,
                status=StoryStatus.REVIEWING if success else StoryStatus.REJECTED,
                worktree_name=story.worktree_name,
                branch_name=story.branch_name,
                review_comments=story.review_comments,
            )

            return state.model_copy(update={
                "stories": new_stories,
                "failed_stories": new_failed,
                "last_claude_result": {
                    "success": success,
                    "files_created": files_created,
                    "files_modified": files_modified,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                },
                "processing_logs": new_logs,
            })

        finally:
            # Clean up prompt file
            if prompt_file.exists():
                prompt_file.unlink()

    except subprocess.TimeoutExpired:
        new_logs.append("ERROR: Claude Code timed out after 300 seconds")
        return state.model_copy(update={
            "error": "Claude Code timed out",
            "processing_logs": new_logs,
        })
    except FileNotFoundError as e:
        new_logs.append(f"ERROR: {str(e)}")
        return state.model_copy(update={
            "error": str(e),
            "processing_logs": new_logs,
        })
    except Exception as e:
        new_logs.append(f"ERROR: {str(e)}")
        return state.model_copy(update={
            "error": str(e),
            "processing_logs": new_logs,
        })


def review_feature_node(state: OrchestratorState) -> OrchestratorState:
    """Review the implemented feature using Claude."""
    if not state.current_story_id:
        return state

    story = state.stories.get(state.current_story_id)
    worktree_info = state.worktrees.get(state.current_story_id)
    claude_result = state.last_claude_result

    if not story or not worktree_info:
        return state

    new_logs = list(state.processing_logs)
    new_logs.append(f"Starting code review for: {story.id}")

    try:
        reviewer = CodeReviewer()

        # Get files from Claude result
        files_created = claude_result.get("files_created", []) if claude_result else []
        files_modified = claude_result.get("files_modified", []) if claude_result else []

        # Run review
        review_result = reviewer.review_code(
            story=story,
            worktree_path=worktree_info.path,
            files_created=files_created,
            files_modified=files_modified,
        )

        # Update story based on review
        new_stories = dict(state.stories)
        new_stories[story.id] = Story(
            id=story.id,
            title=story.title,
            category=story.category,
            priority=story.priority,
            as_a=story.as_a,
            i_want=story.i_want,
            so_that=story.so_that,
            dependencies=story.dependencies,
            acceptance_criteria=story.acceptance_criteria,
            notes=story.notes,
            status=StoryStatus.APPROVED if review_result.approved else StoryStatus.REJECTED,
            worktree_name=story.worktree_name,
            branch_name=story.branch_name,
            review_comments=review_result.comments + review_result.issues,
        )

        if review_result.approved:
            new_logs.append(f"Review APPROVED (score: {review_result.score:.2f})")
        else:
            new_logs.append(f"Review REJECTED: {review_result.issues}")

        return state.model_copy(update={
            "stories": new_stories,
            "processing_logs": new_logs,
        })

    except Exception as e:
        new_logs.append(f"ERROR: Review failed: {str(e)}")
        return state.model_copy(update={
            "error": f"Review failed: {str(e)}",
            "processing_logs": new_logs,
        })


def should_merge_node(state: OrchestratorState) -> Literal["merge_to_main", "cleanup_retry", "check_ready"]:
    """Determine if story should be merged or retried."""
    if not state.current_story_id:
        return "check_ready"

    story = state.stories.get(state.current_story_id)
    if not story:
        return "check_ready"

    if story.status == StoryStatus.APPROVED:
        return "merge_to_main"
    elif story.status == StoryStatus.REJECTED:
        return "cleanup_retry"
    return "check_ready"


def merge_to_main_node(state: OrchestratorState) -> OrchestratorState:
    """Merge the approved feature to main branch."""
    if not state.current_story_id:
        return state

    story = state.stories.get(state.current_story_id)
    worktree_info = state.worktrees.get(state.current_story_id)

    if not story or not worktree_info:
        return state

    new_logs = list(state.processing_logs)
    new_logs.append(f"Merging {story.id} to main...")

    try:
        base_path = Path(__file__).parent.parent.parent / "insurance-homepage"
        worktree_mgr = GitWorktreeManager(str(base_path))

        success = worktree_mgr.merge_to_main(
            worktree_name=worktree_info.name,
            commit_message=f"feat({story.category}): {story.id} - {story.title}",
        )

        new_completed = list(state.completed_stories)
        new_worktrees = dict(state.worktrees)

        if success:
            # Update story to MERGED
            new_stories = dict(state.stories)
            new_stories[story.id] = Story(
                id=story.id,
                title=story.title,
                category=story.category,
                priority=story.priority,
                as_a=story.as_a,
                i_want=story.i_want,
                so_that=story.so_that,
                dependencies=story.dependencies,
                acceptance_criteria=story.acceptance_criteria,
                notes=story.notes,
                status=StoryStatus.MERGED,
                worktree_name=story.worktree_name,
                branch_name=story.branch_name,
                review_comments=story.review_comments,
            )

            new_completed.append(story.id)
            new_logs.append(f"Successfully merged {story.id} to main")

            # Clean up worktree
            worktree_mgr.remove_worktree(worktree_info.name)
            del new_worktrees[story.id]

            return state.model_copy(update={
                "stories": new_stories,
                "completed_stories": new_completed,
                "worktrees": new_worktrees,
                "current_story_id": None,
                "processing_logs": new_logs,
            })
        else:
            new_logs.append(f"ERROR: Merge failed for {story.id}")
            return state.model_copy(update={
                "error": f"Merge failed for {story.id}",
                "processing_logs": new_logs,
            })

    except Exception as e:
        new_logs.append(f"ERROR: Merge failed: {str(e)}")
        return state.model_copy(update={
            "error": f"Merge failed: {str(e)}",
            "processing_logs": new_logs,
        })


def cleanup_retry_node(state: OrchestratorState) -> OrchestratorState:
    """Clean up worktree after rejected story."""
    if not state.current_story_id:
        return state

    story = state.stories.get(state.current_story_id)
    worktree_info = state.worktrees.get(state.current_story_id)

    new_logs = list(state.processing_logs)

    if story and story.status == StoryStatus.REJECTED and worktree_info:
        try:
            base_path = Path(__file__).parent.parent.parent / "insurance-homepage"
            worktree_mgr = GitWorktreeManager(str(base_path))
            worktree_mgr.remove_worktree(worktree_info.name)

            new_worktrees = dict(state.worktrees)
            del new_worktrees[state.current_story_id]
            new_logs.append(f"Cleaned up worktree for rejected story: {story.id}")

            return state.model_copy(update={
                "worktrees": new_worktrees,
                "current_story_id": None,
                "processing_logs": new_logs,
            })
        except Exception:
            pass

    return state.model_copy(update={
        "current_story_id": None,
        "processing_logs": new_logs,
    })


def end_node(state: OrchestratorState) -> OrchestratorState:
    """Final node - summarize results."""
    new_logs = list(state.processing_logs)
    new_logs.append("=" * 50)
    new_logs.append("ORCHESTRATION COMPLETE")
    new_logs.append(f"Completed: {len(state.completed_stories)} stories")
    new_logs.append(f"Failed: {len(state.failed_stories)} stories")
    new_logs.append(f"Merged: {state.completed_stories}")
    new_logs.append(f"Failed: {state.failed_stories}")

    return state.model_copy(update={"processing_logs": new_logs})


# ============================================================================
# Build the LangGraph
# ============================================================================

def build_orchestrator_graph() -> StateGraph:
    """Build the main orchestrator state graph."""

    # Define the graph with Pydantic state
    workflow = StateGraph(OrchestratorState)

    # Add nodes (all sync)
    workflow.add_node("load_data", load_data_node)
    workflow.add_node("init_project", init_project_node)
    workflow.add_node("check_ready", check_ready_stories_node)
    workflow.add_node("select_story", select_story_node)
    workflow.add_node("create_worktree", create_worktree_node)
    workflow.add_node("code_feature", code_feature_node)
    workflow.add_node("review_feature", review_feature_node)
    workflow.add_node("merge_to_main", merge_to_main_node)
    workflow.add_node("cleanup_retry", cleanup_retry_node)
    workflow.add_node("end", end_node)

    # Define entry point
    workflow.set_entry_point("load_data")

    # Main flow edges
    workflow.add_edge("load_data", "init_project")
    workflow.add_edge("init_project", "check_ready")

    # Conditional entry to story loop
    workflow.add_conditional_edges(
        "check_ready",
        should_continue_node,
        {
            "select_story": "select_story",
            "end": "end",
        }
    )

    # Story processing flow
    workflow.add_edge("select_story", "create_worktree")
    workflow.add_edge("create_worktree", "code_feature")
    workflow.add_edge("code_feature", "review_feature")

    # Review outcome routing
    workflow.add_conditional_edges(
        "review_feature",
        should_merge_node,
        {
            "merge_to_main": "merge_to_main",
            "cleanup_retry": "cleanup_retry",
            "check_ready": "check_ready",
        }
    )

    # After merge or cleanup, check for more stories
    workflow.add_edge("merge_to_main", "check_ready")
    workflow.add_edge("cleanup_retry", "check_ready")

    return workflow


# ============================================================================
# Main Orchestrator Class
# ============================================================================

class InsuranceOrchestrator:
    """Main orchestrator for insurance homepage development."""

    def __init__(
        self,
        project_path: str,
        stories_path: str,
        graph_path: str,
        max_parallel: int = 2,
    ):
        self.project_path = Path(project_path)
        self.stories_path = Path(stories_path)
        self.graph_path = Path(graph_path)
        self.max_parallel = max_parallel

        # Build graph with checkpointing
        self.graph = build_orchestrator_graph()
        self.checkpointer = MemorySaver()
        self.app = self.graph.compile(checkpointer=self.checkpointer)

    def run_sync(self, story_ids: list[str] = None, thread_id: str = "main") -> OrchestratorState:
        """
        Run the orchestrator synchronously.

        Args:
            story_ids: Optional list of specific story IDs to process.
            thread_id: Checkpoint thread ID for persistence.
        """
        # Initialize state
        initial_state = OrchestratorState()

        # Load stories if paths provided
        if self.stories_path.exists():
            with open(self.stories_path) as f:
                data = json.load(f)
                for story_data in data.get("stories", []):
                    if story_ids and story_data["id"] not in story_ids:
                        continue
                    story = Story(
                        id=story_data["id"],
                        title=story_data["title"],
                        category=story_data["category"],
                        priority=Priority(story_data["priority"]),
                        as_a=story_data["asA"],
                        i_want=story_data["iWant"],
                        so_that=story_data["soThat"],
                        dependencies=story_data.get("dependencies", []),
                        acceptance_criteria=story_data.get("acceptanceCriteria", []),
                        notes=story_data.get("notes"),
                    )
                    initial_state.stories[story.id] = story

        if self.graph_path.exists():
            with open(self.graph_path) as f:
                data = json.load(f)
                initial_state.dependency_graph = DependencyGraph(
                    nodes=[DependencyNode(**n) for n in data.get("nodes", [])],
                    edges=[(e["from"], e["to"]) for e in data.get("edges", [])],
                    root_nodes=data.get("rootNodes", []),
                    category_colors=data.get("categoryColors", {}),
                )

        # Run the graph with checkpointing
        config = {"configurable": {"thread_id": thread_id}}

        final_state = None
        for state in self.app.stream(initial_state, config):
            final_state = state
            # Print logs as we go
            for log in state.processing_logs[-3:]:
                print(f"  {log}")

        return final_state or initial_state