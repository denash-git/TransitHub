#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${TRANSITHUB_REPO_URL:-https://github.com/denash-git/TransitHub.git}"
BRANCH="${TRANSITHUB_BRANCH:-}"
RAW_BOOTSTRAP_URL="${TRANSITHUB_BOOTSTRAP_URL:-https://raw.githubusercontent.com/denash-git/TransitHub/${BRANCH}/bootstrap.sh}"
TARGET_USER="${SUDO_USER:-${USER:-root}}"

ensure_branch_selected() {
  if [[ -n "$BRANCH" ]]; then
    return
  fi

  printf 'TRANSITHUB_BRANCH is required.\n' >&2
  printf 'Example for dev : TRANSITHUB_BRANCH=dev bash <(wget -qO- "https://raw.githubusercontent.com/denash-git/TransitHub/dev/bootstrap.sh")\n' >&2
  printf 'Example for main: TRANSITHUB_BRANCH=main bash <(wget -qO- "https://raw.githubusercontent.com/denash-git/TransitHub/main/bootstrap.sh")\n' >&2
  exit 1
}

resolve_home_dir() {
  local target_user="$1"
  if [[ -z "$target_user" || "$target_user" == "root" ]]; then
    printf '%s' '/root'
    return
  fi

  local passwd_home
  passwd_home="$(getent passwd "$target_user" | cut -d: -f6)"
  if [[ -n "$passwd_home" ]]; then
    printf '%s' "$passwd_home"
    return
  fi

  printf '%s' "/home/${target_user}"
}

resolve_install_dir() {
  if [[ -n "${TRANSITHUB_INSTALL_DIR:-}" ]]; then
    printf '%s' "$TRANSITHUB_INSTALL_DIR"
    return
  fi

  local home_dir
  home_dir="$(resolve_home_dir "$TARGET_USER")"
  printf '%s' "${home_dir%/}/TransitHub"
}

INSTALL_DIR="$(resolve_install_dir)"

run_as_target_user() {
  if [[ "$TARGET_USER" != "root" && "${EUID:-$(id -u)}" -eq 0 ]]; then
    sudo -u "$TARGET_USER" -H "$@"
    return
  fi
  "$@"
}

ensure_install_dir_owner() {
  if [[ "$TARGET_USER" != "root" && -e "$INSTALL_DIR" ]]; then
    chown -R "$TARGET_USER":"$TARGET_USER" "$INSTALL_DIR"
  fi
}

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

install_already_finalized() {
  local state_path="${INSTALL_DIR}/.transithub-install-state.json"
  [[ -f "$state_path" ]] || return 1
  grep -q '"status"[[:space:]]*:[[:space:]]*"installed"' "$state_path"
}

re_prune_installed_tree() {
  local target
  for target in \
    "$INSTALL_DIR/bootstrap.sh" \
    "$INSTALL_DIR/docs" \
    "$INSTALL_DIR/install" \
    "$INSTALL_DIR/install.sh" \
    "$INSTALL_DIR/README.md" \
    "$INSTALL_DIR/requirements.txt" \
    "$INSTALL_DIR/templates" \
    "$INSTALL_DIR/tests" \
    "$INSTALL_DIR/instance.env.example" \
    "$INSTALL_DIR/__pycache__"
  do
    [[ -e "$target" ]] || continue
    rm -rf -- "$target"
  done
}

prepare_checkout() {
  if install_already_finalized; then
    re_prune_installed_tree
    printf 'TransitHub installation is already finalized in %s\n' "$INSTALL_DIR"
    printf 'Use `menu` for any post-install changes.\n'
    exit 0
  fi

  ensure_install_dir_owner
  if [[ -d "$INSTALL_DIR/.git" ]]; then
    run_as_target_user git -C "$INSTALL_DIR" fetch origin "$BRANCH" --prune
    run_as_target_user git -C "$INSTALL_DIR" checkout "$BRANCH"
    run_as_target_user git -C "$INSTALL_DIR" pull --ff-only origin "$BRANCH"
    return
  fi

  if [[ -e "$INSTALL_DIR" ]]; then
    printf 'Install directory exists and is not a git repository: %s\n' "$INSTALL_DIR" >&2
    exit 1
  fi

  run_as_target_user git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
}

main() {
  ensure_branch_selected
  ensure_root
  ensure_apt
  ensure_git
  prepare_checkout
  cd "$INSTALL_DIR"
  exec bash install.sh "$@"
}

main "$@"
