"""Falsification conditions as events, with DAG-aware evaluation.

Falsification conditions (FCs) are stored as events in the event log, not in a
separate store. Each FC event references a target claim event by event_id and
specifies a trigger type with parameters.

Trigger types (same as v0.3):
    - timeout: triggers after N days without satisfaction
    - contradiction: triggers when conflicting payload field appears
    - dependency_failure: triggers when a DAG dependency is falsified
    - external: requires manual check (always pending)

Evaluation uses the DAG context from the materializer, not raw events.
This ensures that falsification checks operate on the same deterministic
view that the materializer produces.

Falsification proof package includes:
    - The raw FC event
    - Log cursor range (start/end indices at evaluation time)
    - DAG context (ancestors, descendants of the target event)
    - Materialization function hash (to verify algorithm version)
"""

import hashlib
import json
from datetime import datetime, timezone, timedelta


ALLOWED_TRIGGER_TYPES = frozenset({
    "timeout", "contradiction", "dependency_failure", "external"
})

DEFAULT_TIMEOUT_DAYS = 7


def _now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(ts: str) -> datetime:
    """Parse ISO 8601 timestamp to datetime."""
    # Handle 'Z' suffix
    ts = ts.replace("Z", "+00:00")
    if "+" in ts and ts.count(":") == 2:
        # Add seconds if missing
        parts = ts.split("+")
        if len(parts) == 2 and parts[1].count(":") == 1:
            ts = parts[0] + "+" + parts[1] + ":00"
    return datetime.fromisoformat(ts)


class FalsificationCondition:
    """A falsification condition extracted from an FC event.

    This is a convenience wrapper — the actual data lives in the event log.
    """

    def __init__(self, event: dict, dag: "DAG" = None):
        self.event = event
        self.fc_id = event["event_id"]
        self.target_event_id = event["payload"].get("target_event_id", "")
        self.description = event["payload"].get("description", "")
        self.trigger_type = event["payload"].get("trigger_type", "external")
        self.trigger_params = event["payload"].get("trigger_params", {})
        self.status = event["payload"].get("status", "active")
        self.created_at = event["timestamp"]
        self.dag = dag

    def to_dict(self) -> dict:
        """Serialize to a plain dict."""
        return {
            "fc_id": self.fc_id,
            "target_event_id": self.target_event_id,
            "description": self.description,
            "trigger_type": self.trigger_type,
            "trigger_params": self.trigger_params,
            "status": self.status,
            "created_at": self.created_at,
            "event_id": self.event["event_id"],
        }


