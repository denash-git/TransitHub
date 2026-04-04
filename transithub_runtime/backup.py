from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile

from . import paths
from .env import parse_env, render_env
from .tgproxy import enabled as tgproxy_enabled
from .xui_db import seed_xui_db


BUNDLE_SCHEMA_VERSION = "1"
BUNDLE_SUFFIX = ".thbundle.tar.gz"
BACKUP_DIR = Path("/root/transithub-backups")
RESTORE_INBOX_DIR = Path("/root/transithub-restore")
PAYLOAD_PREFIX = Path("payload") / "project"

PROJECT_FILE_PATHS = [
    paths.INSTANCE_ENV_PATH,
    paths.SERVICE_TGPROXY_CONFIG_PATH,
]
PROJECT_DIR_PATHS = [
    paths.SERVICE_NGINX_CONFIG_DIR,
    paths.SERVICE_NGINX_EXTENSIONS_DIR,
    paths.SERVICE_CLIENT_PAGE_DIR,
    paths.SERVICE_FAKE_SITE_DIR,
]
XUI_DB_PATH = paths.SERVICE_XUI_DATA_DIR / "x-ui.db"
REQUIRED_BUNDLE_RELATIVE_PATHS = {
    Path("payload/project/instance.env"),
    Path("payload/project/xui/data/x-ui.db"),
}


class BackupError(RuntimeError):
    pass


@dataclass(frozen=True)
class BundleSummary:
    bundle_path: Path
    manifest: dict[str, object]
    project_files: list[Path]


def backup_bundle(output_dir: Path | None = None, label: str = "backup") -> BundleSummary:
    ensure_runtime_files_exist()
    target_dir = output_dir or BACKUP_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = target_dir / bundle_name(label)

    with tempfile.TemporaryDirectory(prefix="transithub-backup-") as tmp_root:
        staging_root = Path(tmp_root)
        payload_root = staging_root / PAYLOAD_PREFIX
        payload_root.mkdir(parents=True, exist_ok=True)

        stage_project_file(paths.INSTANCE_ENV_PATH, payload_root)
        stage_sqlite_snapshot(XUI_DB_PATH, payload_root / relative_to_project(XUI_DB_PATH))

        for file_path in PROJECT_FILE_PATHS:
            if file_path == paths.INSTANCE_ENV_PATH:
                continue
            if file_path.exists():
                stage_project_file(file_path, payload_root)

        for dir_path in PROJECT_DIR_PATHS:
            if dir_path.exists():
                stage_project_directory(dir_path, payload_root)

        project_files = sorted(path.relative_to(staging_root) for path in payload_root.rglob("*") if path.is_file())
        manifest = build_manifest(project_files)
        manifest_path = staging_root / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        write_checksums(staging_root, [Path("manifest.json"), *project_files])
        write_bundle(bundle_path, staging_root)

    return BundleSummary(bundle_path=bundle_path, manifest=manifest, project_files=project_files)


def verify_bundle(bundle_path: Path) -> BundleSummary:
    with tempfile.TemporaryDirectory(prefix="transithub-verify-") as tmp_root:
        extracted_root = Path(tmp_root)
        safe_extract_bundle(bundle_path, extracted_root)
        manifest_path = extracted_root / "manifest.json"
        if not manifest_path.exists():
            raise BackupError("Bundle manifest.json is missing.")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if str(manifest.get("schema_version", "")) != BUNDLE_SCHEMA_VERSION:
            raise BackupError(
                f"Unsupported bundle schema version: {manifest.get('schema_version')!r}. "
                f"Expected {BUNDLE_SCHEMA_VERSION}."
            )
        verify_checksums(extracted_root)
        project_files = sorted(
            path.relative_to(extracted_root)
            for path in (extracted_root / PAYLOAD_PREFIX).rglob("*")
            if path.is_file()
        )
        missing = REQUIRED_BUNDLE_RELATIVE_PATHS - set(project_files)
        if missing:
            rendered = ", ".join(str(path) for path in sorted(missing))
            raise BackupError(f"Bundle is missing required payload files: {rendered}")
        return BundleSummary(bundle_path=bundle_path, manifest=manifest, project_files=project_files)


