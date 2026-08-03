"""
Builds a static dependency graph of the repo using Python's `ast` module:
for every test file, which source modules does it depend on (directly or
transitively)? This is the primary signal for test selection — it's exact
(no hallucination risk) and fast.

Approach:
  1. Walk the repo, build a module_path -> set(imported module paths) graph
     for ALL .py files (not just tests) by resolving import statements to
     file paths within the repo.
  2. For each test file, do a reverse BFS/DFS over changed files: does this
     test's transitive import closure include any changed file?

Limitations (why we still keep an LLM/embedding fallback in selector.py):
  - Doesn't catch dynamic imports (importlib.import_module with a computed
    string), fixtures loaded via pytest plugins/conftest magic, or
    non-import couplings (e.g. a test reads a config file that changed).
  - Doesn't catch app-level integration tests that don't import the
    changed module directly but exercise it via a running service.
"""

import ast
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ImportGraph:
    # module file path -> set of module file paths it imports (repo-relative, posix)
    edges: dict[str, set[str]] = field(default_factory=dict)
    # quick lookup: dotted module name -> file path, for resolving "import a.b.c"
    module_to_path: dict[str, str] = field(default_factory=dict)


def _path_to_module_name(repo_root: Path, py_file: Path) -> str:
    rel = py_file.relative_to(repo_root).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def build_import_graph(repo_root: str, test_dir: str = "tests", src_dirs: list[str] | None = None) -> ImportGraph:
    root = Path(repo_root)
    graph = ImportGraph()

    py_files = [p for p in root.rglob("*.py") if ".git" not in p.parts and "venv" not in p.parts]

    for f in py_files:
        rel_posix = f.relative_to(root).as_posix()
        graph.module_to_path[_path_to_module_name(root, f)] = rel_posix
        graph.edges.setdefault(rel_posix, set())

    for f in py_files:
        rel_posix = f.relative_to(root).as_posix()
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        except (SyntaxError, UnicodeDecodeError):
            continue

        for node in ast.walk(tree):
            imported_names: list[str] = []
            if isinstance(node, ast.Import):
                imported_names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                # Handles `from a.b import c` -> module "a.b"; relative imports
                # (node.level > 0) are approximated by resolving against the
                # current file's package, which covers the common case.
                if node.level and node.level > 0:
                    pkg_parts = rel_posix.split("/")[:-node.level]
                    prefix = ".".join(pkg_parts)
                    imported_names.append(f"{prefix}.{node.module}" if prefix else node.module)
                else:
                    imported_names.append(node.module)

            for name in imported_names:
                # Try progressively shorter prefixes ("a.b.c" -> "a.b" -> "a")
                # since we may have imported a symbol, not a submodule.
                candidate_parts = name.split(".")
                while candidate_parts:
                    candidate = ".".join(candidate_parts)
                    if candidate in graph.module_to_path:
                        graph.edges[rel_posix].add(graph.module_to_path[candidate])
                        break
                    candidate_parts.pop()

    return graph


def transitive_dependencies(graph: ImportGraph, start_file: str) -> set[str]:
    """All files (repo-relative) that `start_file` depends on, directly or transitively."""
    visited: set[str] = set()
    stack = [start_file]
    while stack:
        current = stack.pop()
        if current in visited:
            continue
        visited.add(current)
        for dep in graph.edges.get(current, ()):
            if dep not in visited:
                stack.append(dep)
    visited.discard(start_file)
    return visited
