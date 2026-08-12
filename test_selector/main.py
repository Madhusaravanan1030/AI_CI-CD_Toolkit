"""
Entry point run by the GitHub Actions workflow before the test step.

Prints the selected test paths to stdout (space-separated) and also
writes them to $GITHUB_OUTPUT as `test_paths`, so the workflow YAML can
do:

    - id: select
      run: python -m test_selector.main
    - run: pytest ${{ steps.select.outputs.test_paths }}

If run_full_suite is True, emits an empty string, which the workflow
step interprets as "run pytest with no path filter" (i.e. everything).
"""

import os
import sys

from shared.git_diff import get_changed_files
from shared.llm_client import LLMClient
from test_selector.selector import select_tests


def main() -> int:
    repo_root = os.environ.get("REPO_ROOT", ".")
    base_ref = os.environ.get("BASE_SHA", "origin/main")
    head_ref = os.environ.get("HEAD_SHA", "HEAD")

    changed_files = get_changed_files(base_ref, head_ref)
    if not changed_files:
        print("No changed files detected; nothing to select.")
        _write_output("test_paths", "")
        _write_output("run_full_suite", "false")
        return 0

    llm = None
    use_semantic_fallback = False
    if os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY"):
        llm = LLMClient()
        use_semantic_fallback = llm.supports_embeddings
        if not use_semantic_fallback:
            print("Note: current provider has no embeddings endpoint (e.g. Groq free "
                  "tier) — skipping semantic fallback. Static import-graph selection "
                  "still runs normally.")

    result = select_tests(
        repo_root, changed_files, llm=llm, use_semantic_fallback=use_semantic_fallback
    )

    print(result.reason)
    if result.run_full_suite:
        print("Decision: run full suite.")
        _write_output("test_paths", "")
        _write_output("run_full_suite", "true")
        return 0

    if not result.selected_tests:
        print("Decision: no tests matched; running full suite as a safety fallback.")
        _write_output("test_paths", "")
        _write_output("run_full_suite", "true")
        return 0

    paths = " ".join(sorted(result.selected_tests))
    print(f"Decision: run {len(result.selected_tests)} selected test file(s):")
    for t in sorted(result.selected_tests):
        print(f"  {t}")
    _write_output("test_paths", paths)
    _write_output("run_full_suite", "false")
    return 0


def _write_output(key: str, value: str) -> None:
    gh_output = os.environ.get("GITHUB_OUTPUT")
    if gh_output:
        with open(gh_output, "a") as f:
            f.write(f"{key}={value}\n")


if __name__ == "__main__":
    sys.exit(main())