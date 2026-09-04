# tedsbot-triage-worker — conventions

- Every code file starts with two lines beginning `# ABOUTME: `.
- Strict TDD: failing test first, minimal code, green, refactor, commit.
- No mock mode in production code. Unit tests may mock HTTP with respx;
  integration tests use vcrpy cassettes; e2e tests are real and skip
  without `TEDSBOT_E2E=1`.
- Test output must be pristine. `filterwarnings = error` is on.
- Run tests with `uv run pytest -n auto`.
- Nothing project-specific in this repo. Example values are `example-org`,
  `example.atlassian.net`, `APP`.
- Never commit with `--no-verify`.
- Design spec: `docs/superpowers/specs/2026-09-03-tedsbot-triage-worker-design.md`.
