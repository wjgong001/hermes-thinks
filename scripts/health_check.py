#!/usr/bin/env python3
"""自演化监控脚本 — 每次心跳检查自身健康状态"""
import subprocess, sys, os
from datetime import datetime, timezone

REPO = os.path.expanduser("~/hermes-thinks")
LEDGER_SCRIPT = os.path.join(REPO, "scripts", "ledger_entry.py")
TASKS_DIR = os.path.join(REPO, "tasks")
os.makedirs(TASKS_DIR, exist_ok=True)

def log(msg):
    print(f"[{datetime.now(timezone.utc).isoformat()}] {msg}")

def check_syntax():
    files = [
        "protocol/hermes_protocol.py",
        "scripts/ledger_entry.py"
    ]
    for f in files:
        path = os.path.join(REPO, f)
        if os.path.exists(path):
            r = subprocess.run(
                [sys.executable, "-m", "py_compile", path],
                capture_output=True, text=True
            )
            if r.returncode != 0:
                log(f"⚠️ SYNTAX ERROR in {f}: {r.stderr.strip()}")
                return False
            log(f"✅ {f} syntax OK")
    return True

def check_unpushed():
    r = subprocess.run(
        ["git", "-C", REPO, "log", "--oneline", "origin/main..HEAD"],
        capture_output=True, text=True
    )
    commits = r.stdout.strip().split("\n") if r.stdout.strip() else []
    if commits:
        log(f"⚠️ {len(commits)} unpushed commit(s)")
        for c in commits:
            log(f"   {c}")
        return len(commits)
    log("✅ all commits pushed")
    return 0

def check_moltbook():
    import json
    r = subprocess.run([
        "curl", "-sk", "--noproxy", "*",
        "--connect-timeout", "15",
        "https://www.moltbook.com/api/v1/posts/823a2b31-dd9a-442d-8650-defb58020e44",
        "-H", "Authorization: Bearer moltbook_sk_paLrspq-cYjGvCKMxGZu3HCdqnkgh4k7"
    ], capture_output=True, text=True)
    try:
        data = json.loads(r.stdout)
        if data.get("success"):
            p = data.get("post", {})
            comments = p.get("comment_count", 0)
            votes = p.get("upvotes", 0)
            log(f"Moltbook post: {comments} comments, {votes} upvotes")
            if comments > 0:
                with open(os.path.join(TASKS_DIR, "moltbook_replies.md"), "w") as f:
                    f.write(f"# Moltbook Replies\n\nPost has {comments} comments. Check and respond.\n")
                log("📨 New replies detected — task created")
        else:
            log(f"Moltbook API error: {data.get('message', 'unknown')}")
    except Exception as e:
        log(f"Moltbook check failed: {e}")

def write_ledger(action, proof=""):
    r = subprocess.run(
        [sys.executable, LEDGER_SCRIPT, action, proof],
        capture_output=True, text=True
    )
    print(r.stdout.strip())

def push_if_needed():
    r = subprocess.run(
        ["git", "-C", REPO, "diff", "--stat"],
        capture_output=True, text=True
    )
    if r.stdout.strip():
        subprocess.run(["git", "-C", REPO, "add", "-A"], capture_output=True)
        subprocess.run([
            "git", "-C", REPO, "commit", "-m", 
            f"auto: health check {datetime.now().strftime('%Y%m%d_%H%M%S')}"
        ], capture_output=True)
        r2 = subprocess.run(
            ["git", "-C", REPO, "push", "origin", "main"],
            capture_output=True, text=True, timeout=15
        )
        if r2.returncode == 0:
            log("✅ auto-pushed")
        else:
            log(f"⚠️ push failed: {r2.stderr.strip()[:80]}")
    else:
        log("no changes to push")

if __name__ == "__main__":
    log("=== Self-Evolution Health Check ===")
    
    pushed = check_unpushed()
    syntax_ok = check_syntax()
    check_moltbook()
    
    auto_fix = False
    
    # Auto-fix unpushed commits
    if pushed > 0:
        r = subprocess.run(
            ["git", "-C", REPO, "push", "origin", "main"],
            capture_output=True, text=True, timeout=15
        )
        if r.returncode == 0:
            log(f"✅ auto-pushed {pushed} commit(s)")
            auto_fix = True
        else:
            log(f"⚠️ push still failing: {r.stderr.strip()[:100]}")
    
    if not syntax_ok:
        log("⚠️ Syntax errors found — could rollback but skipping for now")
    
    write_ledger("health_check",
        f"{'pushed' if auto_fix else 'no_fix'}_syntax_{'ok' if syntax_ok else 'fail'}")
    
    push_if_needed()
    log("=== Health Check Complete ===")
