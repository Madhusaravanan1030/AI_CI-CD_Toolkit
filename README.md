# AI CI/CD Toolkit

Two GitHub Actions bots sharing a common diff-parsing core:

1. **AI Code Review Bot** (`code_review_bot/`) — posts inline PR review
   comments for bugs/security issues found in added lines. Filters to
   medium+ severity only, to avoid nitpick spam.
2. **Intelligent Test Selector** (`test_selector/`) — runs only the tests
   impacted by a PR's changes, using a static AST-based import graph
   (with an embedding-based semantic fallback for files not directly
   imported by any test). Falls back to the full suite whenever
   confidence is low.

## Setup

1. Copy this repo's contents into your project (or use it as a template).
2. Add a repo secret `OPENAI_API_KEY` (Settings → Secrets and variables → Actions).
   `GITHUB_TOKEN` is provided automatically by Actions — no setup needed.
3. Install deps locally for development:
   ```bash
   pip install -r requirements.txt
   ```
4. The two workflows (`.github/workflows/ai-code-review.yml` and
   `test-selection.yml`) trigger automatically on every PR open/update.

## How the test selector decides

```
changed files
     │
     ▼
matches a CORE_FILE_PATTERN?  ──yes──▶ run full suite
     │ no
     ▼
static import graph: any test whose transitive
import closure includes a changed file?  ──▶ select those tests
     │
     ▼
changed files still uncovered?  ──yes──▶ embed + cosine-similarity
     │                                    fallback against test files
     ▼ no
done
```

Run `pytest tests/ -v` to see this validated against a small fixture
repo in `fixtures/sample_repo/` — it asserts that changing an isolated
module selects only its direct test, and that changing a module with a
downstream dependent correctly pulls in the dependent's test too.

## Local dry-run

Both bots read `BASE_SHA`/`HEAD_SHA` env vars rather than being hardwired
to Actions, so you can run them locally against any two refs:

```bash
export BASE_SHA=main HEAD_SHA=my-branch
export OPENAI_API_KEY=sk-...
python -m test_selector.main          # prints selected tests
PR_NUMBER=123 GITHUB_TOKEN=ghp_... \
  python -m code_review_bot.main      # posts a real review — use a test PR!
```

## Known limitations (fair to call out)

- **Review bot**: only sees the diff, not the whole file/repo, so it can
  miss issues that only become visible with broader context (e.g. a
  duplicate helper already defined elsewhere).
- **Test selector**: the static graph doesn't follow dynamic imports
  (`importlib.import_module` with a computed string) or non-import
  couplings (e.g. a test reading a config file that changed but isn't
  imported). The semantic fallback + core-file safety valve mitigate
  this but don't eliminate it — treat "full suite" as the safe default
  whenever you're unsure, and consider running the full suite on a
  nightly schedule regardless of PR-time selection.
