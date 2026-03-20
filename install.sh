#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  if command -v sudo >/dev/null 2>&1; then
    exec sudo -E bash "$0" "$@"
  fi
  printf 'This installer must run as root. Re-run with sudo.\n' >&2
  exit 1
fi

YELLOW=$'\033[1;33m'
GREEN=$'\033[1;32m'
BOLD=$'\033[1m'
RESET=$'\033[0m'
FRAME_WIDTH=60

repeat_char() {
  local char="$1"
  local count="$2"
  local result=""
  local i
  for ((i = 0; i < count; i++)); do
    result+="$char"
  done
  printf '%s' "$result"
}

spacer() {
  local lines="${1:-1}"
  local i
  for ((i = 0; i < lines; i++)); do
    printf '\n'
  done
}

frame() {
  local title="$1"
  local subtitle="$2"
  local side=$'\u2503'
  local horiz=$'\u2501'
  local top=$'\u250f'"$(repeat_char "$horiz" $((FRAME_WIDTH + 2)))"$'\u2513'
  local mid=$'\u2523'"$(repeat_char "$horiz" $((FRAME_WIDTH + 2)))"$'\u252b'
  local bottom=$'\u2517'"$(repeat_char "$horiz" $((FRAME_WIDTH + 2)))"$'\u251b'

  printf '\033c'
  spacer 3
  printf '%b%s%b\n' "$YELLOW" "$top" "$RESET"
  printf '%b%s %-'${FRAME_WIDTH}'s %s%b\n' "$YELLOW" "$side" "$title" "$side" "$RESET"
  printf '%b%s%b\n' "$GREEN" "$mid" "$RESET"
  printf '%b%s %-'${FRAME_WIDTH}'s %s%b\n' "$GREEN" "$side" "$subtitle" "$side" "$RESET"
  printf '%b%s%b\n' "$YELLOW" "$bottom" "$RESET"
  spacer 3
}

prompt_default() {
  local label="$1"
  local default_value="$2"
  local note="${3:-}"
  local value

  printf '%b%s%b [%s]: ' "$BOLD" "$label" "$RESET" "$default_value" > /dev/tty
  IFS= read -r value < /dev/tty

  if [[ -z "$value" ]]; then
    value="$default_value"
  fi

  if [[ -n "$note" ]]; then
    printf '\n%bNotice:%b %s\n\n' "$BOLD" "$RESET" "$note" > /dev/tty
  fi

  printf '%s' "$value"
}

pick_random_fake_site() {
  local root="templates/fakesite"
  mapfile -t FAKE_SITE_CHOICES < <(find "$root" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort)
  if [[ ${#FAKE_SITE_CHOICES[@]} -eq 0 ]]; then
    printf '%s' 'signal-wire'
    return
  fi
  printf '%s' "${FAKE_SITE_CHOICES[RANDOM % ${#FAKE_SITE_CHOICES[@]}]}"
}

detect_tz() {
  timedatectl show -p Timezone --value 2>/dev/null || cat /etc/timezone 2>/dev/null || printf 'Europe/Moscow'
}

main() {
  local tz domain reality_domain mtproxy_tls_domain fake_site instance_name mtproxy_state
  local -a install_args

  frame 'TransitHub v2 Install Menu' 'Fresh host deployment for proxy platform'
  instance_name="$(hostname -s)"
  domain="$(prompt_default 'Main domain' 'example.com' 'To accept the suggested value just press Enter.')"
  reality_domain="$(prompt_default 'REALITY domain' "real.${domain}")"
  printf '\n' > /dev/tty
  printf '%b%s%b [tg.%s]: ' "$BOLD" 'MTProxy TLS domain' "$RESET" "$domain" > /dev/tty
  IFS= read -r mtproxy_tls_domain < /dev/tty
  if [[ -z "$mtproxy_tls_domain" ]]; then
    mtproxy_tls_domain="tg.${domain}"
  elif [[ "$mtproxy_tls_domain" == "-" ]]; then
    mtproxy_tls_domain=""
  fi
  printf '\n' > /dev/tty
  tz="$(prompt_default 'Timezone' "$(detect_tz)")"
  fake_site="$(pick_random_fake_site)"
  if [[ -n "$mtproxy_tls_domain" ]]; then
    mtproxy_state="$mtproxy_tls_domain"
  else
    mtproxy_state='disabled'
  fi

  spacer 3
  printf '%bStarting install with:%b\n' "$BOLD" "$RESET"
  printf '  domain    : %s\n' "$domain"
  printf '  reality   : %s\n' "$reality_domain"
  printf '  mtproxy   : %s\n' "$mtproxy_state"
  printf '  timezone  : %s\n' "$tz"
  printf '  fake site : %s\n' "$fake_site"
  spacer 3

  install_args=(
    python3 -m install.cli
    --non-interactive
    --set "INSTANCE_NAME=${instance_name}"
    --set "DOMAIN=${domain}"
    --set "REALITY_DOMAIN=${reality_domain}"
    --set "MTPROXY_TLS_DOMAIN=${mtproxy_tls_domain}"
    --set "TZ=${tz}"
    --set "FAKE_SITE_TEMPLATE=${fake_site}"
  )

  if [[ -n "${CERTBOT_STAGING:-}" ]]; then
    install_args+=(--set "CERTBOT_STAGING=${CERTBOT_STAGING}")
  fi

  "${install_args[@]}"
}

main "$@"