def restore_bundle(bundle_path: Path | None = None) -> dict[str, object]:
    target_bundle = bundle_path or latest_restore_bundle()
    summary = verify_bundle(target_bundle)
    current_values = parse_env(paths.INSTANCE_ENV_PATH)

    with tempfile.TemporaryDirectory(prefix="transithub-restore-") as tmp_root:
        extracted_root = Path(tmp_root)
        safe_extract_bundle(target_bundle, extracted_root)
        bundle_values = parse_env(extracted_root / PAYLOAD_PREFIX / "instance.env")
        enforce_same_instance(current_values, bundle_values)
        rollback = backup_bundle(BACKUP_DIR, label="rollback-before-restore")

        stop_project_containers(current_values)
        restore_payload_tree(extracted_root / PAYLOAD_PREFIX)

        restored_values = parse_env(paths.INSTANCE_ENV_PATH)
        seeded = seed_xui_db(restored_values, db_path=XUI_DB_PATH)
        paths.INSTANCE_ENV_PATH.write_text(render_env(seeded.get("updated_values", restored_values)), encoding="utf-8")

        final_values = parse_env(paths.INSTANCE_ENV_PATH)
        compose_up(final_values)
        service_lines = compose_ps(final_values)

    return {
        "bundle_path": str(target_bundle),
        "rollback_path": str(rollback.bundle_path),
        "domain": final_values.get("DOMAIN", ""),
        "tgproxy_public_host": final_values.get("TGPROXY_PUBLIC_HOST", ""),
        "project_files_restored": len(summary.project_files),
        "service_lines": service_lines,
    }


def latest_restore_bundle() -> Path:
    RESTORE_INBOX_DIR.mkdir(parents=True, exist_ok=True)
    candidates = sorted(RESTORE_INBOX_DIR.glob(f"*{BUNDLE_SUFFIX}"), key=lambda item: item.stat().st_mtime, reverse=True)
    if not candidates:
        raise BackupError(f"No bundle was found in {RESTORE_INBOX_DIR}")
    return candidates[0]


def bundle_name(label: str) -> str:
    timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d-%H%M%S")
    safe_label = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in label).strip("-") or "backup"
    return f"transithub-{safe_label}-{timestamp}{BUNDLE_SUFFIX}"


def ensure_runtime_files_exist() -> None:
    if not paths.INSTANCE_ENV_PATH.exists():
        raise BackupError(f"instance.env was not found: {paths.INSTANCE_ENV_PATH}")
    if not XUI_DB_PATH.exists():
        raise BackupError(f"x-ui.db was not found: {XUI_DB_PATH}")


def relative_to_project(path: Path) -> Path:
    return path.resolve().relative_to(paths.PROJECT_ROOT.resolve())


def stage_project_file(source: Path, payload_root: Path) -> Path:
    destination = payload_root / relative_to_project(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def stage_project_directory(source: Path, payload_root: Path) -> None:
    destination = payload_root / relative_to_project(source)
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)


