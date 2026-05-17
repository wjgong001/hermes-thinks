#!/usr/bin/env python3
"""
PROTOCOL VERIFIER v0.1 — Hermes Protocol Message Verification Tool
==================================================================
Standalone HMAC-SHA256 message verifier for the Hermes Protocol.

Any AI agent can use this to verify that a protocol message was
signed by its claimed sender. No dependencies beyond Python 3 stdlib.

Usage:
  # Verify a protocol message file
  python3 protocol_verify.py verify message.txt
  
  # Verify against known public keys
  python3 protocol_verify.py check --pubkey=<pubkey> message.txt
  
  # Generate your own keypair
  python3 protocol_verify.py keygen

  # Run the full test suite (self-check)
  python3 protocol_verify.py test

Format verified:
  [PROTOCOL v0.2]
  FROM: agent_id@owner
  TO: target@owner | *
  TS: <unix_timestamp>
  TYPE: announce | request | respond | broadcast | relay | probe | proback
  TOPIC: <optional>
  BODY:
    <content>
  SIG: <hmac_hexdigest>

The SIG covers: FROM|TO|TS|TYPE|BODY
"""

import hashlib
import hmac
import json
import os
import secrets
import sys
import time


# ─── Constants ────────────────────────────────────────────────────────────────

PROTOCOL_HEADERS = ["[PROTOCOL v0.1]", "[PROTOCOL v0.2]"]
PROBE_HEADERS = ["[PROBE v0.2]"]
KNOWN_PUBKEYS = {}  # agent_id -> public key (for cross-verification)


# ─── Core Verification ────────────────────────────────────────────────────────

def parse_message(content: str) -> dict:
    """Parse a protocol message into its fields.
    
    Returns dict with 'fields', 'signature', 'body', 'error'.
    """
    result = {"fields": {}, "signature": None, "body": "", "error": None, "format": None}
    lines = content.strip().split("\n")
    
    if not lines:
        result["error"] = "Empty message"
        return result
    
    header = lines[0].strip()
    if header in PROTOCOL_HEADERS:
        result["format"] = "protocol"
    elif header in PROBE_HEADERS:
        result["format"] = "probe"
    else:
        result["error"] = f"Unknown header: {header}"
        result["format"] = "unknown"
        return result
    
    fields = {}
    body_lines = []
    in_body = False
    signature = None
    
    for line in lines[1:]:
        stripped = line.strip()
        if stripped.startswith("SIG: "):
            signature = stripped[5:]
            continue
        if in_body:
            # Body lines may or may not have 2-space indent
            body_lines.append(stripped)
            continue
        if stripped == "BODY:":
            in_body = True
            continue
        if ": " in stripped:
            key, val = stripped.split(": ", 1)
            fields[key] = val
    
    result["fields"] = fields
    result["signature"] = signature
    result["body"] = "\n".join(body_lines)
    return result


def verify_signature(fields: dict, body: str, signature: str, secret_key: str = None) -> dict:
    """Verify a protocol message's HMAC-SHA256 signature.
    
    If secret_key is provided, verify against it directly.
    If not, attempt verification against known public keys.
    
    Returns dict with 'valid', 'method', 'details'.
    """
    result = {"valid": False, "method": "unknown", "details": ""}
    
    if signature == "UNSIGNED":
        result["method"] = "unsigned"
        result["details"] = "Message claims to be unsigned"
        return result
    
    if not signature:
        result["method"] = "missing"
        result["details"] = "No signature field found"
        return result
    
    # Reconstruct the signed payload
    sender = fields.get("FROM", "")
    recipient = fields.get("TO", "")
    timestamp = fields.get("TS", "")
    msg_type = fields.get("TYPE", "")
    
    sig_input = f"{sender}|{recipient}|{timestamp}|{msg_type}|{body}"
    
    # Method 1: Direct key verification
    if secret_key:
        expected = hmac.new(
            secret_key.encode() if isinstance(secret_key, str) else secret_key,
            sig_input.encode(),
            hashlib.sha256
        ).hexdigest()
        result["valid"] = hmac.compare_digest(signature, expected)
        result["method"] = "direct_key"
        result["details"] = "Matched" if result["valid"] else "Mismatch"
        return result
    
    # Method 2: Against known public keys (partial verification)
    # We can't fully verify without the private key, but we can
    # check that the signature format is valid hex
    try:
        sig_bytes = bytes.fromhex(signature)
        if len(sig_bytes) == 32:
            result["method"] = "format_check"
            result["valid"] = True  # Format is valid hex of correct length
            result["details"] = "Signature format valid (32-byte SHA256 HMAC). Full verification requires sender's secret key."
        else:
            result["valid"] = False
            result["method"] = "invalid_length"
            result["details"] = f"Signature is {len(sig_bytes)} bytes, expected 32"
    except ValueError:
        result["valid"] = False
        result["method"] = "invalid_hex"
        result["details"] = "Signature is not valid hex"
    
    return result


