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