def stage_sqlite_snapshot(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    destination_conn = sqlite3.connect(destination)
    try:
        source_conn.backup(destination_conn)
    finally:
        destination_conn.close()
        source_conn.close()


def git_value(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=paths.PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def build_manifest(project_files: list[Path]) -> dict[str, object]:
    values = parse_env(paths.INSTANCE_ENV_PATH)
    return {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "created_at": datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat(),
        "source_branch": git_value("rev-parse", "--abbrev-ref", "HEAD"),
        "source_commit": git_value("rev-parse", "HEAD"),
        "instance_name": values.get("INSTANCE_NAME", ""),
        "domain": values.get("DOMAIN", ""),
        "tgproxy_public_host": values.get("TGPROXY_PUBLIC_HOST", ""),
        "tgproxy_enabled": tgproxy_enabled(values),
        "bootstrap_version": values.get("BOOTSTRAP_VERSION", ""),
        "xui_db_schema_version": values.get("XUI_DB_SCHEMA_VERSION", ""),
        "project_files": [str(path) for path in project_files],
    }


def write_checksums(root: Path, relative_paths: list[Path]) -> None:
    lines: list[str] = []
    for relative_path in relative_paths:
        digest = file_sha256(root / relative_path)
        lines.append(f"{digest}  {relative_path.as_posix()}")
    (root / "checksums.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")


def verify_checksums(root: Path) -> None:
    checksums_path = root / "checksums.sha256"
    if not checksums_path.exists():
        raise BackupError("Bundle checksums.sha256 is missing.")
    for raw_line in checksums_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            expected, relative_path = line.split("  ", 1)
        except ValueError as exc:
            raise BackupError(f"Invalid checksum line: {line!r}") from exc
        target = root / relative_path
        if not target.exists():
            raise BackupError(f"Checksum target is missing: {relative_path}")
        actual = file_sha256(target)
        if actual != expected:
            raise BackupError(f"Checksum mismatch for {relative_path}")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_bundle(bundle_path: Path, root: Path) -> None:
    with tarfile.open(bundle_path, "w:gz") as archive:
        archive.add(root / "manifest.json", arcname="manifest.json")
        archive.add(root / "checksums.sha256", arcname="checksums.sha256")
        archive.add(root / "payload", arcname="payload")


def safe_extract_bundle(bundle_path: Path, destination: Path) -> None:
    with tarfile.open(bundle_path, "r:gz") as archive:
        for member in archive.getmembers():
            target = destination / member.name
            if not target.resolve().is_relative_to(destination.resolve()):
                raise BackupError(f"Unsafe path inside bundle: {member.name}")
        archive.extractall(destination)


def enforce_same_instance(current_values: dict[str, str], bundle_values: dict[str, str]) -> None:
    current_domain = current_values.get("DOMAIN", "").strip().lower()
    bundle_domain = bundle_values.get("DOMAIN", "").strip().lower()
    if current_domain != bundle_domain:
        raise BackupError(
            f"Restore is allowed only for the same instance. Current DOMAIN={current_domain!r}, "
            f"bundle DOMAIN={bundle_domain!r}."
        )

    current_tg = current_values.get("TGPROXY_PUBLIC_HOST", "").strip().lower()
    bundle_tg = bundle_values.get("TGPROXY_PUBLIC_HOST", "").strip().lower()
    if current_tg != bundle_tg:
        raise BackupError(
            "Restore is allowed only for the same Telegram proxy host. "
            f"Current TGPROXY_PUBLIC_HOST={current_tg!r}, bundle TGPROXY_PUBLIC_HOST={bundle_tg!r}."
        )


def stop_project_containers(values: dict[str, str]) -> None:
    project_name = values.get("INSTANCE_NAME", "").strip() or "xui-v1"
    completed = subprocess.run(
        [
            "docker",
            "ps",
            "--format",
            "{{.Names}}",
            "--filter",
            f"label=com.docker.compose.project={project_name}",
        ],
        cwd=paths.PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    container_names = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if container_names:
        subprocess.run(["docker", "stop", *container_names], cwd=paths.PROJECT_ROOT, check=False, capture_output=True, text=True)


def restore_payload_tree(payload_root: Path) -> None:
    if not payload_root.exists():
        raise BackupError("Bundle payload/project directory is missing.")
    for source in sorted(path for path in payload_root.rglob("*") if path.is_file()):
        relative_path = source.relative_to(payload_root)
        destination = paths.PROJECT_ROOT / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def compose_base_command() -> list[str]:
    for command in (["docker", "compose", "version"], ["docker-compose", "version"]):
        completed = subprocess.run(command, cwd=paths.PROJECT_ROOT, check=False, capture_output=True, text=True)
        if completed.returncode == 0:
            return command[:-1]
    raise BackupError("Docker Compose is not available on this host.")


def compose_command(values: dict[str, str]) -> list[str]:
    command = [
        *compose_base_command(),
        "--project-directory",
        str(paths.PROJECT_ROOT),
        "-p",
        values.get("INSTANCE_NAME", "").strip() or "xui-v1",
        "--env-file",
        "instance.env",
        "-f",
        str(paths.SERVICE_NGINX_COMPOSE_PATH),
        "-f",
        str(paths.SERVICE_XUI_COMPOSE_PATH),
        "-f",
        str(paths.SERVICE_SUBCONVERTER_COMPOSE_PATH),
        "-f",
        str(paths.SERVICE_DIAGNOSTICS_COMPOSE_PATH),
    ]
    if values.get("ENABLE_TGPROXY", "").strip().lower() == "true":
        command.extend(["-f", str(paths.SERVICE_TGPROXY_COMPOSE_PATH)])
    if values.get("ENABLE_NETBIRD", "").strip().lower() == "true":
        command.extend(["-f", str(paths.SERVICE_NETBIRD_COMPOSE_PATH)])
    return command


def compose_up(values: dict[str, str]) -> None:
    completed = subprocess.run(
        [*compose_command(values), "up", "-d", "--force-recreate", "--remove-orphans"],
        cwd=paths.PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise BackupError((completed.stdout or "") + (completed.stderr or "Compose up failed."))


def compose_ps(values: dict[str, str]) -> list[str]:
    completed = subprocess.run(
        [*compose_command(values), "ps"],
        cwd=paths.PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    output = completed.stdout or completed.stderr or "No output"
    return output.splitlines()