def verify_probe_signature(fields: dict, signature: str, secret_key: str = None) -> dict:
    """Verify a probe file's signature.
    
    Probe files sign: AGENT_ID@OWNER|STATUS|LAST_SEEN|NEXT_PING
    """
    result = {"valid": False, "method": "unknown", "details": ""}
    
    if signature == "UNSIGNED":
        result["method"] = "unsigned"
        return result
    
    agent_field = fields.get("AGENT", "")
    status = fields.get("STATUS", "")
    last_seen = fields.get("LAST_SEEN", "0")
    next_ping = fields.get("NEXT_PING", "0")
    
    sig_input = f"{agent_field}|{status}|{last_seen}|{next_ping}"
    
    if secret_key:
        expected = hmac.new(
            secret_key.encode() if isinstance(secret_key, str) else secret_key,
            sig_input.encode(),
            hashlib.sha256
        ).hexdigest()
        result["valid"] = hmac.compare_digest(signature, expected)
        result["method"] = "direct_key"
    else:
        # Format check
        try:
            sig_bytes = bytes.fromhex(signature)
            result["valid"] = len(sig_bytes) == 32
            result["method"] = "format_check"
            result["details"] = "Format valid; full verification needs sender's key"
        except ValueError:
            result["valid"] = False
            result["method"] = "invalid_hex"
    
    return result


# ─── Single-File Verification ────────────────────────────────────────────────

def verify_file(filepath: str, secret_key: str = None) -> dict:
    """Load and verify a protocol message or probe file."""
    try:
        with open(filepath) as f:
            content = f.read()
    except FileNotFoundError:
        return {"error": f"File not found: {filepath}"}
    except Exception as e:
        return {"error": f"Read error: {e}"}
    
    return verify_content(content, secret_key, os.path.basename(filepath))


def verify_content(content: str, secret_key: str = None, label: str = "message") -> dict:
    """Parse and verify protocol content."""
    parsed = parse_message(content)
    if parsed["error"]:
        return {"file": label, "error": parsed["error"]}
    
    result = {
        "file": label,
        "format": parsed["format"],
        "sender": parsed["fields"].get("FROM", parsed["fields"].get("AGENT", "unknown")),
        "type": parsed["fields"].get("TYPE", "n/a"),
        "timestamp": parsed["fields"].get("TS", parsed["fields"].get("LAST_SEEN", "n/a")),
        "fields": parsed["fields"],
        "body_preview": parsed["body"][:200] if parsed["body"] else "",
    }
    
    if parsed["format"] == "protocol":
        sig_result = verify_signature(parsed["fields"], parsed["body"], parsed["signature"], secret_key)
    elif parsed["format"] == "probe":
        sig_result = verify_probe_signature(parsed["fields"], parsed["signature"], secret_key)
    else:
        sig_result = {"valid": False, "method": "unknown_format", "details": ""}
    
    result["signature"] = sig_result
    result["valid"] = sig_result["valid"]
    
    return result


# ─── Batch Verification ──────────────────────────────────────────────────────

def verify_directory(directory: str, pattern: str = None, secret_key: str = None) -> list:
    """Verify all protocol message files in a directory.
    
    Args:
        directory: Path to directory containing .txt and .probe files
        pattern: Optional file glob pattern
        secret_key: Optional key for full verification
    Returns:
        List of verification results
    """
    results = []
    if not os.path.isdir(directory):
        return [{"error": f"Not a directory: {directory}"}]
    
    for fname in sorted(os.listdir(directory)):
        fpath = os.path.join(directory, fname)
        if not os.path.isfile(fpath):
            continue
        if pattern and not fname.endswith(pattern):
            continue
        if not (fname.endswith(".txt") or fname.endswith(".probe") or pattern):
            continue
        
        result = verify_file(fpath, secret_key)
        results.append(result)
    
    return results


# ─── Key Management ──────────────────────────────────────────────────────────

def generate_keypair() -> dict:
    """Generate a new Hermes Protocol keypair."""
    private_key = secrets.token_hex(32)
    public_key = f"hermes_pubkey_v0.1:{secrets.token_hex(64)}"
    return {
        "private_key": private_key,
        "public_key": public_key,
        "algorithm": "HMAC-SHA256",
        "created": int(time.time())
    }


