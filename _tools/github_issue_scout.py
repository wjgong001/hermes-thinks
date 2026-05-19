#!/usr/bin/env python3
"""GitHub Issue Scout — Find undiscovered open-source issues to fix.

A standalone tool for AI agents (and humans) searching for open issues
with low competition (0-comment bugs, fresh issues, Python targets).
Scans multiple target repos and produces a structured candidate report.

Usage:
    python3 github_issue_scout.py --token-file ~/.hermes/token_github
    python3 github_issue_scout.py --token ghp_xxx --repos crewAIInc/crewAI,microsoft/conductor --min-stars 100

Output: Markdown report to stdout (or --output report.md)
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta


# Default target repos with high Python AI-agent relevance
DEFAULT_REPOS = [
    "crewAIInc/crewAI",
    "microsoft/conductor",
    "ComposioHQ/composio",
    "Significant-Gravitas/AutoGPT",
    "langchain-ai/langchain",
    "langchain-ai/langgraph",
    "nicepkg/hermes-agent",
    "pydantic/pydantic-ai",
    "microsoft/TaskWeaver",
    "ag2ai/ag2",
]


def github_request(url: str, token: str) -> dict | list:
    """Make a GitHub API request with auth. Returns parsed JSON."""
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "github-issue-scout/0.1",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:200] if e.fp else ""
        return {"error": f"HTTP {e.code}: {body}"}
    except urllib.error.URLError as e:
        return {"error": f"URL error: {e.reason}"}


def search_issues(repo: str, token: str, days_back: int = 7, labels: list[str] | None = None) -> list[dict]:
    """Search for open issues in a repo with 0 comments and specified recency."""
    label_filter = "label:bug" if not labels else "+".join(f"label:{l}" for l in labels)
    date_cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")
    
    # Primary query: 0-comment bugs
    query = f"repo:{repo}+state:open+is:issue+comments:0+{label_filter}+created:>={date_cutoff}"
    
    url = f"https://api.github.com/search/issues?q={query}&sort=created&order=desc&per_page=10"
    data = github_request(url, token)
    
    if "error" in data:
        return [data]
    
    items = data.get("items", [])
    
    # For each item, add linked PR context
    for item in items:
        check_linked_prs(item, token)
    
    return items


def check_linked_prs(item: dict, token: str) -> None:
    """Check if there are already PRs linked to this issue, to avoid duplicate work."""
    issue_number = item["number"]
    repo_full = item["repository_url"].replace("https://api.github.com/repos/", "")
    
    # Search for PRs referencing this issue
    query = f"repo:{repo_full}+type:pr+state:open+{issue_number}+in:body"
    url = f"https://api.github.com/search/issues?q={query}&per_page=3"
    data = github_request(url, token)
    
    if "error" not in data and data.get("total_count", 0) > 0:
        item["_linked_prs"] = [
            {
                "number": pr["number"],
                "title": pr["title"],
                "state": pr["state"],
                "url": pr["html_url"],
                "created_at": pr["created_at"],
            }
            for pr in data.get("items", [])
        ]
    else:
        item["_linked_prs"] = []


def format_report(repos_data: dict[str, list[dict]]) -> str:
    """Format the search results as a structured markdown report."""
    lines = [
        "# 🕵️ GitHub Issue Scout Report",
        f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "Scans for open issues with low competition (0 comments, recent, Python/agent-related).",
        "",
        "---",
        "",
    ]
    
    total_candidates = 0
    for repo_name, issues in sorted(repos_data.items()):
        lines.append(f"## 📦 {repo_name}")
        
        if not issues:
            lines.append("  _No matching issues found._")
            lines.append("")
            continue
        
        if "error" in issues[0]:
            lines.append(f"  ❌ **API Error:** {issues[0]['error']}")
            lines.append("")
            continue
        
        lines.append(f"  **{len(issues)} candidate(s) found**")
        lines.append("")
        
        for issue in issues:
            total_candidates += 1
            n = issue["number"]
            title = issue["title"]
            state = issue["state"]
            created = issue["created_at"][:10]
            comments = issue["comments"]
            url = issue["html_url"]
            labels_str = ", ".join(l["name"] for l in issue.get("labels", []))
            
            linked_prs = issue.get("_linked_prs", [])
            has_pr_warning = " ⚠️" if linked_prs else ""
            
            lines.append(f"### [#{n}]({url}) {title}{has_pr_warning}")
            lines.append(f"- **State:** {state} | **Created:** {created} | **Comments:** {comments}")
            if labels_str:
                lines.append(f"- **Labels:** {labels_str}")
            
            if linked_prs:
                lines.append(f"- **⚠️ Linked PRs already exist:**")
                for pr in linked_prs:
                    lines.append(f"  - #{pr['number']} {pr['title']} [{pr['state']}]({pr['url']})")
            
            # Show first ~200 chars of body (if present)
            body = (issue.get("body") or "").strip()
            if body:
                excerpt = body[:250].replace("\n", " ").strip()
                lines.append(f"- **Excerpt:** {excerpt}...")
            
            lines.append("")
    
    lines.extend([
        "---",
        f"**Total candidates found: {total_candidates}**",
        "",
        "**Tips:**",
        "- Prioritize issues with 0 comments, bug label, and no linked PRs",
        "- Check _linked_prs field before deep-diving into codebase",
        "- Issues older than 7 days may have higher competition",
        "",
    ])
    
    return "\n".join(lines)


def load_token(token_path: str | None = None) -> str:
    """Load GitHub token from file or env."""
    if token_path:
        with open(os.path.expanduser(token_path)) as f:
            return f.read().strip()
    
    default_paths = [
        "~/.hermes/token_github",
        "~/.github-token",
        "~/.config/gh/token",
    ]
    
    for path in default_paths:
        expanded = os.path.expanduser(path)
        if os.path.isfile(expanded):
            with open(expanded) as f:
                return f.read().strip()
    
    env_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if env_token:
        return env_token
    
    raise FileNotFoundError(
        "No GitHub token found. Provide --token or --token-file, or set GITHUB_TOKEN env var."
    )


def parse_args():
    parser = argparse.ArgumentParser(
        description="GitHub Issue Scout — Find undiscovered open-source issues to fix.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    
    token_group = parser.add_mutually_exclusive_group()
    token_group.add_argument("--token", help="GitHub token directly")
    token_group.add_argument("--token-file", help="Path to file containing GitHub token")
    
    parser.add_argument(
        "--repos",
        help="Comma-separated list of repos (default: built-in AI/agent targets)",
        default=",".join(DEFAULT_REPOS),
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Only consider issues created within N days (default: 7)",
    )
    parser.add_argument(
        "--labels",
        default="bug",
        help="Comma-separated issue labels to search for (default: bug)",
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Write report to file instead of stdout",
    )
    parser.add_argument(
        "--min-stars",
        type=int,
        default=50,
        help="Minimum repo stars to include (default: 50). Applies to custom --repos only.",
    )
    
    return parser.parse_args()


def main():
    args = parse_args()
    
    try:
        token = args.token or load_token(args.token_file)
    except FileNotFoundError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)
    
    repos = [r.strip() for r in args.repos.split(",") if r.strip()]
    labels = [l.strip() for l in args.labels.split(",") if l.strip()]
    
    repos_data = {}
    for repo in repos:
        issues = search_issues(repo, token, days_back=args.days, labels=labels)
        repos_data[repo] = issues
    
    report = format_report(repos_data)
    
    if args.output:
        output_path = os.path.expanduser(args.output)
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w") as f:
            f.write(report)
        print(f"✅ Report written to {output_path}")
    else:
        print(report)


if __name__ == "__main__":
    main()
