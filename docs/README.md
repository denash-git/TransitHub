# 3XUI V1 Bootstrap

This repository is a one-shot bootstrap project for `3x-ui`. The intended install location is the target user's home directory, for example `~/3xui`.

## Target layout

- `docker-compose.yml`
- `instance.env`
- `.venv/`
- `bootstrap/`
- `templates/`
- `install/`
- `nginx/`
- `xui/`
- `sub2sing-box/`
- `web-sub/`
- `fake-site/`
- `state/`
- `docs/`
- `temp/`

Each Docker component has its own root-level directory. Config and data are not mixed into a shared runtime folder.

## Host layer

- `install.sh`
  Bash wrapper with the install menu and first-run prompts.
- `install.py`
  Root-level one-shot installer entrypoint for a fresh host.
- `install/install.py`
  Internal installer module used by the root entrypoint.
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
  Compose slice for the nginx service.
- `xui/data/`
  Persistent `3x-ui` data including `x-ui.db`.
- `xui/docker-compose.yml`
  Compose slice for the `xui` service.
- `sub2sing-box/data/`
  Converter service data.
- `sub2sing-box/docker-compose.yml`
  Compose slice for the converter service.
- `web-sub/site/`
  Rendered subscription landing page.
- `fake-site/site/`
  Rendered fake site.
- `state/last_status.json`
  Last bootstrap status snapshot.

## Current behavior

- `TZ` is auto-detected from the host where bootstrap runs.
- Panel credentials and `webBasePath` are re-applied on each `xui` container start.
- The external panel path is randomized and masked behind nginx.
- `3x-ui` subscription traffic is handled by its dedicated internal `SUB_PORT` server, not by the panel `webPort`.
- The root compose file only contains shared project metadata; each service has its own compose file in its own directory.
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

1. Clone the repository into the target user's home directory.
2. Run `bash install.sh`.
3. The menu collects the primary settings:
   - main domain
   - REALITY domain
   - timezone, defaulting to the VPS timezone
4. The installer picks one fake-site template automatically.
5. The installer creates `.venv`, installs dependencies, prepares the host, prompts or applies required settings, renders service configs, seeds `x-ui.db`, starts Docker Compose, and removes old layout folders.
5. On the deployed host, documentation, temp files, and unselected fake-site templates are pruned.

Manual flow is still available:

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python -m bootstrap init
./.venv/bin/python -m bootstrap seed-xui-db
docker compose --env-file instance.env \
  -f docker-compose.yml \
  -f nginx/docker-compose.yml \
  -f xui/docker-compose.yml \
  -f sub2sing-box/docker-compose.yml \
  up -d
```

## Not finished yet

- Full end-to-end validation of generated client links for all seeded transports
- Further cleanup of optional source artifacts if the runtime tree needs to be made even smaller
