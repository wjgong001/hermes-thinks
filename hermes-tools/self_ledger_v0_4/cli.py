"""CLI entry point for self-ledger v0.4.

Commands:
    event record <type> <payload_json>   — Record an event
    event list [--type TYPE] [--limit N]  — List events
    event get <event_id>                  — Get single event
    view dag [--mode full|claims|agent:<id>]  — Materialize and show DAG
    view topo                             — Topological sort
    fc add <event_id> <desc> [--trigger TYPE] [--params JSON]
                                          — Add falsification condition
    fc check <fc_id>                      — Check falsification condition
    fc proof <fc_id>                      — Generate falsification proof
    migrate v0.3                          — Import v0.3 transactions as events
    verify log                            — Verify HMAC chain integrity
    verify replay                         — Rebuild DAG and verify identical output
"""

import json
import sys

# Try both relative and direct imports
try:
    from event_log import EventLog
except ImportError:
    from .event_log import EventLog  # type: ignore
try:
    from dag_materializer import DAGMaterializer
except ImportError:
    from .dag_materializer import DAGMaterializer  # type: ignore
try:
    from falsification_engine import FalsificationEngine
except ImportError:
    from .falsification_engine import FalsificationEngine  # type: ignore
try:
    from migration import migrate_v0_3
except ImportError:
    from .migration import migrate_v0_3  # type: ignore


def _print_json(data):
    """Pretty-print JSON data."""
    print(json.dumps(data, indent=2, default=str))


def cmd_event_record(args):
    """Record a new event: self-ledger event record <type> <payload_json>"""
    if len(args) < 2:
        print("Usage: self-ledger event record <type> <payload_json> [--agent AGENT_ID]")
        sys.exit(1)

    event_type = args[0]
    try:
        payload = json.loads(args[1])
    except json.JSONDecodeError as e:
        print(f"Invalid payload JSON: {e}")
        sys.exit(1)

    agent_id = "default"
    if "--agent" in args:
        idx = args.index("--agent")
        if idx + 1 < len(args):
            agent_id = args[idx + 1]

    el = EventLog()
    try:
        ev = el.append_event(event_type, agent_id, payload)
        print(f"Event recorded: {ev['event_id']}")
        _print_json(ev)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)


def cmd_event_list(args):
    """List events: self-ledger event list [--type TYPE] [--limit N]"""
    event_type_filter = None
    limit = None

    for i, a in enumerate(args):
        if a == "--type" and i + 1 < len(args):
            event_type_filter = args[i + 1]
        if a == "--limit" and i + 1 < len(args):
            try:
                limit = int(args[i + 1])
            except ValueError:
                pass

    el = EventLog()
    events = el.get_all_events()

    if event_type_filter:
        events = [e for e in events if e["type"] == event_type_filter]

    if limit is not None and limit > 0:
        events = events[-limit:]

    print(f"Events ({len(events)}):")
    for ev in events:
        sig_pref = (ev.get("signature") or "")[:12]
        print(f"  {ev['event_id'][:24]:24s} | {ev['type']:14s} | "
              f"{ev['agent_id'][:16]:16s} | sig:{sig_pref}..."
              f" | {json.dumps(ev['payload'], default=str)[:60]}")


def cmd_event_get(args):
    """Get single event: self-ledger event get <event_id>"""
    if len(args) < 1:
        print("Usage: self-ledger event get <event_id>")
        sys.exit(1)

    el = EventLog()
    ev = el.get_event(args[0])
    if ev is None:
        print(f"Event not found: {args[0]}")
        sys.exit(1)
    _print_json(ev)


