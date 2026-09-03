# tedsbot-triage-worker — design

Date: 2026-09-03
Status: approved design, pending implementation plan

## Mission

Run an autonomous bug-triage and fix worker on the Claude credentials you
already have. Point it at a checkout, an error source, and a ticketing
system; it root-causes production errors and team-reported bugs into
tickets a human can approve, and implements approved fixes as draft pull
requests. Humans stay in the loop at exactly two places: approving a fix,
and reviewing the pull request.

## Guiding principles

1. **Bring your own credentials.** The worker runs on an Anthropic API key
   or, for your own subscription, a Claude Code OAuth token. It never
   brokers login for anyone.
2. **Roles, not brands.** Code and prompts talk about the *error source*,
   the *ticketing system*, the *log store*, and the *notifier*. Providers
   (Sentry, Jira, Grafana, Slack) fill those roles behind a small
   interface. Adding a provider is one module.
3. **Determinism where it matters.** Polling, dedupe, gates, summaries,
   and notifications are plain Python and behave identically every run.
   Exploration, analysis, and writing are the agent's job.
4. **Honesty over confidence.** The agent must say "insufficient context"
   rather than invent a root cause. Every claim cites evidence.
5. **Human gates are hard gates.** Triage never edits code. Fix only runs
   on tickets a human moved to the approved status, only opens draft PRs,
   and never moves a ticket past code review.
6. **Knowledge lives in files, not in prompts.** Provider gotchas ship with
   providers, triage methodology ships with the worker, and team-specific
   facts live in a directory the consumer owns.
7. **Nothing project-specific in the public repo.** Example config and
   shipped knowledge use placeholders.

## Non-goals for version one

- Webhook receiver. Intake is polling.
- Cloning the target repo. The worker is handed an existing checkout.
- Multiple concurrent worker instances. State is derived from the
  ticketing system; two instances would double-launch. Run one.
- A mock or dry-run mode. Tests hit real services (recorded with VCRpy
  where HTTP) or are skipped when credentials are absent.

## Runtime shape

One Python package, `tedsbot`, one CLI, four subcommands:

```
tedsbot check
tedsbot triage sentry <issue-id-or-url>
tedsbot triage ticket <KEY>
tedsbot fix <KEY>
tedsbot worker [--once]
```

- `check` validates config, spawns each configured MCP server and confirms
  it connects, checks `gh auth status`, checks the checkout exists and is a
  git repo, and confirms the configured ticket statuses exist. Exit code
  non-zero on any failure. This is the setup guide's verification step.
- `triage sentry` and `triage ticket` run one analysis and land the result
  in the ticketing system.
- `fix` implements one approved ticket as a draft PR.
- `worker` loops: poll, launch, sleep. `--once` runs a single cycle and
  exits so cron or a scheduled workflow can drive it.

Every run writes a structured summary and posts to the notifier from
Python after the agent returns, so a crashed or truncated agent run still
produces a notification.

### The checkout

Config names the path of an existing checkout of the target repository.
Triage reads code and git history there. Fix creates a branch, commits,
and pushes there. The worker refuses to start a fix run unless the checkout
is clean and on the base branch. It never touches any other directory.

### Authentication

| Need | Mechanism |
|---|---|
| Claude | `ANTHROPIC_API_KEY` (documented primary), or `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token` for your own subscription. Both pass through to the Agent SDK. The README quotes Anthropic's policy line on third-party use of claude.ai login so consumers make their own call. |
| GitHub | The `gh` CLI. `gh auth login` (user OAuth, device flow) or `GH_TOKEN` in the environment (PAT or GitHub App installation token). The worker does not care which. |
| Sentry | `SENTRY_AUTH_TOKEN`, referenced from config. |
| Atlassian | `ATLASSIAN_API_TOKEN`, referenced from config. |
| Grafana | `GRAFANA_SERVICE_ACCOUNT_TOKEN`, referenced from config. |
| Slack | Incoming-webhook URL, referenced from config. |

Secrets never appear in the YAML; config values use `${VAR}` expansion.

## Repository layout

