"""Cross-platform utilities for the orchestrator."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional


def find_executable(name: str) -> Optional[str]:
    """
    Find an executable in PATH (cross-platform).

    Args:
        name: Executable name (e.g., "claude", "git", "npm")

    Returns:
        Full path to executable or None if not found
    """
    return shutil.which(name)


def is_claude_code_available() -> bool:
    """Check if Claude Code CLI is installed and in PATH."""
    return find_executable("claude") is not None


def get_claude_code_path() -> str:
    """
    Get Claude Code CLI path.

    Returns:
        Path to claude executable

    Raises:
        FileNotFoundError: If Claude Code is not installed
    """
    path = find_executable("claude")
    if not path:
        raise FileNotFoundError(
            "Claude Code CLI not found. Install with:\n"
            "  npm install -g @anthropic-ai/claude-code\n"
            "Or: npx @anthropic-ai/claude-code"
        )
    return path


def is_git_available() -> bool:
    """Check if git is installed."""
    return find_executable("git") is not None


def run_command(cmd: list[str], cwd: str | Path, timeout: int = 300) -> subprocess.CompletedProcess:
    """
    Run a command (cross-platform safe).

    Args:
        cmd: Command as list of strings
        cwd: Working directory
        timeout: Timeout in seconds

    Returns:
        CompletedProcess result

    Raises:
        subprocess.TimeoutExpired: If command times out
        subprocess.CalledProcessError: If command fails
    """
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def get_platform_info() -> dict:
    """Get platform information for debugging."""
    return {
        "system": sys.platform,  # 'darwin', 'linux', 'win32'
        "python_version": sys.version,
        "has_git": is_git_available(),
        "has_claude": is_claude_code_available(),
        "path_separator": os.path.sep,
    }


def ensure_directory(path: str | Path) -> Path:
    """Ensure a directory exists (cross-platform)."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_delete_directory(path: str | Path) -> bool:
    """
    Safely delete a directory (cross-platform safe).

    Uses shutil.rmtree but handles common errors gracefully.
    """
    try:
        path = Path(path)
        if path.exists():
            shutil.rmtree(path)
        return True
    except Exception:
        return False


def get_worktrees_directory(base_repo: str | Path) -> Path:
    r"""
    Get worktrees directory path (cross-platform).

    On Windows: <repo_parent>\worktrees\
    On Mac/Linux: <repo_parent>/worktrees/
    """
    base_repo = Path(base_repo)
    return base_repo.parent / "worktrees"


if __name__ == "__main__":
    # Demo
    print("Platform Info:")
    for key, value in get_platform_info().items():
        print(f"  {key}: {value}")

    print(f"\nGit available: {is_git_available()}")
    print(f"Claude Code available: {is_claude_code_available()}")

    if is_claude_code_available():
        print(f"Claude Code path: {get_claude_code_path()}")