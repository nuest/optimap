#!/bin/bash
# OPTIMAP native deployment update script
#
# This script is versioned in the repository at etc/deploy-plain/update-app.sh.
# On a server it is run via a symlink, e.g.
#   /opt/optimap/scripts/update-app.sh -> /opt/optimap/app/etc/deploy-plain/update-app.sh
# so that `git pull` here always refreshes the update procedure itself.
#
# To pick up a newer version of *this script*, the run is split in two phases:
# phase 1 stops services and pulls the latest code (which may rewrite this very
# file), then re-execs itself so phase 2 runs from the updated script. The
# OPTIMAP_UPDATE_REEXEC guard prevents an infinite loop.

set -e

OPTIMAP_USER="${OPTIMAP_USER:-optimap}"
OPTIMAP_HOME="${OPTIMAP_HOME:-/opt/optimap}"
OPTIMAP_APP="${OPTIMAP_HOME}/app"
OPTIMAP_VENV="${OPTIMAP_HOME}/venv"
OPTIMAP_BRANCH="${OPTIMAP_BRANCH:-main}"

echo "=== OPTIMAP Update Script ==="
echo "Started at: $(date)"

if [ -z "${OPTIMAP_UPDATE_REEXEC:-}" ]; then
    # ---- Phase 1: stop services and pull latest code ----
    cd "${OPTIMAP_APP}"

    echo "Stopping services..."
    sudo systemctl stop optimap optimap-worker

    echo "Pulling latest code..."
    sudo -u "${OPTIMAP_USER}" git fetch origin
    sudo -u "${OPTIMAP_USER}" git pull origin "${OPTIMAP_BRANCH}"

    # Re-exec the (possibly updated) script for phase 2. Resolve the real path
    # so we run the file in the repo, not a stale copy bash already buffered.
    echo "Re-running updated update script..."
    export OPTIMAP_UPDATE_REEXEC=1
    exec "${OPTIMAP_APP}/etc/deploy-plain/update-app.sh" "$@"
fi

# ---- Phase 2: dependencies, migrations, assets, restart ----
echo "Updating dependencies..."
sudo -u "${OPTIMAP_USER}" bash -c "
source ${OPTIMAP_VENV}/bin/activate
cd ${OPTIMAP_APP}

# Update pip
pip install --upgrade pip

# Reinstall GDAL if system version changed
pip install gdal==\"\$(gdal-config --version).*\"

# Update dependencies
pip install -r requirements.txt

# Apply migrations
python manage.py migrate --noinput

# Collect static files
python manage.py collectstatic --noinput

# Update global regions if needed
python manage.py load_global_regions

# Update country outlines if needed (cached GeoJSON, mirrors load_global_regions)
python manage.py load_countries

# Insert / update built-in sources from SOURCE_CONFIG.
python manage.py harvest_sources --insert-sources

# Regenerate OGC API OpenAPI document (required for /ogcapi/ endpoint).
# The DB connection is derived from DATABASE_URL, so this connects to the same
# database as Django (a reachable DB is required for the works collection).
python manage.py generate_pygeoapi_openapi --force || echo 'WARNING: OGC API setup failed (non-fatal)'
"

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
sudo -u "${OPTIMAP_USER}" bash -c "
source ${OPTIMAP_VENV}/bin/activate
cd ${OPTIMAP_APP}
python manage.py clear_caches
"

# Verify services
sleep 5
if systemctl is-active --quiet optimap && systemctl is-active --quiet optimap-worker; then
    echo "Update completed successfully at: $(date)"
else
    echo "WARNING: Services may not have started correctly"
    systemctl status optimap optimap-worker
    exit 1
fi
