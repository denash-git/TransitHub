# 3XUI V1 Installer

This repository is a one-shot installer project for `3x-ui`. The intended install location is the target user's home directory, for example `~/3xui`.

## Target layout

- `instance.env`
- `.venv/`
- `templates/`
- `install/`
- `nginx/`
- `xui/`
- `subconverter/`
- `web/`
- `docs/`
- `temp/`

Each Docker component has its own root-level directory. Config and data are not mixed into a shared runtime folder.

## Host layer

- `install.sh`
  Bash wrapper with the install menu and first-run prompts.
- `python3 -m install`
  Command entrypoint used by the shell wrapper on a fresh host.
- `install/cli.py`
  Internal installer module used by the shell wrapper.
- `install/project.py`
  Internal command CLI for init, reconfigure, status, host prep, and DB sync.
- `install/cleanup.py`
  Removes legacy layouts after successful migration/install.
- `install/host/last_prepare.json`
  Result of package and firewall preparation.

## Service layer

- `nginx/config/`
  Generated nginx configs.
- `nginx/extensions/`
  Nginx extension includes.
- `nginx/docker-compose.yml`
  Compose slice for the nginx service and the shared external `proxy-net`.
- `xui/data/`
  Persistent `3x-ui` data including `x-ui.db`.
- `xui/docker-compose.yml`
  Compose slice for the `xui` service.
- `subconverter/data/`
  Converter service data.
- `subconverter/docker-compose.yml`
  Compose slice for the `conv` converter service.
- `web/client_page/`
  Rendered subscription landing page and generated `clash.yaml`.
- `web/fake_site/`
  Rendered fake site.
- `state/last_status.json`
  Optional status snapshot, created only when the status command is used.

## Current behavior

- `TZ` is auto-detected from the host where the installer runs.
- Panel credentials and `webBasePath` are re-applied on each `xui` container start.
- The external panel path is randomized and masked behind nginx.
- `3x-ui` subscription traffic is handled by its dedicated internal `SUB_PORT` server, not by the panel `webPort`.
- Each service keeps its own compose file, and all services attach to the shared external Docker network `proxy-net`.
- Baseline inbounds are seeded into `x-ui.db`:
  - `reality`
  - `ws`
  - `xhttp`
  - `trojan-grpc`
- Legacy layouts are migrated from:
  - `runtime/`
  - `deploy/`

## Install flow

Expected clean-host flow:

1. On a fresh Debian 12 or Debian 13 VPS, log in as `root` or use a sudo-capable user.
2. Install Git if it is missing:

```bash
apt-get update
apt-get install -y git
```

3. Clone the repository into the target user's home directory:

```bash
git clone https://github.com/denash-git/3xui ~/3xui
cd ~/3xui
```

SSH clone also works if the server has a GitHub key configured:

```bash
git clone git@github.com:denash-git/3xui.git ~/3xui
cd ~/3xui
```

4. Run `bash install.sh`.
5. The menu collects the primary settings:
   - main domain
   - REALITY domain
   - timezone, defaulting to the VPS timezone
6. The installer picks one fake-site template automatically.
7. The installer creates `.venv`, installs dependencies, prepares the host, prompts or applies required settings, renders service configs, seeds `x-ui.db`, starts Docker Compose, and removes old layout folders.
8. On the deployed host, the installer sources, templates, documentation, temp files, and other non-runtime artifacts are pruned so only the runtime tree remains.

Manual flow is still available:

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python -m install init
./.venv/bin/python -m install seed-xui-db
docker network inspect proxy-net >/dev/null 2>&1 || docker network create proxy-net
docker compose --env-file instance.env \
  --project-directory . \
  -f nginx/docker-compose.yml \
  -f xui/docker-compose.yml \
  -f subconverter/docker-compose.yml \
  up -d
```

## Not finished yet

- Full end-to-end validation of generated client links for all seeded transports
- Further cleanup of optional source artifacts if the runtime tree needs to be made even smaller
