# tedsbot-triage-worker

Autonomous bug-triage and fix worker on the Claude Agent SDK. Point it at
a checkout, an error source, and a ticketing system; it root-causes
production errors and team-reported bugs into tickets a human can approve,
and implements approved fixes as draft pull requests.

Powered by Claude. Not affiliated with Anthropic.

**Status:** milestone 1 ships `check`, `triage sentry`, and `triage ticket`. The `fix` and `worker` subcommands are registered but print `not implemented yet` and exit 1; milestone 2 implements them.

## Mission

Run an autonomous triage worker on the Claude credentials you already have.
Humans stay in the loop at exactly two places: approving a fix, and
reviewing the pull request.

## Guiding principles

1. Bring your own credentials. Never brokers login for anyone.
2. Roles, not brands. Error source, ticketing, logs, notifier; providers fill them.
3. Determinism where it matters. Polling, dedupe, gates, summaries, notifications are plain Python.
4. Honesty over confidence. 🔴 beats a wrong confident analysis.
5. Human gates are hard gates. Triage never edits code. Fix only runs on approved tickets, draft PRs only.
6. Knowledge lives in files, not prompts.
7. Nothing project-specific in this repo.

## How it works

    error source ──poll──▶ triage sentry ─┐
    ticketing ───poll──▶ triage ticket ──┼─▶ ticket in "Dev Team Review" ──human approves──▶ fix ──▶ draft PR ──human reviews
                                          └─▶ Slack line per run

Triage runs are read-only: Read, Grep, Glob, git history, plus the
provider tools. Every run writes `~/.tedsbot/runs/<id>/summary.json`,
`prompt.md`, and `transcript.jsonl`.

## Setup guide

### 1. Prerequisites
- Python 3.12+, [uv](https://docs.astral.sh/uv/)
- Node.js 18+ (the Sentry MCP server runs with `npx`)
- [GitHub CLI](https://cli.github.com) (`gh`)
- A local checkout of the repository you want triaged, with full history (`git fetch --unshallow` if it was a shallow clone)

### 2. Install
    uv tool install tedsbot-triage-worker
or from a clone:
    git clone https://github.com/tauhir/tedsbot-triage-worker && cd tedsbot-triage-worker && uv sync

### 3. Credentials
Export these in the shell (or the service unit) that runs tedsbot.

**Claude.** One of:
- `ANTHROPIC_API_KEY` from the Claude Console. This is the documented, supported path; usage is metered.
- `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token`, which bills your own Claude subscription (Pro, Max, Team, Enterprise). Anthropic's Agent SDK documentation states: "Unless previously approved, Anthropic does not allow third party developers to offer claude.ai login or rate limits for their products, including agents built on the Claude Agent SDK." tedsbot does not offer login; it passes your own token through. Whether that fits your plan's terms is your call.

**GitHub.** `gh auth login` on the host, or export `GH_TOKEN` (a PAT or a GitHub App installation token). PRs are authored by whichever identity you choose.

**Sentry.** `SENTRY_AUTH_TOKEN`: an auth token with `event:read`, `project:read`, `org:read`.

**Atlassian.** `ATLASSIAN_API_TOKEN`: a service token or an OAuth 2.0 access token with browse, comment, create-issue, edit-issue, and transition permissions on the project. Both are sent as a `Bearer` token, and Atlassian Cloud only honours Bearer tokens on the API gateway (`https://api.atlassian.com/ex/jira/<cloud-id>/rest/api/3`), not on your site host. `tickets.cloud_id` is therefore required: read it from `GET https://<site>.atlassian.net/_edge/tenant_info`, which returns `{"cloudId": "..."}`. `tickets.url` is still your site URL and is used for the `browse/` links in tickets and Slack lines.

**Grafana (optional).** `GRAFANA_SERVICE_ACCOUNT_TOKEN` for a service account with Viewer on the relevant data sources.

**Slack.** `SLACK_WEBHOOK_URL`: an incoming webhook for the channel that should see run results.

### 4. Ticketing prerequisites
The statuses you name under `tickets.statuses` must exist on the project's workflow, and the custom fields under `tickets.fields` must exist on the Bug issue type. Find field IDs with the Jira REST API (`GET /rest/api/3/field`) and status names from the board's workflow. A dedicated bot account for the token is recommended so triage comments are clearly machine-authored.

### 5. Error-source prerequisites
Turn on Sentry's inbound filters (legacy browsers, web crawlers, health checks, localhost) so noise never becomes an event. Confirm the exact spelling and case of the environment name; Sentry searches are case-sensitive.

### 6. Configure
    cp tedsbot.example.yaml tedsbot.yaml
Edit every value. Put your team's knowledge (transition map, deploy topology, known noise, replication conventions) as markdown files in the directory named by `agent.knowledge_dir`. Pay particular attention to the `errors.poll` block; the example config's inline comments explain each knob, including `first_seen`.

### 7. Verify
    tedsbot check
Every line must read `[ok]`. Nothing has spent credits yet.

### 8. First run
    tedsbot triage sentry <issue-id-or-url>
Read the Slack line, the ticket, and `~/.tedsbot/runs/<id>/transcript.jsonl`.

### 9. Deploy
- **systemd**: a unit running `tedsbot worker` with the env vars in an `EnvironmentFile`. (Milestone 2.)
- **cron**: `*/15 * * * * tedsbot -c /etc/tedsbot/tedsbot.yaml worker --once`. (Milestone 2.)
- **GitHub Action**: composite wrapper. (Milestone 3.)

## Extending: writing a provider
Implement one of the protocols in `src/tedsbot/providers/base.py`, ship a knowledge markdown file next to it, and call `register(role, kind, YourClass)` at import. Add the module to `providers/__init__.py`. Your `kind` becomes selectable in the YAML.

## Operating
Each run directory holds `prompt.md` (what the agent was told), `transcript.jsonl` (every message), `summary.json` (what the agent wrote), and `summary.resolved.json` (what Python accepted). A 🔴 means the agent could not establish a credible root cause; read the transcript before deciding whether the ticket needs more context or the knowledge directory needs a note.

### Security notes
The agent subprocess inherits the worker process's full environment — the
SDK merges its own env over `os.environ`, and the worker does not isolate
it. The mitigation is the tool allowlist: it restricts Bash to four
read-only git subcommands (log, show, blame, diff) during triage, and to
git and gh during fix. Run the worker as a dedicated user holding only
the secrets it needs, not a shared or broadly-privileged account.

MCP server credentials are handed to the agent process through its
environment rather than its command line, so a token never appears in
an argv listing or a process table.

## Policy and billing
Each run consumes Claude tokens under whichever credential you configured. Set `agent.max_turns` to cap a runaway run. See Credentials above for the subscription-token note.

## License
MIT
