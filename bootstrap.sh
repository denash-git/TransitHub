#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${TRANSITHUB_REPO_URL:-https://github.com/denash-git/TransitHub.git}"
INSTALL_DIR="${TRANSITHUB_INSTALL_DIR:-/root/TransitHub}"
BRANCH="${TRANSITHUB_BRANCH:-main}"
RAW_BOOTSTRAP_URL="${TRANSITHUB_BOOTSTRAP_URL:-https://raw.githubusercontent.com/denash-git/TransitHub/${BRANCH}/bootstrap.sh}"

rerun_with_sudo() {
  if ! command -v sudo >/dev/null 2>&1; then
    printf 'This bootstrap script must run as root or via sudo.\n' >&2
    exit 1
  fi

  if command -v curl >/dev/null 2>&1; then
    exec sudo -E bash -c "bash <(curl -fsSL '$RAW_BOOTSTRAP_URL')"
  fi

  if command -v wget >/dev/null 2>&1; then
    exec sudo -E bash -c "bash <(wget -qO- '$RAW_BOOTSTRAP_URL')"
  fi

  printf 'Neither curl nor wget is available to re-run bootstrap via sudo.\n' >&2
  exit 1
}

ensure_root() {
  if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    rerun_with_sudo
  fi
}

ensure_apt() {
  if ! command -v apt-get >/dev/null 2>&1; then
    printf 'apt-get is required. TransitHub bootstrap supports Debian 12 and Debian 13.\n' >&2
    exit 1
  fi
}

ensure_git() {
  if command -v git >/dev/null 2>&1; then
    return
  fi
  apt-get update
  apt-get install -y git ca-certificates
}

prepare_checkout() {
  if [[ -d "$INSTALL_DIR/.git" ]]; then
    git -C "$INSTALL_DIR" fetch origin "$BRANCH" --prune
    git -C "$INSTALL_DIR" checkout "$BRANCH"
    git -C "$INSTALL_DIR" pull --ff-only origin "$BRANCH"
    return
  fi

  if [[ -e "$INSTALL_DIR" ]]; then
    printf 'Install directory exists and is not a git repository: %s\n' "$INSTALL_DIR" >&2
    exit 1
  fi

  git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
}

main() {
  ensure_root
  ensure_apt
  ensure_git
  prepare_checkout
  cd "$INSTALL_DIR"
  exec bash install.sh "$@"
}

main "$@"
