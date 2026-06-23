"""Code reviewer agent using Claude for automated code review."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import SecretStr

from .models import Story, StoryStatus


@dataclass
class ReviewResult:
    """Result from code review."""
    approved: bool
    score: float  # 0.0 to 1.0
    comments: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    overall_feedback: str = ""


class CodeReviewer:
    """Automated code reviewer using Claude for intelligent review."""

    def __init__(self, anthropic_api_key: Optional[str] = None):
        # Get API key from env or parameter
        import os
        api_key = anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY", "")

        self.llm = ChatAnthropic(
            model="claude-opus-4-20241107",
            anthropic_api_key=SecretStr(api_key) if api_key else None,
            temperature=0.3,
        )

    def review_code(
        self,
        story: Story,
        worktree_path: str,
        files_created: list[str],
        files_modified: list[str],
    ) -> ReviewResult:
        """
        Review code for a story implementation.

        Args:
            story: The story being reviewed
            worktree_path: Path to the worktree with the implementation
            files_created: List of files created by the implementation
            files_modified: List of files modified by the implementation

        Returns:
            ReviewResult with approval decision
        """
        # Collect code to review
        code_snippets = self._collect_code(worktree_path, files_created, files_modified)

        if not code_snippets:
            return ReviewResult(
                approved=False,
                score=0.0,
                issues=["No code files found to review"],
                overall_feedback="No implementation found in the worktree.",
            )

        # Build review prompt
        prompt = self._build_review_prompt(story, code_snippets)

        try:
            # Get LLM response
            response = self.llm.invoke([
                SystemMessage(content="You are an expert code reviewer for a React/Tailwind/Framer Motion insurance homepage project. Review the code carefully and provide detailed feedback."),
                HumanMessage(content=prompt),
            ])

            # Parse response
            return self._parse_review_response(response.content, story)

        except Exception as e:
            return ReviewResult(
                approved=False,
                score=0.0,
                issues=[f"Review failed: {str(e)}"],
                overall_feedback="Code review encountered an error.",
            )

    def _collect_code(
        self,
        worktree_path: str,
        files_created: list[str],
        files_modified: list[str],
    ) -> dict[str, str]:
        """Collect code from files."""
        code = {}
        all_files = list(set(files_created + files_modified))

        for file_path in all_files:
            full_path = Path(worktree_path) / file_path
            if full_path.exists() and full_path.suffix in [".js", ".jsx", ".ts", ".tsx", ".css"]:
                try:
                    content = full_path.read_text(encoding="utf-8")
                    # Limit file size
                    if len(content) > 5000:
                        content = content[:5000] + "\n... (truncated)"
                    code[str(file_path)] = content
                except Exception:
                    pass

        return code

    def _build_review_prompt(self, story: Story, code_snippets: dict[str, str]) -> str:
        """Build the review prompt."""
        files_content = "\n\n".join([
            f"## {path}\n```\n{content}\n```"
            for path, content in code_snippets.items()
        ])

        acceptance = "\n".join([f"- {c}" for c in story.acceptance_criteria])

        return f"""## Code Review Request

### Story: {story.id} - {story.title}
**As a**: {story.as_a}
**I want**: {story.i_want}
**So that**: {story.so_that}

### Acceptance Criteria
{acceptance}

### Implementation Files
{files_content}

## Review Task
Analyze the implementation against the acceptance criteria. Consider:
1. **Functionality**: Does the code meet all acceptance criteria?
2. **Code Quality**: Is the code clean, well-organized, and maintainable?
3. **Tailwind/CSS**: Are Tailwind classes used correctly?
4. **Accessibility**: Does the code have proper ARIA labels, semantic HTML?
5. **Responsive Design**: Does it handle mobile/tablet/desktop?
6. **Framer Motion**: Are animations smooth and appropriate?

Respond with:
1. APPROVED or REJECTED
2. Score (0.0 to 1.0)
3. Issues found (if any)
4. Suggestions for improvement (if any)
5. Overall feedback

Format your response as JSON:
```json
{{
  "decision": "APPROVED" or "REJECTED",
  "score": 0.0-1.0,
  "issues": ["list of issues"],
  "suggestions": ["list of suggestions"],
  "feedback": "overall feedback"
}}
```"""

    def _parse_review_response(self, response: str, story: Story) -> ReviewResult:
        """Parse the LLM review response."""
        import json
        import re

        # Try to extract JSON from response
        json_match = re.search(r'\{[^{}]*"decision"[^{}]*\}', response, re.DOTALL)
        if not json_match:
            # Try broader JSON match
            json_match = re.search(r'\{.*\}', response, re.DOTALL)

        if json_match:
            try:
                data = json.loads(json_match.group())
                return ReviewResult(
                    approved=data.get("decision", "").upper() == "APPROVED",
                    score=float(data.get("score", 0.0)),
                    issues=data.get("issues", []),
                    suggestions=data.get("suggestions", []),
                    overall_feedback=data.get("feedback", ""),
                )
            except json.JSONDecodeError:
                pass

        # Fallback: check for APPROVED/REJECTED in text
        if "APPROVED" in response.upper() and "REJECTED" not in response.upper():
            approved = True
            score = 0.8
        elif "REJECTED" in response.upper():
            approved = False
            score = 0.3
        else:
            approved = False
            score = 0.5

        # Extract score if present
        score_match = re.search(r'score[:\s]*(\d+\.?\d*)', response, re.IGNORECASE)
        if score_match:
            score = float(score_match.group(1))
            if score > 1:
                score = score / 10  # Normalize if 0-10 scale

        return ReviewResult(
            approved=approved,
            score=score,
            overall_feedback=response[:500],
        )

    def review_with_linter(self, worktree_path: str) -> tuple[bool, list[str]]:
        """
        Run linting checks on the worktree.

        Returns:
            Tuple of (passed, list of errors)
        """
        errors = []

        try:
            # Check if npm dependencies are installed
            node_modules = Path(worktree_path) / "node_modules"
            if not node_modules.exists():
                result = subprocess.run(
                    ["npm", "install"],
                    cwd=worktree_path,
                    capture_output=True,
                    text=True,
                )
                if result.returncode != 0:
                    errors.append(f"npm install failed: {result.stderr}")

            # Run ESLint if available
            package_json = Path(worktree_path) / "package.json"
            if package_json.exists():
                content = package_json.read_text()
                if "eslint" in content:
                    result = subprocess.run(
                        ["npx", "eslint", "src/", "--ext", ".jsx,.js"],
                        cwd=worktree_path,
                        capture_output=True,
                        text=True,
                    )
                    if result.returncode != 0:
                        errors.append(f"Linting errors:\n{result.stdout}")

            # Check TypeScript if available
            if (Path(worktree_path) / "tsconfig.json").exists():
                result = subprocess.run(
                    ["npx", "tsc", "--noEmit"],
                    cwd=worktree_path,
                    capture_output=True,
                    text=True,
                )
                if result.returncode != 0:
                    errors.append(f"TypeScript errors:\n{result.stdout}")

        except Exception as e:
            errors.append(f"Linter check failed: {str(e)}")

        return len(errors) == 0, errors