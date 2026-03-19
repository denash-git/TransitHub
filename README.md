# 3XUI V1

Target flow:

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
