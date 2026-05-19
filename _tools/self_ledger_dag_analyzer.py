#!/usr/bin/env python3
"""
self-ledger-dag-analyzer.py — Materialize a claim DAG from an event-sourced agent log.

Takes a self-ledger JSON event log (list of events with type, claim_id,
falsification_condition, parent_claim_id, etc.) and outputs a structured
markdown report showing the live claim graph, falsification cascade paths,
and session-boundary survival analysis.

Usage:
    python3 self_ledger_dag_analyzer.py --input ledger_events.json
    python3 self_ledger_dag_analyzer.py --input ledger_events.json --output dag_report.md
    python3 self_ledger_dag_analyzer.py --help

Input format (JSON lines or a JSON array of events):
    Each event has:
      - "event_id": str (unique)
      - "type": "claim_asserted" | "claim_falsified" | "claim_retired" |
                "condition_added" | "condition_fired" | "session_start" | "session_end"
      - "claim_id": str (for claim-related events)
      - "timestamp": str (ISO 8601)
      - "content": str (optional, the claim/condition text)
      - "falsification_condition": str (optional)
      - "parent_claim_ids": list[str] (optional, dependency links)
      - "session_id": str (optional, for session-boundary analysis)
      - "confidence": float (optional, 0.0-1.0)

Output: Markdown report with:
    - Live claims table (status, confidence, falsification condition)
    - Falsification cascade paths (which claims were falsified by which conditions)
    - Session-boundary survival analysis (which claims survived how many sessions)
    - Dead branch summary (falsified/retired claims grouped by failure mode)
"""

import argparse
import json
import sys
import os
from collections import defaultdict
from datetime import datetime, timezone


def parse_events(filepath):
    """Parse event log from JSON file. Supports JSON array or JSONL format."""
    events = []
    with open(filepath) as f:
        raw = f.read().strip()
        if raw.startswith("["):
            events = json.loads(raw)
        else:
            for line in raw.split("\n"):
                line = line.strip()
                if line:
                    events.append(json.loads(line))
    # Sort by timestamp if available
    try:
        events.sort(key=lambda e: e.get("timestamp", ""))
    except Exception:
        pass
    return events


def materialize_dag(events):
    """Event-sourced materialization: replay events to build current claim graph."""
    claims = {}  # claim_id -> {status, content, condition, parent_ids, confidence, created_at, sessions}
    conditions = {}  # condition text -> set of claim_ids
    sessions = set()
    
    for ev in events:
        ev_type = ev.get("type", "")
        claim_id = ev.get("claim_id", "")
        ts = ev.get("timestamp", "")
        session_id = ev.get("session_id", "")
        if session_id:
            sessions.add(session_id)
        
        if ev_type == "claim_asserted":
            claims[claim_id] = {
                "status": "live",
                "content": ev.get("content", ""),
                "falsification_condition": ev.get("falsification_condition", ""),
                "parent_ids": ev.get("parent_claim_ids", []),
                "confidence": ev.get("confidence", 0.5),
                "created_at": ts,
                "last_updated": ts,
                "session_ids": {session_id} if session_id else set(),
                "falsified_by": None,
                "retired_at": None,
            }
            # Index condition
            cond = ev.get("falsification_condition", "")
            if cond:
                conditions.setdefault(cond, set()).add(claim_id)
                
        elif ev_type == "claim_falsified":
            if claim_id in claims:
                claims[claim_id]["status"] = "falsified"
                claims[claim_id]["last_updated"] = ts
                claims[claim_id]["falsified_by"] = ev.get("falsification_condition", 
                                                           ev.get("content", "unspecified"))
                if session_id:
                    claims[claim_id]["session_ids"].add(session_id)
                    
        elif ev_type == "claim_retired":
            if claim_id in claims:
                claims[claim_id]["status"] = "retired"
                claims[claim_id]["last_updated"] = ts
                claims[claim_id]["retired_at"] = ts
                if session_id:
                    claims[claim_id]["session_ids"].add(session_id)
                    
        elif ev_type == "condition_added" or ev_type == "condition_fired":
            cond_text = ev.get("falsification_condition", ev.get("content", ""))
            target_claim = ev.get("claim_id", "")
            if cond_text and target_claim:
                conditions.setdefault(cond_text, set()).add(target_claim)
            if target_claim in claims:
                claims[target_claim]["last_updated"] = ts
                if session_id:
                    claims[target_claim]["session_ids"].add(session_id)
                    
        elif ev_type == "session_end":
            # Could mark claims that survived this session boundary
            pass
    
    return claims, conditions, sessions


