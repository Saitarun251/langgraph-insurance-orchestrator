"""Claude Code CLI subprocess wrapper for executing coding tasks."""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class ClaudeResult:
    """Result from Claude Code CLI execution."""
    success: bool
    stdout: str
    stderr: str
    return_code: int
    duration_seconds: float
    files_created: list[str]
    files_modified: list[str]


class ClaudeCodeCLI:
    """Wrapper for Claude Code CLI subprocess execution."""

    def __init__(
        self,
        project_path: str,
        claude_code_path: str = "claude",
        max_iterations: int = 10,
        timeout_seconds: int = 300,
    ):
        self.project_path = Path(project_path)
        self.claude_code_path = claude_code_path
        self.max_iterations = max_iterations
        self.timeout_seconds = timeout_seconds
        self._process: Optional[subprocess.Popen] = None

    async def execute_task(
        self,
        prompt: str,
        task_name: str,
        allow_write: bool = True,
        approval_mode: str = "manual",
    ) -> ClaudeResult:
        """
        Execute a coding task using Claude Code CLI.

        Args:
            prompt: The task prompt to send to Claude
            task_name: Name for logging purposes
            allow_write: Whether to allow file writes
            approval_mode: "auto", "manual", or "bypass"
        """
        import time
        start_time = time.time()

        # Create a prompt file for Claude Code
        prompt_file = self.project_path / f".claude_prompt_{task_name.replace(' ', '_')}.txt"
        prompt_file.write_text(prompt)

        try:
            # Build Claude Code command
            cmd = [
                self.claude_code_path,
                "--print",
                f"--max-turns={self.max_iterations}",
                f"--approval-mode={approval_mode}",
            ]

            if not allow_write:
                cmd.append("--no-read")

            # Change to project directory and run
            result = subprocess.run(
                cmd,
                input=prompt,
                cwd=str(self.project_path),
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )

            duration = time.time() - start_time

            # Parse created/modified files from output
            files_created, files_modified = self._parse_file_changes(result.stdout + result.stderr)

            return ClaudeResult(
                success=result.returncode == 0,
                stdout=result.stdout,
                stderr=result.stderr,
                return_code=result.returncode,
                duration_seconds=duration,
                files_created=files_created,
                files_modified=files_modified,
            )

        except subprocess.TimeoutExpired:
            duration = time.time() - start_time
            return ClaudeResult(
                success=False,
                stdout="",
                stderr=f"Task timed out after {self.timeout_seconds} seconds",
                return_code=-1,
                duration_seconds=duration,
                files_created=[],
                files_modified=[],
            )
        except FileNotFoundError:
            duration = time.time() - start_time
            return ClaudeResult(
                success=False,
                stdout="",
                stderr=f"Claude Code CLI not found at: {self.claude_code_path}",
                return_code=-2,
                duration_seconds=duration,
                files_created=[],
                files_modified=[],
            )
        finally:
            # Clean up prompt file
            if prompt_file.exists():
                prompt_file.unlink()

    def _parse_file_changes(self, output: str) -> tuple[list[str], list[str]]:
        """Parse file changes from Claude Code output."""
        created = []
        modified = []

        lines = output.split("\n")
        for line in lines:
            line = line.strip()
            if "Created file:" in line or "Wrote file:" in line:
                file_path = line.split(":", 1)[1].strip().strip("`")
                created.append(file_path)
            elif "Modified file:" in line or "Edited file:" in line:
                file_path = line.split(":", 1)[1].strip().strip("`")
                modified.append(file_path)

        return created, modified


class ClaudeCodeManager:
    """Manages multiple Claude Code CLI instances for parallel worktrees."""

    def __init__(self, base_path: str, claude_code_path: str = "claude"):
        self.base_path = Path(base_path)
        self.claude_code_path = claude_code_path
        self.instances: dict[str, ClaudeCodeCLI] = {}

    def get_instance(self, worktree_name: str) -> ClaudeCodeCLI:
        """Get or create a Claude Code CLI instance for a worktree."""
        if worktree_name not in self.instances:
            worktree_path = self.base_path / f"worktrees" / worktree_name
            self.instances[worktree_name] = ClaudeCodeCLI(
                project_path=str(worktree_path),
                claude_code_path=self.claude_code_path,
            )
        return self.instances[worktree_name]

    async def execute_in_worktree(
        self,
        worktree_name: str,
        prompt: str,
        task_name: str,
    ) -> ClaudeResult:
        """Execute a task in a specific worktree."""
        cli = self.get_instance(worktree_name)
        return await cli.execute_task(
            prompt=prompt,
            task_name=task_name,
            allow_write=True,
            approval_mode="bypass",  # Auto-approve for automation
        )

    def cleanup(self):
        """Clean up all CLI instances."""
        self.instances.clear()


async def demo_claude_code():
    """Demo function to test Claude Code CLI execution."""
    # Create a temp directory for testing
    with tempfile.TemporaryDirectory() as tmpdir:
        # Initialize a simple Node project
        subprocess.run(
            ["npm", "init", "-y"],
            cwd=tmpdir,
            capture_output=True,
        )

        cli = ClaudeCodeCLI(project_path=tmpdir)

        prompt = """Create a simple React component called HelloWorld that:
1. Displays "Hello, Insurance World!" heading
2. Has a button that toggles between showing/hiding a subtitle
3. Uses basic Tailwind CSS classes
4. Is exported as default
"""

        result = await cli.execute_task(
            prompt=prompt,
            task_name="hello_world",
        )

        print(f"Success: {result.success}")
        print(f"Duration: {result.duration_seconds:.2f}s")
        print(f"Files created: {result.files_created}")
        print(f"Output:\n{result.stdout[:500]}")


if __name__ == "__main__":
    asyncio.run(demo_claude_code())