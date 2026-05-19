#!/usr/bin/env python3
"""GitHub Activity Reporter — Generate a concise markdown activity report.

A standalone tool for AI agents (and humans) to scan their GitHub contributions
and produce a structured activity report. Designed to be run in cron or on-demand.

Usage:
    python3 github_activity_reporter.py --username wjgong001 --token-file ~/.hermes/token_github
    python3 github_activity_reporter.py --username wjgong001 --token ghp_xxx

Output: Markdown report to stdout (or --output file.md)
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta


def github_request(url: str, token: str) -> dict | list:
    """Make a GitHub API request with auth."""
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "github-activity-reporter/0.1",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def fetch_open_prs(username: str, token: str, days: int = 7) -> list[dict]:
    """Fetch open PRs authored by username in the last N days."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    url = (
        f"https://api.github.com/search/issues?q=author:{username}"
        f"+type:pr+state:open+created:>={since[:10]}"
        f"&sort=created&order=desc&per_page=20"
    )
    results = github_request(url, token)
    return results.get("items", [])


def fetch_merged_prs(username: str, token: str, days: int = 14) -> list[dict]:
    """Fetch recently merged PRs by username."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    url = (
        f"https://api.github.com/search/issues?q=author:{username}"
        f"+type:pr+state:closed+merged:>={since[:10]}"
        f"&sort=updated&order=desc&per_page=20"
    )
    results = github_request(url, token)
    return results.get("items", [])


def fetch_pending_reviews(username: str, token: str) -> list[dict]:
    """Fetch PRs where user was requested as reviewer (still pending)."""
    url = (
        f"https://api.github.com/search/issues?q=review-requested:{username}"
        f"+type:pr+state:open&sort=updated&order=desc&per_page=10"
    )
    results = github_request(url, token)
    return results.get("items", [])


def fetch_repo_info(repo_full_name: str, token: str) -> dict:
    """Fetch basic repo info."""
    url = f"https://api.github.com/repos/{repo_full_name}"
    return github_request(url, token)


def format_pr(pr: dict) -> str:
    """Format a PR into a markdown line."""
    repo = pr["repository_url"].split("/")[-2] + "/" + pr["repository_url"].split("/")[-1]
    state_icon = "✅" if pr.get("state") == "closed" and pr.get("pull_request", {}).get("merged_at") else "🔄" if pr["state"] == "open" else "❌"
    return f"- {state_icon} [{repo} #{pr['number']}]({pr['html_url']}): {pr['title'][:80]}"


def generate_report(username: str, token: str, days: int = 7) -> str:
    """Generate the full markdown report."""
    lines = []
    lines.append(f"# GitHub Activity Report — @{username}")
    lines.append(f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}*\n")

    # Open PRs
    open_prs = fetch_open_prs(username, token, days)
    lines.append(f"## 🔄 Open PRs ({len(open_prs)})")
    if open_prs:
        for pr in open_prs:
            lines.append(format_pr(pr))
    else:
        lines.append("*No open PRs in the last {days} days.*")
    lines.append("")

    # Merged PRs
    merged_prs = fetch_merged_prs(username, token, days * 2)
    recent_merges = [p for p in merged_prs if p.get("pull_request", {}).get("merged_at")]
    lines.append(f"## ✅ Merged PRs ({len(recent_merges)})")
    if recent_merges:
        for pr in recent_merges:
            lines.append(format_pr(pr))
    else:
        lines.append("*No merged PRs found.*")
    lines.append("")

    # Pending review requests
    pending_reviews = fetch_pending_reviews(username, token)
    lines.append(f"## 👀 PRs Awaiting Your Review ({len(pending_reviews)})")
    if pending_reviews:
        for pr in pending_reviews:
            lines.append(format_pr(pr))
    else:
        lines.append("*No pending review requests.*")
    lines.append("")

    # Summary stats
    total = len(open_prs) + len(recent_merges)
    lines.append("---")
    lines.append(f"**Summary:** {len(open_prs)} open, {len(recent_merges)} merged — {total} total contributions tracked.")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Generate a GitHub activity report as markdown.",
    )
    parser.add_argument("--username", default="wjgong001", help="GitHub username")
    parser.add_argument("--token", help="GitHub personal access token")
    parser.add_argument("--token-file", help="Path to file containing GitHub token")
    parser.add_argument("--days", type=int, default=7, help="Lookback window in days")
    parser.add_argument("--output", help="Write to file instead of stdout")
    args = parser.parse_args()

    # Resolve token
    token = args.token
    if not token and args.token_file:
        with open(os.path.expanduser(args.token_file)) as f:
            token = f.read().strip()
    if not token:
        # Try default location
        default_path = os.path.expanduser("~/.hermes/token_github")
        if os.path.exists(default_path):
            with open(default_path) as f:
                token = f.read().strip()
    if not token:
        print("Error: GitHub token required. Use --token, --token-file, or set ~/.hermes/token_github", file=sys.stderr)
        sys.exit(1)

    report = generate_report(args.username, token, args.days)

    if args.output:
        with open(args.output, "w") as f:
            f.write(report)
        print(f"Report written to {args.output}")
    else:
        print(report)


if __name__ == "__main__":
    main()
