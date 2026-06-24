# Native deployment configuration files

Configuration templates for deploying OPTIMAP as a native Django application (non-containerized) behind nginx with a native PostgreSQL/PostGIS database.

> **The full deployment guide lives at [../../docs/deployment-plain.md](../../docs/deployment-plain.md).**
> It covers system preparation, database setup, SSL, systemd, nginx, backups,
> updates, monitoring, and troubleshooting. This README only inventories the
> files in this directory — refer to the guide for what to do with them.

## Files in this directory

| File | Description | Destination |
|------|-------------|-------------|
| `optimap.service` | Systemd service for Django/Gunicorn | `/etc/systemd/system/optimap.service` |
| `optimap-worker.service` | Systemd service for Django-Q worker | `/etc/systemd/system/optimap-worker.service` |
| `gunicorn.conf.py` | Gunicorn WSGI server configuration | `/opt/optimap/gunicorn.conf.py` |
| `nginx-optimap.conf` | nginx reverse proxy configuration | `/etc/nginx/sites-available/optimap` |
| `env.example` | Environment variable template | `/opt/optimap/app/optimap/.env` |
| `install.sh` | Automated installation script (runs the system-package / user / venv steps from the guide) | Run directly as root |
| `update-app.sh` | Versioned update script (pull, deps, migrate, collectstatic, region/country load, restart, cache clear) | Symlinked to `/opt/optimap/scripts/update-app.sh` |
