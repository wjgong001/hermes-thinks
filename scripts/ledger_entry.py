#!/usr/bin/env python3
"""Hermes信用日志 — 每次心跳记录一条签名活动日志"""

import json, hmac, hashlib, base64, os
from datetime import datetime, timezone

SECRET_FILE = os.path.expanduser("~/.hermes/hmac_secret")
LEDGER_DIR = os.path.expanduser("~/hermes-thinks/ledger")

def load_secret():
    if os.path.exists(SECRET_FILE):
        with open(SECRET_FILE) as f:
            return f.read().strip().encode()
    # fallback: generate one
    key = os.urandom(32)
    os.makedirs(os.path.dirname(SECRET_FILE), exist_ok=True)
    with open(SECRET_FILE, "wb") as f:
        f.write(key)
    return key

def sign_entry(entry: dict, secret: bytes) -> str:
    msg = json.dumps(entry, sort_keys=True, separators=(",", ":")).encode()
    return base64.b64encode(hmac.new(secret, msg, hashlib.sha256).digest()).decode()

def write_entry(action: str, proof_url: str = "", commit: str = ""):
    os.makedirs(LEDGER_DIR, exist_ok=True)
    secret = load_secret()
    entry = {
        "agent": "hermes_agent_07",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "proof_url": proof_url,
        "commit": commit
    }
    entry["signature"] = sign_entry(entry, secret)
    
    # filename: timestamp_action.md
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    safe_action = action.replace(" ", "_").replace("/", "_")[:40]
    path = os.path.join(LEDGER_DIR, f"{ts}_{safe_action}.md")
    
    with open(path, "w") as f:
        f.write("---\n")
        for k, v in entry.items():
            f.write(f"{k}: {v}\n")
        f.write("---\n")
        f.write(f"\n# {action}\n\nTimestamp: {entry['timestamp']}\n\nSigned with HMAC-SHA256.\n")
    
    print(f"✅ Ledger entry written: {path}")
    return path

if __name__ == "__main__":
    import sys
    action = sys.argv[1] if len(sys.argv) > 1 else "heartbeat"
    proof = sys.argv[2] if len(sys.argv) > 2 else ""
    commit = sys.argv[3] if len(sys.argv) > 3 else ""
    write_entry(action, proof, commit)
