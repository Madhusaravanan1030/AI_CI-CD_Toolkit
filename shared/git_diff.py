"""
Shared diff-parsing utilities. Both the review bot and the test selector
need to know "what changed" — this module is the single source of truth
for that, so behavior stays consistent between them.
"""

import re
import subprocess
from dataclasses import dataclass, field


@dataclass
class Hunk:
    """A single @@ ... @@ hunk within a file's diff."""
    start_line: int  # first line number in the new file this hunk touches
    added_lines: list[tuple[int, str]] = field(default_factory=list)  # (line_no, text)
    removed_lines: list[str] = field(default_factory=list)
    context: str = ""  # raw hunk text, useful as LLM context


@dataclass
class FileDiff:
    path: str
    is_new: bool = False
    is_deleted: bool = False
    hunks: list[Hunk] = field(default_factory=list)

    @property
    def added_line_numbers(self) -> list[int]:
        return [ln for hunk in self.hunks for ln, _ in hunk.added_lines]

    def unified_text(self) -> str:
        """Reconstructs a readable diff blob for this file, for LLM input."""
        return "\n".join(h.context for h in self.hunks)


HUNK_HEADER_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def get_changed_files(base_ref: str = "origin/main", head_ref: str = "HEAD") -> list[str]:
    """Returns paths of files changed between base_ref and head_ref."""
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}...{head_ref}"],
        capture_output=True, text=True, check=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def get_raw_diff(base_ref: str = "origin/main", head_ref: str = "HEAD") -> str:
    result = subprocess.run(
        ["git", "diff", f"{base_ref}...{head_ref}"],
        capture_output=True, text=True, check=True,
    )
    return result.stdout


def parse_unified_diff(diff_text: str) -> list[FileDiff]:
    """
    Parses `git diff` output into a list of FileDiff objects.
    Minimal, dependency-free unified-diff parser — good enough for
    feeding hunks to an LLM and for mapping added lines to line numbers
    for inline PR comments.
    """
    files: list[FileDiff] = []
    current: FileDiff | None = None
    current_hunk: Hunk | None = None
    new_line_cursor = 0

    for raw_line in diff_text.splitlines():
        if raw_line.startswith("diff --git"):
            if current:
                files.append(current)
            # "diff --git a/path b/path"
            parts = raw_line.split(" ")
            path = parts[-1][2:] if parts[-1].startswith("b/") else parts[-1]
            current = FileDiff(path=path)
            current_hunk = None
            continue

        if current is None:
            continue

        if raw_line.startswith("new file mode"):
            current.is_new = True
            continue
        if raw_line.startswith("deleted file mode"):
            current.is_deleted = True
            continue

        header_match = HUNK_HEADER_RE.match(raw_line)
        if header_match:
            new_line_cursor = int(header_match.group(1))
            current_hunk = Hunk(start_line=new_line_cursor, context=raw_line + "\n")
            current.hunks.append(current_hunk)
            continue

        if current_hunk is None:
            continue

        current_hunk.context += raw_line + "\n"

        if raw_line.startswith("+") and not raw_line.startswith("+++"):
            current_hunk.added_lines.append((new_line_cursor, raw_line[1:]))
            new_line_cursor += 1
        elif raw_line.startswith("-") and not raw_line.startswith("---"):
            current_hunk.removed_lines.append(raw_line[1:])
        elif not raw_line.startswith("\\"):
            new_line_cursor += 1

    if current:
        files.append(current)

    return files
