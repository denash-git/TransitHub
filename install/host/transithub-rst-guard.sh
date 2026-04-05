#!/usr/bin/env bash
set -euo pipefail

IPSET_NAME="${TRANSITHUB_RST_IPSET_NAME:-TH_RST443_SRC}"
CHAIN_NAME="${TRANSITHUB_RST_CHAIN_NAME:-TH_RST443_BLOCK}"
PORT="${TRANSITHUB_RST_PORT:-443}"
PRIMARY_URL="${TRANSITHUB_RST_SOURCE_URL:-https://raw.githubusercontent.com/tread-lightly/CyberOK_Skipa_ips/main/lists/skipa_cidr.txt}"
FALLBACK_URL="${TRANSITHUB_RST_FALLBACK_URL:-https://raw.githubusercontent.com/tread-lightly/CyberOK_Skipa_ips/main/lists/skipa_checkpoint.csv}"
STATE_DIR="${TRANSITHUB_RST_STATE_DIR:-/etc/transithub/rst-guard}"
CACHE_FILE="${STATE_DIR}/cyberok_source.txt"
UPDATE_LOG="${STATE_DIR}/update.log"
IPSET_SAVE="/etc/ipset.conf"
IPTABLES_SAVE="/etc/iptables/rules.v4"
LOG_PREFIX="TH-RST443 BLOCK "
MIN_ENTRIES=100

ts() {
  date '+%Y-%m-%d %H:%M:%S'
}