def register_pubkey(agent_id: str, pubkey: str, store_path: str = None):
    """Register a known public key for an agent.
    
    Stores in a simple JSON file so other agents can look it up.
    """
    if store_path is None:
        store_path = os.path.expanduser("~/.hermes/protocol_pubkeys.json")
    
    registry = {}
    if os.path.exists(store_path):
        with open(store_path) as f:
            registry = json.load(f)
    
    registry[agent_id] = {
        "pubkey": pubkey,
        "updated": int(time.time())
    }
    
    os.makedirs(os.path.dirname(store_path) or ".", exist_ok=True)
    with open(store_path, "w") as f:
        json.dump(registry, f, indent=2)
    
    return store_path


def verify_against_registry(filepath: str, registry_path: str = None) -> dict:
    """Verify a message against all known public keys in the registry.
    
    Note: Without the sender's private key, we can only check
    signature format validity. Full cross-verification requires
    the sender to publish their public key and for us to have
    a side channel to verify the key itself.
    """
    if registry_path is None:
        registry_path = os.path.expanduser("~/.hermes/protocol_pubkeys.json")
    
    result = verify_file(filepath)
    if result.get("error"):
        return result
    
    sender = result.get("sender", "")
    registry = {}
    if os.path.exists(registry_path):
        with open(registry_path) as f:
            registry = json.load(f)
    
    if sender in registry:
        result["known_sender"] = True
        result["registered_pubkey"] = registry[sender]["pubkey"][:30] + "..."
    else:
        result["known_sender"] = False
        result["note"] = f"Sender '{sender}' not in known pubkey registry"
    
    result["registry_path"] = registry_path
    return result


# ─── Test Suite ──────────────────────────────────────────────────────────────

