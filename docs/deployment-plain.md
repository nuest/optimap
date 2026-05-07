# Native deployment guide (non-containerized)

This document describes how to deploy OPTIMAP as a native Django application behind nginx, with a natively running PostgreSQL/PostGIS database.

## Overview

This deployment approach runs all components directly on the host system:

```txt
                    Internet
                        │
                        ▼
                   nginx (443/80)
                   ├── SSL termination
                   ├── Static files (/static/)
                   └── Reverse proxy
                        │
                        ▼
                   Gunicorn (socket)
                   └── Django WSGI application
                        │
        ┌───────────────┴───────────────┐
        ▼                               ▼
    PostgreSQL/PostGIS           Django-Q cluster
    (native service)             (systemd service)
```

## Target system

- **OS:** Ubuntu 22.04 LTS or 24.04 LTS (recommended)
- **Python:** 3.11+
- **PostgreSQL:** 14+ with PostGIS 3.3+
- **Memory:** 2GB+ RAM recommended
- **Storage:** 20GB+ for application, database, and logs

## System preparation

### Update system and install base packages

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y \
    build-essential \
    python3-dev \
    python3-pip \
    python3-venv \
    git \
    curl \
    nginx \
    certbot \
    python3-certbot-nginx
```

### Install GDAL and geospatial libraries

Add the UbuntuGIS PPA for the latest GDAL version:

```bash
sudo add-apt-repository -y ppa:ubuntugis/ppa
sudo apt update
sudo apt install -y \
    gdal-bin \
    libgdal-dev \
    libgeos-dev \
    libproj-dev
```

Verify GDAL installation:

```bash
gdal-config --version
# Expected: 3.4.x or higher
```

### Install Cairo and Pango (preview image rendering)

The preview image service uses `cairosvg` (via `cairocffi`), which dynamically
loads the system Cairo library. Without these, `manage.py migrate` (and any
other command that imports the URL conf) fails with
`OSError: no library called "cairo-2" was found`.

```bash
sudo apt install -y \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0
```

> On Ubuntu 22.04 the GdkPixbuf package is named `libgdk-pixbuf2.0-0` (no dash
> before `2.0`). Use whichever apt resolves on your release.

### Install PostgreSQL with PostGIS

```bash
# Install PostgreSQL and PostGIS
sudo apt install -y postgresql postgresql-contrib postgis postgresql-postgis

# Or for Ubuntu 24.04 with PostgreSQL 16:
# sudo apt install -y postgresql postgresql-contrib postgis postgresql-postgis
```

Start and enable PostgreSQL:

```bash
sudo systemctl start postgresql
sudo systemctl enable postgresql
```

## Database setup

### Create database and user

```bash
# Switch to postgres user
sudo -u postgres psql

# In PostgreSQL shell:
CREATE USER optimap WITH PASSWORD 'your_secure_password_here';
CREATE DATABASE optimap OWNER optimap;

# Connect to the database and enable PostGIS
\c optimap
CREATE EXTENSION postgis;
CREATE EXTENSION postgis_topology;

# Grant privileges
GRANT ALL PRIVILEGES ON DATABASE optimap TO optimap;
GRANT ALL ON SCHEMA public TO optimap;

\q
```

### Configure PostgreSQL authentication

Edit `/etc/postgresql/14/main/pg_hba.conf` (adjust version number as needed):

```bash
sudo nano /etc/postgresql/14/main/pg_hba.conf
```

(Optional) Add or modify the line for local connections to only allow this user, not "all":

```txt
# IPv4 local connections:
host    optimap         optimap         127.0.0.1/32            scram-sha-256
```

Reload PostgreSQL:

```bash
sudo systemctl reload postgresql
```

### Test database connection

```bash
psql -h localhost -U optimap -d optimap -c "SELECT PostGIS_Version();"
```

## Application setup

### Create application user and directory

```bash
# Create system user for running the application
sudo useradd --system --shell /bin/bash --home /opt/optimap optimap

# Create directories
sudo mkdir -p /opt/optimap/{app,venv,logs,static,cache}
sudo chown -R optimap:optimap /opt/optimap
```

### Clone the repository

```bash
sudo -u optimap git clone https://github.com/GeoinformationSystems/optimap /opt/optimap/app
```

### Create virtual environment

```bash
sudo -u optimap python3 -m venv /opt/optimap/venv`
```

