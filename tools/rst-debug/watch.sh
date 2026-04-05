#!/usr/bin/env bash
set -euo pipefail

LOG_FILE="${1:-/var/log/transithub-rst-debug/rst443.log}"
exec /usr/bin/python3 /usr/local/lib/transithub-rst-debug/classify_rst.py "$LOG_FILE"
