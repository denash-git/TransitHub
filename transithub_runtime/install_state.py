from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

from . import paths


STATUS_FRESH = "fresh"
STATUS_IN_PROGRESS = "in_progress"
STATUS_FAILED = "failed"
STATUS_INSTALLED = "installed"
VALID_STATUSES = {
    STATUS_FRESH,
    STATUS_IN_PROGRESS,
    STATUS_FAILED,
    STATUS_INSTALLED,
}


def utc_timestamp() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()


def default_state() -> dict[str, str]:
    return {
        "status": STATUS_FRESH,
        "branch": current_branch(),
        "install_id": "",
        "started_at": "",
        "completed_at": "",
        "last_failed_step": "",
        "last_error": "",
    }


def current_branch() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=paths.PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def read_state(path: Path = paths.INSTALL_STATE_PATH) -> dict[str, str]:
    if not path.exists():
        return default_state()
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid install state JSON in {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ValueError(f"Install state file must contain a JSON object: {path}")

    state = default_state()
    for key in state:
        value = loaded.get(key, "")
        if isinstance(value, str):
            state[key] = value
    if state["status"] not in VALID_STATUSES:
        state["status"] = STATUS_FAILED
        state["last_error"] = f"Unknown install state status: {loaded.get('status')!r}"
    return state


def write_state(state: dict[str, str], path: Path = paths.INSTALL_STATE_PATH) -> dict[str, str]:
    rendered = default_state()
    rendered.update({key: str(value) for key, value in state.items() if key in rendered})
    path.write_text(json.dumps(rendered, indent=2) + "\n", encoding="utf-8")
    return rendered


def begin_install(mode: str, path: Path = paths.INSTALL_STATE_PATH) -> dict[str, str]:
    state = read_state(path)
    state.update(
        {
            "status": STATUS_IN_PROGRESS,
            "branch": current_branch(),
            "install_id": utc_timestamp(),
            "started_at": utc_timestamp(),
            "completed_at": "",
            "last_failed_step": f"{mode}: starting",
            "last_error": "",
        }
    )
    return write_state(state, path)


def mark_step(step_title: str, path: Path = paths.INSTALL_STATE_PATH) -> dict[str, str]:
    state = read_state(path)
    state["last_failed_step"] = step_title
    return write_state(state, path)


def mark_failed(
    step_title: str,
    error_message: str,
    path: Path = paths.INSTALL_STATE_PATH,
) -> dict[str, str]:
    state = read_state(path)
    state.update(
        {
            "status": STATUS_FAILED,
            "last_failed_step": step_title,
            "last_error": error_message,
            "completed_at": "",
        }
    )
    return write_state(state, path)


def mark_installed(path: Path = paths.INSTALL_STATE_PATH) -> dict[str, str]:
    state = read_state(path)
    state.update(
        {
            "status": STATUS_INSTALLED,
            "completed_at": utc_timestamp(),
            "last_error": "",
        }
    )
    return write_state(state, path)
