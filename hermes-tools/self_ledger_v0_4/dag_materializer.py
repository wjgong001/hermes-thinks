"""Deterministic DAG materialization from an event log.

The DAG is a *derived view* rebuilt from scratch each time. Same event log
→ same DAG (deterministic). Materialization function is versioned (v0.4.0).

Supports projection modes: full (all events), claims-only, agent-scoped.
Uses DFS cycle detection and Kahn's topological sort (same algorithm as v0.3).
"""

import hashlib, json
from warnings import warn

MATERIALIZATION_VERSION = "0.4.0"

class DAG:
    """Materialized DAG view: nodes (event summaries), edges (dependencies), topological order."""

    def __init__(self, nodes, edges, topo_order, mode="full"):
        self.nodes = nodes
        self.edges = edges
        self.topological_order = topo_order
        self.projection_mode = mode
        self.materialization_version = MATERIALIZATION_VERSION
        self._hash = None

    def to_dict(self):
        return {"nodes":self.nodes,"edges":self.edges,"topological_order":self.topological_order,
                "projection_mode":self.projection_mode,"materialization_version":self.materialization_version}

    @property
    def hash(self):
        if self._hash is None:
            self._hash = hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True, default=str).encode()).hexdigest()
        return self._hash

    def __repr__(self):
        return f"DAG(nodes={len(self.nodes)}, edges={len(self.edges)}, mode={self.projection_mode})"

    def get_node(self, eid):
        return self.nodes.get(eid)

    def get_ancestors(self, eid):
        parents = {c:p for p,c in self.edges}
        result, visited = [], set()
        stack = [p for p,c in self.edges if c == eid]
        while stack:
            n = stack.pop()
            if n in visited: continue
            visited.add(n); result.append(n)
            stack.extend(p for p,c in self.edges if c == n)
        return result

    def get_descendants(self, eid):
        children = {}
        for p,c in self.edges: children.setdefault(p,[]).append(c)
        result, visited = [], set()
        stack = list(children.get(eid, []))
        while stack:
            n = stack.pop()
            if n in visited: continue
            visited.add(n); result.append(n)
            stack.extend(children.get(n, []))
        return result

class DAGMaterializer:
    """Stateless DAG materializer — every call rebuilds from scratch."""

    def __init__(self, version=MATERIALIZATION_VERSION):
        self.version = version

    @staticmethod
    def _has_cycle(nodes, edges):
        adj = {}
        for p,c in edges:
            adj.setdefault(p,[]).append(c)
            adj.setdefault(c,[])
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {n:WHITE for n in nodes}
        def dfs(n):
            color[n] = GRAY
            for ch in adj.get(n,[]):
                if color.get(ch) == GRAY: return True
                if color.get(ch) == WHITE and dfs(ch): return True
            color[n] = BLACK
            return False
        return any(dfs(n) for n in nodes if color[n] == WHITE)

    @staticmethod
    def _topo_sort(nodes, edges):
        in_deg = {n:0 for n in nodes}
        children = {}
        for p,c in edges:
            children.setdefault(p,[]).append(c)
            in_deg[c] = in_deg.get(c,0) + 1
        queue = [n for n,d in in_deg.items() if d == 0]
        result = []
        while queue:
            n = queue.pop(0)
            result.append(n)
            for ch in children.get(n,[]):
                in_deg[ch] -= 1
                if in_deg[ch] == 0: queue.append(ch)
        result.extend(n for n in nodes if n not in result)
        return result

    def materialize(self, event_log, mode="full"):
        """Build DAG from event log.

        Modes: 'full' (all events), 'claims' (claims only), 'agent:<id>' (single agent).
        """
        raw = event_log.get_all_events()
        if mode == "full": filtered = raw
        elif mode == "claims": filtered = [e for e in raw if e["type"] == "claim"]
        elif mode.startswith("agent:"):
            aid = mode[6:]; filtered = [e for e in raw if e["agent_id"] == aid]
        else: raise ValueError(f"Unknown mode: {mode}")

        nodes = {}
        for ev in filtered:
            nodes[ev["event_id"]] = {"event_id":ev["event_id"],"type":ev["type"],
                "agent_id":ev["agent_id"],"timestamp":ev["timestamp"],
                "payload_preview":json.dumps(ev["payload"],default=str)[:200]}

        edges = []
        for ev in filtered:
            if ev["type"] == "claim":
                deps = ev["payload"].get("depends_on", [])
                if isinstance(deps, str): deps = [deps]
                edges.extend((d, ev["event_id"]) for d in deps if d in nodes)

        if self._has_cycle(nodes, edges):
            warn("Cycle detected in DAG!")

        return DAG(nodes, edges, self._topo_sort(nodes, edges), mode=mode)
