import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from test_selector.import_graph import build_import_graph, transitive_dependencies
from test_selector.selector import select_tests

FIXTURE_REPO = str(Path(__file__).resolve().parent.parent / "fixtures" / "sample_repo")


def test_import_graph_resolves_direct_import():
    graph = build_import_graph(FIXTURE_REPO)
    deps = transitive_dependencies(graph, "tests/test_math_utils.py")
    assert "src/math_utils.py" in deps


def test_import_graph_resolves_transitive_import():
    # test_service.py imports src/service.py, which imports src/math_utils.py
    graph = build_import_graph(FIXTURE_REPO)
    deps = transitive_dependencies(graph, "tests/test_service.py")
    assert "src/service.py" in deps
    assert "src/math_utils.py" in deps  # transitive


def test_import_graph_no_false_positive():
    graph = build_import_graph(FIXTURE_REPO)
    deps = transitive_dependencies(graph, "tests/test_string_utils.py")
    assert "src/math_utils.py" not in deps


def test_select_tests_only_selects_impacted_tests():
    # Changing math_utils.py should select test_math_utils.py AND
    # test_service.py (transitive dep), but NOT test_string_utils.py.
    result = select_tests(FIXTURE_REPO, ["src/math_utils.py"], use_semantic_fallback=False)

    assert result.run_full_suite is False
    assert "tests/test_math_utils.py" in result.selected_tests
    assert "tests/test_service.py" in result.selected_tests
    assert "tests/test_string_utils.py" not in result.selected_tests


def test_select_tests_isolated_change():
    # Changing string_utils.py should select ONLY test_string_utils.py.
    result = select_tests(FIXTURE_REPO, ["src/string_utils.py"], use_semantic_fallback=False)

    assert result.selected_tests == {"tests/test_string_utils.py"}


def test_core_file_triggers_full_suite():
    result = select_tests(FIXTURE_REPO, ["conftest.py"], use_semantic_fallback=False)
    assert result.run_full_suite is True


def test_changed_test_file_is_always_included():
    result = select_tests(
        FIXTURE_REPO, ["tests/test_string_utils.py"], use_semantic_fallback=False
    )
    assert "tests/test_string_utils.py" in result.selected_tests
