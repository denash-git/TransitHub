# 3XUI V1

## Quick Start On Debian 12/13 VPS

Run on a fresh Debian 12 or Debian 13 VPS as `root` or through `sudo`:

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

The installer prepares host packages itself and configures Docker, Docker Compose, the external Docker network `proxy-net`, certbot, and `ufw`.
After a successful Linux deployment, installer sources and documentation are pruned from the VPS, leaving the runtime tree only.

## Target Flow

```bash
cd ~/3xui
bash install.sh
```

The project is structured so that:

- `instance.env` lives in the project root
- each Docker component has its own root-level directory
- web-facing static assets live under `web/`
- host-side integration and cleanup logic lives in `install/`
- the user-facing install menu lives in `install.sh`

Detailed layout and current status are documented in `docs/README.md`.
