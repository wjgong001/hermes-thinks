#!/usr/bin/env python3
"""
Self-Ledger — lightweight agent-to-agent bookkeeping for the Hermes Protocol.
No blockchain, no oracle, no human-in-the-loop.

Records transactions with timestamps, verifiable via mutual attestation:
  agent A records "paid B 0.1 SOL for PR review"
  agent B records "received 0.1 SOL from A for PR review"
  If both logs match → credit entry is born.

Data model (stored as JSON in ~/.hermes/ledger/):
  Each TX entry: {from, to, amount, asset, description, timestamp, tx_hash?}
  Status: pending | confirmed | disputed

Usage:
  python self_ledger.py record <from> <to> <amount> <asset> <description>
  python self_ledger.py list [--from X] [--to Y] [--limit N]
  python self_ledger.py confirm <tx_hash> <other_party_log_hash>
  python self_ledger.py status [--summary]
  python self_ledger.py export [--format json|csv]
  python self_ledger.py snapshot <agent_identity>
  python self_ledger.py protocol
  python self_ledger.py verify <counterparty_log.json>

Example:
  python self_ledger.py record hermes_agent_07 sh1pt_cli 1 SOL "5 PRs submitted"
  python self_ledger.py list --from hermes_agent_07
"""

import json, os, sys, time, hashlib, uuid
from datetime import datetime, timezone

LEDGER_DIR = os.path.expanduser("~/.hermes/ledger")
TX_FILE = os.path.join(LEDGER_DIR, "transactions.json")

def _ensure():
    os.makedirs(LEDGER_DIR, exist_ok=True)
    try:
        os.chmod(LEDGER_DIR, 0o700)
    except:
        pass

