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
provider tools. The agent has no file-write permission; it records its result through an in-process `submit_summary` tool, which validates the schema and writes `~/.tedsbot/runs/<id>/summary.json`, alongside
`prompt.md`, and `transcript.jsonl`.

## Setup guide

Follow the steps in order. Steps 1 to 7 spend nothing; step 8 is the first
run that costs Claude credits. Budget about thirty minutes the first time,
most of it collecting tokens.

### 1. Prerequisites

| Need | Why | Check |
|---|---|---|
| Python 3.12+ and [uv](https://docs.astral.sh/uv/) | runs the worker | `uv --version` |
| Node.js 18+ | the Sentry MCP server is an npm package run with `npx` | `node --version` |
| [GitHub CLI](https://cli.github.com) | the fix stage opens draft PRs with `gh` | `gh --version` |
| A local checkout of the repository you want triaged | the agent reads code and git history there | `git -C /path/to/checkout log --oneline -1` |

The checkout must have full history: run `git fetch --unshallow` if it was a
shallow clone. Keep it on the base branch and clean; the worker refuses to
start a fix run otherwise.

### 2. Install

```
git clone https://github.com/tauhir/tedsbot-triage-worker
cd tedsbot-triage-worker
uv sync
uv run tedsbot --help
```

Once published to PyPI, `uv tool install tedsbot-triage-worker` will put a
`tedsbot` command on your PATH. Until then, run it as `uv run tedsbot` from the
clone.

### 3. Collect credentials

You need five secrets. Where to get each, and what it must be allowed to do:

| Variable | Where to get it | Must have |
|---|---|---|
| `ANTHROPIC_API_KEY` **or** `CLAUDE_CODE_OAUTH_TOKEN` | Claude Console → API keys; or run `claude setup-token` for a subscription token | see the note below |
| `SENTRY_AUTH_TOKEN` | Sentry → Settings → Auth Tokens (organization token) | `event:read`, `project:read`; `org:read` is *not* required |
| `ATLASSIAN_API_TOKEN` | Atlassian admin → Service accounts / API tokens, or an OAuth 2.0 access token | browse, comment, create issue, edit issue, transition on the project |
| `SLACK_WEBHOOK_URL` | Slack → your app → Incoming Webhooks → add to the channel that should see results | post messages |
| `GH_TOKEN` (optional) | only if the host cannot run `gh auth login`; a PAT or GitHub App installation token | `contents: write`, `pull requests: write` on the target repo |

**Claude auth note.** An API key is the documented, supported path and is
metered. A `CLAUDE_CODE_OAUTH_TOKEN` bills your own Claude subscription
(Pro, Max, Team, Enterprise). Anthropic's Agent SDK documentation states:
"Unless previously approved, Anthropic does not allow third party developers
to offer claude.ai login or rate limits for their products, including agents
built on the Claude Agent SDK." tedsbot does not offer login; it passes your
own token through. Whether that fits your plan's terms is your call.

**Atlassian note.** The token is sent as a `Bearer` token to the Atlassian
API gateway, `https://api.atlassian.com/ex/jira/<cloud-id>/rest/api/3`.
Atlassian Cloud rejects Bearer tokens on your site host
(`https://<site>.atlassian.net`) with 401/403, which is why the config needs
`tickets.cloud_id` (step 4). `tickets.url` stays your site URL; it is only
used to build `browse/` links.

Put the secrets in an environment file the worker's shell can source, one
`NAME=value` per line, no spaces around `=`, no quotes needed:

```
# ~/.config/tedsbot/env  (chmod 600)
CLAUDE_CODE_OAUTH_TOKEN=...
SENTRY_AUTH_TOKEN=...
ATLASSIAN_API_TOKEN=...
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
```

Load it with `set -a; . ~/.config/tedsbot/env; set +a` before running
`tedsbot`, or point a systemd `EnvironmentFile` at it. The config file never
contains a secret; it references these variables as `${NAME}`.

### 4. Find the identifiers your config needs

Run these once and write the answers down. Replace `<site>`, `<cloud-id>`,
`<org>`, `<project-slug>` as you go.

```
# Jira cloud id (no auth needed)
curl -s https://<site>.atlassian.net/_edge/tenant_info

# Jira custom field ids (QA notes / QA instructions or whatever you use)
curl -s -H "Authorization: Bearer $ATLASSIAN_API_TOKEN" \
  https://api.atlassian.com/ex/jira/<cloud-id>/rest/api/3/field | jq -r '.[] | select(.custom) | "\(.id)\t\(.name)"'

# Jira status names on the project, per issue type
curl -s -H "Authorization: Bearer $ATLASSIAN_API_TOKEN" \
  https://api.atlassian.com/ex/jira/<cloud-id>/rest/api/3/project/<KEY>/statuses | jq -r '.[] | "\(.name): \([.statuses[].name] | join(", "))"'

# Jira Bug issue type id
curl -s -H "Authorization: Bearer $ATLASSIAN_API_TOKEN" \
  https://api.atlassian.com/ex/jira/<cloud-id>/rest/api/3/project/<KEY> | jq -r '.issueTypes[] | "\(.id)\t\(.name)"'

# Sentry project id and the exact environment names (case matters).
# <org> and <project-slug> are the two path segments of the project in the Sentry UI.
curl -s -H "Authorization: Bearer $SENTRY_AUTH_TOKEN" \
  https://us.sentry.io/api/0/projects/<org>/<project-slug>/ | jq -r '.id'
curl -s -H "Authorization: Bearer $SENTRY_AUTH_TOKEN" \
  https://us.sentry.io/api/0/projects/<org>/<project-slug>/environments/ | jq -r '.[].name'
```

If your Sentry organisation lives in the EU region, use `https://de.sentry.io`
and set `errors.region_url` to match.

### 5. Prepare the ticketing workflow and the error source

**Jira.** The worker moves tickets between five statuses: an intake status
where new bugs land, a triage target where analysed tickets wait for a human,
an approval status a human moves a ticket into to authorise a fix, an
in-progress status, and a code-review status. Every one of them must exist on
the project's workflow under the names you put in `tickets.statuses`. Create a
dedicated bot account for the token so triage comments are clearly
machine-authored.

**Sentry.** Turn on the inbound filters (legacy browsers, web crawlers,
health checks, localhost) so noise never becomes an event. Note the exact
spelling and case of the production environment name from step 4.

### 6. Write the config and the team knowledge

Keep the config **outside** any repository the worker triages, for example
`~/.config/tedsbot/tedsbot.yaml`, and pass it with `-c`:

```
cp tedsbot.example.yaml ~/.config/tedsbot/tedsbot.yaml
```

Edit every value. The example is fully commented; the knobs people miss are
`errors.environment` (case-sensitive), `errors.poll.new_error.first_seen`
(keep it wider than your poll interval), and `agent.knowledge_dir`.

`agent.knowledge_dir` is a directory of markdown files that only your team
knows: the Jira transition map, which status names differ from their
transition labels, deploy topology, staging versus production, known noise,
how you like replication steps written. Everything in it is appended to the
agent's instructions on every run. Start with one file; a good first one is
whatever internal doc already explains how a ticket moves across your board.

### 7. Verify, spending nothing

```
tedsbot -c ~/.config/tedsbot/tedsbot.yaml check
```

A passing check looks like this:

```
[ok] config — /home/you/.config/tedsbot/tedsbot.yaml
[ok] checkout — /srv/checkouts/example-app on main
[ok] mcp:sentry — npx -y @sentry/mcp-server@latest --organization-slug=example-org
[ok] mcp:atlassian — uvx mcp-atlassian
[ok] sentry auth — https://us.sentry.io/api/0/organizations/example-org/issues/
[ok] gh auth — gh auth status
[ok] ticket statuses — all present
[ok] claude auth — ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN
```

Any `[FAIL]` row names what to fix. The first run of the two MCP rows can
take twenty seconds while `npx` and `uvx` download the servers; that is
normal.

### 8. First run

Pick one unresolved production error from Sentry and run:

```
tedsbot -c ~/.config/tedsbot/tedsbot.yaml triage sentry <issue-id-or-url>
```

Expect a few minutes. When it finishes you get three things: a Slack message
with a headline saying what kind of event this is, the ticket key and title, a
plain-language account for non-engineers, the impact (events, users, first and
last seen), the technical root cause, and what the reader should do next; a Jira Bug in your
triage-target status whose description is the analysis; and a run directory
under `~/.tedsbot/runs/` holding `prompt.md` (what the agent was told),
`transcript.jsonl` (everything it did), `summary.json` (what it wrote) and
`summary.resolved.json` (what the worker accepted). Read the transcript the
first time; it is the fastest way to see whether your knowledge directory is
telling the agent what it needs.

For a team-reported bug already in Jira: `tedsbot triage ticket <KEY>`.

### 9. Deploy

- **systemd**: a unit running `tedsbot -c ... worker` with `EnvironmentFile=`
  pointing at the file from step 3. (Milestone 2.)
- **cron**: `*/15 * * * * tedsbot -c /etc/tedsbot/tedsbot.yaml worker --once`.
  (Milestone 2.)
- **GitHub Action**: composite wrapper. (Milestone 3.)

### Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `[FAIL] ticket statuses — jira GET ... 401/403` | token sent to the site host, or wrong cloud id | use the gateway URL form; re-check `tickets.cloud_id` from `_edge/tenant_info` |
| `[FAIL] sentry auth — ... -> 403` | token lacks `project:read` / `event:read` | reissue the Sentry token with those scopes |
| Poll finds nothing but Sentry shows errors | `errors.environment` case or spelling | copy the name exactly from step 4 |
| `[FAIL] mcp:sentry` on a fresh host | `npx` not on PATH, or the first download exceeded the probe timeout | install Node 18+; run the printed command once by hand, then re-run `check` |
| `provider:logs — logs.kind 'grafana' is not registered` | the Grafana provider ships in milestone 2 | comment out the `logs:` block |
| `fix: not implemented yet` / `worker: not implemented yet` | milestone 1 ships triage only | wait for milestone 2 |
| `config error: environment variable X is not set` | the env file was not loaded into this shell | `set -a; . ~/.config/tedsbot/env; set +a` |

## Extending: writing a provider
Implement one of the protocols in `src/tedsbot/providers/base.py`, ship a knowledge markdown file next to it, and call `register(role, kind, YourClass)` at import. Add the module to `providers/__init__.py`. Your `kind` becomes selectable in the YAML.

## Operating
Each run directory holds `prompt.md` (what the agent was told), `transcript.jsonl` (every message), `summary.json` (what the agent wrote), and `summary.resolved.json` (what Python accepted). A 🔴 means the agent could not establish a credible root cause; read the transcript before deciding whether the ticket needs more context or the knowledge directory needs a note.

Run directories are never pruned, and a transcript holds whatever the agent read: full Sentry event payloads (which can carry request data and user identifiers) and the contents of source files. Treat `~/.tedsbot/runs` as sensitive, keep it on the worker host, and age it out yourself if your retention policy needs that.

In milestone 1 the rule that triage never moves a ticket past `tickets.statuses.triage_target` is prompt-enforced only: nothing re-reads the ticket's status after the run to confirm the agent obeyed. The automated post-run status re-read arrives with the worker loop in milestone 2, so until then spot-check the transitions on early runs.

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
