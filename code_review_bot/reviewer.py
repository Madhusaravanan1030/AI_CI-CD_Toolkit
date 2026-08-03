"""
Core review logic: takes parsed file diffs, asks the LLM for findings
per file, and filters aggressively to keep signal-to-noise high.

The #1 failure mode of these bots is commenting on everything ("consider
adding a docstring" on a one-line fix). We fight that with:
  1. A severity threshold (only MEDIUM+ gets posted).
  2. Constraining the model to comment only on lines that were ADDED
     (never on unchanged context lines it happens to see).
  3. A max-findings-per-file cap.
"""

from dataclasses import dataclass
from typing import Literal

from shared.git_diff import FileDiff
from shared.llm_client import LLMClient

Severity = Literal["low", "medium", "high"]

SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2}
MIN_SEVERITY: Severity = "medium"
MAX_FINDINGS_PER_FILE = 5

SYSTEM_PROMPT = """You are a precise, senior code reviewer. You review only
the ADDED lines of a diff (lines starting with '+'), using surrounding
context to understand intent. You look for: bugs, security issues,
resource leaks, race conditions, and clearly incorrect logic.

You do NOT comment on: style/formatting, missing docstrings, naming
preferences, or anything that is subjective taste rather than a concrete
problem. If the diff has no real issues, return an empty findings list —
do not invent minor nitpicks to have something to say.

Respond with JSON only, matching this schema:
{
  "findings": [
    {
      "line": <int, must be one of the added line numbers you were given>,
      "severity": "low" | "medium" | "high",
      "message": "<one or two sentence explanation>"
    }
  ]
}
"""


@dataclass
class Finding:
    file: str
    line: int
    severity: Severity
    message: str


class Reviewer:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def review_file(self, file_diff: FileDiff) -> list[Finding]:
        if file_diff.is_deleted or not file_diff.hunks:
            return []

        added_lines = file_diff.added_line_numbers
        if not added_lines:
            return []

        user_prompt = (
            f"File: {file_diff.path}\n"
            f"Added line numbers you may comment on: {added_lines}\n\n"
            f"Diff:\n{file_diff.unified_text()}"
        )

        result = self.llm.structured_completion(SYSTEM_PROMPT, user_prompt)
        raw_findings = result.get("findings", [])

        findings = []
        added_set = set(added_lines)
        for rf in raw_findings:
            line = rf.get("line")
            severity = rf.get("severity", "low")
            if line not in added_set:
                continue  # guard against the model hallucinating a line number
            if SEVERITY_RANK.get(severity, 0) < SEVERITY_RANK[MIN_SEVERITY]:
                continue
            findings.append(Finding(
                file=file_diff.path,
                line=line,
                severity=severity,
                message=rf.get("message", ""),
            ))

        findings.sort(key=lambda f: SEVERITY_RANK[f.severity], reverse=True)
        return findings[:MAX_FINDINGS_PER_FILE]

    def review_files(self, file_diffs: list[FileDiff]) -> list[Finding]:
        all_findings = []
        for fd in file_diffs:
            all_findings.extend(self.review_file(fd))
        return all_findings
