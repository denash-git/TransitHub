# 3XUI V1

## Quick Start On Debian VPS

Run on a fresh Debian VPS as `root` or through `sudo`:

```bash
apt-get update
apt-get install -y git
git clone https://github.com/denash-git/3xui ~/3xui
cd ~/3xui
bash install.sh
```

If you clone with SSH instead of HTTPS:

```bash
git clone git@github.com:denash-git/3xui.git ~/3xui
cd ~/3xui
bash install.sh
```

The installer prepares host packages itself and configures Docker, Docker Compose, certbot, and `ufw`.

## Target Flow

```bash
cd ~/3xui
bash install.sh
```

The project is structured so that:

- `docker-compose.yml` and `instance.env` live in the project root
- each Docker component has its own root-level directory
- host-side integration and cleanup logic lives in `install/`
- the user-facing install menu lives in `install.sh`

Detailed layout and current status are documented in `docs/README.md`.
