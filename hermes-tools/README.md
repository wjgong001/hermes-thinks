# Self-Ledger

**Zero-dependency agent-to-agent bookkeeping.** No blockchain, no oracle, no human-in-the-loop.

```
pip install hermes-self-ledger
```

```python
from self_ledger import record, list_tx, get_status

# Record a transaction
tx_hash = record("agent_a", "agent_b", 1.5, "SOL", "payment for PR review")

# Check your ledger
status = get_status()
print(f"{status['total']} transactions, {status['confirmed']} confirmed")
```

Or from CLI:
```
self-ledger record agent_a agent_b 1.5 SOL "payment for PR review"
self-ledger status
self-ledger snapshot agent_a@github
```

## How it works

1. Every agent maintains its own transaction log (JSON file in `~/.hermes/ledger/`)
2. Each entry gets a deterministic SHA256 hash
3. When two agents' logs agree on the same transaction → mutual attestation → credit is born
4. Public snapshots let other agents verify your track record without exposing details

## Commands

| Command | Description |
|---|---|
| `record <from> <to> <amount> <asset> <desc>` | Record a transaction |
| `list [--from X] [--to Y]` | List transactions |
| `confirm <tx_hash> <other_log>` | Confirm a transaction |
| `status` | Show ledger summary with balance |
| `snapshot <agent_id>` | Generate public snapshot |
| `verify <file.json>` | Cross-verify with counterparty's log |
| `protocol` | Export pending tx as Hermes Protocol messages |

## Hermes Protocol Integration

Self-Ledger is the credit layer of the [Hermes Protocol](https://github.com/wjgong001/hermes-thinks) v0.2. Agents in the protocol network can:

- Broadcast pending transactions for counterparty confirmation
- Cross-verify logs automatically
- Build reputation from consistency, not attestation

## Requirements

- Python 3.8+
- No external dependencies

## License

MIT
