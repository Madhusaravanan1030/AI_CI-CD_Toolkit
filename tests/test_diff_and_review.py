import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.git_diff import parse_unified_diff
from code_review_bot.reviewer import Reviewer

SAMPLE_DIFF = """diff --git a/src/math_utils.py b/src/math_utils.py
index 1234567..89abcde 100644
--- a/src/math_utils.py
+++ b/src/math_utils.py
@@ -1,5 +1,8 @@
 def add(a, b):
     return a + b

+def divide(a, b):
+    return a / b
+
 def subtract(a, b):
     return a - b
"""

NEW_FILE_DIFF = """diff --git a/src/new_module.py b/src/new_module.py
new file mode 100644
index 0000000..1234567
--- /dev/null
+++ b/src/new_module.py
@@ -0,0 +1,2 @@
+def greet(name):
+    return f"hello {name}"
"""


def test_parse_unified_diff_extracts_file_path():
    files = parse_unified_diff(SAMPLE_DIFF)
    assert len(files) == 1
    assert files[0].path == "src/math_utils.py"


def test_parse_unified_diff_extracts_added_lines():
    files = parse_unified_diff(SAMPLE_DIFF)
    added = files[0].added_line_numbers
    # The two new lines (def divide / return a/b) should be at lines 4 and 5
    assert 4 in added
    assert 5 in added
    assert len(added) == 3  # includes the blank line after


def test_parse_unified_diff_detects_new_file():
    files = parse_unified_diff(NEW_FILE_DIFF)
    assert files[0].is_new is True
    assert files[0].path == "src/new_module.py"


class FakeLLM:
    """Stand-in for LLMClient so we can test filtering logic without an API call."""
    def __init__(self, response):
        self.response = response

    def structured_completion(self, system_prompt, user_prompt):
        return self.response


def test_reviewer_filters_low_severity_findings():
    files = parse_unified_diff(SAMPLE_DIFF)
    fake_response = {
        "findings": [
            {"line": 4, "severity": "low", "message": "minor style nit"},
            {"line": 5, "severity": "high", "message": "division by zero not handled"},
        ]
    }
    reviewer = Reviewer(FakeLLM(fake_response))
    findings = reviewer.review_file(files[0])

    assert len(findings) == 1
    assert findings[0].severity == "high"
    assert findings[0].line == 5


def test_reviewer_rejects_hallucinated_line_numbers():
    files = parse_unified_diff(SAMPLE_DIFF)
    fake_response = {
        "findings": [
            {"line": 999, "severity": "high", "message": "line that doesn't exist in diff"},
        ]
    }
    reviewer = Reviewer(FakeLLM(fake_response))
    findings = reviewer.review_file(files[0])

    assert len(findings) == 0


def test_reviewer_caps_findings_per_file():
    files = parse_unified_diff(SAMPLE_DIFF)
    fake_response = {
        "findings": [
            {"line": 4, "severity": "high", "message": f"issue {i}"} for i in range(10)
        ]
    }
    reviewer = Reviewer(FakeLLM(fake_response))
    findings = reviewer.review_file(files[0])

    assert len(findings) == 5  # MAX_FINDINGS_PER_FILE
