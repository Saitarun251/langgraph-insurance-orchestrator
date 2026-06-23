"""Main entry point for the insurance homepage orchestrator."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from .orchestrator import InsuranceOrchestrator, OrchestratorState
from .models import StoryStatus, Priority

console = Console()


def print_banner():
    """Print the banner."""
    banner = """
╔══════════════════════════════════════════════════════════════════╗
║         Insurance Homepage LangGraph Orchestrator                ║
║                                                                  ║
║  Coordinates Claude Code CLI subprocesses with:                  ║
║  • Git worktrees for isolated development                        ║
║  • Dependency-aware story processing                             ║
║  • Automated code review and merge to main                       ║
╚══════════════════════════════════════════════════════════════════╝
"""
    console.print(banner, style="bold blue")


def print_status(state):
    """Print current orchestrator status."""
    table = Table(title="Story Status")
    table.add_column("Story ID", style="cyan")
    table.add_column("Title", style="white")
    table.add_column("Status", style="green")
    table.add_column("Priority", style="yellow")

    for story_id, story in state.stories.items():
        status_color = {
            StoryStatus.PENDING: "dim",
            StoryStatus.IN_PROGRESS: "yellow",
            StoryStatus.REVIEWING: "blue",
            StoryStatus.APPROVED: "green",
            StoryStatus.REJECTED: "red",
            StoryStatus.MERGED: "bold green",
        }.get(story.status, "white")

        table.add_row(
            story.id,
            story.title[:30] + "..." if len(story.title) > 30 else story.title,
            f"[{status_color}]{story.status.value}[/{status_color}]",
            story.priority.value,
        )

    console.print(table)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="LangGraph orchestrator for insurance homepage development"
    )
    parser.add_argument(
        "--project",
        type=str,
        default=None,
        help="Path to the insurance homepage project",
    )
    parser.add_argument(
        "--stories",
        type=str,
        default=None,
        help="Path to the stories JSON file",
    )
    parser.add_argument(
        "--graph",
        type=str,
        default=None,
        help="Path to the dependency graph JSON file",
    )
    parser.add_argument(
        "--stories-filter",
        type=str,
        nargs="+",
        default=None,
        help="Filter to specific story IDs (e.g., US-01 US-02)",
    )
    parser.add_argument(
        "--max-parallel",
        type=int,
        default=2,
        help="Maximum parallel worktrees (default: 2)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without executing",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all stories and their status",
    )

    args = parser.parse_args()

    # Default paths
    base_path = Path(__file__).parent.parent
    project_path = args.project or str(base_path / "insurance-homepage")
    stories_path = args.stories or str(base_path / "data" / "insurance-homepage-stories.json")
    graph_path = args.graph or str(base_path / "data" / "insurance-homepage-dependency-graph.json")

    print_banner()

    # Load stories for listing
    stories_data = {}
    if Path(stories_path).exists():
        with open(stories_path) as f:
            stories_data = json.load(f)

    if args.list:
        table = Table(title="User Stories")
        table.add_column("ID", style="cyan")
        table.add_column("Category", style="blue")
        table.add_column("Priority", style="yellow")
        table.add_column("Title", style="white")
        table.add_column("Deps", style="dim")

        for story in stories_data.get("stories", []):
            table.add_row(
                story["id"],
                story["category"],
                story["priority"],
                story["title"][:40] + "..." if len(story["title"]) > 40 else story["title"],
                ", ".join(story.get("dependencies", [])) or "-",
            )

        console.print(table)
        console.print(f"\nTotal: {len(stories_data.get('stories', []))} stories")
        return

    if args.dry_run:
        console.print("[yellow]DRY RUN MODE[/yellow]")
        console.print(f"\nProject path: {project_path}")
        console.print(f"Stories path: {stories_path}")
        console.print(f"Graph path: {graph_path}")

        if args.stories_filter:
            console.print(f"\nFiltered stories: {args.stories_filter}")

        console.print(f"\nMax parallel worktrees: {args.max_parallel}")
        console.print("\nStories to be processed:")
        for story in stories_data.get("stories", []):
            if not args.stories_filter or story["id"] in args.stories_filter:
                if story["priority"] != "Won't Have":
                    console.print(f"  • {story['id']}: {story['title']}")
        return

    # Run the orchestrator
    console.print(f"\n[green]Starting orchestrator...[/green]")
    console.print(f"Project: {project_path}")
    console.print(f"Stories: {len(stories_data.get('stories', []))}")

    orchestrator = InsuranceOrchestrator(
        project_path=project_path,
        stories_path=stories_path,
        graph_path=graph_path,
        max_parallel=args.max_parallel,
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Processing stories...", total=None)

        try:
            final_state = orchestrator.run_sync(story_ids=args.stories_filter)

            progress.update(task, completed=True)

            console.print("\n[bold green]✓ Orchestrator finished![/bold green]\n")
            print_status(final_state)

            # Summary
            console.print(f"\n[bold]Summary:[/bold]")
            console.print(f"  Completed: {len(final_state.completed_stories)}")
            console.print(f"  Failed: {len(final_state.failed_stories)}")

            if final_state.completed_stories:
                console.print(f"\n[green]Merged to main:[/green]")
                for story_id in final_state.completed_stories:
                    console.print(f"  ✓ {story_id}")

            if final_state.failed_stories:
                console.print(f"\n[red]Failed:[/red]")
                for story_id in final_state.failed_stories:
                    console.print(f"  ✗ {story_id}")

        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted by user[/yellow]")
            sys.exit(1)
        except Exception as e:
            console.print(f"\n[red]Error: {e}[/red]")
            sys.exit(1)


if __name__ == "__main__":
    main()