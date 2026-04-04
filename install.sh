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
INSTALL_BRANCH="${TRANSITHUB_BRANCH:-dev}"

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

has_tty() {
  [[ -t 0 && -t 1 && -e /dev/tty ]]
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

prompt_yes_no() {
  local label="$1"
  local default_answer="${2:-n}"
  local prompt_suffix='y/N'
  local value

  if [[ "$default_answer" == "y" || "$default_answer" == "Y" ]]; then
    prompt_suffix='Y/n'
  fi

  while true; do
    printf '%b%s%b [%s]: ' "$BOLD" "$label" "$RESET" "$prompt_suffix" > /dev/tty
    IFS= read -r value < /dev/tty
    value="${value:-$default_answer}"
    case "${value,,}" in
      y|yes)
        printf 'true'
        return
        ;;
      n|no)
        printf 'false'
        return
        ;;
    esac
    printf '\nPlease answer y or n.\n\n' > /dev/tty
  done
}

append_set_arg() {
  local key="$1"
  local value="$2"
  local -n target_ref="$3"
  target_ref+=(--set "${key}=${value}")
}

append_optional_env_arg() {
  local env_name="$1"
  local key="$2"
  local -n target_ref="$3"
  local value="${!env_name:-}"
  if [[ -n "$value" ]]; then
    target_ref+=(--set "${key}=${value}")
  fi
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

run_interactive_install() {
  local tz domain reality_domain tgproxy_public_host fake_site instance_name tgproxy_state
  local netbird_setup_key netbird_management_url netbird_state
  local enable_netbird
  local -a install_args

  frame 'TransitHub v2 Install Menu' "Branch: ${INSTALL_BRANCH}"
  instance_name="$(hostname -s)"
  domain="$(prompt_default 'Main domain' 'example.com' 'To accept the suggested value just press Enter.')"
  reality_domain="$(prompt_default 'REALITY domain' "real.${domain}")"
  printf '\n' > /dev/tty
  printf '%b%s%b [tg.%s]: ' "$BOLD" 'Telegram proxy domain' "$RESET" "$domain" > /dev/tty
  IFS= read -r tgproxy_public_host < /dev/tty
  if [[ -z "$tgproxy_public_host" ]]; then
    tgproxy_public_host="tg.${domain}"
  elif [[ "$tgproxy_public_host" == "-" ]]; then
    tgproxy_public_host=""
  fi
  printf '\n' > /dev/tty
  enable_netbird="$(prompt_yes_no 'Enable NetBird' 'n')"
  netbird_setup_key=""
  if [[ "$enable_netbird" == "true" ]]; then
    printf '\n' > /dev/tty
    printf '%b%s%b [required]: ' "$BOLD" 'NetBird setup key' "$RESET" > /dev/tty
    IFS= read -r netbird_setup_key < /dev/tty
  fi
  if [[ "$netbird_setup_key" == "-" || "$enable_netbird" != "true" ]]; then
    netbird_setup_key=""
  fi
  netbird_management_url=""
  if [[ -n "$netbird_setup_key" ]]; then
    while true; do
      printf '%b%s%b [https://management.example.com]: ' "$BOLD" 'NetBird management URL' "$RESET" > /dev/tty
      IFS= read -r netbird_management_url < /dev/tty
      if [[ -z "$netbird_management_url" || "$netbird_management_url" == "-" ]]; then
        netbird_setup_key=""
        netbird_management_url=""
        break
      fi
      if [[ "$netbird_management_url" == https://* ]]; then
        break
      fi
      printf '\nNetBird management URL must start with https:// or be skipped with -.\n\n' > /dev/tty
    done
  fi
  printf '\n' > /dev/tty
  tz="$(prompt_default 'Timezone' "$(detect_tz)")"
  fake_site="$(pick_random_fake_site)"
  if [[ -n "$tgproxy_public_host" ]]; then
    tgproxy_state="${tgproxy_public_host}"
  else
    tgproxy_state='disabled'
  fi
  if [[ -n "$netbird_setup_key" && -n "$netbird_management_url" ]]; then
    netbird_state="${netbird_management_url}"
  else
    netbird_state='disabled'
  fi

  spacer 3
  printf '%bStarting install with:%b\n' "$BOLD" "$RESET"
  printf '  domain    : %s\n' "$domain"
  printf '  reality   : %s\n' "$reality_domain"
  printf '  tgproxy   : %s\n' "$tgproxy_state"
  printf '  netbird   : %s\n' "$netbird_state"
  printf '  timezone  : %s\n' "$tz"
  printf '  fake site : %s\n' "$fake_site"
  spacer 3

  install_args=(
    python3 -m install.cli
    --non-interactive
    --set "INSTANCE_NAME=${instance_name}"
    --set "DOMAIN=${domain}"
    --set "REALITY_DOMAIN=${reality_domain}"
    --set "TGPROXY_PUBLIC_HOST=${tgproxy_public_host}"
    --set "NETBIRD_SETUP_KEY=${netbird_setup_key}"
    --set "NETBIRD_MANAGEMENT_URL=${netbird_management_url}"
    --set "TZ=${tz}"
    --set "FAKE_SITE_TEMPLATE=${fake_site}"
  )

  if [[ -n "${CERTBOT_STAGING:-}" ]]; then
    install_args+=(--set "CERTBOT_STAGING=${CERTBOT_STAGING}")
  fi

  "${install_args[@]}"
}

run_noninteractive_install() {
  local domain reality_domain tgproxy_public_host fake_site instance_name tz install_mode
  local netbird_setup_key netbird_management_url
  local -a install_args

  domain="${TRANSITHUB_DOMAIN:-}"
  if [[ -z "$domain" ]]; then
    printf 'No TTY is available. Set TRANSITHUB_DOMAIN and related TRANSITHUB_* variables, or pass explicit install.cli arguments.\n' >&2
    exit 1
  fi

  instance_name="${TRANSITHUB_INSTANCE_NAME:-$(hostname -s)}"
  reality_domain="${TRANSITHUB_REALITY_DOMAIN:-real.${domain}}"
  tgproxy_public_host="${TRANSITHUB_TGPROXY_PUBLIC_HOST:-tg.${domain}}"
  netbird_setup_key="${TRANSITHUB_NETBIRD_SETUP_KEY:-}"
  netbird_management_url="${TRANSITHUB_NETBIRD_MANAGEMENT_URL:-}"
  tz="${TRANSITHUB_TZ:-$(detect_tz)}"
  fake_site="${TRANSITHUB_FAKE_SITE_TEMPLATE:-$(pick_random_fake_site)}"
  install_mode="${TRANSITHUB_INSTALL_MODE:-auto}"
  if [[ "$tgproxy_public_host" == "-" ]]; then
    tgproxy_public_host=""
  fi
  if [[ "$netbird_setup_key" == "-" ]]; then
    netbird_setup_key=""
    netbird_management_url=""
  fi

  install_args=(
    python3 -m install.cli
    --non-interactive
    --mode "${install_mode}"
  )
  append_set_arg "INSTANCE_NAME" "${instance_name}" install_args
  append_set_arg "DOMAIN" "${domain}" install_args
  append_set_arg "REALITY_DOMAIN" "${reality_domain}" install_args
  append_set_arg "TGPROXY_PUBLIC_HOST" "${tgproxy_public_host}" install_args
  append_set_arg "NETBIRD_SETUP_KEY" "${netbird_setup_key}" install_args
  append_set_arg "NETBIRD_MANAGEMENT_URL" "${netbird_management_url}" install_args
  append_set_arg "TZ" "${tz}" install_args
  append_set_arg "FAKE_SITE_TEMPLATE" "${fake_site}" install_args
  append_optional_env_arg "TRANSITHUB_CERTBOT_STAGING" "CERTBOT_STAGING" install_args
  append_optional_env_arg "TRANSITHUB_CERTBOT_EMAIL" "CERTBOT_EMAIL" install_args

  printf 'No TTY detected. Running non-interactive install.\n'
  printf '  domain    : %s\n' "$domain"
  printf '  reality   : %s\n' "$reality_domain"
  printf '  tgproxy   : %s\n' "$tgproxy_public_host"
  if [[ -n "$netbird_setup_key" && -n "$netbird_management_url" ]]; then
    printf '  netbird   : %s\n' "$netbird_management_url"
  else
    printf '  netbird   : disabled\n'
    printf '              set TRANSITHUB_NETBIRD_SETUP_KEY and TRANSITHUB_NETBIRD_MANAGEMENT_URL to enable it\n'
  fi
  printf '  timezone  : %s\n' "$tz"
  printf '  fake site : %s\n' "$fake_site"
  printf '\n'

  "${install_args[@]}"
}

main() {
  if [[ "$#" -gt 0 ]]; then
    exec python3 -m install.cli "$@"
  fi

  if has_tty; then
    run_interactive_install
    return
  fi

  run_noninteractive_install
}

main "$@"