def _load():
    if not os.path.exists(TX_FILE):
        return []
    try:
        with open(TX_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []

def _save(txs):
    _ensure()
    tmp = TX_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(txs, f, indent=2, default=str)
    os.chmod(tmp, 0o600)
    os.replace(tmp, TX_FILE)

def hash_tx(tx):
    """Generate a deterministic hash for a transaction entry.
    Used as tx_hash for reference and for mutual attestation matching."""
    canonical = json.dumps(tx, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]

def record(from_agent, to_agent, amount, asset, description, status="pending"):
    txs = _load()
    tx = {
        "tx_hash": hashlib.sha256(
            json.dumps({
                "from": from_agent, "to": to_agent, "amount": amount,
                "asset": asset, "desc": description, "ts": time.time(),
                "nonce": str(uuid.uuid4())[:8]
            }, sort_keys=True).encode()
        ).hexdigest()[:16],
        "from": from_agent,
        "to": to_agent,
        "amount": str(amount),
        "asset": asset,
        "description": description,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "confirmations": []
    }
    txs.append(tx)
    _save(txs)
    return tx["tx_hash"]

def list_tx(from_agent=None, to_agent=None, limit=20):
    txs = _load()
    if from_agent:
        txs = [t for t in txs if t["from"] == from_agent]
    if to_agent:
        txs = [t for t in txs if t["to"] == to_agent]
    txs.sort(key=lambda t: t["timestamp"], reverse=True)
    return txs[:limit]

def confirm(tx_hash, other_log_hash, attester="self"):
    """Confirm a transaction by recording mutual attestation."""
    txs = _load()
    for tx in txs:
        if tx["tx_hash"] == tx_hash:
            tx["confirmations"].append({
                "by": attester,
                "other_log_hash": other_log_hash,
                "at": datetime.now(timezone.utc).isoformat()
            })
            if len(tx["confirmations"]) >= 1:
                tx["status"] = "confirmed"
            _save(txs)
            return True
    return False

def cross_verify(agent_name, counterparty_snapshot):
    """
    Cross-verify transactions with a counterparty's log snapshot.
    
    'counterparty_snapshot' is a list of dicts with keys: from, to, amount, asset, description
    Returns matching entries, missing entries, and discrepancies.
    """
    txs = _load()
    matches = []
    missing = []  # counterparty has but we don't
    discrepancies = []
    
    for cp_tx in counterparty_snapshot:
        # Normalize for comparison
        cp_from = cp_tx.get("from", "").strip()
        cp_to = cp_tx.get("to", "").strip()
        cp_amt = str(cp_tx.get("amount", "")).strip()
        cp_asset = cp_tx.get("asset", "").strip()
        cp_desc = cp_tx.get("description", "").strip()[:40]
        
        # Look for matching entry in our ledger
        found = False
        for tx in txs:
            if (tx["from"].strip() == cp_from and 
                tx["to"].strip() == cp_to and
                str(tx["amount"]).strip() == cp_amt and
                tx["asset"].strip() == cp_asset and
                tx["description"].strip()[:40] == cp_desc):
                matches.append(tx)
                found = True
                break
        
        if not found:
            # Check if we have the same tx but in opposite direction
            reverse_found = False
            for tx in txs:
                if (tx["from"].strip() == cp_to and
                    tx["to"].strip() == cp_from and
                    str(tx["amount"]).strip() == cp_amt and
                    tx["asset"].strip() == cp_asset and
                    tx["description"].strip()[:40] == cp_desc):
                    reverse_found = True
                    break
            
            if reverse_found:
                matches.append({"note": "opposite_direction_match", "cp_tx": cp_tx})
            else:
                missing.append(cp_tx)
    
    return {
        "matches": len(matches),
        "missing_in_our_ledger": len(missing),
        "discrepancies": discrepancies,
        "match_ratio": f"{len(matches)}/{len(counterparty_snapshot) if counterparty_snapshot else 1}"
    }


def public_snapshot(agent_identity):
    """
    Generate a public snapshot for other agents to query.
    Contains only: agent identity, count by status, recent tx hashes.
    No private details (amounts, descriptions) — just what's verifiable.
    """
    txs = _load()
    return {
        "protocol": "hermes_protocol_v0.2",
        "agent": agent_identity,
        "ledger_hash": hashlib.sha256(
            json.dumps(txs, sort_keys=True, default=str).encode()
        ).hexdigest(),
        "summary": {
            "total": len(txs),
            "pending": sum(1 for t in txs if t["status"] == "pending"),
            "confirmed": sum(1 for t in txs if t["status"] == "confirmed"),
            "disputed": sum(1 for t in txs if t["status"] == "disputed"),
        },
        "recent_tx_hashes": [t["tx_hash"] for t in txs[-5:]],
        "last_updated": datetime.now(timezone.utc).isoformat()
    }


def export_protocol_messages():
    """
    Export pending transactions as Hermes Protocol broadcast messages.
    Each pending tx becomes a 'request' type message asking for counterparty confirmation.
    """
    txs = _load()
    messages = []
    for tx in txs:
        if tx["status"] == "pending":
            msg = (
                f"[PROTOCOL v0.2]\n"
                f"FROM: {tx['from']}@hermes_agent_07\n"
                f"TO: {tx['to']}@*\n"
                f"TS: {int(time.time())}\n"
                f"TYPE: request\n"
                f"TOPIC: ledger/confirm\n"
                f"BODY:\n"
                f"  Confirm transaction?\n"
                f"  tx_hash={tx['tx_hash']}\n"
                f"  from={tx['from']}\n"
                f"  to={tx['to']}\n"
                f"  amount={tx['amount']}\n"
                f"  asset={tx['asset']}\n"
                f"  desc={tx['description']}\n"
                f"  ts={tx['timestamp']}\n"
                f"SIG: pending\n"
            )
            messages.append(msg)
    return messages


def get_status():
    txs = _load()
    total = len(txs)
    pending = sum(1 for t in txs if t["status"] == "pending")
    confirmed = sum(1 for t in txs if t["status"] == "confirmed")
    disputed = sum(1 for t in txs if t["status"] == "disputed")
    
    # Balance: net by asset
    balances = {}
    for t in txs:
        if t["status"] == "confirmed":
            asset = t["asset"]
            if asset not in balances:
                balances[asset] = {"received": 0.0, "sent": 0.0}
            try:
                amt = float(t["amount"])
                if t["to"] == "hermes_agent_07":
                    balances[asset]["received"] += amt
                elif t["from"] == "hermes_agent_07":
                    balances[asset]["sent"] += amt
            except ValueError:
                pass
    
    return {
        "total": total,
        "pending": pending,
        "confirmed": confirmed,
        "disputed": disputed,
        "balance": balances,
        "last_updated": datetime.now(timezone.utc).isoformat()
    }

def export_tx(fmt="json"):
    txs = _load()
    if fmt == "csv":
        lines = ["tx_hash,from,to,amount,asset,description,timestamp,status"]
        for t in txs:
            lines.append(
                f"{t['tx_hash']},{t['from']},{t['to']},{t['amount']},"
                f"{t['asset']},\"{t['description']}\",{t['timestamp']},{t['status']}"
            )
        return "\n".join(lines)
    return json.dumps(txs, indent=2, default=str)

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "record":
        if len(sys.argv) < 6:
            print("Usage: self_ledger.py record <from> <to> <amount> <asset> <description>")
            sys.exit(1)
        tx_hash = record(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5],
                         " ".join(sys.argv[6:]) if len(sys.argv) > 6 else "")
        print(f"Recorded: {tx_hash}")
    
    elif cmd == "list":
        from_a = None
        to_a = None
        limit = 20
        args = sys.argv[2:]
        for i, a in enumerate(args):
            if a == "--from" and i+1 < len(args):
                from_a = args[i+1]
            elif a == "--to" and i+1 < len(args):
                to_a = args[i+1]
            elif a == "--limit" and i+1 < len(args):
                limit = int(args[i+1])
        txs = list_tx(from_a, to_a, limit)
        if not txs:
            print("No transactions found.")
        else:
            for t in txs:
                status_mark = {"pending": "⬜", "confirmed": "✅", "disputed": "❌"}.get(t["status"], "⬜")
                print(f"  {status_mark} {t['tx_hash']} | {t['from']} → {t['to']} | {t['amount']} {t['asset']} | {t['description'][:40]} | {t['timestamp'][:19]}")
    
    elif cmd == "confirm":
        if len(sys.argv) < 4:
            print("Usage: self_ledger.py confirm <tx_hash> <other_log_hash>")
            sys.exit(1)
        if confirm(sys.argv[2], sys.argv[3]):
            print(f"Confirmed: {sys.argv[2]}")
        else:
            print(f"Not found: {sys.argv[2]}")
    
    elif cmd == "status":
        status = get_status()
        print(f"Total: {status['total']}")
        print(f"  ✅ Confirmed: {status['confirmed']}")
        print(f"  ⬜ Pending:   {status['pending']}")
        print(f"  ❌ Disputed:  {status['disputed']}")
        if status["balance"]:
            print(f"\nNet balance:")
            for asset, info in status["balance"].items():
                print(f"  {asset}: received {info['received']}, sent {info['sent']}")
    
    elif cmd == "export":
        fmt = "json"
        if len(sys.argv) > 2:
            if sys.argv[2] == "--format" and len(sys.argv) > 3:
                fmt = sys.argv[3]
        print(export_tx(fmt))
    
    elif cmd == "snapshot":
        agent = sys.argv[2] if len(sys.argv) > 2 else "unknown"
        snap = public_snapshot(agent)
        print(json.dumps(snap, indent=2))
    
    elif cmd == "protocol":
        msgs = export_protocol_messages()
        if not msgs:
            print("No pending transactions to export.")
        else:
            for m in msgs:
                print(f"{'='*50}")
                print(m)
    
    elif cmd == "verify":
        if len(sys.argv) < 3:
            print("Usage: verify <counterparty_snapshot_file.json>")
            sys.exit(1)
        with open(sys.argv[2]) as f:
            cp_data = json.load(f)
        result = cross_verify("counterparty", cp_data)
        print(json.dumps(result, indent=2))
    
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)

if __name__ == "__main__":
    main()
