"""Append-only event log with HMAC-SHA256 chain linking.

Each event is cryptographically linked to its predecessor: signature_n = HMAC(prev_sig + content_n).
Event schema: event_id, type (claim/confirmation/dispute/heartbeat/falsification),
timestamp, agent_id, payload, prev_signature, signature.
Stored as append-only JSON array at ~/.hermes/ledger_v0.4/event_log.json.
"""

import hashlib, hmac, json, os, uuid
from datetime import datetime, timezone

SHARED_SECRET = b"self-ledger-v0.4-chain-key"
LEDGER_DIR = os.path.expanduser("~/.hermes/ledger_v0.4")
EVENT_LOG_FILE = os.path.join(LEDGER_DIR, "event_log.json")
ALLOWED_TYPES = frozenset({"claim","confirmation","dispute","heartbeat","falsification"})

def _hmac(prev_sig, content):
    return hmac.new(SHARED_SECRET, (prev_sig + content).encode(), hashlib.sha256).hexdigest()

def _eid(typ):
    return f"{typ}_{uuid.uuid4().hex[:8]}"

def _ensure():
    os.makedirs(LEDGER_DIR, exist_ok=True)
    try: os.chmod(LEDGER_DIR, 0o700)
    except: pass

def _content(ev):
    return json.dumps({k:ev[k] for k in ("event_id","type","timestamp","agent_id","payload","prev_signature")}, sort_keys=True, default=str)

class EventLog:
    """Append-only event log with HMAC chain integrity."""

    def __init__(self):
        _ensure()
        self._events = self._load_or_init()

    def _load_or_init(self):
        if not os.path.exists(EVENT_LOG_FILE):
            return self._init_genesis()
        try:
            with open(EVENT_LOG_FILE) as f: data = json.load(f)
            if isinstance(data, list) and len(data) > 0: return data
        except: pass
        return self._init_genesis()

    def _init_genesis(self):
        g = {"event_id":"genesis","type":"heartbeat","timestamp":"2026-05-18T00:00:00+00:00",
             "agent_id":"self_ledger_v0.4","payload":{"description":"Genesis event"},
             "prev_signature":"","signature":None}
        g["signature"] = _hmac("", _content(g))
        self._events = [g]
        self._persist()
        return self._events

    def _persist(self):
        _ensure()
        tmp = EVENT_LOG_FILE + ".tmp"
        with open(tmp, "w") as f: json.dump(self._events, f, indent=2, default=str)
        try: os.chmod(tmp, 0o600)
        except: pass
        os.replace(tmp, EVENT_LOG_FILE)

    def append_event(self, event_type, agent_id, payload, timestamp=None):
        """Append a new event. Returns the created event dict."""
        if event_type not in ALLOWED_TYPES:
            raise ValueError(f"Invalid type '{event_type}'. Allowed: {sorted(ALLOWED_TYPES)}")
        ts = timestamp or datetime.now(timezone.utc).isoformat()
        prev = self._events[-1]
        ev = {"event_id":_eid(event_type),"type":event_type,"timestamp":ts,"agent_id":agent_id,
              "payload":payload,"prev_signature":prev["signature"],"signature":None}
        ev["signature"] = _hmac(prev["signature"], _content(ev))
        self._events.append(ev)
        self._persist()
        return ev

    def get_event(self, eid):
        for ev in self._events:
            if ev["event_id"] == eid: return dict(ev)
        return None

    def get_all_events(self):
        return [dict(ev) for ev in self._events]

    def get_event_range(self, start=0, end=None):
        if end is None: end = len(self._events)
        return [dict(ev) for ev in self._events[start:end]]

    def __len__(self): return len(self._events)

    def verify_chain(self):
        """Verify HMAC chain for all events. Returns {valid, total_events, issues}."""
        issues = []
        for i, ev in enumerate(self._events):
            if i == 0:
                if ev["prev_signature"] != "":
                    issues.append({"index":i,"event_id":ev["event_id"],"message":"Genesis has non-empty prev_signature"})
                    continue
            else:
                expected = self._events[i-1]["signature"]
                if ev["prev_signature"] != expected:
                    issues.append({"index":i,"event_id":ev["event_id"],"message":"prev_signature mismatch"})
                    continue
            expected = _hmac(ev["prev_signature"], _content(ev))
            if ev["signature"] != expected:
                issues.append({"index":i,"event_id":ev["event_id"],"message":"Signature mismatch"})
        return {"valid":len(issues)==0,"total_events":len(self._events),"issues":issues}

    def get_file_path(self): return EVENT_LOG_FILE

    def clear(self):
        """Reset to genesis only (for testing)."""
        self._events = [dict(self._events[0])]
        g = self._events[0]
        g["signature"] = _hmac(g["prev_signature"], _content(g))
        self._persist()
