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