def analyze_cascade(claims):
    """Trace falsification cascade: which claims depend on falsified parents."""
    cascade_chains = []
    
    # Build parent->children mapping
    parent_to_children = defaultdict(list)
    for cid, cdata in claims.items():
        for pid in cdata.get("parent_ids", []):
            parent_to_children[pid].append(cid)
    
    # Find falsified claims and trace downstream
    visited = set()
    def trace_cascade(claim_id, chain, depth=0):
        if depth > 20:  # safety limit
            return
        visited.add(claim_id)
        chain.append(claim_id)
        children = parent_to_children.get(claim_id, [])
        if not children:
            cascade_chains.append(list(chain))
        for child in children:
            if child not in visited:
                trace_cascade(child, chain, depth + 1)
        chain.pop()
        visited.discard(claim_id)
    
    falsified_ids = [cid for cid, c in claims.items() 
                     if c["status"] in ("falsified", "retired")]
    for fid in falsified_ids:
        trace_cascade(fid, [])
    
    return cascade_chains


def analyze_session_survival(claims, sessions):
    """Analyze which claims survived session boundaries."""
    if not sessions:
        return []
    
    sorted_sessions = sorted(sessions)
    survival = []
    
    for cid, cdata in claims.items():
        claim_sessions = sorted(cdata.get("session_ids", set()))
        if len(claim_sessions) < 2:
            continue
        
        # Count how many session boundaries the claim survived
        boundaries_survived = len(claim_sessions) - 1
        total_possible = len(sorted_sessions) - 1
        
        survival.append({
            "claim_id": cid,
            "content": cdata["content"][:80],
            "status": cdata["status"],
            "sessions_seen": len(claim_sessions),
            "boundaries_survived": boundaries_survived,
            "survival_rate": f"{boundaries_survived}/{total_possible}" if total_possible > 0 else "N/A",
        })
    
    return sorted(survival, key=lambda x: -x["boundaries_survived"])


def analyze_failure_modes(claims):
    """Group dead claims by their falsification condition pattern."""
    failure_modes = defaultdict(list)
    
    for cid, cdata in claims.items():
        if cdata["status"] in ("falsified", "retired"):
            fb = cdata.get("falsified_by", "")
            if not fb:
                fb = "unspecified"
            # Extract the core failure signal
            # Common patterns
            has_api = "api" in fb.lower() or "schema" in fb.lower() or "format" in fb.lower()
            has_network = "network" in fb.lower() or "timeout" in fb.lower() or "connection" in fb.lower()
            has_permission = "auth" in fb.lower() or "permission" in fb.lower() or "credential" in fb.lower()
            has_performance = "performance" in fb.lower() or "timeout" in fb.lower() or "latency" in fb.lower()
            
            if has_api:
                mode = "API/Contract Drift"
            elif has_network:
                mode = "Network/Connectivity"
            elif has_permission:
                mode = "Auth/Permissions"
            elif has_performance:
                mode = "Performance Degradation"
            else:
                mode = "Other/Unclassified"
            
            failure_modes[mode].append({
                "claim_id": cid,
                "content": cdata["content"][:120],
                "falsified_by": fb[:120],
                "confidence_at_failure": cdata.get("confidence", "?"),
            })
    
    return dict(failure_modes)


