# Native deployment configuration files

This directory contains configuration templates for deploying OPTIMAP as a native Django application (non-containerized) behind nginx with a native PostgreSQL/PostGIS database.

## Files

| File | Description | Destination |
|------|-------------|-------------|
| `optimap.service` | Systemd service for Django/Gunicorn | `/etc/systemd/system/optimap.service` |
| `optimap-worker.service` | Systemd service for Django-Q worker | `/etc/systemd/system/optimap-worker.service` |
| `gunicorn.conf.py` | Gunicorn WSGI server configuration | `/opt/optimap/gunicorn.conf.py` |
| `nginx-optimap.conf` | nginx reverse proxy configuration | `/etc/nginx/sites-available/optimap` |
| `env.example` | Environment variable template | `/opt/optimap/app/optimap/.env` |
| `install.sh` | Automated installation script | Run directly |

## Quick start

See the full deployment guide at `docs/deployment-plain.md`.

### Automated installation

```bash
# Run the installation script as root
sudo ./install.sh
```

The script installs system packages, creates the application user and directories, clones the repository, and sets up the Python virtual environment. Manual steps are required after running the script.

### Manual installation

1. Install system packages (PostgreSQL, nginx, GDAL, Python)
2. Create the `optimap` system user and directories
3. Clone the repository to `/opt/optimap/app`
4. Create and configure the virtual environment
5. Copy configuration files to their destinations
6. Create the database and configure PostgreSQL
7. Initialize Django (migrate, collectstatic, load_global_regions)
8. Obtain SSL certificate with certbot
9. Enable and start systemd services

## Architecture

```
nginx (443/80)
    │
    └─── proxy_pass ──► Gunicorn (Unix socket)
                            │
                            └─── Django WSGI
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
            PostgreSQL/PostGIS              Django-Q worker
```

## Comparison with Docker deployment

| Aspect | Native | Docker |
|--------|--------|--------|
| Resource overhead | Lower | Container runtime overhead |
| Updates | Manual package management | Pull new images |
| Isolation | Process-level | Container-level |
| Complexity | More system admin work | Simpler with docker-compose |
| Debugging | Direct system access | Container shell required |
| Backup | Standard tools | Volume management |

## Requirements

- Ubuntu 22.04 LTS or 24.04 LTS
- Python 3.11+
- PostgreSQL 14+ with PostGIS 3.3+
- nginx 1.18+
- 2GB+ RAM recommended
- 20GB+ storage