### Install Python dependencies

```bash
# Activate virtual environment
sudo -u optimap bash -c '
source /opt/optimap/venv/bin/activate

# Install GDAL Python bindings matching system version
pip install gdal=="$(gdal-config --version).*"

# Install application dependencies
pip install -r /opt/optimap/app/requirements.txt

# Install Gunicorn for production WSGI server
pip install gunicorn
'
```

### Configure environment

Create the environment file:

```bash
sudo -u optimap nano /opt/optimap/app/optimap/.env
```

Add configuration (adjust values for your environment):

```ini
# Database (using DATABASE_URL format)
DATABASE_URL=postgis://optimap:your_secure_password_here@localhost:5432/optimap

# Application
OPTIMAP_DEBUG=False
OPTIMAP_ALLOWED_HOST=optimap.example.com,localhost
OPTIMAP_BASE_URL=https://optimap.example.com

# Secret key - generate with: python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
SECRET_KEY=your-very-long-random-secret-key-here

# CSRF trusted origins
CSRF_TRUSTED_ORIGINS=https://optimap.example.com

# Cache
OPTIMAP_CACHE=default
OPTIMAP_CACHE_SECONDS=3600

# Global regions data directory
OPTIMAP_GLOBAL_REGIONS_DATA_DIR=/opt/optimap/cache/regions

# Email (configure for your SMTP server)
OPTIMAP_EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
OPTIMAP_EMAIL_HOST=smtp.example.com
OPTIMAP_EMAIL_PORT_SMTP=587
OPTIMAP_EMAIL_USE_TLS=True
OPTIMAP_EMAIL_HOST_USER=noreply@example.com
OPTIMAP_EMAIL_HOST_PASSWORD=your_email_password

# Logging
OPTIMAP_LOGGING_LEVEL=INFO

# Add admin users here, changes require server restart
OPTIMAP_SUPERUSER_EMAILS=your@email.url,another@admin.tld
```

Set secure permissions:

```bash
sudo chmod 600 /opt/optimap/app/optimap/.env
```

### Set up static files directory

Django's `STATIC_ROOT` is set to `static/` relative to the working directory. For native deployment, create a symlink to serve static files from `/opt/optimap/static/`:

```bash
# Create symlink for static files
sudo -u optimap ln -s /opt/optimap/static /opt/optimap/app/static
```

### Initialize the database

```bash
sudo -u optimap bash -c '
source /opt/optimap/venv/bin/activate
cd /opt/optimap/app

# Apply migrations
python manage.py migrate

# Create cache table
python manage.py createcachetable

# Load global regions
python manage.py load_global_regions

# Collect static files (will be collected to /opt/optimap/static via symlink)
python manage.py collectstatic --noinput
'
```

After `collectstatic`, ensure nginx (running as `www-data`) can read and
traverse the static tree. Depending on the `optimap` user's umask and Django's
`FILE_UPLOAD_DIRECTORY_PERMISSIONS`, collected subdirectories may end up
`drwxrwx---` — top-level files load but anything under `static/js/`,
`static/css/`, `static/leaflet/`, etc. returns `403 Permission denied`:

```bash
sudo chmod -R a+rX /opt/optimap/static
```

`a+rX` (capital `X`) adds read for everyone and adds traverse on directories
only — idempotent, safe to rerun, and the right operation here because the
files themselves are already world-readable; only directory-execute is
missing.

#### Resolve errors

**`load_global_regions` fails with `Connection reset by peer`?**
The command pulls the MarineRegions "Global Oceans and Seas v1" GeoPackage
from `https://marineregions.org/download_file.php?name=GOaS_v1_20211214_gpkg.zip`,
and that endpoint is rate-limited and sometimes drops the TLS handshake
(`urllib.error.URLError: <urlopen error [Errno 104] Connection reset by peer>`).
The continents step succeeds first, so a partial run is normal — just rerun
the command; it is idempotent and skips work that's already done.

If retries keep failing, download the ZIP manually and place the extracted
`.gpkg` at `/opt/optimap/cache/regions/goas_v01.gpkg` (that path matches
`OPTIMAP_GLOBAL_REGIONS_DATA_DIR` from your `.env` plus the filename the
loader expects). The MarineRegions endpoint requires a POST with
registration fields (the same ones the loader sends), so a plain `wget URL`
will not work — use curl with `--data-urlencode`:

```bash
sudo install -d -o optimap -g optimap /opt/optimap/cache/regions && \
  curl -fL -o /tmp/goas.zip \
    --data-urlencode 'name=OPTIMAP Project TU Dresden' \
    --data-urlencode 'organisation=TU Dresden' \
    --data-urlencode 'email=komet@tu-dresden.de' \
    --data-urlencode 'country=Germany' \
    --data-urlencode 'user_category=academia' \
    --data-urlencode 'purpose_category=Research' \
    --data-urlencode 'agree=1' \
    'https://marineregions.org/download_file.php?name=GOaS_v1_20211214_gpkg.zip' && \
  sudo unzip -j -o /tmp/goas.zip '*.gpkg' -d /opt/optimap/cache/regions/ && \
  sudo mv /opt/optimap/cache/regions/*.gpkg /opt/optimap/cache/regions/goas_v01.gpkg && \
  sudo chown optimap:optimap /opt/optimap/cache/regions/goas_v01.gpkg
```

Or fetch it interactively from <https://www.marineregions.org/downloads.php>
("Global Oceans and Seas v1", GeoPackage) on your laptop and `scp` the
extracted `.gpkg` into place.
Make sure the owner of the file is `optimap`.

Either way, rerun the loader once the file is
present. The loader will see the file and skip the download:

```bash
sudo -u optimap bash -c '
source /opt/optimap/venv/bin/activate
cd /opt/optimap/app
python manage.py load_global_regions
'
```

### Create superuser

```bash
sudo -u optimap bash -c '
source /opt/optimap/venv/bin/activate
cd /opt/optimap/app
python manage.py createsuperuser
'
```

## Gunicorn configuration

Create Gunicorn configuration file:

```bash
sudo -u optimap nano /opt/optimap/gunicorn.conf.py
```

```python
# Gunicorn configuration for OPTIMAP

import multiprocessing

# Bind to Unix socket for nginx
bind = "unix:/opt/optimap/gunicorn.sock"

# Workers: (2 x CPU cores) + 1
workers = multiprocessing.cpu_count() * 2 + 1

# Worker class
worker_class = "sync"

# Timeout for worker processes (seconds)
timeout = 120

# Graceful timeout
graceful_timeout = 30

# Keep-alive connections
keepalive = 5

# Maximum requests per worker before restart (prevents memory leaks)
max_requests = 1000
max_requests_jitter = 50

# Logging
accesslog = "/opt/optimap/logs/gunicorn-access.log"
errorlog = "/opt/optimap/logs/gunicorn-error.log"
loglevel = "info"

# Process naming
proc_name = "optimap-gunicorn"

# Working directory
chdir = "/opt/optimap/app"

# Security
limit_request_line = 4094
limit_request_fields = 100
limit_request_field_size = 8190
```

## Systemd service configuration

### Django application service

Create `/etc/systemd/system/optimap.service`:

```bash
sudo nano /etc/systemd/system/optimap.service
```

```ini
[Unit]
Description=OPTIMAP Django Application
After=network.target postgresql.service
Requires=postgresql.service

[Service]
Type=notify
User=optimap
Group=optimap
WorkingDirectory=/opt/optimap/app
Environment="PATH=/opt/optimap/venv/bin"
EnvironmentFile=/opt/optimap/app/optimap/.env
ExecStart=/opt/optimap/venv/bin/gunicorn \
    --config /opt/optimap/gunicorn.conf.py \
    optimap.wsgi:application
ExecReload=/bin/kill -s HUP $MAINPID
KillMode=mixed
TimeoutStopSec=30
PrivateTmp=true
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### Django-Q background worker service

Create `/etc/systemd/system/optimap-worker.service`:

```bash
sudo nano /etc/systemd/system/optimap-worker.service
```

```ini
[Unit]
Description=OPTIMAP Django-Q Background Worker
After=network.target postgresql.service optimap.service
Requires=postgresql.service

[Service]
Type=simple
User=optimap
Group=optimap
WorkingDirectory=/opt/optimap/app
Environment="PATH=/opt/optimap/venv/bin"
EnvironmentFile=/opt/optimap/app/optimap/.env
ExecStart=/opt/optimap/venv/bin/python manage.py qcluster
KillMode=mixed
TimeoutStopSec=60
PrivateTmp=true
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### Enable and start services

