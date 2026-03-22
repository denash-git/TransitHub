# TransitHub Project Context

## Purpose

TransitHub v2 is an installer-driven proxy platform for a clean Debian 12/13 VPS.
The project prepares the host, renders runtime configs, starts Docker services,
and configures `3x-ui` with a shared public `443`.

## Current Runtime Architecture

- Public ingress is only `80/tcp` and `443/tcp`.
- `nginx` owns external `80/443`.
- `x-ui` runs in Docker and is exposed only behind `nginx`.
- `subconverter` runs in Docker and is exposed only behind `nginx`.
- Telegram proxy uses `tgproxy` based on `nineseconds/mtg`, not official Telegram MTProxy.
- Shared `443` routing is done through `nginx stream` with SNI-based dispatch.
- Browser traffic for the Telegram proxy domain falls back to a fake site cloak.

## Image Policy

- Runtime images are pinned to exact working digests.
- Do not switch runtime defaults back to floating tags like `latest`.
- The current lock snapshot is stored in `runtime-images.lock.json`.
- Existing `instance.env` values that still contain legacy floating refs are
  migrated to pinned refs by `install.env.sync_derived_fields()`.

## Documentation Policy

- Public GitHub documentation stays minimal in `README.md`.
- Detailed internal documentation is kept only locally in:
  - `D:\\WORK\\TransitHub-local-docs\\README.md`
  - `D:\\WORK\\TransitHub-local-docs\\TransitHub-v2-internals.md`
- Do not reintroduce detailed architecture docs into the GitHub repository
  unless explicitly requested.

## Branch Policy

- `main` is the only long-lived GitHub branch.
- Temporary research or redesign branches may exist locally during work, but
  should not remain on GitHub after the result is merged or abandoned.

## Operational Notes

- TLS is managed with Let's Encrypt and auto-renewed through a systemd timer.
- Installer warns in red if host time/NTP is not synchronized, but continues.
- `3x-ui` is managed inside its container, not as a host-native install.
- Useful container CLI pattern:

```bash
XUI_CONTAINER="$(docker ps --format '{{.Names}}' | grep xui | head -n1)"
docker exec -it "$XUI_CONTAINER" /bin/sh
x-ui
```

## Safety Notes

- Before major installer or runtime changes, create a rollback point.
- Keep local bundle backups in `D:\\WORK\\TransitHub-backups`.
- Prefer changing templates, installer logic, and env defaults in a way that is
  safe for both fresh installs and reruns on partially configured hosts.
