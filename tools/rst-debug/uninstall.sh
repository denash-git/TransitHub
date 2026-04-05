#!/usr/bin/env bash
set -euo pipefail

[[ "${EUID:-$(id -u)}" -eq 0 ]] || {
  echo "Run as root." >&2
  exit 1
}

systemctl disable --now transithub-rst-debug.service 2>/dev/null || true
rm -f /etc/systemd/system/transithub-rst-debug.service
rm -f /usr/local/bin/transithub-rst-debug-watch
rm -f /usr/local/bin/transithub-rst-debug-watch-color
rm -rf /usr/local/lib/transithub-rst-debug
systemctl daemon-reload

echo "Removed binaries and service."
echo "Left intact:"
echo "  /etc/default/transithub-rst-debug"
echo "  /var/log/transithub-rst-debug"