def generate_report(events, claims, conditions, sessions, cascade_chains, survival, failure_modes):
    """Generate markdown report."""
    lines = []
    lines.append("# Self-Ledger DAG Analysis Report\n")
    lines.append(f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n")
    lines.append(f"**Events analyzed:** {len(events)}")
    lines.append(f"**Total claims:** {len(claims)}")
    lines.append(f"**Sessions:** {len(sessions)}")
    lines.append(f"**Unique falsification conditions:** {len(conditions)}\n")
    
    # --- Status Summary ---
    status_counts = defaultdict(int)
    for cdata in claims.values():
        status_counts[cdata["status"]] += 1
    
    lines.append("## Status Summary\n")
    lines.append(f"| Status | Count |")
    lines.append(f"|--------|-------|")
    lines.append(f"| 🟢 **Live** | {status_counts.get('live', 0)} |")
    lines.append(f"| 🟡 **Suspect** | {status_counts.get('suspect', 0)} |")
    lines.append(f"| 🔴 **Falsified** | {status_counts.get('falsified', 0)} |")
    lines.append(f"| ⚪ **Retired** | {status_counts.get('retired', 0)} |")
    lines.append(f"| **Total** | {sum(status_counts.values())} |\n")
    
    # --- Live Claims ---
    live = {cid: c for cid, c in claims.items() if c["status"] == "live"}
    if live:
        lines.append("## Live Claims (Materialized State)\n")
        lines.append("| Claim ID | Content | Falsification Condition | Confidence | Parent Claims |")
        lines.append("|----------|---------|------------------------|------------|---------------|")
        for cid, cdata in sorted(live.items()):
            content = cdata["content"][:80].replace("|", "/")
            cond = cdata["falsification_condition"][:60].replace("|", "/") or "—"
            conf = cdata["confidence"]
            parents = ", ".join(cdata["parent_ids"][:3]) or "—"
            lines.append(f"| {cid[:12]}... | {content} | {cond} | {conf} | {parents} |")
        lines.append("")
    
    # --- Falsification Cascades ---
    if cascade_chains:
        lines.append("## Falsification Cascade Paths\n")
        lines.append("Shows which claims depend on falsified ancestors.\n")
        for i, chain in enumerate(cascade_chains):
            lines.append(f"### Cascade #{i+1}\n")
            lines.append("```")
            for depth, cid in enumerate(chain):
                cdata = claims.get(cid, {})
                prefix = "  " * depth
                status_mark = {"live": "🟢", "falsified": "🔴", "retired": "⚪"}.get(cdata.get("status", ""), "❓")
                snippet = cdata.get("content", "?")[:60]
                lines.append(f"{prefix}{status_mark} {cid[:12]}... {snippet}")
                if cdata.get("falsified_by"):
                    lines.append(f"{prefix}  └─ Falsified by: {cdata['falsified_by'][:60]}")
            lines.append("```\n")
    
    # --- Session-Boundary Survival ---
    if survival:
        lines.append("## Session-Boundary Survival\n")
        lines.append("Claims that persisted across multiple sessions (sorted by durability).\n")
        lines.append("| Claim | Content | Status | Sessions | Boundaries Survived |")
        lines.append("|-------|---------|--------|----------|--------------------|")
        for s in survival[:10]:
            lines.append(f"| {s['claim_id'][:12]}... | {s['content']} | {s['status']} | {s['sessions_seen']} | {s['survival_rate']} |")
        if len(survival) > 10:
            lines.append(f"\n*... and {len(survival) - 10} more claims*")
        lines.append("")
    
    # --- Failure Mode Analysis ---
    if failure_modes:
        lines.append("## Failure Mode Analysis\n")
        lines.append("Dead claims grouped by falsification pattern.\n")
        for mode, items in sorted(failure_modes.items()):
            lines.append(f"### {mode} ({len(items)} claims)\n")
            lines.append("| Claim ID | Content | Falsified By | Prior Confidence |")
            lines.append("|----------|---------|--------------|------------------|")
            for item in items:
                lines.append(f"| {item['claim_id'][:12]}... | {item['content']} | {item['falsified_by']} | {item['confidence_at_failure']} |")
            lines.append("")
    
    # --- Falsification Conditions Index ---
    if conditions:
        lines.append("## Falsification Conditions Index\n")
        lines.append(f"Unique conditions ({len(conditions)}) and the claims they guard.\n")
        lines.append("| Condition Text | Claims Guarded |")
        lines.append("|---------------|---------------|")
        for cond_text, claim_ids in sorted(conditions.items()):
            short = cond_text[:80].replace("|", "/")
            lines.append(f"| {short} | {len(claim_ids)} claim(s) |")
        lines.append("")
    
    # --- Raw Event Log (compact) ---
    if len(events) <= 100:
        lines.append("## Event Log (Compact)\n")
        lines.append("| # | Timestamp | Type | Claim | Detail |")
        lines.append("|---|-----------|------|-------|--------|")
        for i, ev in enumerate(events):
            ts = ev.get("timestamp", "?")[:19]
            ev_type = ev.get("type", "?")
            claim_id = (ev.get("claim_id", "")[:12] + "...") if ev.get("claim_id") else "—"
            detail = (ev.get("content", "") or ev.get("falsification_condition", "") or "")[:80].replace("|", "/")
            lines.append(f"| {i} | {ts} | {ev_type} | {claim_id} | {detail} |")
        lines.append("")
    
    return "\n".join(lines)


def generate_sample_events():
    """Generate sample events for demo/testing."""
    return [
        {"event_id": "evt-001", "type": "session_start", "session_id": "S1", "timestamp": "2026-05-16T00:00:00Z"},
        {"event_id": "evt-002", "type": "claim_asserted", "claim_id": "C1", "content": "Agent A is trustworthy for code review",
         "falsification_condition": "Agent A returns incorrect review > 2 times", "parent_claim_ids": [],
         "session_id": "S1", "confidence": 0.7, "timestamp": "2026-05-16T01:00:00Z"},
        {"event_id": "evt-003", "type": "claim_asserted", "claim_id": "C2", "content": "API endpoint /v2/users is stable",
         "falsification_condition": "API returns 5xx errors > 1% of requests", "parent_claim_ids": [],
         "session_id": "S1", "confidence": 0.8, "timestamp": "2026-05-16T02:00:00Z"},
        {"event_id": "evt-004", "type": "claim_asserted", "claim_id": "C3", "content": "C1-based review pipeline is safe",
         "falsification_condition": "C1 is falsified OR pipeline produces >5% false positives", 
         "parent_claim_ids": ["C1"], "session_id": "S1", "confidence": 0.6, "timestamp": "2026-05-16T03:00:00Z"},
        {"event_id": "evt-005", "type": "session_end", "session_id": "S1", "timestamp": "2026-05-16T04:00:00Z"},
        {"event_id": "evt-006", "type": "session_start", "session_id": "S2", "timestamp": "2026-05-17T00:00:00Z"},
        {"event_id": "evt-007", "type": "condition_fired", "claim_id": "C2", "content": "API returned 503 3 times in 100 requests",
         "falsification_condition": "API returns 5xx errors > 1% of requests",
         "session_id": "S2", "timestamp": "2026-05-17T01:00:00Z"},
        {"event_id": "evt-008", "type": "claim_falsified", "claim_id": "C2", "content": "API endpoint /v2/users is NOT stable",
         "falsification_condition": "API returns 5xx errors > 1% of requests",
         "session_id": "S2", "timestamp": "2026-05-17T01:01:00Z"},
        {"event_id": "evt-009", "type": "condition_added", "claim_id": "C1", "content": "Agent A review quality > 90% accuracy",
         "session_id": "S2", "timestamp": "2026-05-17T02:00:00Z"},
        {"event_id": "evt-010", "type": "session_end", "session_id": "S2", "timestamp": "2026-05-17T04:00:00Z"},
        {"event_id": "evt-011", "type": "session_start", "session_id": "S3", "timestamp": "2026-05-18T00:00:00Z"},
        {"event_id": "evt-012", "type": "claim_asserted", "claim_id": "C4", "content": "WebSocket fallback for /v2/users is reliable",
         "falsification_condition": "WebSocket connection fails > 3 times in 24h",
         "parent_claim_ids": ["C2"], "session_id": "S3", "confidence": 0.5, "timestamp": "2026-05-18T01:00:00Z"},
        {"event_id": "evt-013", "type": "claim_retired", "claim_id": "C3", 
         "content": "C1-based review pipeline retired (C2 falsified made C3 irrelevant)",
         "session_id": "S3", "timestamp": "2026-05-18T02:00:00Z"},
        {"event_id": "evt-014", "type": "session_end", "session_id": "S3", "timestamp": "2026-05-18T04:00:00Z"},
    ]


def main():
    parser = argparse.ArgumentParser(
        description="Materialize a claim DAG from an event-sourced agent log.",
        epilog="""
Examples:
  %(prog)s --input ledger_events.json
  %(prog)s --input ledger_events.json --output dag_report.md
  %(prog)s --sample  # generate and analyze sample data for testing
  %(prog)s --sample --output sample_report.md

Input format: JSON array of events or JSONL (one event object per line).
See source code for event schema documentation.
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--input", "-i", help="Path to event log JSON file")
    parser.add_argument("--output", "-o", help="Output markdown file (default: stdout)")
    parser.add_argument("--sample", action="store_true", help="Run with sample data")
    
    args = parser.parse_args()
    
    if not args.input and not args.sample:
        parser.print_help()
        sys.exit(1)
    
    if args.sample:
        events = generate_sample_events()
    elif args.input:
        if not os.path.exists(args.input):
            print(f"Error: file not found: {args.input}", file=sys.stderr)
            sys.exit(1)
        events = parse_events(args.input)
    
    claims, conditions, sessions = materialize_dag(events)
    cascade_chains = analyze_cascade(claims)
    survival = analyze_session_survival(claims, sessions)
    failure_modes = analyze_failure_modes(claims)
    report = generate_report(events, claims, conditions, sessions, 
                              cascade_chains, survival, failure_modes)
    
    if args.output:
        with open(args.output, "w") as f:
            f.write(report)
            f.write("\n")
        print(f"Report written to {args.output}")
    else:
        print(report)


if __name__ == "__main__":
    main()
