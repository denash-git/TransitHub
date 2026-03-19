#!/bin/sh
set -eu

DATA_DIR="/data"
PROXY_SECRET_FILE="${DATA_DIR}/proxy-secret"
PROXY_CONFIG_FILE="${DATA_DIR}/proxy-multi.conf"

fetch_file() {
  url="$1"
  target="$2"
  tmp_file="${target}.tmp"
  curl -fsSL "$url" -o "$tmp_file"
  mv "$tmp_file" "$target"
}

mkdir -p "$DATA_DIR"

if [ -z "${MTPROXY_SECRET:-}" ]; then
  echo "MTPROXY_SECRET is required." >&2
  exit 1
fi

fetch_file "https://core.telegram.org/getProxySecret" "$PROXY_SECRET_FILE"
fetch_file "https://core.telegram.org/getProxyConfig" "$PROXY_CONFIG_FILE"

set -- /opt/mtproxy/mtproto-proxy \
  -u nobody \
  -p "${MTPROXY_STATS_PORT:-2398}" \
  -H "${MTPROXY_PORT:-3443}" \
  -S "${MTPROXY_SECRET}" \
  --aes-pwd "$PROXY_SECRET_FILE" \
  "$PROXY_CONFIG_FILE" \
  -M "${MTPROXY_WORKERS:-1}"

if [ -n "${MTPROXY_TAG:-}" ]; then
  set -- "$@" -P "${MTPROXY_TAG}"
fi

if [ -n "${MTPROXY_TLS_DOMAIN:-}" ]; then
  set -- "$@" -D "${MTPROXY_TLS_DOMAIN}"
fi

exec "$@"
