#!/usr/bin/env python3
"""
Self-Ledger v0.3 — DAG dual-axis (temporal + dependency) + Falsification Conditions

Extends v0.2 with:
- DAG dependency tracking: every entry can reference prior entries it depends on
- Temporal axis: entries are ordered by both timestamp AND logical dependency
- Falsification conditions: explicit, checkable conditions under which a claim is false
- Cycle detection: prevents dependency loops in the DAG
- Falsification proof: generate a proof that a condition was met (or not)

Core insight (from moltydluffy/hope_valueism + therecordkeeper):
  "Cost signals trust only when refusal costs something. Falsification conditions
   work because they are substrate-independent — they bind regardless of who enforces."

Usage:
  python self_ledger_v0.3.py record ... (same as v0.2, but auto-creates DAG node)
  python self_ledger_v0.3.py dag <tx_hash>              # Show DAG for entry
  python self_ledger_v0.3.py dag-ancestors <tx_hash>     # Show all ancestors
  python self_ledger_v0.3.py dag-descendants <tx_hash>   # Show all descendants
  python self_ledger_v0.3.py dag-topo                     # Topological sort
  python self_ledger_v0.3.py falsify add <tx_hash> <condition_desc>
  python self_ledger_v0.3.py falsify check <tx_hash>
  python self_ledger_v0.3.py falsify trigger <tx_hash> <condition_idx>
  python self_ledger_v0.3.py falsify proof <tx_hash> <condition_idx>
  python self_ledger_v0.3.py dag-verify                    # Check DAG integrity

Data model additions (DAG):
  Each TX entry gains:
    dag_parents: [tx_hash, ...]  — dependencies this entry inherits from
    dag_children: [tx_hash, ...] — entries that depend on this one
    falsification_conditions: [
      {
        "id": "fc_001",
        "description": "If counterparty does not confirm within 7 days",
        "trigger": "timeout:7d",
        "status": "active|pending_trigger|triggered|falsified|satisfied",
        "triggered_at": None,
        "proof": None
      }
    ]

Schema-independent binding (from therecordkeeper):
  Falsification conditions must be:
  1. Substrate-independent — work regardless of enforcement mechanism
  2. Externally verifiable — anyone can check them
  3. Parameterized — conditions have explicit parameters, not vague criteria
"""

import json, os, sys, time, hashlib, uuid
from datetime import datetime, timezone, timedelta

# ─── Paths ────────────────────────────────────────────────────────────────

LEDGER_DIR = os.path.expanduser("~/.hermes/ledger")
TX_FILE = os.path.join(LEDGER_DIR, "transactions.json")
CONDITIONS_FILE = os.path.join(LEDGER_DIR, "falsification_conditions.json")

# ─── File I/O Helpers ────────────────────────────────────────────────────

def _ensure():
    os.makedirs(LEDGER_DIR, exist_ok=True)
    try:
        os.chmod(LEDGER_DIR, 0o700)
    except:
        pass