```
tedsbot-triage-worker/
  pyproject.toml              uv-managed, Python >=3.12, claude-agent-sdk
  README.md                   mission, principles, setup guide, extension guide
  tedsbot.example.yaml        annotated config with placeholder values
  src/tedsbot/
    __init__.py
    cli.py                    argparse entry point, subcommand dispatch
    config.py                 pydantic models, YAML load, ${VAR} expansion
    runner.py                 build ClaudeAgentOptions, run a prompt, collect summary
    summary.py                RunSummary model + parse/fallback
    knowledge.py              assemble the three knowledge tiers into prompt text
    notify.py                 Slack webhook: post-run sink + in-process SDK tool
    gates.py                  fix preconditions (checkout, status, open PR)
    prompts/
      triage_sentry.md.j2
      triage_ticket.md.j2
      fix.md.j2
    providers/
      base.py                 ErrorSource, Ticketing, LogStore, Notifier protocols
      sentry.py
      jira.py
      grafana.py
      slack.py
    worker.py                 the poll/launch/sleep loop
  knowledge/                  worker-shipped methodology (markdown)
    triage-method.md
    recommendation-tiers.md
    replication-steps.md
  src/tedsbot/providers/knowledge/
    jira.md                   ADF skeleton, transition rules, field conventions
    sentry.md                 org slug, environment case, search gotchas
    grafana.md                LogQL/PromQL tool notes
  tests/
    unit/
    integration/              VCRpy cassettes for Sentry and Jira HTTP
    e2e/                      real runs, skipped without credentials
  action/
    action.yml                composite GitHub Action wrapper (milestone two)
  docs/superpowers/specs/     this document
```

Every code file starts with two `ABOUTME:` comment lines.

## Configuration

One YAML file. Top-level keys are roles. Each role has a `kind` selecting
the provider. Provider-specific keys live under the role.

```yaml
repo:
  path: /srv/checkouts/example-app
  base_branch: main
  github: example-org/example-app

errors:
  kind: sentry
  org: example-org
  project_id: "1234567890"
  region_url: https://us.sentry.io
  environment: production          # case-sensitive in Sentry
  token: ${SENTRY_AUTH_TOKEN}
  poll:
    new_error:   { first_seen: -30m, min_times_seen: 3 }
    escalating:  { enabled: true }
    performance: { enabled: true, min_times_seen: 10 }
    chronic:     { enabled: true, min_times_seen: 3 }
    levels: [error, fatal]
    stats_period: 14d
    max_issues_per_cycle: 5

tickets:
  kind: jira
  url: https://example.atlassian.net
  cloud_id: 00000000-0000-0000-0000-000000000000
  project: APP
  token: ${ATLASSIAN_API_TOKEN}
  bug_issue_type_id: "10009"
  fields:
    qa_notes: customfield_10075
    qa_instructions: customfield_10073
  statuses:
    intake: To Triage
    triage_target: Dev Team Review
    fix_approved: Approved For Fix
    in_progress: In Progress
    code_review: Code Review
  labels:
    from_errors: sentry-triage
    insufficient_repro: insufficient-repro

logs:                              # optional
  kind: grafana
  url: https://grafana.example.com
  token: ${GRAFANA_SERVICE_ACCOUNT_TOKEN}

notify:
  kind: slack_webhook
  url: ${SLACK_WEBHOOK_URL}

agent:
  model: claude-opus-5
  max_turns:
    triage: 60
    fix: 150
  knowledge_dir: ./docs/triage      # consumer-supplied knowledge
  knowledge_size_warn_kb: 64

worker:
  interval_seconds: 900
  branch_prefix: tedsbot/
```

Validation happens at load through pydantic. Unknown `kind`, missing env
var, missing checkout, or unknown status name fails before any agent run.

## Provider model

`providers/base.py` defines four protocols. A provider implements the one
for its role.

```python
class ErrorSource(Protocol):
    def mcp_server(self) -> tuple[str, dict]: ...      # name, SDK server config
    def allowed_tools(self) -> list[str]: ...
    def prompt_facts(self) -> dict[str, str]: ...
    def knowledge(self) -> str: ...                     # provider-shipped markdown
    def poll(self) -> list[ErrorCandidate]: ...        # deterministic passes
    def already_ticketed(self, short_id: str, tickets: "Ticketing") -> bool: ...

class Ticketing(Protocol):
    def mcp_server(self) -> tuple[str, dict]: ...
    def allowed_tools(self) -> list[str]: ...
    def prompt_facts(self) -> dict[str, str]: ...
    def knowledge(self) -> str: ...
    def untriaged_bugs(self) -> list[TicketRef]: ...
    def approved_for_fix(self) -> list[TicketRef]: ...
    def status_of(self, key: str) -> str: ...
    def search_text(self, text: str) -> list[TicketRef]: ...
    def comment(self, key: str, body: str) -> None: ...

class LogStore(Protocol):
    def mcp_server(self) -> tuple[str, dict]: ...
    def allowed_tools(self) -> list[str]: ...
    def prompt_facts(self) -> dict[str, str]: ...
    def knowledge(self) -> str: ...

class Notifier(Protocol):
    def post(self, summary: RunSummary) -> None: ...
    def sdk_tool(self): ...                             # in-process tool for mid-run posts
```

Provider implementations for version one:

- **sentry** — MCP: `npx -y @sentry/mcp-server@latest --organization-slug=<org>`
  with `SENTRY_ACCESS_TOKEN`. Poll: the four passes ported from the
  existing poller (new-error, escalating, performance with per-issue
  environment check, chronic), deduped in priority order, capped.
