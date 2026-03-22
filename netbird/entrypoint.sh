#!/bin/sh
set -eu

NETBIRD_BIN="${NETBIRD_BIN:-netbird}"
NB_DAEMON_ADDR="${NB_DAEMON_ADDR:-unix:///var/run/netbird.sock}"
NB_LOG_LEVEL="${NB_LOG_LEVEL:-info}"
NB_ENTRYPOINT_SERVICE_TIMEOUT="${NB_ENTRYPOINT_SERVICE_TIMEOUT:-30}"

if [ -z "${NB_SETUP_KEY:-}" ]; then
  echo "NB_SETUP_KEY is required" >&2
  exit 1
fi

cleanup() {
  if [ -n "${service_pid:-}" ]; then
    kill -TERM "$service_pid" 2>/dev/null || true
    wait "$service_pid" 2>/dev/null || true
  fi
}

trap cleanup INT TERM EXIT

"$NETBIRD_BIN" service run &
service_pid="$!"

ready=0
i=0
while [ "$i" -lt "$NB_ENTRYPOINT_SERVICE_TIMEOUT" ]; do
  if [ -S /var/run/netbird.sock ]; then
    ready=1
    break
  fi
  i=$((i + 1))
  sleep 1
done

if [ "$ready" -ne 1 ]; then
  echo "NetBird daemon socket did not appear in time" >&2
  exit 1
fi

set -- up \
  --setup-key "${NB_SETUP_KEY}" \
  --management-url "${NB_MANAGEMENT_URL}" \
  --hostname "${NB_HOSTNAME:-$(hostname)}" \
  --log-level "${NB_LOG_LEVEL}"

if [ "${NB_DISABLE_DEFAULT_ROUTE:-false}" = "true" ]; then
  set -- "$@" --disable-client-routes
fi

"$NETBIRD_BIN" "$@"

wait "$service_pid"
