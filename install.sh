#!/usr/bin/env bash
set -euo pipefail

frame() {
  local title="$1"
  local subtitle="${2:-}"
  printf '\033c'
  printf '┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓\n'
  printf '┃ %-60s ┃\n' "$title"
  if [[ -n "$subtitle" ]]; then
    printf '┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫\n'
    printf '┃ %-60s ┃\n' "$subtitle"
  fi
  printf '┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛\n'
}

prompt_default() {
  local label="$1"
  local default_value="$2"
  local value
  read -r -p "$label [$default_value]: " value
  if [[ -z "$value" ]]; then
    value="$default_value"
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
  local tz domain reality_domain fake_site instance_name

  frame '3XUI V1 Install Menu' 'Fresh host deployment for 3x-ui'
  instance_name="$(hostname -s)"
  domain="$(prompt_default 'Main domain' 'example.com')"
  reality_domain="$(prompt_default 'REALITY domain' "real.${domain}")"
  tz="$(prompt_default 'Timezone, Enter = keep VPS default' "$(detect_tz)")"
  fake_site="$(pick_random_fake_site)"

  printf '\nStarting install with:\n'
  printf '  domain    : %s\n' "$domain"
  printf '  reality   : %s\n' "$reality_domain"
  printf '  timezone  : %s\n' "$tz"
  printf '  fake site : %s\n\n' "$fake_site"

  python3 install.py \
    --non-interactive \
    --set "INSTANCE_NAME=${instance_name}" \
    --set "DOMAIN=${domain}" \
    --set "REALITY_DOMAIN=${reality_domain}" \
    --set "TZ=${tz}" \
    --set "FAKE_SITE_TEMPLATE=${fake_site}"
}

main "$@"
