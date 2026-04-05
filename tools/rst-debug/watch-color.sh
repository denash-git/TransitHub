#!/usr/bin/env bash
set -euo pipefail

LOG_FILE="${1:-/var/log/transithub-rst-debug/rst443.log}"

tail -f "$LOG_FILE" | awk '
  /\[susp-/ {print "\033[1;31m" $0 "\033[0m"; fflush(); next}
  /\[unknown / {print "\033[1;33m" $0 "\033[0m"; fflush(); next}
  /\[has-conn\]/ {print "\033[0;36m" $0 "\033[0m"; fflush(); next}
  /\[normal  \]|\[norm-fin\]/ {print "\033[0;32m" $0 "\033[0m"; fflush(); next}
  {print; fflush()}
'