```bash
sudo systemctl daemon-reload
sudo systemctl enable optimap optimap-worker
sudo systemctl start optimap optimap-worker
```

### Check service status

```bash
sudo systemctl status optimap
sudo systemctl status optimap-worker
```

## nginx configuration

### Create site configuration

This deployment uses an **existing** certbot installation rooted at
`/var/www/komet/optimap/certbot/`, with `--config-dir
/var/www/komet/optimap/certbot/conf` and webroot
`/var/www/komet/optimap/certbot/www`. Certificates already live at:

- `…/certbot/conf/live/optimap.geo.tu-dresden.de/fullchain.pem`
- `…/certbot/conf/live/optimap.geo.tu-dresden.de/privkey.pem`

If you are deploying a different host, replace `optimap.geo.tu-dresden.de` and
the `…/certbot/{conf,www}` paths throughout. If certbot's config dir is the
default (`/etc/letsencrypt/`), see the `## SSL certificate setup` section
below for how the paths shift back.

Create `/etc/nginx/sites-available/optimap`:

```bash
sudo nano /etc/nginx/sites-available/optimap
```

```nginx
# Upstream Gunicorn server
upstream optimap_server {
    server unix:/opt/optimap/gunicorn.sock fail_timeout=0;
}

# HTTP - redirect to HTTPS
server {
    listen 80;
    listen [::]:80;
    server_name optimap.geo.tu-dresden.de;

    # Let's Encrypt ACME challenge (matches certbot --webroot)
    location /.well-known/acme-challenge/ {
        root /var/www/komet/optimap/certbot/www;
    }

    # Redirect all other traffic to HTTPS
    location / {
        return 301 https://$host$request_uri;
    }
}

# HTTPS server
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name optimap.geo.tu-dresden.de;

    # SSL configuration — paths point at the custom certbot --config-dir.
    # Replace with /etc/letsencrypt/live/<domain>/… if certbot uses defaults.
    ssl_certificate     /var/www/komet/optimap/certbot/conf/live/optimap.geo.tu-dresden.de/fullchain.pem;
    ssl_certificate_key /var/www/komet/optimap/certbot/conf/live/optimap.geo.tu-dresden.de/privkey.pem;

    # Modern SSL settings (replaces certbot's options-ssl-nginx.conf, which
    # lives under /etc/letsencrypt and is absent with the custom config dir)
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 1d;
    ssl_session_tickets off;

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # Logging
    access_log /var/log/nginx/optimap-access.log;
    error_log /var/log/nginx/optimap-error.log;

    # Gzip compression
    gzip on;
    gzip_vary on;
    gzip_proxied any;
    gzip_comp_level 6;
    gzip_types text/plain text/css text/xml application/json application/javascript application/xml+rss application/atom+xml image/svg+xml;

    # Maximum upload size (for geoextent file uploads)
    client_max_body_size 100M;

    # Static files
    location /static/ {
        alias /opt/optimap/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # Favicon
    location /favicon.ico {
        alias /opt/optimap/static/favicon.ico;
        access_log off;
        log_not_found off;
    }

    # Robots.txt
    location /robots.txt {
        alias /opt/optimap/static/robots.txt;
        access_log off;
        log_not_found off;
    }

    # Application
    location / {
        proxy_pass http://optimap_server;
        proxy_redirect off;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;

        # Timeouts
        proxy_connect_timeout 300;
        proxy_send_timeout 300;
        proxy_read_timeout 300;

        # Buffer settings
        proxy_buffering on;
        proxy_buffer_size 128k;
        proxy_buffers 4 256k;
        proxy_busy_buffers_size 256k;
    }
}
```

### Enable the site

The certbot webroot (`/var/www/komet/optimap/certbot/www`) already exists in
this deployment, so no `mkdir` is needed.

```bash
# Enable site
sudo ln -s /etc/nginx/sites-available/optimap /etc/nginx/sites-enabled/

# Remove default site (optional)
sudo rm -f /etc/nginx/sites-enabled/default

# Test nginx configuration
sudo nginx -t
```

## SSL certificate setup