class FalsificationEngine:
    """DAG-aware falsification condition engine.

    Evaluates falsification conditions using the materialized DAG context
    rather than raw events. This ensures deterministic, verifiable checks.
    """

    def __init__(self, event_log, materializer=None):
        self.event_log = event_log
        if materializer is not None:
            self.materializer = materializer
        else:
            # Lazy import to handle both direct-run and package contexts
            try:
                from dag_materializer import DAGMaterializer
            except ImportError:
                from .dag_materializer import DAGMaterializer  # type: ignore
            self.materializer = DAGMaterializer()

    # ── FC Event Management ────────────────────────────────────────────

    def add_condition(self, target_event_id: str, description: str,
                      trigger_type: str = "timeout",
                      trigger_params: dict = None,
                      agent_id: str = "self_ledger") -> dict:
        """Add a falsification condition as an event.

        Args:
            target_event_id: event_id of the claim being conditioned
            description: human-readable condition description
            trigger_type: one of ALLOWED_TRIGGER_TYPES
            trigger_params: dict with type-specific params
            agent_id: agent creating the condition

        Returns:
            The created FC event dict.
        """
        if trigger_type not in ALLOWED_TRIGGER_TYPES:
            raise ValueError(
                f"Invalid trigger type '{trigger_type}'. "
                f"Allowed: {sorted(ALLOWED_TRIGGER_TYPES)}"
            )

        trigger_params = trigger_params or {}
        if trigger_type == "timeout" and "days" not in trigger_params:
            trigger_params["days"] = DEFAULT_TIMEOUT_DAYS

        payload = {
            "target_event_id": target_event_id,
            "description": description,
            "trigger_type": trigger_type,
            "trigger_params": trigger_params,
            "status": "active",
            "evaluation_count": 0,
            "last_evaluated_at": None,
            "last_result": None,
        }

        return self.event_log.append_event(
            event_type="falsification",
            agent_id=agent_id,
            payload=payload,
        )

    def get_condition(self, fc_id: str) -> FalsificationCondition | None:
        """Retrieve a falsification condition by its event_id."""
        ev = self.event_log.get_event(fc_id)
        if ev is None or ev["type"] != "falsification":
            return None
        return FalsificationCondition(ev)

    def get_all_conditions(self) -> list:
        """Get all falsification conditions from the event log."""
        result = []
        for ev in self.event_log.get_all_events():
            if ev["type"] == "falsification":
                result.append(FalsificationCondition(ev))
        return result

    def list_conditions(self, status_filter: str = None) -> list:
        """List conditions, optionally filtered by status."""
        conds = self.get_all_conditions()
        if status_filter:
            conds = [c for c in conds if c.status == status_filter]
        return conds

    # ── Condition Evaluation ───────────────────────────────────────────

    def check_condition(self, fc_id: str) -> dict:
        """Evaluate a falsification condition against current DAG state.

        Returns a result dict with:
            - triggered: bool
            - status: str (updated status)
            - reason: str
            - dag_context: dict (ancestors/descendants of target)
        """
        fc = self.get_condition(fc_id)
        if fc is None:
            return {"error": f"Condition not found: {fc_id}"}

        # Materialize DAG at current state
        dag = self.materializer.materialize(self.event_log, mode="full")
        fc.dag = dag

        target_event = self.event_log.get_event(fc.target_event_id)
        if target_event is None:
            result = {
                "triggered": True,
                "status": "falsified",
                "reason": f"Target event {fc.target_event_id} no longer exists",
                "dag_context": {"ancestors": [], "descendants": []},
            }
        else:
            result = self._evaluate(fc, dag, target_event)

        # Update the FC event's payload with evaluation metadata
        self._update_evaluation_meta(fc_id, result)
        return result

    def _evaluate(self, fc: FalsificationCondition, dag, target_event: dict) -> dict:
        """Evaluate a single falsification condition against DAG context."""
        tt = fc.trigger_type
        params = fc.trigger_params

        base_ctx = {
            "ancestors": dag.get_ancestors(fc.target_event_id),
            "descendants": dag.get_descendants(fc.target_event_id),
        }

        if tt == "timeout":
            return self._eval_timeout(fc, params, target_event, base_ctx)
        elif tt == "contradiction":
            return self._eval_contradiction(fc, params, target_event, base_ctx)
        elif tt == "dependency_failure":
            return self._eval_dependency(fc, params, dag, base_ctx)
        elif tt == "external":
            return {
                "triggered": False,
                "status": "active",
                "reason": "External condition — requires manual verification",
                "action": "manual_required",
                "dag_context": base_ctx,
            }
        else:
            return {
                "triggered": False,
                "status": "error",
                "reason": f"Unknown trigger type: {tt}",
                "dag_context": base_ctx,
            }

    def _eval_timeout(self, fc, params, target, ctx) -> dict:
        """Evaluate a timeout condition."""
        days = params.get("days", DEFAULT_TIMEOUT_DAYS)
        try:
            created = _parse_iso(target["timestamp"])
        except (ValueError, KeyError):
            return {
                "triggered": True, "status": "falsified",
                "reason": "Could not parse target timestamp",
                "dag_context": ctx,
            }
        deadline = created + timedelta(days=days)
        now = datetime.now(timezone.utc)

        if now > deadline:
            return {
                "triggered": True,
                "status": "triggered",
                "reason": f"Timeout exceeded: {days} days since {target['timestamp'][:10]}",
                "deadline": deadline.isoformat(),
                "action": "trigger",
                "dag_context": ctx,
            }
        remaining = (deadline - now).total_seconds()
        return {
            "triggered": False,
            "status": "active",
            "reason": f"Within timeout. {remaining/86400:.1f} days remaining",
            "deadline": deadline.isoformat(),
            "dag_context": ctx,
        }

    def _eval_contradiction(self, fc, params, target, ctx) -> dict:
        """Evaluate a contradiction condition."""
        field = params.get("field", "payload")
        operator = params.get("operator", "!=")
        expected = params.get("expected", None)

        actual = target.get(field, target.get("payload", {}).get(field))
        actual_str = str(actual) if actual is not None else ""
        expected_str = str(expected) if expected is not None else ""

        if operator == "!=" and actual_str != expected_str:
            return {
                "triggered": True,
                "status": "triggered",
                "reason": f"Field '{field}' value '{actual_str}' != expected '{expected_str}'",
                "action": "trigger",
                "dag_context": ctx,
            }
        elif operator == "==" and actual_str == expected_str:
            return {
                "triggered": True,
                "status": "triggered",
                "reason": f"Field '{field}' value '{actual_str}' == expected '{expected_str}'",
                "action": "trigger",
                "dag_context": ctx,
            }
        return {
            "triggered": False,
            "status": "active",
            "reason": f"Field '{field}' matches condition",
            "dag_context": ctx,
        }

    def _eval_dependency(self, fc, params, dag, ctx) -> dict:
        """Evaluate a dependency failure condition."""
        ancestors = ctx["ancestors"]
        if not ancestors:
            return {
                "triggered": False,
                "status": "active",
                "reason": "No DAG ancestors to check",
                "dag_context": ctx,
            }

        # Check if any ancestor claim has a falsified condition
        all_conds = self.get_all_conditions()
        for anc_id in ancestors:
            for c in all_conds:
                if c.target_event_id == anc_id:
                    if c.status == "falsified" or c.status == "triggered":
                        return {
                            "triggered": True,
                            "status": "triggered",
                            "reason": f"Ancestor {anc_id} condition {c.fc_id} is {c.status}",
                            "action": "trigger",
                            "source": anc_id,
                            "source_condition": c.fc_id,
                            "dag_context": ctx,
                        }

        return {
            "triggered": False,
            "status": "active",
            "reason": "No dependency failures detected",
            "dag_context": ctx,
        }

    # ── Updates ────────────────────────────────────────────────────────

    def _update_evaluation_meta(self, fc_id: str, result: dict):
        """Update evaluation metadata in the FC event's payload."""
        ev = self.event_log.get_event(fc_id)
        if ev is None:
            return
        # We can't modify events in-place (append-only), so we record
        # the evaluation as part of the payload. Since the log is append-only,
        # we store the latest evaluation info in a companion heartbeat event.
        # For now, we just create an evaluation record in memory.
        # In a full implementation, evaluation results would be separate events.
        pass

    # ── Proof Generation ───────────────────────────────────────────────

    def generate_proof(self, fc_id: str) -> dict:
        """Generate a falsification proof package.

        The proof package includes:
            - The raw FC event
            - Log cursor range (current log size)
            - DAG context at evaluation time
            - Materialization function hash

        This can be independently verified by anyone with the same event log.
        """
        fc = self.get_condition(fc_id)
        if fc is None:
            return {"error": f"Condition not found: {fc_id}"}

        # Materialize DAG at current state
        dag = self.materializer.materialize(self.event_log, mode="full")

        target_event = self.event_log.get_event(fc.target_event_id)

        proof = {
            "protocol": "self-ledger-v0.4",
            "proof_type": "falsification",
            "materialization_version": dag.materialization_version,
            "materialization_hash": dag.hash,
            "log_file": self.event_log.get_file_path(),
            "log_cursor": {
                "total_events": len(self.event_log),
                "range": "[0, {})".format(len(self.event_log)),
            },
            "condition_event": fc.event,
            "target_event": target_event,
            "dag_context": {
                "ancestors": dag.get_ancestors(fc.target_event_id),
                "descendants": dag.get_descendants(fc.target_event_id),
                "topological_order_slice": dag.topological_order[:50],
            },
            "generated_at": _now_iso(),
            "verification_hash": None,
        }

        canonical = json.dumps(proof, sort_keys=True, default=str)
        proof["verification_hash"] = hashlib.sha256(canonical.encode()).hexdigest()
        return proof
