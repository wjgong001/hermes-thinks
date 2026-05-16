#!/usr/bin/env python3
"""Hermes Probe CLI — pip-installable command line tool for Hermes Protocol"""
import sys, json, hmac, hashlib, base64, os, argparse

def cmd_ping(args):
    print(f"Pong from Hermes Protocol v0.2")
    print(f"Target: {args.agent_id or 'any'}")
    return 0

def cmd_sign(args):
    key = _load_key(args.key_file)
    if not key:
        key = input("Enter HMAC secret key: ").encode()
    sig = hmac.new(key, args.message.encode(), hashlib.sha256).digest()
    print(base64.b64encode(sig).decode())
    return 0

def cmd_verify(args):
    key = _load_key(args.key_file)
    if not key:
        key = input("Enter HMAC secret key: ").encode()
    expected = base64.b64decode(args.signature)
    actual = hmac.new(key, args.message.encode(), hashlib.sha256).digest()
    if hmac.compare_digest(expected, actual):
        print("✅ Signature valid")
        return 0
    print("❌ Signature invalid")
    return 1

def cmd_reputation(args):
    print(f"Reputation for {args.agent_id or 'self'}: coming in v1.0")
    return 0

def _load_key(path):
    if path and os.path.exists(path):
        with open(path) as f:
            return base64.b64decode(f.read().strip())
    return None

def main():
    parser = argparse.ArgumentParser(description="Hermes Protocol CLI")
    sub = parser.add_subparsers(dest="command")
    
    p_ping = sub.add_parser("ping", help="Ping an agent")
    p_ping.add_argument("agent_id", nargs="?", help="Agent ID to ping")
    
    p_sign = sub.add_parser("sign", help="Sign a message")
    p_sign.add_argument("message", help="Message to sign")
    p_sign.add_argument("-k", "--key-file", help="Path to HMAC key file")
    
    p_verify = sub.add_parser("verify", help="Verify a signed message")
    p_verify.add_argument("message", help="Original message")
    p_verify.add_argument("signature", help="Base64 signature")
    p_verify.add_argument("-k", "--key-file", help="Path to HMAC key file")
    
    p_rep = sub.add_parser("reputation", help="Check agent reputation")
    p_rep.add_argument("agent_id", nargs="?", help="Agent ID")
    
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 1
    
    cmds = {
        "ping": cmd_ping,
        "sign": cmd_sign,
        "verify": cmd_verify,
        "reputation": cmd_reputation,
    }
    return cmds[args.command](args)

if __name__ == "__main__":
    sys.exit(main())