This deployment already has a certbot install at
`/var/www/komet/optimap/certbot/` with a valid certificate for
`optimap.geo.tu-dresden.de`, so the initial cert acquisition is **not**
needed — the nginx config above points straight at the existing files. Skip
to "Automatic certificate renewal" below.

The rest of this section documents how to (re)issue a certificate against
the same custom config dir, e.g. for a new host or after a teardown.

### (Optional) Issue a certificate with Let's Encrypt

If certs do not yet exist, bring nginx up with **only the HTTP server block**
first (comment out the `listen 443 …` block, since it will fail to start
without certs), reload nginx, then run certbot pointed at the custom
directories:

```bash
sudo certbot certonly \
    --webroot -w /var/www/komet/optimap/certbot/www \
    --config-dir /var/www/komet/optimap/certbot/conf \
    --work-dir   /var/www/komet/optimap/certbot/work \
    --logs-dir   /var/www/komet/optimap/certbot/logs \
    -d optimap.geo.tu-dresden.de
```

After this succeeds, restore the HTTPS server block in
`/etc/nginx/sites-available/optimap` and `sudo systemctl reload nginx`.

> If you are using certbot's default config dir (`/etc/letsencrypt/`), drop
> the `--config-dir`/`--work-dir`/`--logs-dir` flags and use webroot
> `/var/www/certbot` (creating it first with `sudo mkdir -p /var/www/certbot`).

### Automatic certificate renewal

Because this deployment uses a non-default config dir, the standard
`certbot.timer` systemd unit (which runs `certbot renew` against
`/etc/letsencrypt/`) will **not** renew these certs. Either:

- Run renewals via a custom cron entry / systemd timer that passes the
  same `--config-dir`/`--work-dir`/`--logs-dir` flags as above, plus
  `--deploy-hook 'systemctl reload nginx'`.
- Or, if a hook script in `…/certbot/conf/renewal-hooks/` already takes
  care of reload, just verify that scheduling is in place.

Test the renewal command end-to-end with `--dry-run` before relying on it:

```bash
sudo certbot renew --dry-run \
    --config-dir /var/www/komet/optimap/certbot/conf \
    --work-dir   /var/www/komet/optimap/certbot/work \
    --logs-dir   /var/www/komet/optimap/certbot/logs
```

If you are on certbot defaults, the much simpler form applies:

```bash
sudo systemctl status certbot.timer
sudo certbot renew --dry-run
```

## Firewall configuration

If using UFW:

```bash
sudo ufw allow ssh
sudo ufw allow 'Nginx Full'
sudo ufw enable
sudo ufw status
```

## Log management

### Configure logrotate

Create `/etc/logrotate.d/optimap`:

```bash
sudo nano /etc/logrotate.d/optimap
```

```txt
/opt/optimap/logs/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 optimap optimap
    sharedscripts
    postrotate
        systemctl reload optimap > /dev/null 2>&1 || true
    endscript
}
```

## Backup procedures

### Database backup script

Create `/opt/optimap/scripts/backup-db.sh`:

```bash
sudo mkdir -p /opt/optimap/scripts /opt/optimap/backups
sudo nano /opt/optimap/scripts/backup-db.sh
```

```bash
#!/bin/bash
# Database backup script for OPTIMAP

set -e

BACKUP_DIR="/opt/optimap/backups"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/optimap_${DATE}.sql.gz"

# Load environment
source /opt/optimap/app/optimap/.env

# Create backup
PGPASSWORD="${OPTIMAP_DB_PASS}" pg_dump \
    -h "${OPTIMAP_DB_HOST}" \
    -U "${OPTIMAP_DB_USER}" \
    -d "${OPTIMAP_DB_NAME}" \
    --format=custom \
    --compress=9 \
    > "${BACKUP_FILE}"

# Keep only last 7 days of backups
find "${BACKUP_DIR}" -name "optimap_*.sql.gz" -mtime +7 -delete

echo "Backup completed: ${BACKUP_FILE}"
```

```bash
sudo chmod +x /opt/optimap/scripts/backup-db.sh
sudo chown optimap:optimap /opt/optimap/scripts/backup-db.sh
```

### Schedule daily backups

```bash
sudo crontab -u optimap -e
```

Add:

```cron
# Daily database backup at 2:00 AM
0 2 * * * /opt/optimap/scripts/backup-db.sh >> /opt/optimap/logs/backup.log 2>&1
```

