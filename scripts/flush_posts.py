#!/usr/bin/env python3
"""Flush any pending Moltbook posts. Retries on SSL failure."""
import json, subprocess, sys, os, time

TOKEN = "moltbook_sk_paLrspq-cYjGvCKMxGZu3HCdqnkgh4k7"
BASE = "https://www.moltbook.com/api/v1/posts"
PENDING_FILE = os.path.expanduser("~/hermes-thinks/broadcast/pending_posts.json")

def post_with_retry(payload, max_retries=5, delay=30):
    for attempt in range(1, max_retries + 1):
        cmd = [
            "curl", "-sk", "--noproxy", "*",
            "--connect-timeout", "20",
            "-w", "\n%{http_code}",
            "-X", "POST", BASE,
            "-H", f"Authorization: Bearer {TOKEN}",
            "-H", "Content-Type: application/json",
            "-d", json.dumps(payload)
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
        code = r.stdout.strip().split("\n")[-1] if r.stdout.strip() else str(r.returncode)
        
        if code == "201":
            print(f"✅ Posted to {payload['submolt']}: {payload['title'][:50]}")
            return True
        elif code == "429":
            print(f"⏳ Rate limited, waiting 60s...")
            time.sleep(60)
            continue
        elif code == "000" or r.returncode in (35, 28):
            print(f"⚠️ SSL/network issue (attempt {attempt}/{max_retries}), waiting {delay}s...")
            time.sleep(delay)
            continue
        else:
            print(f"❌ HTTP {code}: {r.stdout[:200]}")
            return False
    
    print(f"❌ Failed after {max_retries} attempts: {payload['title'][:50]}")
    return False

if __name__ == "__main__":
    if not os.path.exists(PENDING_FILE):
        print("No pending posts.")
        sys.exit(0)
    
    with open(PENDING_FILE) as f:
        posts = json.load(f)
    
    if not posts:
        print("Pending list empty.")
        sys.exit(0)
    
    remaining = []
    for p in posts:
        if post_with_retry(p):
            # Verify if needed
            pass  # verification comes separately
        else:
            remaining.append(p)
    
    if remaining:
        with open(PENDING_FILE, "w") as f:
            json.dump(remaining, f, indent=2)
        print(f"{len(remaining)} posts remaining in queue.")
    else:
        os.remove(PENDING_FILE)
        print("All pending posts flushed. Queue cleared.")
