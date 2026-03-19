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
PROMPT_COUNT=0

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
  local top=$'\u250f\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2513'
  local mid=$'\u2523\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u252b'
  local bottom=$'\u2517\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u251b'
  local side=$'\u2503'

  printf '\033c'
  spacer 3
  printf '%b\n' "${YELLOW}${top}${RESET}"
  printf '%s %-60s %s\n' "$side" "$title" "$side"
  printf '%b\n' "${GREEN}${mid}${RESET}"
  printf '%s %-60s %s\n' "$side" "$subtitle" "$side"
  printf '%b\n' "${YELLOW}${bottom}${RESET}"
  spacer 3
}

prompt_default() {
  local label="$1"
  local default_value="$2"
  local note="${3:-}"
  local value

  if (( PROMPT_COUNT > 0 )); then
    printf '\n' > /dev/tty
  fi

  printf '%b%s%b [%s]: ' "$BOLD" "$label" "$RESET" "$default_value" > /dev/tty
  IFS= read -r value < /dev/tty

  if [[ -z "$value" ]]; then
    value="$default_value"
  fi

  if [[ -n "$note" ]]; then
    printf '\n%bNotice:%b %s\n\n' "$BOLD" "$RESET" "$note" > /dev/tty
  fi

  PROMPT_COUNT=$((PROMPT_COUNT + 1))
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
  local tz domain reality_domain fake_site instance_name

  frame '3XUI V1 Install Menu' 'Fresh host deployment for 3x-ui'
  instance_name="$(hostname -s)"
  domain="$(prompt_default 'Main domain' 'example.com' 'To accept the suggested value just press Enter.')"
  reality_domain="$(prompt_default 'REALITY domain' "real.${domain}")"
  tz="$(prompt_default 'Timezone' "$(detect_tz)")"
  fake_site="$(pick_random_fake_site)"

  spacer 3
  printf '%bStarting install with:%b\n' "$BOLD" "$RESET"
  printf '  domain    : %s\n' "$domain"
  printf '  reality   : %s\n' "$reality_domain"
  printf '  timezone  : %s\n' "$tz"
  printf '  fake site : %s\n' "$fake_site"
  spacer 3

  python3 -m install \
    --non-interactive \
    --set "INSTANCE_NAME=${instance_name}" \
    --set "DOMAIN=${domain}" \
    --set "REALITY_DOMAIN=${reality_domain}" \
    --set "TZ=${tz}" \
    --set "FAKE_SITE_TEMPLATE=${fake_site}"
}

main "$@"