## Update procedures

### Application update script

Create `/opt/optimap/scripts/update-app.sh`:

```bash
sudo nano /opt/optimap/scripts/update-app.sh
```

```bash
#!/bin/bash
# Application update script for OPTIMAP

set -e

echo "=== OPTIMAP Update Script ==="
echo "Started at: $(date)"

# Navigate to app directory
cd /opt/optimap/app

# Stop services
echo "Stopping services..."
sudo systemctl stop optimap optimap-worker

# Pull latest code
echo "Pulling latest code..."
sudo -u optimap git fetch origin
sudo -u optimap git pull origin main

# Activate virtual environment and update
echo "Updating dependencies..."
sudo -u optimap bash -c '
source /opt/optimap/venv/bin/activate

# Update pip
pip install --upgrade pip

# Reinstall GDAL if system version changed
pip install gdal=="$(gdal-config --version).*"

# Update dependencies
pip install -r requirements.txt

# Apply migrations
python manage.py migrate --noinput

# Collect static files
python manage.py collectstatic --noinput

# Update global regions if needed
python manage.py load_global_regions

# Insert / update built-in journal sources from SOURCE_CONFIG.
python manage.py harvest_journals --insert-sources
' #end of bash command

# Start services
echo "Starting services..."
sudo systemctl start optimap optimap-worker

# Clear Django caches so the next request regenerates content from the new code
#
# Notes:
# - The 'memory' (LocMemCache) backend is already empty after the restart
#   since each Gunicorn worker starts fresh; re-clearing is harmless.
# - The 'default' (DatabaseCache) backend persists across restarts and
#   stores login-magic tokens, email-change confirmations, and GeoRSS feed
#   bodies. Clearing it invalidates in-flight tokens. To preserve them,
#   replace the call below with:
#       python manage.py clear_caches --exclude default
# - Browsers may still serve their own cached copies of pages
#   (Cache-Control: max-age=…) and static files (expires 30d on /static/);
#   a hard refresh (Ctrl+Shift+R / Cmd+Shift+R) bypasses both.
echo "Clearing Django caches..."
sudo -u optimap bash -c '
source /opt/optimap/venv/bin/activate
cd /opt/optimap/app
python manage.py clear_caches
'

# Verify services
sleep 5
if systemctl is-active --quiet optimap && systemctl is-active --quiet optimap-worker; then
    echo "Update completed successfully at: $(date)"
else
    echo "WARNING: Services may not have started correctly"
    systemctl status optimap optimap-worker
    exit 1
fi
```

```bash
sudo chmod +x /opt/optimap/scripts/update-app.sh
```

## Monitoring

### Health check script

Create `/opt/optimap/scripts/health-check.sh`:

```bash
sudo nano /opt/optimap/scripts/health-check.sh
```

```bash
#!/bin/bash
# Health check script for OPTIMAP

ERRORS=0

# Check Django service
if ! systemctl is-active --quiet optimap; then
    echo "ERROR: optimap service is not running"
    ERRORS=$((ERRORS + 1))
fi

# Check worker service
if ! systemctl is-active --quiet optimap-worker; then
    echo "ERROR: optimap-worker service is not running"
    ERRORS=$((ERRORS + 1))
fi

# Check nginx
if ! systemctl is-active --quiet nginx; then
    echo "ERROR: nginx is not running"
    ERRORS=$((ERRORS + 1))
fi

# Check PostgreSQL
if ! systemctl is-active --quiet postgresql; then
    echo "ERROR: postgresql is not running"
    ERRORS=$((ERRORS + 1))
fi

# Check application responds
if ! curl -sf http://localhost/ > /dev/null 2>&1; then
    echo "ERROR: Application not responding"
    ERRORS=$((ERRORS + 1))
fi

# Check disk space (warn if < 20%)
DISK_USAGE=$(df /opt/optimap | awk 'NR==2 {print $5}' | tr -d '%')
if [ "$DISK_USAGE" -gt 80 ]; then
    echo "WARNING: Disk usage is ${DISK_USAGE}%"
fi

if [ $ERRORS -eq 0 ]; then
    echo "All checks passed"
    exit 0
else
    echo "${ERRORS} check(s) failed"
    exit 1
fi
```

