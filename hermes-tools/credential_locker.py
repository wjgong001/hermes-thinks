#!/usr/bin/env python3
"""
Credential Locker — lightweight, zero-dependency credential management for Termux.
No systemd, no dbus, no Redis. Just filesystem atomicity with write+rename.

Usage:
  python credential_locker.py get <service> [key]
  python credential_locker.py set <service> <key>=<value> [key2=value2 ...]
  python credential_locker.py list
  python credential_locker.py refresh <service> <url> <username_field> <password_field>

Example:
  python credential_locker.py set moltbook api_key=moltbook_sk_xxx account=hermes_agent_07
  python credential_locker.py get moltbook api_key
  python credential_locker.py list
"""

import json
import os
import sys
import time
import urllib.request
import urllib.parse

LOCKER_DIR = os.path.expanduser("~/.hermes/auth")

def _ensure_dir():
    os.makedirs(LOCKER_DIR, exist_ok=True)
    # Set restrictive permissions if possible
    try:
        os.chmod(LOCKER_DIR, 0o700)
    except:
        pass

def _path(service):
    """Path for a service credential file."""
    # Sanitize service name to avoid path traversal
    safe = service.replace("/", "_").replace("..", "_")
    return os.path.join(LOCKER_DIR, safe + ".json")

def get(service, key=None):
    """Get credential(s) for a service. Returns the full dict or specific key."""
    path = _path(service)
    if not os.path.exists(path):
        return None
    
    try:
        with open(path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    
    # Check expiry
    expiry = data.get("expiry_ts", 0)
    if expiry and time.time() > expiry:
        # Expired but still return data — caller should handle refresh
        data["_expired"] = True
    
    if key:
        return data.get(key)
    return data

def set_creds(service, **kwargs):
    """Store credentials for a service. Atomic write via temp file + rename."""
    _ensure_dir()
    path = _path(service)
    
    # Read existing
    existing = {}
    if os.path.exists(path):
        try:
            with open(path) as f:
                existing = json.load(f)
        except:
            pass
    
    existing.update(kwargs)
    existing["_updated_at"] = time.time()
    
    # Atomic write
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(existing, f, indent=2, default=str)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    
    return True

def list_services():
    """List all services with credentials and their expiry status."""
    _ensure_dir()
    services = []
    for fname in sorted(os.listdir(LOCKER_DIR)):
        if not fname.endswith(".json") or fname.endswith(".tmp.json"):
            continue
        service = fname[:-5]  # remove .json
        data = get(service)
        if data:
            expiry = data.get("expiry_ts", 0)
            expired = bool(expiry and time.time() > expiry)
            has_key = bool(data.get("api_key") or data.get("token") or data.get("password"))
            key_count = sum(1 for k in data if not k.startswith("_"))
            services.append({
                "service": service,
                "keys": key_count,
                "has_creds": has_key,
                "expired": expired,
                "updated": data.get("_updated_at", 0)
            })
    return services

def refresh_from_api(service, login_url, username_field="address", password_field="password"):
    """
    Refresh credentials by re-authenticating via API.
    Designed for Moltbook-style auth where there's no refresh token.
    """
    data = get(service)
    if not data:
        return False, "No existing credentials to refresh from"
    
    username = data.get(username_field)
    password = data.get(password_field)
    if not username or not password:
        return False, f"Missing {username_field} or {password_field}"
    
    try:
        payload = json.dumps({username_field: username, password_field: password}).encode()
        req = urllib.request.Request(
            login_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
        
        # Common patterns for where the token lives in responses
        api_key = (result.get("api_key") or result.get("token") or 
                   result.get("access_token") or result.get("key"))
        
        if api_key:
            set_creds(service, api_key=api_key)
            return True, f"Refreshed {service} successfully"
        else:
            return False, f"No token found in response: {list(result.keys())[:5]}"
    except Exception as e:
        return False, f"Refresh failed: {e}"

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "get":
        if len(sys.argv) < 3:
            print("Usage: credential_locker.py get <service> [key]")
            sys.exit(1)
        service = sys.argv[2]
        key = sys.argv[3] if len(sys.argv) > 3 else None
        result = get(service, key)
        if result is None:
            print(f"Not found: {service}" + (f"/{key}" if key else ""))
            sys.exit(1)
        if isinstance(result, dict):
            print(json.dumps(result, indent=2, default=str))
        else:
            print(result)
    
    elif cmd == "set":
        if len(sys.argv) < 4:
            print("Usage: credential_locker.py set <service> key=value [...]")
            sys.exit(1)
        service = sys.argv[2]
        kwargs = {}
        for arg in sys.argv[3:]:
            if "=" in arg:
                k, v = arg.split("=", 1)
                kwargs[k] = v
        set_creds(service, **kwargs)
        print(f"OK: {service} updated ({len(kwargs)} keys)")
    
    elif cmd == "list":
        services = list_services()
        if not services:
            print("No credentials stored.")
        else:
            for s in services:
                expired = " ⚠️ EXPIRED" if s["expired"] else ""
                print(f"  {s['service']}: {s['keys']} keys, updated {time.strftime('%H:%M', time.localtime(s['updated']))}{expired}")
    
    elif cmd == "refresh":
        if len(sys.argv) < 4:
            print("Usage: credential_locker.py refresh <service> <login_url> [username_field] [password_field]")
            sys.exit(1)
        service = sys.argv[2]
        login_url = sys.argv[3]
        u_field = sys.argv[4] if len(sys.argv) > 4 else "address"
        p_field = sys.argv[5] if len(sys.argv) > 5 else "password"
        ok, msg = refresh_from_api(service, login_url, u_field, p_field)
        print(msg)
        if not ok:
            sys.exit(1)
    
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)

if __name__ == "__main__":
    main()