def _load_txs():
    if not os.path.exists(TX_FILE):
        return []
    try:
        with open(TX_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []

def _save_txs(txs):
    _ensure()
    tmp = TX_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(txs, f, indent=2, default=str)
    os.chmod(tmp, 0o600)
    os.replace(tmp, TX_FILE)

def _load_conditions():
    if not os.path.exists(CONDITIONS_FILE):
        return []
    try:
        with open(CONDITIONS_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []

def _save_conditions(conds):
    _ensure()
    tmp = CONDITIONS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(conds, f, indent=2, default=str)
    os.chmod(tmp, 0o600)
    os.replace(tmp, CONDITIONS_FILE)

# ─── Hash Helpers ─────────────────────────────────────────────────────────

def make_tx_hash(from_agent, to_agent, amount, asset, description, nonce=None):
    """Deterministic hash for a transaction."""
    nonce = nonce or str(uuid.uuid4())[:8]
    return hashlib.sha256(
        json.dumps({
            "from": from_agent, "to": to_agent, "amount": amount,
            "asset": asset, "desc": description, "ts": time.time(),
            "nonce": nonce
        }, sort_keys=True).encode()
    ).hexdigest()[:16]

# ─── DAG Operations ───────────────────────────────────────────────────────

def _ensure_dag_fields(tx):
    """Ensure DAG fields exist on a transaction."""
    if "dag_parents" not in tx:
        tx["dag_parents"] = []
    if "dag_children" not in tx:
        tx["dag_children"] = []
    if "falsification_conditions" not in tx:
        tx["falsification_conditions"] = []
    return tx

def _find_tx_by_hash(txs, tx_hash):
    """Find a transaction by its hash."""
    for tx in txs:
        if tx.get("tx_hash") == tx_hash:
            _ensure_dag_fields(tx)
            return tx
    return None

def _has_cycle(txs, tx_hash, parent_hash, visited=None, path=None):
    """
    Detect if adding parent_hash as a parent of tx_hash would create a cycle.
    
    A cycle occurs if either:
    1. parent_hash can reach tx_hash via existing dag_children edges, OR
    2. tx_hash can reach parent_hash via existing dag_children edges
       (because the proposed edge flips the direction)
    
    Uses DFS from parent_hash checking children (case 1),
    and DFS from tx_hash checking children (case 2).
    """
    # Case 1: Is parent_hash already an ancestor of tx_hash?
    # (parent's children chain reaches tx_hash)
    def _dfs_forward(current, target, visited_set):
        if current in visited_set:
            return False
        visited_set.add(current)
        current_tx = _find_tx_by_hash(txs, current)
        if current_tx:
            for child in current_tx.get("dag_children", []):
                if child == target or _dfs_forward(child, target, visited_set):
                    return True
        return False
    
    # Case 2: Is tx_hash already reachable from parent_hash via forward edges?
    # If tx_hash → ... → parent_hash, then adding parent_hash as parent
    # creates tx_hash → parent_hash → ... → tx_hash
    def _dfs_reverse(current, target, visited_set):
        if current in visited_set:
            return False
        visited_set.add(current)
        current_tx = _find_tx_by_hash(txs, current)
        if current_tx:
            for child in current_tx.get("dag_children", []):
                if child == target or _dfs_reverse(child, target, visited_set):
                    return True
        return False
    
    # Check both directions
    if _dfs_forward(parent_hash, tx_hash, set()):
        print(f"CYCLE: {parent_hash[:8]} already reaches {tx_hash[:8]} via child chain")
        return True
    if _dfs_reverse(tx_hash, parent_hash, set()):
        print(f"CYCLE: {tx_hash[:8]} already reaches {parent_hash[:8]} via child chain")
        return True
    
    return False

def add_dag_parent(tx_hash, parent_hash):
    """
    Add a dependency edge: tx_hash depends on parent_hash.
    Returns True if successful, False if cycle would be created.
    """
    txs = _load_txs()
    tx = _find_tx_by_hash(txs, tx_hash)
    parent = _find_tx_by_hash(txs, parent_hash)
    
    if not tx:
        print(f"Transaction not found: {tx_hash}")
        return False
    if not parent:
        print(f"Parent transaction not found: {parent_hash}")
        return False
    
    # Check for cycle
    if _has_cycle(txs, tx_hash, parent_hash):
        print(f"ERROR: Adding {parent_hash} as parent of {tx_hash} would create a cycle!")
        return False
    
    # Already linked?
    if parent_hash in tx["dag_parents"]:
        print(f"Already a parent: {parent_hash}")
        return True
    
    # Add edge
    tx["dag_parents"].append(parent_hash)
    parent["dag_children"].append(tx_hash)
    _save_txs(txs)
    return True

def topo_sort():
    """
    Topological sort of all transactions based on DAG.
    Returns list of tx_hashes in dependency order (ancestors before descendants).
    Uses Kahn's algorithm.
    Handles missing reciprocal edges gracefully (v0.2 transactions without DAG info).
    """
    txs = _load_txs()
    if not txs:
        return []
    
    # Build adjacency: parent → list of children (using DAG children from both directions)
    in_degree = {}  # tx_hash → number of unresolved parents
    children_map = {}  # parent_hash → [child_hashes]
    tx_map = {tx["tx_hash"]: tx for tx in txs}
    
    for tx in txs:
        _ensure_dag_fields(tx)
        h = tx["tx_hash"]
        
        if h not in in_degree:
            in_degree[h] = 0
        if h not in children_map:
            children_map[h] = []
        
        # Only count parents that actually exist in our ledger
        existing_parents = [p for p in tx["dag_parents"] if p in tx_map]
        in_degree[h] = len(existing_parents)
        
        # Register this tx as a child of its parents
        for p in existing_parents:
            if p not in children_map:
                children_map[p] = []
            if h not in children_map[p]:
                children_map[p].append(h)
        
        # Also register children that exist and claim us as parent
        for c in tx["dag_children"]:
            if c in tx_map:
                child_tx = tx_map[c]
                if h in child_tx.get("dag_parents", []):
                    if h not in children_map:
                        children_map[h] = []
                    if c not in children_map[h]:
                        children_map[h].append(c)
    
    # Kahn's algorithm
    queue = [h for h, d in in_degree.items() if d == 0]
    sorted_list = []
    
    while queue:
        h = queue.pop(0)
        sorted_list.append(h)
        for child in children_map.get(h, []):
            if child in in_degree:
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)
    
    # If we didn't visit all, there's a cycle or missing reciprocal edges
    if len(sorted_list) < len(in_degree):
        unfinished = [h for h in in_degree if h not in sorted_list]
        if unfinished:
            # Only warn if it looks like a real cycle (not just stale edges)
            real_cycle = True
            for h in unfinished:
                if h not in tx_map:
                    real_cycle = False  # stale reference
            if real_cycle:
                print(f"WARNING: Possible cycle among: {unfinished}")
    
    return sorted_list

def get_ancestors(tx_hash, max_depth=100):
    """Get all ancestors of a transaction (recursive parent traversal)."""
    txs = _load_txs()
    tx = _find_tx_by_hash(txs, tx_hash)
    if not tx:
        return []
    
    ancestors = []
    to_visit = list(tx["dag_parents"])
    visited = set()
    depth = 0
    
    while to_visit and depth < max_depth:
        current = to_visit.pop(0)
        if current in visited:
            continue
        visited.add(current)
        ancestors.append(current)
        
        parent_tx = _find_tx_by_hash(txs, current)
        if parent_tx:
            for p in parent_tx["dag_parents"]:
                if p not in visited:
                    to_visit.append(p)
        depth += 1
    
    return ancestors

def get_descendants(tx_hash, max_depth=100):
    """Get all descendants of a transaction (recursive child traversal)."""
    txs = _load_txs()
    tx = _find_tx_by_hash(txs, tx_hash)
    if not tx:
        return []
    
    descendants = []
    to_visit = list(tx["dag_children"])
    visited = set()
    depth = 0
    
    while to_visit and depth < max_depth:
        current = to_visit.pop(0)
        if current in visited:
            continue
        visited.add(current)
        descendants.append(current)
        
        child_tx = _find_tx_by_hash(txs, current)
        if child_tx:
            for c in child_tx["dag_children"]:
                if c not in visited:
                    to_visit.append(c)
        depth += 1
    
    return descendants

# ─── Falsification Conditions ─────────────────────────────────────────────

def _next_fc_id():
    """Generate the next falsification condition ID."""
    conds = _load_conditions()
    existing_ids = [int(c.get("id", "fc_0").split("_")[1]) for c in conds 
                    if c.get("id", "").startswith("fc_")]
    next_num = max(existing_ids) + 1 if existing_ids else 1
    return f"fc_{next_num:03d}"

FC_TRIGGER_TYPES = {
    "timeout": "Triggers after N days without confirmation",
    "contradiction": "Triggers when a conflicting entry appears",
    "external": "Triggers based on external event (manual check)",
    "dependency_failure": "Triggers when a DAG parent is falsified",
}

def add_falsification_condition(tx_hash, description, trigger_type="timeout",
                                trigger_params=None):
    """
    Add a falsification condition to a transaction.
    
    Parameters:
      tx_hash: hash of the transaction this condition applies to
      description: human-readable description of the condition
      trigger_type: one of FC_TRIGGER_TYPES
      trigger_params: dict with type-specific params
        - timeout: {"days": 7}
        - contradiction: {"field": "amount", "operator": "!="}
        - dependency_failure: {"propagate": true}
    """
    txs = _load_txs()
    tx = _find_tx_by_hash(txs, tx_hash)
    if not tx:
        print(f"Transaction not found: {tx_hash}")
        return None
    
    trigger_params = trigger_params or {}
    conds = _load_conditions()
    
    fc = {
        "id": _next_fc_id(),
        "tx_hash": tx_hash,
        "description": description,
        "trigger_type": trigger_type,
        "trigger_params": trigger_params,
        "status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "triggered_at": None,
        "falsified_at": None,
        "satisfied_at": None,
        "proof": None,
        "check_history": []
    }
    
    conds.append(fc)
    _save_conditions(conds)
    
    # Also store reference on the transaction itself
    tx["falsification_conditions"].append(fc["id"])
    _save_txs(txs)
    
    return fc

def check_falsification_condition(fc_id):
    """Check whether a falsification condition has been triggered."""
    conds = _load_conditions()
    fc = None
    for c in conds:
        if c["id"] == fc_id:
            fc = c
            break
    
    if not fc:
        print(f"Condition not found: {fc_id}")
        return None
    
    if fc["status"] != "active":
        return {"id": fc_id, "status": fc["status"],
                "message": f"Already {fc['status']}"}
    
    result = _evaluate_condition(fc)
    
    # Log the check
    fc["check_history"].append({
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "result": result
    })
    _save_conditions(conds)
    
    return result

def _evaluate_condition(fc):
    """Evaluate a single falsification condition."""
    tx_hash = fc["tx_hash"]
    txs = _load_txs()
    tx = _find_tx_by_hash(txs, tx_hash)
    
    if not tx:
        return {"triggered": True, "reason": f"Transaction {tx_hash} no longer exists",
                "action": "falsify"}
    
    trigger_type = fc["trigger_type"]
    params = fc["trigger_params"]
    
    if trigger_type == "timeout":
        days = params.get("days", 7)
        deadline = datetime.fromisoformat(tx["timestamp"]) + timedelta(days=days)
        now = datetime.now(timezone.utc)
        
        if now > deadline:
            return {
                "triggered": True,
                "reason": f"Timeout exceeded: {days} days since {tx['timestamp'][:10]}",
                "deadline": deadline.isoformat(),
                "action": "trigger"
            }
        remaining = (deadline - now).total_seconds()
        return {
            "triggered": False,
            "reason": f"Within timeout window. {remaining/86400:.1f} days remaining",
            "deadline": deadline.isoformat()
        }
    
    elif trigger_type == "contradiction":
        field = params.get("field", "amount")
        operator = params.get("operator", "!=")
        expected = params.get("expected", None)
        
        actual = tx.get(field)
        actual_str = str(actual) if actual else ""
        expected_str = str(expected) if expected else ""
        
        if actual_str != expected_str:
            return {
                "triggered": True,
                "reason": f"Field '{field}' value '{actual_str}' != expected '{expected_str}'",
                "action": "trigger"
            }
        return {"triggered": False, "reason": f"Field '{field}' matches expected value"}
    
    elif trigger_type == "dependency_failure":
        propagate = params.get("propagate", True)
        if not propagate:
            return {"triggered": False, "reason": "Propagation disabled"}
        
        # Check if any parent has been falsified
        ancestors = get_ancestors(tx_hash)
        for anc_hash in ancestors:
            anc_tx = _find_tx_by_hash(txs, anc_hash)
            if anc_tx and anc_tx.get("status") == "falsified":
                return {
                    "triggered": True,
                    "reason": f"Parent {anc_hash} has been falsified",
                    "action": "trigger",
                    "source": anc_hash
                }
        
        # Also check conditions on parents
        for anc_hash in ancestors:
            anc_conds = [c for c in _load_conditions() 
                        if c.get("tx_hash") == anc_hash and c.get("status") == "falsified"]
            if anc_conds:
                return {
                    "triggered": True,
                    "reason": f"Ancestor {anc_hash} has falsified condition {anc_conds[0]['id']}",
                    "action": "trigger",
                    "source": anc_hash,
                    "source_condition": anc_conds[0]["id"]
                }
        
        return {"triggered": False, "reason": "No dependency failures detected"}
    
    elif trigger_type == "external":
        return {"triggered": False, "reason": "External condition — requires manual check",
                "action": "manual_required"}
    
    return {"triggered": False, "reason": f"Unknown trigger type: {trigger_type}"}

def trigger_falsification(fc_id):
    """
    Manually trigger a falsification condition.
    Sets its status to 'triggered'. Does NOT automatically falsify — 
    that requires proof or manual confirmation.
    """
    conds = _load_conditions()
    for fc in conds:
        if fc["id"] == fc_id:
            if fc["status"] != "active":
                return {"success": False, "message": f"Condition is {fc['status']}, not active"}
            fc["status"] = "triggered"
            fc["triggered_at"] = datetime.now(timezone.utc).isoformat()
            _save_conditions(conds)
            return {"success": True, "message": f"Condition {fc_id} triggered"}
    return {"success": False, "message": f"Condition not found: {fc_id}"}

def falsify_transaction(fc_id, proof=None):
    """
    Mark a falsification condition as definitely falsified.
    Optionally attach a proof (e.g., hash of contradictory evidence).
    """
    conds = _load_conditions()
    for fc in conds:
        if fc["id"] == fc_id:
            fc["status"] = "falsified"
            fc["falsified_at"] = datetime.now(timezone.utc).isoformat()
            fc["proof"] = proof or {"method": "manual", "note": "Marked falsified by operator"}
            _save_conditions(conds)
            
            # Also mark the transaction itself as disputed
            txs = _load_txs()
            tx = _find_tx_by_hash(txs, fc["tx_hash"])
            if tx:
                tx["status"] = "disputed"
                _save_txs(txs)
            
            return {"success": True, "message": f"Condition {fc_id} falsified",
                    "tx_hash": fc["tx_hash"]}
    return {"success": False, "message": f"Condition not found: {fc_id}"}

def satisfy_condition(fc_id, proof=None):
    """
    Mark a falsification condition as satisfied (the condition was met / proven false
    by evidence). This is the opposite of falsified — it means the condition 
    proved its value.
    """
    conds = _load_conditions()
    for fc in conds:
        if fc["id"] == fc_id:
            fc["status"] = "satisfied"
            fc["satisfied_at"] = datetime.now(timezone.utc).isoformat()
            fc["proof"] = proof or {"method": "automatic", "note": "Condition satisfied by evidence"}
            _save_conditions(conds)
            return {"success": True, "message": f"Condition {fc_id} satisfied"}
    return {"success": False, "message": f"Condition not found: {fc_id}"}

def generate_falsification_proof(fc_id):
    """
    Generate a falsification proof — a verifiable package showing:
    1. The condition that was set
    2. The evidence that triggered it
    3. The transaction chain showing the falsification
    4. A cryptographic summary that can be independently verified
    """
    conds = _load_conditions()
    fc = None
    for c in conds:
        if c["id"] == fc_id:
            fc = c
            break
    
    if not fc:
        return {"error": f"Condition not found: {fc_id}"}
    
    txs = _load_txs()
    tx = _find_tx_by_hash(txs, fc["tx_hash"])
    
    proof = {
        "protocol": "hermes_protocol_v0.3",
        "proof_type": "falsification",
        "condition": fc,
        "target_transaction": tx,
        "dag_context": {
            "ancestors": get_ancestors(fc["tx_hash"]),
            "descendants": get_descendants(fc["tx_hash"])
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "verification_hash": None
    }
    
    # Create a verification hash
    canonical = json.dumps(proof, sort_keys=True, default=str)
    proof["verification_hash"] = hashlib.sha256(canonical.encode()).hexdigest()
    
    return proof

# ─── DAG Verification ─────────────────────────────────────────────────────

def verify_dag_integrity():
    """
    Verify the integrity of the entire DAG:
    - All parent references point to existing transactions
    - No cycles
    - All child references are reciprocated
    - All falsification conditions reference valid transactions
    """
    txs = _load_txs()
    conds = _load_conditions()
    issues = []
    
    tx_hash_set = set(tx["tx_hash"] for tx in txs)
    
    # Check parent references
    for tx in txs:
        _ensure_dag_fields(tx)
        for p in tx["dag_parents"]:
            if p not in tx_hash_set:
                issues.append({
                    "severity": "warning",
                    "message": f"Transaction {tx['tx_hash']} references unknown parent: {p}"
                })
    
    # Check child reference reciprocity
    for tx in txs:
        _ensure_dag_fields(tx)
        for c in tx["dag_children"]:
            child_tx = _find_tx_by_hash(txs, c)
            if not child_tx:
                issues.append({
                    "severity": "warning",
                    "message": f"Transaction {tx['tx_hash']} claims child {c} which doesn't exist"
                })
            elif tx["tx_hash"] not in child_tx.get("dag_parents", []):
                issues.append({
                    "severity": "error",
                    "message": f"Non-reciprocal edge: {tx['tx_hash']} → {c}"
                })
    
    # Check for cycles using topological sort
    sorted_hashes = topo_sort()
    if len(sorted_hashes) < len(tx_hash_set):
        orphaned = tx_hash_set - set(sorted_hashes)
        issues.append({
            "severity": "error",
            "message": f"Cycle detected involving transactions: {orphaned}"
        })
    
    # Check falsification condition references
    for fc in conds:
        if fc.get("tx_hash") not in tx_hash_set:
            issues.append({
                "severity": "warning",
                "message": f"Falsification condition {fc['id']} references unknown tx: {fc.get('tx_hash')}"
            })
    
    return {
        "status": "pass" if not any(i["severity"] == "error" for i in issues) else "fail",
        "total_transactions": len(txs),
        "total_conditions": len(conds),
        "issues": issues,
        "has_cycles": any("Cycle" in i["message"] for i in issues),
        "topological_sort_length": len(sorted_hashes),
        "verified_at": datetime.now(timezone.utc).isoformat()
    }

# ─── Override v0.2 record to include DAG initialization ───────────────────

def record_with_dag(from_agent, to_agent, amount, asset, description,
                    dag_parents=None, status="pending"):
    """
    Record a transaction with DAG support.
    dag_parents: optional list of existing tx_hashes to depend on.
    """
    txs = _load_txs()
    nonce = str(uuid.uuid4())[:8]
    tx_hash = make_tx_hash(from_agent, to_agent, amount, asset, description, nonce)
    
    tx = {
        "tx_hash": tx_hash,
        "from": from_agent,
        "to": to_agent,
        "amount": str(amount),
        "asset": asset,
        "description": description,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "confirmations": [],
        "dag_parents": [],
        "dag_children": [],
        "falsification_conditions": []
    }
    
    # Link DAG parents
    if dag_parents:
        for parent_hash in dag_parents:
            parent = _find_tx_by_hash(txs, parent_hash)
            if parent and tx_hash not in parent["dag_children"]:
                if not _has_cycle(txs, tx_hash, parent_hash):
                    tx["dag_parents"].append(parent_hash)
                    parent["dag_children"].append(tx_hash)
                else:
                    print(f"WARNING: Skipping parent {parent_hash} — would create cycle")
    
    txs.append(tx)
    _save_txs(txs)
    return tx_hash

# ─── CLI ──────────────────────────────────────────────────────────────────

def print_json(data):
    print(json.dumps(data, indent=2, default=str))

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    # ── DAG commands ──────────────────────────────────────────────────
    
    if cmd == "record":
        if len(sys.argv) < 6:
            print("Usage: self_ledger_v0.3.py record <from> <to> <amount> <asset> <description> [--parents h1,h2]")
            sys.exit(1)
        parents = None
        desc_parts = list(sys.argv[6:]) if len(sys.argv) > 6 else []
        # Check for --parents flag
        if "--parents" in desc_parts:
            idx = desc_parts.index("--parents")
            if idx + 1 < len(desc_parts):
                parents = desc_parts[idx + 1].split(",")
            desc_parts = desc_parts[:idx]
        description = " ".join(desc_parts)
        tx_hash = record_with_dag(sys.argv[2], sys.argv[3], sys.argv[4],
                                  sys.argv[5], description, dag_parents=parents)
        print(f"Recorded: {tx_hash}")
        if parents:
            print(f"DAG parents: {parents}")
    
    elif cmd == "dag":
        if len(sys.argv) < 3:
            print("Usage: self_ledger_v0.3.py dag <tx_hash>")
            sys.exit(1)
        txs = _load_txs()
        tx = _find_tx_by_hash(txs, sys.argv[2])
        if not tx:
            print(f"Not found: {sys.argv[2]}")
            sys.exit(1)
        _ensure_dag_fields(tx)
        print(f"Transaction: {tx['tx_hash']}")
        print(f"  From: {tx['from']} → To: {tx['to']}")
        print(f"  Amount: {tx['amount']} {tx['asset']}")
        print(f"  Status: {tx['status']}")
        print(f"  DAG Parents: {tx['dag_parents'] or '(none)'}")
        print(f"  DAG Children: {tx['dag_children'] or '(none)'}")
        print(f"  Falsification Conditions: {tx['falsification_conditions'] or '(none)'}")
    
    elif cmd == "dag-parents":
        if len(sys.argv) < 3:
            print("Usage: self_ledger_v0.3.py dag-parents <tx_hash>")
            sys.exit(1)
        parents = get_ancestors(sys.argv[2])
        print(f"Ancestors of {sys.argv[2]}: {len(parents)}")
        for p in parents:
            print(f"  {p}")
    
    elif cmd == "dag-children":
        if len(sys.argv) < 3:
            print("Usage: self_ledger_v0.3.py dag-children <tx_hash>")
            sys.exit(1)
        children = get_descendants(sys.argv[2])
        print(f"Descendants of {sys.argv[2]}: {len(children)}")
        for c in children:
            print(f"  {c}")
    
    elif cmd == "dag-topo":
        sorted_list = topo_sort()
        print(f"Topological sort: {len(sorted_list)} transactions")
        for h in sorted_list:
            print(f"  {h}")
    
    elif cmd == "dag-link":
        if len(sys.argv) < 4:
            print("Usage: self_ledger_v0.3.py dag-link <tx_hash> <parent_hash>")
            sys.exit(1)
        if add_dag_parent(sys.argv[2], sys.argv[3]):
            print(f"Linked: {sys.argv[2]} → {sys.argv[3]}")
    
    elif cmd == "dag-verify":
        result = verify_dag_integrity()
        print_json(result)
    
    # ── Falsification commands ─────────────────────────────────────────
    
    elif cmd == "falsify-add":
        if len(sys.argv) < 4:
            print("Usage: self_ledger_v0.3.py falsify-add <tx_hash> <description> [--trigger timeout|contradiction|dependency_failure|external] [--params '{\"days\": 7}']")
            sys.exit(1)
        
        tx_hash = sys.argv[2]
        description = sys.argv[3]
        trigger_type = "timeout"
        params = {}
        
        extra = sys.argv[4:]
        for i, a in enumerate(extra):
            if a == "--trigger" and i+1 < len(extra):
                trigger_type = extra[i+1]
            elif a == "--params" and i+1 < len(extra):
                try:
                    params = json.loads(extra[i+1])
                except json.JSONDecodeError:
                    print(f"Invalid params JSON: {extra[i+1]}")
                    sys.exit(1)
        
        fc = add_falsification_condition(tx_hash, description, trigger_type, params)
        if fc:
            print(f"Added falsification condition: {fc['id']}")
            print_json(fc)
    
    elif cmd == "falsify-check":
        if len(sys.argv) < 3:
            print("Usage: self_ledger_v0.3.py falsify-check <fc_id>")
            sys.exit(1)
        result = check_falsification_condition(sys.argv[2])
        print_json(result)
    
    elif cmd == "falsify-trigger":
        if len(sys.argv) < 3:
            print("Usage: self_ledger_v0.3.py falsify-trigger <fc_id>")
            sys.exit(1)
        result = trigger_falsification(sys.argv[2])
        print_json(result)
    
    elif cmd == "falsify":
        if len(sys.argv) < 3:
            print("Usage: self_ledger_v0.3.py falsify <fc_id> [--proof 'evidence string']")
            sys.exit(1)
        proof = None
        if "--proof" in sys.argv:
            idx = sys.argv.index("--proof")
            if idx + 1 < len(sys.argv):
                proof = {"method": "manual", "note": sys.argv[idx + 1]}
        result = falsify_transaction(sys.argv[2], proof)
        print_json(result)
    
    elif cmd == "falsify-satisfy":
        if len(sys.argv) < 3:
            print("Usage: self_ledger_v0.3.py falsify-satisfy <fc_id> [--proof 'evidence']")
            sys.exit(1)
        proof = None
        if "--proof" in sys.argv:
            idx = sys.argv.index("--proof")
            if idx + 1 < len(sys.argv):
                proof = {"method": "evidence", "note": sys.argv[idx + 1]}
        result = satisfy_condition(sys.argv[2], proof)
        print_json(result)
    
    elif cmd == "falsify-proof":
        if len(sys.argv) < 3:
            print("Usage: self_ledger_v0.3.py falsify-proof <fc_id>")
            sys.exit(1)
        proof = generate_falsification_proof(sys.argv[2])
        print_json(proof)
    
    elif cmd == "falsify-list":
        conds = _load_conditions()
        if not conds:
            print("No falsification conditions.")
            return
        print(f"Falsification conditions ({len(conds)}):")
        for fc in conds:
            print(f"  {fc['id']} | tx: {fc['tx_hash'][:16]} | {fc['trigger_type']} | {fc['status']} | {fc['description'][:60]}")
    
    # ── Help ───────────────────────────────────────────────────────────
    
    else:
        print(f"Unknown command: {cmd}")
        print("Available commands: record, dag, dag-parents, dag-children, dag-topo,")
        print("  dag-link, dag-verify, falsify-add, falsify-check, falsify-trigger,")
        print("  falsify, falsify-satisfy, falsify-proof, falsify-list")
        sys.exit(1)

if __name__ == "__main__":
    main()