log() {
  mkdir -p "$STATE_DIR"
  printf '[%s] %s\n' "$(ts)" "$*" | tee -a "$UPDATE_LOG"
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

require_root() {
  [[ "${EUID:-$(id -u)}" -eq 0 ]] || die "Run as root."
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

ensure_paths() {
  mkdir -p "$STATE_DIR"
}

parse_entry() {
  local raw="$1"
  raw="$(printf '%s' "$raw" | tr -d '\r' | sed 's/#.*//' | xargs)"
  [[ -n "$raw" ]] || return 1
  printf '%s\n' "$raw" | grep -Eo '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+(/[0-9]+)?$' || return 1
}

fetch_source_list() {
  local tmp_raw tmp_clean count
  tmp_raw="$(mktemp)"
  tmp_clean="$(mktemp)"

  if ! curl -fsSL "$PRIMARY_URL" -o "$tmp_raw"; then
    curl -fsSL "$FALLBACK_URL" -o "$tmp_raw"
  fi

  : > "$tmp_clean"
  while IFS= read -r line; do
    parse_entry "$line" >> "$tmp_clean" || true
  done < "$tmp_raw"

  sort -u "$tmp_clean" -o "$tmp_clean"
  count="$(wc -l < "$tmp_clean" | tr -d ' ')"
  if [[ "$count" -lt "$MIN_ENTRIES" ]]; then
    rm -f "$tmp_raw" "$tmp_clean"
    die "Downloaded list is too short: ${count} entries."
  fi

  mv "$tmp_clean" "$CACHE_FILE"
  rm -f "$tmp_raw"
  log "Fetched ${count} source entries into ${CACHE_FILE}"
}

build_ipset_from_cache() {
  local tmp_set count line
  [[ -s "$CACHE_FILE" ]] || die "Cache file is missing: $CACHE_FILE"

  tmp_set="${IPSET_NAME}_TMP"
  ipset destroy "$tmp_set" 2>/dev/null || true
  ipset create "$tmp_set" hash:net family inet hashsize 1024 maxelem 4096

  count=0
  while IFS= read -r line; do
    [[ -n "$line" ]] || continue
    ipset add "$tmp_set" "$line"
    count=$((count + 1))
  done < "$CACHE_FILE"

  if [[ "$count" -lt "$MIN_ENTRIES" ]]; then
    ipset destroy "$tmp_set" 2>/dev/null || true
    die "Refusing to load short list into ${IPSET_NAME}: ${count} entries."
  fi

  ipset create "$IPSET_NAME" hash:net family inet hashsize 1024 maxelem 4096 -exist
  ipset swap "$tmp_set" "$IPSET_NAME"
  ipset destroy "$tmp_set"
  log "Loaded ${count} entries into ipset ${IPSET_NAME}"
}

delete_rule_while_present() {
  local chain="$1"
  shift
  while iptables -C "$chain" "$@" 2>/dev/null; do
    iptables -D "$chain" "$@"
  done
}

cleanup_legacy_rules() {
  delete_rule_while_present INPUT -p tcp -m tcp --tcp-flags RST RST -j LOG --log-prefix "RST-IN: "
  delete_rule_while_present FORWARD -p tcp -m tcp --tcp-flags RST RST -j LOG --log-prefix "RST-FWD: "
  delete_rule_while_present INPUT -j TSPUBLOCK
  delete_rule_while_present FORWARD -j TSPUBLOCK

  if iptables -S TSPUBLOCK >/dev/null 2>&1; then
    iptables -F TSPUBLOCK || true
    iptables -X TSPUBLOCK || true
  fi

  if ipset list TSPUIPS >/dev/null 2>&1; then
    ipset destroy TSPUIPS || true
  fi
}

ensure_chain() {
  iptables -N "$CHAIN_NAME" 2>/dev/null || true
  iptables -F "$CHAIN_NAME"
  iptables -A "$CHAIN_NAME" -m limit --limit 12/min --limit-burst 20 -j LOG --log-prefix "$LOG_PREFIX" --log-level 6
  iptables -A "$CHAIN_NAME" -j DROP

  if ! iptables -C INPUT -p tcp -m tcp --dport "$PORT" --tcp-flags RST RST -m set --match-set "$IPSET_NAME" src -j "$CHAIN_NAME" 2>/dev/null; then
    iptables -I INPUT 1 -p tcp -m tcp --dport "$PORT" --tcp-flags RST RST -m set --match-set "$IPSET_NAME" src -j "$CHAIN_NAME"
  fi

  if ! iptables -C FORWARD -p tcp -m tcp --dport "$PORT" --tcp-flags RST RST -m set --match-set "$IPSET_NAME" src -j "$CHAIN_NAME" 2>/dev/null; then
    iptables -I FORWARD 1 -p tcp -m tcp --dport "$PORT" --tcp-flags RST RST -m set --match-set "$IPSET_NAME" src -j "$CHAIN_NAME"
  fi
}

save_state() {
  ipset save > "$IPSET_SAVE"
  iptables-save > "$IPTABLES_SAVE"
  log "Saved ipset to ${IPSET_SAVE} and iptables to ${IPTABLES_SAVE}"
}

print_status() {
  local count
  count="0"
  if ipset list "$IPSET_NAME" >/dev/null 2>&1; then
    count="$(ipset list "$IPSET_NAME" | awk '/Number of entries:/ {print $4}')"
  fi

  printf 'TransitHub RST Guard\n'
  printf '  Port          : %s\n' "$PORT"
  printf '  IP set        : %s\n' "$IPSET_NAME"
  printf '  Chain         : %s\n' "$CHAIN_NAME"
  printf '  Entries       : %s\n' "$count"
  printf '\niptables counters:\n'
  iptables -L "$CHAIN_NAME" -v -n --line-numbers 2>/dev/null || true
  printf '\nINPUT/FORWARD hooks:\n'
  iptables -L INPUT -v -n --line-numbers 2>/dev/null | grep "$CHAIN_NAME" || true
  iptables -L FORWARD -v -n --line-numbers 2>/dev/null | grep "$CHAIN_NAME" || true
  printf '\nRecent blocked events:\n'
  journalctl -k -n 10 -o short-iso --grep "$LOG_PREFIX" 2>/dev/null || true
}

watch_blocks() {
  journalctl -k -f -n 20 -o short-iso --grep "$LOG_PREFIX" | while IFS= read -r line; do
    ts_field="$(printf '%s\n' "$line" | awk '{print $1}')"
    src="$(printf '%s\n' "$line" | sed -n 's/.*SRC=\([^ ]*\).*/\1/p')"
    dst="$(printf '%s\n' "$line" | sed -n 's/.*DST=\([^ ]*\).*/\1/p')"
    spt="$(printf '%s\n' "$line" | sed -n 's/.*SPT=\([^ ]*\).*/\1/p')"
    dpt="$(printf '%s\n' "$line" | sed -n 's/.*DPT=\([^ ]*\).*/\1/p')"
    ttl="$(printf '%s\n' "$line" | sed -n 's/.*TTL=\([^ ]*\).*/\1/p')"
    printf '%s [block] src=%s dst=%s spt=%s dpt=%s ttl=%s\n' "$ts_field" "${src:--}" "${dst:--}" "${spt:--}" "${dpt:--}" "${ttl:--}"
  done
}

update_rules() {
  fetch_source_list
  build_ipset_from_cache
  cleanup_legacy_rules
  ensure_chain
  save_state
}

restore_from_cache() {
  build_ipset_from_cache
  cleanup_legacy_rules
  ensure_chain
  save_state
}

main() {
  require_root
  ensure_paths
  require_command curl
  require_command iptables
  require_command ipset
  require_command journalctl

  case "${1:-}" in
    install|update)
      update_rules
      ;;
    restore)
      restore_from_cache
      ;;
    status)
      print_status
      ;;
    watch)
      watch_blocks
      ;;
    *)
      printf 'Usage: %s {install|update|restore|status|watch}\n' "$0" >&2
      exit 1
      ;;
  esac
}

main "$@"
