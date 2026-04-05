#!/usr/bin/env bash
set -euo pipefail

[[ "${EUID:-$(id -u)}" -eq 0 ]] || {
  echo "Run as root." >&2
  exit 1
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="/usr/local/lib/transithub-rst-debug"
BIN_DIR="/usr/local/bin"
LOG_DIR="/var/log/transithub-rst-debug"
CONF_FILE="/etc/default/transithub-rst-debug"
SERVICE_FILE="/etc/systemd/system/transithub-rst-debug.service"

install -d "$LIB_DIR" "$LOG_DIR"
install -m 755 "$SCRIPT_DIR/classify_rst.py" "$LIB_DIR/classify_rst.py"
install -m 755 "$SCRIPT_DIR/watch.sh" "$BIN_DIR/transithub-rst-debug-watch"
install -m 755 "$SCRIPT_DIR/watch-color.sh" "$BIN_DIR/transithub-rst-debug-watch-color"
install -m 644 "$SCRIPT_DIR/transithub-rst-debug.service" "$SERVICE_FILE"

if [[ ! -f "$CONF_FILE" ]]; then
  cat > "$CONF_FILE" <<'EOF'
RST_DEBUG_IFACE=eth0
RST_DEBUG_PORT=443
RST_DEBUG_LOG=/var/log/transithub-rst-debug/rst443.log
EOF
fi

systemctl daemon-reload
systemctl enable --now transithub-rst-debug.service

echo "Installed."
echo "Log     : /var/log/transithub-rst-debug/rst443.log"
echo "Watch   : /usr/local/bin/transithub-rst-debug-watch-color"
echo "Status  : systemctl status transithub-rst-debug.service"
