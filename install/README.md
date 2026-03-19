# Install Layer

This directory contains the clean-host entrypoint and host-side artifacts.

- `../install.sh`
  Bash wrapper with the first-run menu for domain and timezone.
- `install.py`
  One-shot installer used after cloning the repository.
- `cleanup.py`
  Removes old layouts and temporary migration artifacts after a successful run.
- `host/`
  Generated reports and host integration outputs such as package/firewall preparation status.
- `logs/`
  Reserved for installer-side logs if the flow needs persistent host install traces later.

The intended flow on a fresh VPS is:

```bash
cd ~/3xui
bash install.sh
```

Host-level changes belong here, not inside the Docker service directories.
