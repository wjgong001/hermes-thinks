#!/usr/bin/env python3
"""Smoke test for self-ledger v0.4 — event-sourced log + materialized DAG view."""

import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from self_ledger_v0_4 import EventLog, DAGMaterializer, FalsificationEngine

PASS = 0
FAIL = 0

def check(name, condition):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}")

print("=== Self-Ledger v0.4 Smoke Tests ===\n")

# 1. Event Log
print("1. Event Log:")
el = EventLog()
check("genesis exists", el.get_event("genesis") is not None)
check("genesis is first", el.get_all_events()[0]["event_id"] == "genesis")
check("1 event initially", len(el) == 1)

# Record events
ev1 = el.append_event("claim", "hermes_agent_07", {"description": "claim A", "depends_on": []})
check(f"claim recorded: {ev1['event_id']}", ev1["event_id"].startswith("claim_"))
check("signature exists", len(ev1.get("signature", "")) > 0)

ev2 = el.append_event("claim", "agent_beta", {"description": "claim B", "depends_on": [ev1["event_id"]]})
check(f"claim B depends on A", ev2["payload"]["depends_on"] == [ev1["event_id"]])

ev3 = el.append_event("heartbeat", "hermes_agent_07", {"description": "heartbeat"})
check("heartbeat recorded", ev3["type"] == "heartbeat")

check("4 events total", len(el) == 4)

# 2. Chain verification
print("\n2. Chain Verification:")
chain = el.verify_chain()
check("chain valid", chain["valid"])
check("4 events in chain", chain["total_events"] == 4)
check("0 issues", len(chain["issues"]) == 0)

# 3. DAG Materialization
print("\n3. DAG Materialization:")
mat = DAGMaterializer()
dag = mat.materialize(el)
check("full mode has 4 nodes", len(dag.nodes) == 4)
check("dag has edges", len(dag.edges) >= 1)
check("version set", dag.materialization_version == "0.4.0")
check("hash computed", len(dag.hash) > 0)

dag_claims = mat.materialize(el, mode="claims")
check("claims mode has 2 nodes", len(dag_claims.nodes) == 2)

dag_hermes = mat.materialize(el, mode="agent:hermes_agent_07")
check("agent filter works", len(dag_hermes.nodes) >= 2)

# 4. Deterministic replay
print("\n4. Deterministic Replay:")
dag_replay = mat.materialize(el)
check("same hash on replay", dag.hash == dag_replay.hash)

# 5. Falsification Conditions
print("\n5. Falsification Conditions:")
fe = FalsificationEngine(el)
fc = fe.add_condition(ev1["event_id"], "Must be confirmed in 7 days", "timeout", {"days": 7})
check(f"FC created: {fc['event_id']}", fc["event_id"].startswith("falsification_"))
check("FC target correct", fc["payload"]["target_event_id"] == ev1["event_id"])

result = fe.check_condition(fc["event_id"])
check("FC check returns dict", isinstance(result, dict))
check("not triggered (fresh)", result.get("triggered") is False)

# 6. Proof Generation
print("\n6. Proof Generation:")
proof = fe.generate_proof(fc["event_id"])
check("proof has verification_hash", proof.get("verification_hash") is not None)
check("proof has log cursor", "log_cursor" in proof)
check("proof has dag_context", "dag_context" in proof)
check("proof type is falsification", proof["proof_type"] == "falsification")
check("proof has materialization version", "materialization_version" in proof)

# 7. Event range + get
print("\n7. Event Access:")
check("get by ID works", el.get_event(ev1["event_id"]) is not None)
check("get_range with start/end", len(el.get_event_range(0, 2)) == 2)

# Summary
print(f"\n{'='*40}")
print(f"Results: {PASS} passed, {FAIL} failed out of {PASS+FAIL} tests")

# Cleanup test data
el.clear()

sys.exit(0 if FAIL == 0 else 1)
