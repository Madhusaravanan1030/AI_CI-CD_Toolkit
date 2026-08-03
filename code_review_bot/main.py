"""
Entry point run by the GitHub Actions workflow on pull_request events.

Expects these env vars (all set automatically by the workflow, see
.github/workflows/ai-code-review.yml):
  GITHUB_TOKEN        - provided by Actions
  GITHUB_REPOSITORY   - "owner/repo", provided by Actions
  PR_NUMBER           - pull request number
  BASE_SHA            - base ref of the PR (usually origin/main)
  HEAD_SHA            - head ref of the PR
  OPENAI_API_KEY      - your secret
"""

import os
import sys

from code_review_bot.github_client import GitHubClient
from code_review_bot.reviewer import Reviewer
from shared.git_diff import get_raw_diff, parse_unified_diff
from shared.llm_client import LLMClient

MAX_FILES = 40  # safety cap so a huge PR doesn't blow the LLM budget


def main() -> int:
    pr_number = int(os.environ["PR_NUMBER"])
    base_ref = os.environ.get("BASE_SHA", "origin/main")
    head_ref = os.environ.get("HEAD_SHA", "HEAD")

    diff_text = get_raw_diff(base_ref, head_ref)
    file_diffs = parse_unified_diff(diff_text)

    if not file_diffs:
        print("No changes detected in diff; skipping review.")
        return 0

    if len(file_diffs) > MAX_FILES:
        print(f"PR touches {len(file_diffs)} files (> {MAX_FILES}); "
              f"reviewing first {MAX_FILES} only.")
        file_diffs = file_diffs[:MAX_FILES]

    # Skip lockfiles, generated files, etc. — cheap noise reduction.
    SKIP_SUFFIXES = (".lock", ".min.js", ".svg", ".png", ".jpg", ".jpeg")
    file_diffs = [f for f in file_diffs if not f.path.endswith(SKIP_SUFFIXES)]

    llm = LLMClient(model=os.environ.get("REVIEW_MODEL", "gpt-4o"))
    reviewer = Reviewer(llm)
    findings = reviewer.review_files(file_diffs)

    print(f"Reviewed {len(file_diffs)} file(s), found {len(findings)} finding(s).")
    for f in findings:
        print(f"  {f.file}:{f.line} [{f.severity}] {f.message}")

    gh = GitHubClient()
    gh.post_review(pr_number, findings)
    return 0


if __name__ == "__main__":
    sys.exit(main())