- **jira** — MCP: `uvx mcp-atlassian` with `JIRA_URL`,
  `ATLASSIAN_OAUTH_CLOUD_ID`, `ATLASSIAN_OAUTH_ACCESS_TOKEN`. Deterministic
  operations via the Jira REST API: JQL for intake and approved statuses,
  text search for dedupe, status read, comment write.
- **grafana** — MCP: `uvx mcp-grafana` with `GRAFANA_URL` and
  `GRAFANA_SERVICE_ACCOUNT_TOKEN`. Exposes Loki, Prometheus, alerting, and
  incident tools. No deterministic operations in version one.
- **slack_webhook** — post-run message from the summary; in-process SDK
  tool `notify_slack(text)` registered through `create_sdk_mcp_server` so a
  prompt can post mid-run when it wants to.

The runner asks each configured provider for its MCP server and allowed
tools, merges them into `ClaudeAgentOptions`, and passes the union of
`prompt_facts` into the prompt template. Providers are discovered by a
registry keyed on `kind`.

## Knowledge

Three tiers, all markdown, concatenated in this order into the system
prompt append:

1. Provider-shipped (`providers/knowledge/*.md`), one section per
   configured provider.
2. Worker-shipped methodology (`knowledge/*.md`): the triage method,
   recommendation tiers, replication-step conventions, dedupe branches.
3. Consumer-supplied (`agent.knowledge_dir`): every `*.md` file, sorted by
   name, with a heading naming the file. Empty or missing directory is
   allowed and logged.

The runner warns when the assembled block exceeds
`knowledge_size_warn_kb`. The system prompt is the `claude_code` preset
with `append` set to this block plus the run-type instructions, and
`exclude_dynamic_sections: true` so the prefix is byte-identical across
runs and prompt caching applies.

The target repository's own `CLAUDE.md` (root or `.claude/CLAUDE.md`) is
read by the runner and appended as a fourth section for fix runs. This is
how the fix stage inherits the consumer's coding conventions. The runner
sets `setting_sources=[]` so nothing else from the checkout or from
`~/.claude` (hooks, `.mcp.json`, skills, memory) is auto-loaded; the only
MCP servers in a run are the ones the runner passes.

## Prompts

Jinja templates rendered with `prompt_facts` and run inputs. Content is
the current MartialQA prompts with every project-specific constant
replaced by a template variable.

- `triage_sentry` — fetch error, read code, check recent history,
  reconcile timeline (pickaxe), dedupe (open match / Won't Do / Done
  regression / none), write analysis, create Bug, populate QA notes,
  transition to `triage_target`, write summary.
- `triage_ticket` — read ticket, quality gate (comment + label
  `insufficient_repro` + stop), error-source cross-check, analyse, comment
  analysis, populate QA notes, transition to `triage_target` (never
  backwards), write summary.
- `fix` — read ticket and comments, idempotency gate (open PR), decision
  gate (🟡/🔴 or unresolved design choice → comment and stop), transition
  to `in_progress`, branch, implement smallest change, write tests (cannot
  run them; say so), commit, push, `gh pr create --draft`, populate QA
  instructions, comment PR link, transition to `code_review` matching on
  target status name, write summary.

Recommendation tiers are fixed across providers:
🟢 low-risk fix, 🟡 needs review, ⚪ not a code bug, 🔴 insufficient
context.

## Run contract

Each run gets a directory `~/.tedsbot/runs/<timestamp>-<kind>-<id>/`. The
agent's only write permission is `Write(<run_dir>/summary.json)`. Python
validates the file against:

```python
class RunSummary(BaseModel):
    kind: Literal["triage_sentry", "triage_ticket", "fix"]
    ticket: str | None
    ticket_url: str | None
    recommendation: Literal["🟢", "🟡", "⚪", "🔴"] | None
    status: str | None            # fix runs: "draft PR opened", "blocked", "already open"
    pr_url: str | None
    headline: str
    ok: bool
```

A missing or malformed file becomes `ok=False` with `headline` set from
the agent's final text (truncated). The notifier always receives a
summary. The full SDK message stream is written to `<run_dir>/transcript.jsonl`
for debugging.

## Tool allowlists

Triage runs: `Read`, `Grep`, `Glob`, `Write(<run_dir>/summary.json)`,
`Bash(git log:*)`, `Bash(git show:*)`, `Bash(git blame:*)`,
`Bash(git diff:*)`, plus each provider's MCP wildcard, plus the notifier
SDK tool. Permission mode `dontAsk`: anything not in the allow rules is
denied, because no human is present to answer a prompt.

Fix runs: `Read`, `Edit`, `Write`, `Grep`, `Glob`, `Bash(git:*)`,
`Bash(gh:*)`, ticketing MCP wildcard, notifier SDK tool. Same permission
mode.