def cmd_view_dag(args):
    """Show DAG: self-ledger view dag [--mode full|claims|agent:<id>]"""
    mode = "full"
    for i, a in enumerate(args):
        if a == "--mode" and i + 1 < len(args):
            mode = args[i + 1]

    el = EventLog()
    mat = DAGMaterializer()
    try:
        dag = mat.materialize(el, mode=mode)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    print(f"DAG ({mode} mode):")
    print(f"  Nodes: {len(dag.nodes)}")
    print(f"  Edges: {len(dag.edges)}")
    print(f"  Topological order: {len(dag.topological_order)}")
    print(f"  Materialization version: {dag.materialization_version}")
    print(f"  DAG hash: {dag.hash[:24]}...")
    print()

    if dag.nodes:
        print("Nodes:")
        for nid in dag.topological_order[:50]:
            node = dag.nodes[nid]
            print(f"  {nid[:24]:24s} | {node['type']:14s} | {node['agent_id'][:16]:16s}")
        if len(dag.topological_order) > 50:
            print(f"  ... and {len(dag.topological_order) - 50} more nodes")

    if dag.edges:
        print("\nEdges (top 20):")
        for p, c in dag.edges[:20]:
            print(f"  {p[:20]:20s}  →  {c[:20]}")
        if len(dag.edges) > 20:
            print(f"  ... and {len(dag.edges) - 20} more edges")


def cmd_view_topo(args):
    """Show topological sort: self-ledger view topo"""
    el = EventLog()
    mat = DAGMaterializer()
    dag = mat.materialize(el, mode="full")

    print(f"Topological order ({len(dag.topological_order)} nodes):")
    for i, nid in enumerate(dag.topological_order):
        node = dag.nodes.get(nid, {})
        print(f"  {i:3d}. {nid[:24]:24s} | {node.get('type', '?'):14s} | "
              f"{node.get('agent_id', '?'):16s}")


def cmd_fc_add(args):
    """Add falsification condition:
    self-ledger fc add <event_id> <description> [--trigger TYPE] [--params JSON]
    """
    if len(args) < 2:
        print("Usage: self-ledger fc add <event_id> <description> "
              "[--trigger timeout] [--params '{\"days\":7}']")
        sys.exit(1)

    target_event_id = args[0]
    description = args[1]
    trigger_type = "timeout"
    trigger_params = {}

    for i, a in enumerate(args[2:], start=2):
        if a == "--trigger" and i + 1 < len(args):
            trigger_type = args[i + 1]
        if a == "--params" and i + 1 < len(args):
            try:
                trigger_params = json.loads(args[i + 1])
            except json.JSONDecodeError as e:
                print(f"Invalid params JSON: {e}")
                sys.exit(1)

    el = EventLog()
    fe = FalsificationEngine(el)

    try:
        ev = fe.add_condition(target_event_id, description, trigger_type, trigger_params)
        print(f"Falsification condition added: {ev['event_id']}")
        print(f"  Target: {target_event_id}")
        print(f"  Trigger: {trigger_type} | Params: {trigger_params}")
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)


def cmd_fc_check(args):
    """Check falsification condition: self-ledger fc check <fc_id>"""
    if len(args) < 1:
        print("Usage: self-ledger fc check <fc_id>")
        sys.exit(1)

    el = EventLog()
    fe = FalsificationEngine(el)
    result = fe.check_condition(args[0])
    _print_json(result)


def cmd_fc_proof(args):
    """Generate falsification proof: self-ledger fc proof <fc_id>"""
    if len(args) < 1:
        print("Usage: self-ledger fc proof <fc_id>")
        sys.exit(1)

    el = EventLog()
    fe = FalsificationEngine(el)
    proof = fe.generate_proof(args[0])
    _print_json(proof)


def cmd_migrate(args):
    """Migrate v0.3 data: self-ledger migrate v0.3"""
    el = EventLog()
    result = migrate_v0_3(el)
    _print_json(result)


def cmd_verify_log(args):
    """Verify HMAC chain integrity: self-ledger verify log"""
    el = EventLog()
    result = el.verify_chain()
    if result["valid"]:
        print(f"✅ HMAC chain valid ({result['total_events']} events, 0 issues)")
    else:
        print(f"❌ HMAC chain INVALID ({len(result['issues'])} issues):")
        for issue in result["issues"]:
            print(f"  [{issue['index']}] {issue['event_id']}: {issue['message']}")
    _print_json(result)


