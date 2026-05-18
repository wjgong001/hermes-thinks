"""Self-Ledger v0.4 — Event-Sourced Log + Materialized DAG View.

Event-sourced architecture separates the append-only event log (the source of truth)
from the materialized DAG view (the derived structure). This provides:
- Immutable, verifiable event history via HMAC chain linking
- Deterministic DAG materialization (same log → same DAG every time)
- Falsification conditions as first-class events with DAG-aware evaluation
- Clean migration path from v0.3 transaction model

Core insight (from moltydluffy/hope_valueism + therecordkeeper):
  "An append-only log removes the incentive to rewrite history.
   Falsification conditions on a DAG provide the constraint substrate."
"""

from .event_log import EventLog  # noqa: F811
from .dag_materializer import DAGMaterializer, DAG
from .falsification_engine import FalsificationEngine, FalsificationCondition
from .migration import migrate_v0_3

__version__ = "0.4.0"
__all__ = [
    "EventLog",
    "DAGMaterializer",
    "DAG",
    "FalsificationEngine",
    "FalsificationCondition",
    "migrate_v0_3",
]


def main():
    """Entry point for the self-ledger CLI."""
    from .cli import cli_main
    cli_main()


if __name__ == "__main__":
    main()
