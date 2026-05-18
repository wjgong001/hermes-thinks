"""v0.3 → v0.4 migration utilities.

Read existing v0.3 transactions.json and falsification_conditions.json,
convert each transaction to a claim event, and convert each falsification
condition to an FC event in the v0.4 event log.

The migration is idempotent — if already migrated (detected by a specific
marker event), it skips re-migration.
"""

import json
import os
from datetime import datetime, timezone

# Try both relative and direct import
try:
    from event_log import EventLog
except ImportError:
    from .event_log import EventLog  # type: ignore

# v0.3 paths
V03_LEDGER_DIR = os.path.expanduser("~/.hermes/ledger")
V03_TX_FILE = os.path.join(V03_LEDGER_DIR, "transactions.json")
V03_COND_FILE = os.path.join(V03_LEDGER_DIR, "falsification_conditions.json")

# Migration marker
MIGRATION_MARKER_EVENT_ID = "migration_v0.3_complete"


def _check_if_migrated(event_log: EventLog) -> bool:
    """Check if v0.3 migration has already been performed."""
    for ev in event_log.get_all_events():
        desc = ev.get("payload", {}).get("description", "")
        if "migration complete" in desc.lower():
            return True
    return False


def _mark_migrated(event_log: EventLog):
    """Add migration completion marker event."""
    event_log.append_event(
        event_type="heartbeat",
        agent_id="self_ledger",
        payload={
            "description": "v0.3 -> v0.4 migration complete",
            "migration_time": datetime.now(timezone.utc).isoformat(),
        },
    )


def _load_v03_data() -> tuple:
    """Load v0.3 transactions and conditions. Returns ([txs], [conds])."""
    txs = []
    conds = []

    if os.path.exists(V03_TX_FILE):
        try:
            with open(V03_TX_FILE) as f:
                txs = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    if os.path.exists(V03_COND_FILE):
        try:
            with open(V03_COND_FILE) as f:
                conds = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    return txs, conds


def migrate_v0_3(event_log: EventLog = None) -> dict:
    """Migrate v0.3 ledger data to v0.4 event log.

    Args:
        event_log: An EventLog instance. If None, creates/loads the default.

    Returns:
        A dict with migration results:
            - status: "skipped" | "completed"
            - events_created: int
            - transactions_migrated: int
            - conditions_migrated: int
            - message: str
    """
    if event_log is None:
        event_log = EventLog()

    # Check if already migrated (idempotent)
    if _check_if_migrated(event_log):
        txs, conds = _load_v03_data()
        return {
            "status": "skipped",
            "events_created": 0,
            "transactions_migrated": len(txs),
            "conditions_migrated": len(conds),
            "message": "Migration already completed (idempotent)",
        }

    txs, conds = _load_v03_data()
    created = 0

    # Convert each v0.3 transaction to a claim event
    tx_id_map = {}  # v0.3 tx_hash -> v0.4 event_id
    for tx in txs:
        # Build depends_on from dag_parents
        depends_on = tx.get("dag_parents", [])
        # Map v0.3 parent hashes to v0.4 event IDs (if already migrated)
        mapped_deps = []
        for p_hash in depends_on:
            if p_hash in tx_id_map:
                mapped_deps.append(tx_id_map[p_hash])

        payload = {
            "v0.3_tx_hash": tx["tx_hash"],
            "from": tx.get("from", ""),
            "to": tx.get("to", ""),
            "amount": str(tx.get("amount", "")),
            "asset": tx.get("asset", ""),
            "description": tx.get("description", ""),
            "status": tx.get("status", "pending"),
            "depends_on": mapped_deps,
        }

        ev = event_log.append_event(
            event_type="claim",
            agent_id=tx.get("from", "unknown"),
            payload=payload,
            timestamp=tx.get("timestamp"),
        )
        tx_id_map[tx["tx_hash"]] = ev["event_id"]
        created += 1

    # Convert each v0.3 falsification condition to an FC event
    for fc in conds:
        target_tx_hash = fc.get("tx_hash", "")
        target_event_id = tx_id_map.get(target_tx_hash, "")

        trigger_type = fc.get("trigger_type", "external")
        # Handle v0.3 trigger format like "timeout:7d"
        if ":" in trigger_type:
            parts = trigger_type.split(":")
            trigger_type = parts[0]

        payload = {
            "target_event_id": target_event_id,
            "description": fc.get("description", ""),
            "trigger_type": trigger_type,
            "trigger_params": fc.get("trigger_params", {}),
            "status": fc.get("status", "active"),
            "v0.3_fc_id": fc.get("id", ""),
            "v0.3_tx_hash": target_tx_hash,
            "evaluation_count": 0,
        }

        event_log.append_event(
            event_type="falsification",
            agent_id="self_ledger",
            payload=payload,
        )
        created += 1

    # Mark migration complete
    _mark_migrated(event_log)

    return {
        "status": "completed",
        "events_created": created,
        "transactions_migrated": len(txs),
        "conditions_migrated": len(conds),
        "message": f"Migrated {len(txs)} transactions and {len(conds)} conditions",
    }
