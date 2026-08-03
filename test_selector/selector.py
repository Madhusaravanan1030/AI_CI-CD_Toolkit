"""
Given a set of changed files, decides which tests to run.

Strategy:
  1. Static pass (cheap, exact): for each test file, compute its
     transitive import closure via import_graph. If it includes any
     changed file, select that test.
  2. Semantic fallback (LLM embeddings): for changed files that aren't
     imported by any test at all (e.g. config/data files, or files only
     reached via dynamic imports), embed the changed file's content and
     each test file's content, and select tests above a similarity
     threshold. This catches cases the static graph misses, at the cost
     of being fuzzier.
  3. Safety valve: if a changed file matches CORE_FILE_PATTERNS (conftest,
     shared config, CI files, requirements), skip selection entirely and
     signal "run the full suite" — too risky to guess narrowly here.
"""

import fnmatch
from dataclasses import dataclass
from pathlib import Path

from shared.llm_client import LLMClient
from test_selector.import_graph import ImportGraph, build_import_graph, transitive_dependencies

CORE_FILE_PATTERNS = [
    "*/conftest.py", "conftest.py",
    "requirements*.txt", "pyproject.toml", "setup.py", "setup.cfg",
    "*.github/workflows/*",
    "*/settings.py", "*/config.py",
]

SIMILARITY_THRESHOLD = 0.55


@dataclass
class SelectionResult:
    run_full_suite: bool
    selected_tests: set[str]
    reason: str


def _matches_core_pattern(path: str) -> bool:
    return any(fnmatch.fnmatch(path, pat) for pat in CORE_FILE_PATTERNS)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


def select_tests(
    repo_root: str,
    changed_files: list[str],
    llm: LLMClient | None = None,
    use_semantic_fallback: bool = True,
) -> SelectionResult:
    for cf in changed_files:
        if _matches_core_pattern(cf):
            return SelectionResult(
                run_full_suite=True,
                selected_tests=set(),
                reason=f"Core/config file changed ({cf}); running full suite for safety.",
            )

    graph: ImportGraph = build_import_graph(repo_root)
    all_test_files = [f for f in graph.edges if _is_test_file(f)]

    selected: set[str] = set()
    changed_set = set(changed_files)

    for test_file in all_test_files:
        deps = transitive_dependencies(graph, test_file)
        if deps & changed_set:
            selected.add(test_file)

    covered_changed = {
        cf for cf in changed_set
        if any(cf in transitive_dependencies(graph, t) for t in selected)
    }
    uncovered_changed = changed_set - covered_changed - set(all_test_files)
    # Changed test files themselves should always run.
    selected |= {cf for cf in changed_set if cf in all_test_files}

    if uncovered_changed and use_semantic_fallback and llm is not None:
        semantic_matches = _semantic_fallback(repo_root, uncovered_changed, all_test_files, llm)
        selected |= semantic_matches

    reason = (
        f"Static import analysis matched {len(selected)} test file(s) "
        f"to {len(changed_set)} changed file(s)."
    )
    if uncovered_changed:
        reason += f" {len(uncovered_changed)} changed file(s) had no direct test importer."

    return SelectionResult(run_full_suite=False, selected_tests=selected, reason=reason)


def _is_test_file(path: str) -> bool:
    name = Path(path).name
    return name.startswith("test_") or name.endswith("_test.py")


def _semantic_fallback(
    repo_root: str, uncovered_files: set[str], all_test_files: list[str], llm: LLMClient
) -> set[str]:
    root = Path(repo_root)
    changed_texts, changed_paths = [], []
    for cf in uncovered_files:
        p = root / cf
        if p.exists() and p.suffix in (".py", ".json", ".yaml", ".yml", ".toml"):
            changed_texts.append(p.read_text(encoding="utf-8", errors="ignore")[:4000])
            changed_paths.append(cf)

    if not changed_texts or not all_test_files:
        return set()

    test_texts = []
    for t in all_test_files:
        p = root / t
        test_texts.append(p.read_text(encoding="utf-8", errors="ignore")[:4000] if p.exists() else "")

    changed_embeddings = llm.embed(changed_texts)
    test_embeddings = llm.embed(test_texts)

    matches: set[str] = set()
    for ce in changed_embeddings:
        for test_path, te in zip(all_test_files, test_embeddings):
            if _cosine(ce, te) >= SIMILARITY_THRESHOLD:
                matches.add(test_path)
    return matches