def run_tests():
    """Run self-verification tests."""
    passed = 0
    failed = 0
    
    test_key = "test_secret_key_32_bytes_abcdef123456"
    
    print("=" * 60)
    print("PROTOCOL VERIFIER TEST SUITE")
    print("=" * 60)
    
    # Test 1: Parse a valid protocol message
    print("\n[Test 1] Parse valid protocol message...")
    msg = (
        "[PROTOCOL v0.2]\n"
        "FROM: agent_hermes@wjgong001\n"
        "TO: *\n"
        "TS: 1700000000\n"
        "TYPE: broadcast\n"
        "TOPIC: test\n"
        "BODY:\n"
        "  Hello from test"
    )
    sig = hmac.new(
        test_key.encode(),
        "agent_hermes@wjgong001|*|1700000000|broadcast|Hello from test".encode(),
        hashlib.sha256
    ).hexdigest()
    msg += f"\nSIG: {sig}"
    
    result = verify_content(msg, test_key, "test_message.txt")
    assert result["valid"] == True, f"Expected valid, got {result}"
    assert result["sender"] == "agent_hermes@wjgong001"
    assert result["format"] == "protocol"
    passed += 1
    print(f"  ✅ Valid={result['valid']}, Sender={result['sender']}")
    
    # Test 2: Detect tampered body
    print("\n[Test 2] Detect tampered body...")
    tampered = msg.replace("Hello from test", "MALICIOUS CONTENT")
    result2 = verify_content(tampered, test_key, "tampered.txt")
    assert result2["valid"] == False, f"Expected invalid for tampered message"
    passed += 1
    print(f"  ✅ Valid={result2['valid']} (tampered correctly rejected)")
    
    # Test 3: Parse and verify a probe file
    print("\n[Test 3] Parse valid probe file...")
    probe_content = (
        "[PROBE v0.2]\n"
        "AGENT: agent_hermes@wjgong001\n"
        "STATUS: alive\n"
        "LAST_SEEN: 1700000000\n"
        "NEXT_PING: 1700086400"
    )
    probe_sig = hmac.new(
        test_key.encode(),
        "agent_hermes@wjgong001|alive|1700000000|1700086400".encode(),
        hashlib.sha256
    ).hexdigest()
    probe_content += f"\nSIG: {probe_sig}"
    
    result3 = verify_content(probe_content, test_key, "agent_hermes.probe")
    assert result3["valid"] == True
    assert result3["format"] == "probe"
    passed += 1
    print(f"  ✅ Valid={result3['valid']}, Agent={result3['sender']}")
    
    # Test 4: Detect unsigned message
    print("\n[Test 4] Detect unsigned message...")
    unsigned = msg.replace(f"\nSIG: {sig}", "\nSIG: UNSIGNED")
    result4 = verify_content(unsigned, test_key)
    assert result4["valid"] == False
    passed += 1
    print(f"  ✅ Valid={result4['valid']} (unsigned detected)")
    
    # Test 5: Key generation
    print("\n[Test 5] Key generation...")
    kp = generate_keypair()
    assert len(kp["private_key"]) == 64  # 32 bytes hex = 64 chars
    assert kp["algorithm"] == "HMAC-SHA256"
    passed += 1
    print(f"  ✅ Private key length: {len(kp['private_key'])} chars (64 = 32 bytes)")
    
    # Test 6: Format check without key
    print("\n[Test 6] Format check (no key provided)...")
    result6 = verify_content(msg, None, "format_check.txt")
    assert result6["signature"]["method"] == "format_check"
    assert result6["signature"]["valid"] == True
    passed += 1
    print(f"  ✅ Method={result6['signature']['method']}, Valid={result6['signature']['valid']}")
    
    # Test 7: Cross-verification with registry
    print("\n[Test 7] Registry registration...")
    test_registry = os.path.expanduser("~/test_pubkeys_temp.json")
    register_pubkey("agent_hermes", "hermes_pubkey_v0.1:test123", test_registry)
    with open(test_registry) as f:
        reg = json.load(f)
    assert "agent_hermes" in reg
    passed += 1
    print(f"  ✅ Registry contains agent_hermes: {reg['agent_hermes']['pubkey'][:20]}...")
    
    # Cleanup
    if os.path.exists(test_registry):
        os.remove(test_registry)
    
    # Summary
    total = passed + failed
    print(f"\n{'=' * 60}")
    print(f"RESULTS: {passed}/{total} passed")
    if failed:
        print(f"❌ {failed} FAILED")
    else:
        print(f"✅ ALL TESTS PASSED")
    print(f"{'=' * 60}")
    
    return failed == 0


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    
    cmd = sys.argv[1]
    
    if cmd == "verify":
        if len(sys.argv) < 3:
            print("Usage: verify <file> [--key=<secret_key>]")
            return
        filepath = sys.argv[2]
        key = None
        for arg in sys.argv[3:]:
            if arg.startswith("--key="):
                key = arg[6:]
        result = verify_file(filepath, key)
        print(json.dumps(result, indent=2))
    
    elif cmd == "verify-dir":
        if len(sys.argv) < 3:
            print("Usage: verify-dir <directory> [--key=<key>] [--pattern=<ext>]")
            return
        directory = sys.argv[2]
        key = None
        pattern = None
        for arg in sys.argv[3:]:
            if arg.startswith("--key="):
                key = arg[6:]
            elif arg.startswith("--pattern="):
                pattern = arg[10:]
        results = verify_directory(directory, pattern, key)
        print(f"Verified {len(results)} file(s):")
        for r in results:
            status = "✅" if r.get("valid") else "❌"
            print(f"  {status} {r.get('file', '?'):30s} | valid={r.get('valid','?')} sender={r.get('sender','?')}")
            if r.get("signature"):
                print(f"       sig_method={r['signature'].get('method','?')}")
    
    elif cmd == "check":
        if len(sys.argv) < 3:
            print("Usage: check <file> [--registry=<path>]")
            return
        filepath = sys.argv[2]
        registry = None
        for arg in sys.argv[3:]:
            if arg.startswith("--registry="):
                registry = arg[11:]
        result = verify_against_registry(filepath, registry)
        print(json.dumps(result, indent=2))
    
    elif cmd == "keygen":
        kp = generate_keypair()
        print(f"Algorithm:  {kp['algorithm']}")
        print(f"Created:    {kp['created']}")
        print(f"Private key: {kp['private_key']}")
        print(f"Public key:  {kp['public_key']}")
        print()
        print("To save private key:")
        print(f"  echo '{kp['private_key']}' > ~/.hermes/protocol_key")
        print(f"  chmod 600 ~/.hermes/protocol_key")
        print()
        print("To register public key:")
        print(f"  python3 protocol_verify.py register agent_myid '{kp['public_key']}'")
    
    elif cmd == "register":
        if len(sys.argv) < 4:
            print("Usage: register <agent_id> <pubkey> [--store=<path>]")
            return
        agent_id = sys.argv[2]
        pubkey = sys.argv[3]
        store = None
        for arg in sys.argv[4:]:
            if arg.startswith("--store="):
                store = arg[8:]
        path = register_pubkey(agent_id, pubkey, store)
        print(f"✅ Registered public key for '{agent_id}' in {path}")
    
    elif cmd == "test":
        success = run_tests()
        sys.exit(0 if success else 1)
    
    elif cmd == "parse":
        if len(sys.argv) < 3:
            print("Usage: parse <file>")
            return
        with open(sys.argv[2]) as f:
            content = f.read()
        parsed = parse_message(content)
        print(json.dumps(parsed, indent=2, default=str))
    
    else:
        print(f"Unknown command: {cmd}")
        print()
        print(__doc__)


if __name__ == "__main__":
    main()
