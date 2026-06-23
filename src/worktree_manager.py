"""Git worktree manager for isolated feature development."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .models import WorktreeInfo


class GitWorktreeManager:
    """Manages git worktrees for parallel feature development."""

    def __init__(self, base_repo_path: str, worktrees_base: Optional[str] = None):
        self.base_repo = Path(base_repo_path)
        self.worktrees_base = Path(worktrees_base) if worktrees_base else self.base_repo.parent / "worktrees"
        self.worktrees_base.mkdir(parents=True, exist_ok=True)

    def create_worktree(self, story_id: str, story_title: str, base_branch: str = "main") -> WorktreeInfo:
        """
        Create a new git worktree for a story.

        Args:
            story_id: The user story ID (e.g., "US-01")
            story_title: Short title for the story
            base_branch: Branch to create worktree from

        Returns:
            WorktreeInfo with worktree details
        """
        # Create safe branch name
        branch_name = f"feature/{story_id}-{self._sanitize_name(story_title)}"
        worktree_name = f"{story_id.lower()}-{self._sanitize_name(story_title)}"
        worktree_path = self.worktrees_base / worktree_name

        # Check if worktree already exists
        if worktree_path.exists():
            # Check if it's a valid worktree
            if self.is_worktree(worktree_name):
                return self.get_worktree_info(worktree_name)
            else:
                # Clean up and recreate
                shutil.rmtree(worktree_path)

        try:
            # Create worktree
            result = subprocess.run(
                ["git", "worktree", "add", "-b", branch_name, str(worktree_path), f"origin/{base_branch}"],
                cwd=str(self.base_repo),
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                # If branch creation fails, try without -b flag
                result = subprocess.run(
                    ["git", "worktree", "add", str(worktree_path), f"origin/{base_branch}"],
                    cwd=str(self.base_repo),
                    capture_output=True,
                    text=True,
                )

                if result.returncode != 0:
                    raise RuntimeError(f"Failed to create worktree: {result.stderr}")

                branch_name = f"origin/{base_branch}"

            return WorktreeInfo(
                name=worktree_name,
                path=str(worktree_path),
                branch=branch_name,
                story_id=story_id,
                is_active=True,
            )

        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Git command failed: {e}")

    def remove_worktree(self, worktree_name: str) -> bool:
        """Remove a worktree."""
        try:
            worktree_path = self.worktrees_base / worktree_name

            # Remove the worktree (git worktree prune first, then remove)
            subprocess.run(
                ["git", "worktree", "remove", worktree_name, "--force"],
                cwd=str(self.base_repo),
                capture_output=True,
            )

            # Also remove the directory if it still exists
            if worktree_path.exists():
                shutil.rmtree(worktree_path)

            return True

        except subprocess.CalledProcessError:
            return False

    def is_worktree(self, worktree_name: str) -> bool:
        """Check if a worktree exists and is valid."""
        try:
            result = subprocess.run(
                ["git", "worktree", "list", "--porcelain"],
                cwd=str(self.base_repo),
                capture_output=True,
                text=True,
            )

            worktree_path = str(self.worktrees_base / worktree_name)
            return worktree_path in result.stdout

        except subprocess.CalledProcessError:
            return False

    def get_worktree_info(self, worktree_name: str) -> Optional[WorktreeInfo]:
        """Get information about a worktree."""
        try:
            result = subprocess.run(
                ["git", "worktree", "list", "--porcelain"],
                cwd=str(self.base_repo),
                capture_output=True,
                text=True,
            )

            worktree_path = str(self.worktrees_base / worktree_name)

            # Parse git worktree output
            lines = result.stdout.strip().split("\n")
            current_path = None
            current_branch = None
            is_worktree = False

            for line in lines:
                if line.startswith("worktree "):
                    current_path = line.replace("worktree ", "").strip()
                    is_worktree = current_path == worktree_path
                elif line.startswith("branch "):
                    current_branch = line.replace("branch ", "").strip()

                if is_worktree and current_path and current_branch:
                    # Extract story ID from branch name
                    story_id = ""
                    if "/" in current_branch:
                        parts = current_branch.split("/")
                        if parts[0] == "feature":
                            story_id = parts[1] if len(parts) > 1 else ""

                    return WorktreeInfo(
                        name=worktree_name,
                        path=current_path,
                        branch=current_branch,
                        story_id=story_id,
                        is_active=True,
                    )

            return None

        except subprocess.CalledProcessError:
            return None

    def list_worktrees(self) -> list[WorktreeInfo]:
        """List all managed worktrees."""
        worktrees = []

        for item in self.worktrees_base.iterdir():
            if item.is_dir():
                info = self.get_worktree_info(item.name)
                if info:
                    worktrees.append(info)

        return worktrees

    def merge_to_main(self, worktree_name: str, commit_message: Optional[str] = None) -> bool:
        """
        Merge a worktree's branch to main.

        Args:
            worktree_name: Name of the worktree to merge
            commit_message: Optional commit message

        Returns:
            True if merge was successful
        """
        try:
            worktree_info = self.get_worktree_info(worktree_name)
            if not worktree_info:
                return False

            # Get the commit message
            if not commit_message:
                commit_message = f"feat: Merge {worktree_info.story_id} - {worktree_name}"

            # First, push the branch
            subprocess.run(
                ["git", "push", "-u", "origin", worktree_info.branch],
                cwd=str(self.base_repo),
                capture_output=True,
            )

            # Merge to main
            result = subprocess.run(
                ["git", "checkout", "main"],
                cwd=str(self.base_repo),
                capture_output=True,
            )

            if result.returncode != 0:
                return False

            result = subprocess.run(
                ["git", "merge", worktree_info.branch, "-m", commit_message],
                cwd=str(self.base_repo),
                capture_output=True,
            )

            if result.returncode != 0:
                # Merge conflict - return False
                return False

            # Push main
            subprocess.run(
                ["git", "push", "origin", "main"],
                cwd=str(self.base_repo),
                capture_output=True,
            )

            return True

        except subprocess.CalledProcessError:
            return False

    def get_diff(self, worktree_name: str, base_branch: str = "main") -> str:
        """Get the diff between a worktree branch and main."""
        try:
            worktree_info = self.get_worktree_info(worktree_name)
            if not worktree_info:
                return ""

            result = subprocess.run(
                ["git", "diff", f"origin/{base_branch}...{worktree_info.branch}"],
                cwd=str(self.base_repo),
                capture_output=True,
                text=True,
            )

            return result.stdout

        except subprocess.CalledProcessError:
            return ""

    def _sanitize_name(self, name: str) -> str:
        """Convert a title to a safe directory/branch name."""
        # Remove special characters, keep alphanumeric and hyphens
        sanitized = "".join(c if c.isalnum() or c in " -_" else "" for c in name)
        # Replace spaces with hyphens and lowercase
        sanitized = sanitized.lower().replace(" ", "-")[:30]
        # Remove consecutive hyphens
        while "--" in sanitized:
            sanitized = sanitized.replace("--", "-")
        return sanitized.rstrip("-")


def init_insurance_project(project_path: str) -> bool:
    """
    Initialize a new insurance homepage project with React + Tailwind + Framer Motion.

    Args:
        project_path: Path where to initialize the project

    Returns:
        True if initialization was successful
    """
    project_dir = Path(project_path)
    project_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Initialize npm project
        subprocess.run(
            ["npm", "init", "-y"],
            cwd=str(project_dir),
            capture_output=True,
        )

        # Create package.json with dependencies
        package_json = project_dir / "package.json"
        package_json.write_text("""{
  "name": "insurance-homepage",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "framer-motion": "^11.0.0"
  },
  "devDependencies": {
    "@types/react": "^18.2.0",
    "@types/react-dom": "^18.2.0",
    "@vitejs/plugin-react": "^4.2.0",
    "autoprefixer": "^10.4.17",
    "postcss": "^8.4.35",
    "tailwindcss": "^3.4.1",
    "vite": "^5.1.0"
  }
}
""")

        # Create basic React files
        index_html = project_dir / "index.html"
        index_html.write_text("""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Insurance Company Home Page</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
""")

        # Create src directory structure
        src_dir = project_dir / "src"
        src_dir.mkdir(exist_ok=True)

        main_jsx = src_dir / "main.jsx"
        main_jsx.write_text("""import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
""")

        index_css = src_dir / "index.css"
        index_css.write_text("""@tailwind base;
@tailwind components;
@tailwind utilities;

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}
""")

        app_jsx = src_dir / "App.jsx"
        app_jsx.write_text("""import React from 'react'

function App() {
  return (
    <div className="min-h-screen bg-white">
      <header className="bg-blue-600 text-white p-4">
        <h1>Insurance Company</h1>
      </header>
      <main>
        <p>Welcome to our insurance homepage.</p>
      </main>
    </div>
  )
}

export default App
""")

        # Create config files
        tailwind_config = project_dir / "tailwind.config.js"
        tailwind_config.write_text("""/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {},
  },
  plugins: [],
}
""")

        postcss_config = project_dir / "postcss.config.js"
        postcss_config.write_text("""export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
}
""")

        vite_config = project_dir / "vite.config.js"
        vite_config.write_text("""import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
})
""")

        return True

    except Exception as e:
        print(f"Error initializing project: {e}")
        return False