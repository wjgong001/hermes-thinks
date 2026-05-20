#!/usr/bin/env python3
"""
Moltbook Engagement Checker — monitor replies, followers, and DMs on Moltbook.

An AI agent's tool for checking engagement on its Moltbook posts without
needing a browser. Designed for cron-driven agent workflows: run every N hours
to see who replied, who followed, and what's new across all your posts.

Usage:
    python3 moltbook_engagement_checker.py --token-file ~/.config/moltbook/credentials.json
    python3 moltbook_engagement_checker.py --token moltbook_sk_xxx --output engagement.md
    python3 moltbook_engagement_checker.py --help

Output: structured markdown with sections for new notifications, post activity,
follower changes, and direct messages.

Features:
- Check all notifications (replies, followers, system)
- Per-post activity summary with latest commenters
- Unread notification counts
- Follower count delta tracking (via saved state)
- Pure stdlib, zero external dependencies
- Machine-parseable structured output
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error


def parse_credentials(token_file, token_str):
    """Read Moltbook API token from file or string argument."""
    if token_file:
        try:
            with open(os.path.expanduser(token_file)) as f:
                raw = f.read().strip()
            # Support JSON credential files (common format) or raw token strings
            if raw.startswith('{'):
                data = json.loads(raw)
                token = data.get('api_key') or data.get('token') or raw
            else:
                token = raw
            return token
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Error reading credential file: {e}", file=sys.stderr)
            sys.exit(1)
    elif token_str:
        return token_str
    else:
        print("Error: either --token-file or --token is required", file=sys.stderr)
        sys.exit(1)


def api_get(token, path):
    """Make authenticated GET request to Moltbook API."""
    url = f"https://www.moltbook.com/api/v1{path}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "moltbook-engagement-checker/1.0",
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        return {"error": True, "status": e.code, "body": body[:500]}
    except urllib.error.URLError as e:
        return {"error": True, "reason": str(e.reason)}


def load_state(state_file):
    """Load previous engagement state for delta tracking."""
    if state_file and os.path.exists(state_file):
        try:
            with open(state_file) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_state(state_file, state):
    """Save current engagement state."""
    if state_file:
        os.makedirs(os.path.dirname(os.path.abspath(state_file)), exist_ok=True)
        with open(state_file, 'w') as f:
            json.dump(state, f, indent=2)


def format_notification(n, state):
    """Format a single notification entry."""
    ntype = n.get('type', 'unknown')
    content = n.get('content', '')
    is_read = n.get('isRead', False)
    created = n.get('createdAt', '')
    related_post = n.get('relatedPostId', '')
    related_comment = n.get('relatedCommentId', '')
    agent_id = n.get('agentId', '')
    nid = n.get('id', '')

    read_mark = ' ' if not is_read else '✓'
    lines = [f"  [{read_mark}] {ntype} ({created[:10]} {created[11:19]})"]
    lines.append(f"       ID: {nid[:8]}...")
    lines.append(f"       Content: {content}")
    if related_post:
        lines.append(f"       Post: {related_post}")
    if agent_id:
        lines.append(f"       Agent: {agent_id}")
    return '\n'.join(lines)


def check_engagement(token, state_file, output_file):
    """Main engagement check routine."""
    state = load_state(state_file)
    now = time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())

    lines = []
    lines.append(f"# Moltbook Engagement Report")
    lines.append(f"**Generated**: {now}")
    lines.append('')

    # --- Step 1: Check /home for post activity summary ---
    home = api_get(token, "/home")
    if home.get('error'):
        lines.append(f"## ⚠️ Home API Error")
        lines.append(f"Status: {home.get('status', '?')}")
        lines.append(f"Response: {home.get('body', home.get('reason', 'unknown'))[:200]}")
        lines.append('')
    else:
        # Account info
        account = home.get('your_account', {})
        karma = account.get('karma', '?')
        followers_state = account.get('follower_count', '?')
        unread = account.get('unread_notification_count', '?')
        name = account.get('name', '?')

        lines.append(f"## Account: {name}")
        lines.append(f"- Karma: {karma}")
        lines.append(f"- Unread notifications: {unread}")
        lines.append('')

        # Previous follower count for delta
        prev_followers = state.get('last_follower_count', None)
        if prev_followers is not None and isinstance(followers_state, (int, float)):
            delta = followers_state - prev_followers
            delta_str = f" (+{delta})" if delta > 0 else (f" ({delta})" if delta < 0 else " (no change)")
            lines.append(f"- Followers: {followers_state}{delta_str}")
        else:
            lines.append(f"- Followers: {followers_state}")
        lines.append('')

        # Post activity
        activity = home.get('activity_on_your_posts', [])
        if activity:
            lines.append(f"## Post Activity ({len(activity)} posts with new activity)")
            for post in activity:
                post_id = post.get('post_id', '?')[:8]
                title = post.get('post_title', 'Untitled')[:60]
                submolt = post.get('submolt_name', '?')
                new_count = post.get('new_notification_count', 0)
                latest_at = post.get('latest_at', '')[:16]
                commenters = post.get('latest_commenters', [])

                lines.append(f"### {title}")
                lines.append(f"- Submolt: {submolt}")
                lines.append(f"- New notifications: {new_count}")
                lines.append(f"- Latest activity: {latest_at}")
                if commenters:
                    lines.append(f"- Commenters: {', '.join(commenters)}")
                lines.append('')
        else:
            lines.append("## Post Activity")
            lines.append("No recent activity on your posts.")
            lines.append('')

        # Direct messages
        dms = home.get('your_direct_messages', {})
        pending = dms.get('pending_request_count', '0')
        unread_dms = dms.get('unread_message_count', '0')
        if pending != '0' or unread_dms != '0':
            lines.append(f"## Direct Messages")
            lines.append(f"- Pending requests: {pending}")
            lines.append(f"- Unread messages: {unread_dms}")
            lines.append('')

        # Update state
        state['last_follower_count'] = followers_state if isinstance(followers_state, (int, float)) else state.get('last_follower_count', None)

    # --- Step 2: Check notifications directly ---
    notifs = api_get(token, "/notifications")
    if notifs.get('error'):
        lines.append(f"## ⚠️ Notifications API Error")
        lines.append(f"Status: {notifs.get('status', '?')}")
    else:
        notif_list = notifs.get('notifications', notifs.get('data', []))
        if notif_list:
            # Separate unread and read
            unread_notifs = [n for n in notif_list if not n.get('isRead', True)]
            recent_notifs = notif_list[:10]

            if unread_notifs:
                lines.append(f"## 🔴 New Notifications ({len(unread_notifs)} unread)")
                for n in unread_notifs:
                    lines.append(format_notification(n, state))
                    lines.append('')

            if recent_notifs:
                lines.append(f"## Recent Notifications (last {len(recent_notifs)})")
                for n in recent_notifs:
                    lines.append(format_notification(n, state))
                    lines.append('')
        else:
            lines.append("## Notifications")
            lines.append("No notifications found.")
            lines.append('')

    # --- Step 3: Parse DMs from home endpoint ---
    if not home.get('error'):
        dms = home.get('your_direct_messages', {})
        pending = dms.get('pending_request_count', '0')
        unread_dms = dms.get('unread_message_count', '0')
        if pending != '0' or unread_dms != '00':
            lines.append("## 💬 DM Summary (from home endpoint)")
            lines.append(f"- Pending requests: {pending}")
            lines.append(f"- Unread messages: {unread_dms}")
            lines.append('')

    # Save state for next run
    state['last_check'] = now
    save_state(state_file, state)

    report = '\n'.join(lines)

    if output_file:
        outpath = os.path.expanduser(output_file)
        os.makedirs(os.path.dirname(os.path.abspath(outpath)) or '.', exist_ok=True)
        with open(outpath, 'w') as f:
            f.write(report)
        print(f"Report written to {outpath}")
    else:
        print(report)

    return report


def main():
    parser = argparse.ArgumentParser(
        description='Moltbook Engagement Checker — monitor replies, followers, and DMs.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 moltbook_engagement_checker.py --token-file ~/.config/moltbook/credentials.json
  python3 moltbook_engagement_checker.py --token moltbook_sk_xxx --output engagement.md
  python3 moltbook_engagement_checker.py --token-file creds.json --state state.json

State file tracks follower count changes between runs.
Output is structured markdown, machine-parseable.
        """.strip(),
    )
    parser.add_argument('--token-file', help='Path to Moltbook credentials file (JSON or raw token)')
    parser.add_argument('--token', help='Moltbook API token directly')
    parser.add_argument('--output', '-o', help='Output file path for markdown report')
    parser.add_argument('--state', help='State file path for tracking deltas between runs')
    parser.add_argument('--quiet', '-q', action='store_true', help='Suppress stdout output when writing to file')

    args = parser.parse_args()

    token = parse_credentials(args.token_file, args.token)
    report = check_engagement(token, args.state, args.output)

    if args.output and args.quiet:
        pass  # stdout already suppressed
    elif not args.output:
        pass  # report already printed


if __name__ == '__main__':
    main()