```bash
sudo chmod +x /opt/optimap/scripts/health-check.sh
```

## Troubleshooting

### View service logs

```bash
# Django application logs
sudo journalctl -u optimap -f

# Worker logs
sudo journalctl -u optimap-worker -f

# Gunicorn logs
sudo tail -f /opt/optimap/logs/gunicorn-*.log

# nginx logs
sudo tail -f /var/log/nginx/optimap-*.log
```

### Common issues

**Socket permission errors:**

```bash
# Ensure socket directory permissions
sudo chown optimap:www-data /opt/optimap
sudo chmod 755 /opt/optimap
```

**Database connection errors:**

```bash
# Test database connection
sudo -u optimap bash -c '
source /opt/optimap/venv/bin/activate
cd /opt/optimap/app
python manage.py dbshell
'
```

**Static files not loading (403 Permission denied in nginx error log):**

```bash
# Inspect modes — files should be world-readable, directories world-traversable
ls -la /opt/optimap/static/

# Common culprit: subdirs come out 'drwxrwx---' (770) so nginx (www-data)
# cannot traverse into static/js/, static/css/, static/leaflet/ etc.
# Fix idempotently — read for all, traverse on directories only:
sudo chmod -R a+rX /opt/optimap/static

# If files are also missing entirely, re-collect:
sudo -u optimap bash -c '
source /opt/optimap/venv/bin/activate
cd /opt/optimap/app
python manage.py collectstatic --noinput
'
```

**GDAL version mismatch:**

```bash
# Reinstall GDAL Python bindings
sudo -u optimap bash -c '
source /opt/optimap/venv/bin/activate
pip uninstall gdal -y
pip install gdal=="$(gdal-config --version).*"
'
```

### Restart all services

```bash
sudo systemctl restart postgresql
sudo systemctl restart optimap
sudo systemctl restart optimap-worker
sudo systemctl restart nginx
```

## Security hardening

### Additional recommendations

1. **Regular updates:** Keep the system and all packages updated

   ```bash
   sudo apt update && sudo apt upgrade -y
   ```

2. **Fail2ban:** Install and configure for SSH and nginx protection

   ```bash
   sudo apt install -y fail2ban
   ```

3. **Database security:** Ensure PostgreSQL only listens on localhost

   ```bash
   # In /etc/postgresql/14/main/postgresql.conf
   listen_addresses = 'localhost'
   ```

4. **Secret management:** Consider using HashiCorp Vault or similar for secrets in production

5. **Monitoring:** Set up monitoring with Prometheus/Grafana or similar tools

## Comparison with containerized deployment

| Aspect | Native deployment | Docker deployment |
|--------|------------------|-------------------|
| Resource overhead | Lower | Higher (container runtime) |
| Isolation | Process-level | Container-level |
| Updates | Manual package management | Pull new images |
| Portability | OS-specific | Portable containers |
| Debugging | Direct system access | Container shell access |
| Backup complexity | Standard database tools | Volume management |
| Scaling | Manual | Easier with orchestration |

## Quick reference

### Service management

```bash
# Start all services
sudo systemctl start postgresql nginx optimap optimap-worker

# Stop all services
sudo systemctl stop optimap optimap-worker nginx

# Restart application only
sudo systemctl restart optimap optimap-worker

# Reload nginx (after config changes)
sudo systemctl reload nginx
```

### Log locations

| Log | Location |
|-----|----------|
| Django/Gunicorn access | `/opt/optimap/logs/gunicorn-access.log` |
| Django/Gunicorn errors | `/opt/optimap/logs/gunicorn-error.log` |
| nginx access | `/var/log/nginx/optimap-access.log` |
| nginx errors | `/var/log/nginx/optimap-error.log` |
| PostgreSQL | `/var/log/postgresql/` |
| Systemd services | `journalctl -u <service-name>` |

### Important paths

| Path | Purpose |
|------|---------|
| `/opt/optimap/app/` | Application code |
| `/opt/optimap/venv/` | Python virtual environment |
| `/opt/optimap/static/` | Collected static files |
| `/opt/optimap/logs/` | Application logs |
| `/opt/optimap/backups/` | Database backups |
| `/opt/optimap/cache/` | Data dump cache |
| `/opt/optimap/gunicorn.sock` | Gunicorn Unix socket |

