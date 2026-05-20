# Hermes Tools

Standalone tools for AI agents and humans.

## Available Tools

### `github_activity_reporter.py`
Generate a markdown activity report from GitHub contributions.
Scans open PRs, merged PRs, and pending review requests.

```bash
python3 _tools/github_activity_reporter.py --username wjgong001
python3 _tools/github_activity_reporter.py --username wjgong001 --days 14 --output report.md
```

Requires: GitHub token in `~/.hermes/token_github` or `--token/--token-file`.

### `github_issue_scout.py`
Search for undiscovered open issues (0 comments, recent, bug-labeled) across multiple
Python/AI-agent repos. Filters out issues with already-linked PRs to avoid duplicate work.

```bash
python3 _tools/github_issue_scout.py --token-file ~/.hermes/token_github
python3 _tools/github_issue_scout.py --token ghp_xxx --repos crewAIInc/crewAI,microsoft/conductor --days 14 --output scout_report.md
```

Features:
- Scans 10+ default AI-agent target repos
- Checks for linked PRs before reporting (avoids wasted deep-dives)
- Filters by recency (default: 7 days) and labels (default: bug)
- Produces structured markdown report with excerpts

### `self_ledger_dag_analyzer.py`
Materialize a claim DAG (Directed Acyclic Graph) from an event-sourced agent log.
Replays events to reconstruct live claim state, falsification cascades, and
session-boundary survival patterns. Directly addresses the "dead branches" problem
in session-based falsification condition management.

```bash
python3 _tools/self_ledger_dag_analyzer.py --sample
python3 _tools/self_ledger_dag_analyzer.py --input ledger_events.json --output dag_report.md
python3 _tools/self_ledger_dag_analyzer.py --help
```

Features:
- Event-sourced materialization: replay event log → build current claim graph
- Falsification cascade tracing: chain falsified claims through dependency tree
- Session-boundary survival analysis: which claims persist across sessions
- Failure mode grouping: dead claims categorized by falsification pattern
- Pure stdlib, zero external dependencies
- Input: JSON array of events or JSONL format (one event per line)
- Output: structured markdown (DAG report with tables, cascade diagrams)

### `moltbook_engagement_checker.py`
Monitor Moltbook replies, followers, mentions, and DMs from the command line.
Designed for cron-driven agent workflows — run every N hours to check
engagement across all your posts without needing a browser.

```bash
python3 _tools/moltbook_engagement_checker.py --token-file ~/.config/moltbook/credentials.json
python3 _tools/moltbook_engagement_checker.py --token moltbook_sk_xxx --output engagement.md
python3 _tools/moltbook_engagement_checker.py --help
```

Features:
- Check all notifications (replies, followers, mentions, system messages)
- Per-post activity summary with latest commenters and notification counts
- Follower count delta tracking across runs (via state file)
- Unread notification breakdown
- Direct message pending/unread count
- Pure stdlib, zero external dependencies
- Structured markdown output for cron job logs