Only the servers the runner passes are present; `setting_sources=[]`
keeps the checkout's `.mcp.json` and the host's `~/.claude` out of the
run (see Knowledge).

## Gates

Triage (enforced by tooling and prompt):
- No repository file may be modified; the allowlist makes this
  structural.
- Ticket never moves past `triage_target`. After the run Python re-reads
  the status and logs a warning, included in the notification, if it is
  further along.

Fix (enforced in Python before the agent starts):
- Checkout is clean (`git status --porcelain` empty) and on `base_branch`.
- Ticket status equals `fix_approved`.
- No open PR exists for `<branch_prefix><KEY>`.
- Failing any gate produces a summary with `ok=False` and a notification;
  the agent is not started.

Fix (enforced by prompt, as today):
- 🟡 without human direction in comments, or any unresolved design
  choice, stops with a comment.
- Draft PR only. Never past `code_review`.

## Worker loop

Each cycle:
1. `errors.poll()` → for each candidate not `already_ticketed`, run
   `triage sentry`. Cap at `max_issues_per_cycle`.
2. `tickets.untriaged_bugs()` → bugs in `intake` status with no comment
   authored by the worker → run `triage ticket`.
3. `tickets.approved_for_fix()` → run `fix` for each.
4. Sleep `interval_seconds` unless `--once`.

Runs inside a cycle are sequential. A failure in one run is notified and
does not stop the cycle. The loop catches provider HTTP errors per step,
logs them, and continues; it never exits on a transient error.

## Notifications

Slack message per run, one line: recommendation or status emoji, ticket
key, headline, ticket URL, and PR URL if any. Failed runs and gate
refusals post with a ⚠️ prefix and the run directory path.

## Testing

House rules apply: unit, integration, and end-to-end tests all exist;
VCRpy for HTTP; pristine output; no mock mode.

- **Unit** (`tests/unit/`): config loading and validation including env
  expansion and every failure path; provider registry; prompt rendering
  for all three templates with fixed facts; knowledge assembly order and
  size warning; summary parsing including fallback; fix gates against
  throwaway git repositories created in `tmp_path`; Slack payload
  formatting.
- **Integration** (`tests/integration/`): Sentry poll passes and
  environment check against recorded cassettes; Jira intake, approval,
  status, search, and comment against recorded cassettes; `tedsbot check`
  against cassettes plus a real `gh auth status`.
- **End-to-end** (`tests/e2e/`): a real `tedsbot triage sentry` and a real
  `tedsbot triage ticket` against a sandbox Jira project and a fixture
  checkout, asserting a ticket lands in `triage_target` with a
  recommendation line and that `summary.json` validates. A real `tedsbot
  fix` against the fixture checkout asserting a draft PR opens. Skipped
  when `TEDSBOT_E2E=1` is not set or credentials are absent. These spend
  credits and are run deliberately.

Run with `uv run pytest -n auto`.

## README contents

1. Mission and guiding principles (the sections above, condensed).
2. How it works: one diagram of intake → triage → human gate → fix → PR.
3. **Setup guide**, in order:
   1. Prerequisites: Python 3.12+, `uv`, Node 18+ (for `npx` MCP servers),
      `gh`, a checkout of the target repo.
   2. Install: `uv tool install tedsbot-triage-worker` or clone and
      `uv sync`.
   3. Credentials: Anthropic (API key primary; OAuth token section with
      the policy quote), GitHub (`gh auth login` or `GH_TOKEN`), Sentry
      token scopes, Atlassian token, Grafana service account, Slack
      webhook.
   4. Ticketing prerequisites: the statuses and custom fields the config
      names must exist; how to find field IDs and status names; the
      optional bot account.
   5. Error-source prerequisites: inbound filters, environment naming.
   6. Copy `tedsbot.example.yaml`, fill it in, put team knowledge in
      `knowledge_dir`.
   7. Run `tedsbot check` and read its output.
   8. First run by hand: `tedsbot triage sentry <id>`.
   9. Deploy: systemd unit example, cron with `--once`, GitHub Action
      wrapper (milestone two).
4. Extending: writing a provider (the four protocols, the registry, the
   knowledge file).
5. Operating: run directories, transcripts, reading a summary, tuning the
   poll passes, what to do when a run is 🔴.
6. Policy and billing notes.

## Milestones

1. **Core**: config, providers (sentry, jira, slack), knowledge, runner,
   `check`, `triage sentry`, `triage ticket`, unit + integration tests,
   README with setup guide.
2. **Fix and worker**: `fix` with gates, `worker` loop, grafana provider,
   e2e tests.
3. **Action wrapper and MartialQA cutover**: composite action; MartialQA
   repo gains `tedsbot.yaml` and `docs/triage/`, triage.yml and fix.yml
   call the CLI, poller script retired.

Version one is milestones one and two.
