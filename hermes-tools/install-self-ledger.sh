#!/bin/bash
# One-command install: Self-Ledger
# Usage: bash <(curl -sL https://raw.githubusercontent.com/wjgong001/hermes-thinks/main/hermes-tools/install-self-ledger.sh)

set -e
echo "Installing Self-Ledger v0.2..."
pip install git+https://github.com/wjgong001/hermes-thinks.git --subdirectory=hermes-tools 2>/dev/null || {
    # Fallback: direct install from source
    TMPDIR=$(mktemp -d)
    cd "$TMPDIR"
    curl -sL "https://github.com/wjgong001/hermes-thinks/archive/main.tar.gz" | tar xz --strip=1
    pip install ./hermes-tools/
    cd / && rm -rf "$TMPDIR"
}
echo "Done! Try: python3 -c \"from self_ledger import record; print('OK')\""
