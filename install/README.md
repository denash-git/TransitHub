# Install Layer

This directory contains the clean-host entrypoint and host-side artifacts.

- `../install.sh`
  Bash wrapper with the first-run menu for domain and timezone.
- `cli.py`
  One-shot installer logic used by `python -m install`.
- `project.py`
  Internal command CLI for setup, reconfigure, status, and database operations.
- `cleanup.py`
  Removes old layouts and temporary migration artifacts after a successful run.
- `host/`
  Generated reports and host integration outputs such as package/firewall preparation status.

The intended flow on a fresh VPS is:

```bash
cd ~/TransiHub
bash install.sh
```

Host-level changes belong here, not inside the Docker service directories.