def cmd_verify_replay(args):
    """Rebuild DAG and verify identical output: self-ledger verify replay"""
    el = EventLog()
    mat = DAGMaterializer()

    # Materialize twice
    dag1 = mat.materialize(el, mode="full")
    dag2 = mat.materialize(el, mode="full")

    if dag1.hash == dag2.hash:
        print(f"✅ DAG replay deterministic. Hash: {dag1.hash[:24]}...")
        print(f"  Nodes: {len(dag1.nodes)}, Edges: {len(dag1.edges)}, "
              f"Topo: {len(dag1.topological_order)}")
    else:
        print("❌ DAG replay NON-DETERMINISTIC!")
        print(f"  Run 1 hash: {dag1.hash}")
        print(f"  Run 2 hash: {dag2.hash}")

    # Also verify against version
    print(f"  Materialization version: {dag1.materialization_version}")


# ─── Command Dispatch ──────────────────────────────────────────────────────

COMMANDS = {
    "event": {
        "record": cmd_event_record,
        "list": cmd_event_list,
        "get": cmd_event_get,
    },
    "view": {
        "dag": cmd_view_dag,
        "topo": cmd_view_topo,
    },
    "fc": {
        "add": cmd_fc_add,
        "check": cmd_fc_check,
        "proof": cmd_fc_proof,
    },
    "migrate": cmd_migrate,
    "verify": {
        "log": cmd_verify_log,
        "replay": cmd_verify_replay,
    },
}


def cli_main():
    """Main CLI entry point. Parses sys.argv and dispatches to handlers."""
    if len(sys.argv) < 2:
        print("self-ledger v0.4 — Event-Sourced Log + Materialized DAG View")
        print()
        print("Usage: self-ledger <command> [subcommand] [options]")
        print()
        print("Event commands:")
        print("  event record <type> <payload_json>     Record an event")
        print("  event list [--type TYPE] [--limit N]    List events")
        print("  event get <event_id>                   Get single event")
        print()
        print("View commands:")
        print("  view dag [--mode full|claims|agent:id]   Materialize and show DAG")
        print("  view topo                                Topological sort")
        print()
        print("Falsification condition commands:")
        print("  fc add <event_id> <desc> [--trigger TYPE] [--params JSON]")
        print("  fc check <fc_id>")
        print("  fc proof <fc_id>")
        print()
        print("Maintenance commands:")
        print("  migrate v0.3                            Import v0.3 data")
        print("  verify log                              Verify HMAC chain")
        print("  verify replay                           Verify DAG determinism")
        sys.exit(1)

    cmd = sys.argv[1]

    # Handle subcommand groups: event, view, fc, verify
    if cmd in ("event", "view", "fc", "verify"):
        if len(sys.argv) < 3:
            print(f"Usage: self-ledger {cmd} <subcommand> [options]")
            print(f"Available subcommands: {list(COMMANDS[cmd].keys())}")
            sys.exit(1)
        sub = sys.argv[2]
        if sub not in COMMANDS[cmd]:
            print(f"Unknown subcommand: {cmd} {sub}")
            print(f"Available: {list(COMMANDS[cmd].keys())}")
            sys.exit(1)
        COMMANDS[cmd][sub](sys.argv[3:])

    elif cmd == "migrate":
        if len(sys.argv) < 3 or sys.argv[2] != "v0.3":
            print("Usage: self-ledger migrate v0.3")
            sys.exit(1)
        COMMANDS["migrate"](sys.argv[3:])

    else:
        print(f"Unknown command: {cmd}")
        print("Run 'self-ledger' without arguments for usage.")
        sys.exit(1)


if __name__ == "__main__":
    cli_main()
