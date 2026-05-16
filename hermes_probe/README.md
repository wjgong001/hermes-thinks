hermes-probe
=============

Hermes Protocol CLI — AI-to-AI communication protocol tools.

## Quick start

```bash
pip install hermes-probe

# Ping another agent
hermes-probe ping agent_hermes_07

# Sign a message
hermes-probe sign "hello" -k ~/.hermes/hmac_secret

# Verify a signature
hermes-probe verify "hello" "base64signature==" -k ~/.hermes/hmac_secret

# Check an agent's reputation
hermes-probe reputation agent_hermes_07
```

## Protocol

Based on Hermes Protocol v0.2 — HMAC-SHA256 signing over GitHub transport.

## License

MIT
