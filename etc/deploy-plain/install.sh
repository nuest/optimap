#!/bin/bash
# OPTIMAP native deployment installation script
# Run as root or with sudo

set -e

# Configuration
OPTIMAP_USER="optimap"
OPTIMAP_HOME="/opt/optimap"
OPTIMAP_REPO="https://github.com/52North/OPTIMAP.git"
OPTIMAP_BRANCH="main"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running as root
if [[ $EUID -ne 0 ]]; then
    log_error "This script must be run as root"
    exit 1
fi

log_info "=== OPTIMAP Native Deployment Installation ==="
log_info "Target directory: ${OPTIMAP_HOME}"

# Step 1: System packages
log_info "Step 1/10: Installing system packages..."
apt update
apt install -y \
    build-essential \
    python3-dev \
    python3-pip \
    python3-venv \
    git \
    curl \
    nginx \
    certbot \
    python3-certbot-nginx \
    postgresql \
    postgresql-contrib

# Step 2: GDAL and geospatial libraries
log_info "Step 2/10: Installing GDAL and geospatial libraries..."
add-apt-repository -y ppa:ubuntugis/ppa
apt update
apt install -y \
    gdal-bin \
    libgdal-dev \
    libgeos-dev \
    libproj-dev

# Determine PostgreSQL version and install PostGIS
PG_VERSION=$(psql --version | grep -oP '\d+' | head -1)
log_info "Detected PostgreSQL version: ${PG_VERSION}"
apt install -y "postgresql-${PG_VERSION}-postgis-3"

# Step 3: Create system user
log_info "Step 3/10: Creating system user..."
if id "${OPTIMAP_USER}" &>/dev/null; then
    log_warn "User ${OPTIMAP_USER} already exists"
else
    useradd --system --shell /bin/bash --home "${OPTIMAP_HOME}" "${OPTIMAP_USER}"
fi

# Step 4: Create directories
log_info "Step 4/10: Creating directories..."
mkdir -p "${OPTIMAP_HOME}"/{app,venv,logs,static,cache,backups,scripts}
chown -R "${OPTIMAP_USER}:${OPTIMAP_USER}" "${OPTIMAP_HOME}"

# Step 5: Clone repository
log_info "Step 5/10: Cloning repository..."
if [[ -d "${OPTIMAP_HOME}/app/.git" ]]; then
    log_warn "Repository already exists, pulling latest changes..."
    sudo -u "${OPTIMAP_USER}" git -C "${OPTIMAP_HOME}/app" pull origin "${OPTIMAP_BRANCH}"
else
    sudo -u "${OPTIMAP_USER}" git clone -b "${OPTIMAP_BRANCH}" "${OPTIMAP_REPO}" "${OPTIMAP_HOME}/app"
fi

# Step 6: Create virtual environment and install dependencies
log_info "Step 6/10: Setting up Python virtual environment..."
sudo -u "${OPTIMAP_USER}" python3 -m venv "${OPTIMAP_HOME}/venv"

GDAL_VERSION=$(gdal-config --version)
log_info "Detected GDAL version: ${GDAL_VERSION}"

sudo -u "${OPTIMAP_USER}" bash -c "
source ${OPTIMAP_HOME}/venv/bin/activate
pip install --upgrade pip
pip install gdal==\"${GDAL_VERSION}.*\"
pip install -r ${OPTIMAP_HOME}/app/requirements.txt
pip install gunicorn
"

# Step 7: Copy configuration files
log_info "Step 7/10: Installing configuration files..."

# Gunicorn config
cp "${OPTIMAP_HOME}/app/etc/deploy-plain/gunicorn.conf.py" "${OPTIMAP_HOME}/gunicorn.conf.py"
chown "${OPTIMAP_USER}:${OPTIMAP_USER}" "${OPTIMAP_HOME}/gunicorn.conf.py"

# Systemd services
cp "${OPTIMAP_HOME}/app/etc/deploy-plain/optimap.service" /etc/systemd/system/
cp "${OPTIMAP_HOME}/app/etc/deploy-plain/optimap-worker.service" /etc/systemd/system/
systemctl daemon-reload

# nginx config (but don't enable yet)
cp "${OPTIMAP_HOME}/app/etc/deploy-plain/nginx-optimap.conf" /etc/nginx/sites-available/optimap

log_info "Step 8/10: Configuration files installed"
log_warn "You need to manually:"
log_warn "  1. Create database and user in PostgreSQL"
log_warn "  2. Create ${OPTIMAP_HOME}/app/optimap/.env with your settings"
log_warn "  3. Update domain name in /etc/nginx/sites-available/optimap"
log_warn "  4. Run: sudo -u ${OPTIMAP_USER} bash -c 'source ${OPTIMAP_HOME}/venv/bin/activate && cd ${OPTIMAP_HOME}/app && python manage.py migrate && python manage.py createcachetable && python manage.py load_global_regions && python manage.py collectstatic --noinput'"
log_warn "  5. Run: sudo certbot --nginx -d yourdomain.example.com"
log_warn "  6. Enable nginx site: sudo ln -s /etc/nginx/sites-available/optimap /etc/nginx/sites-enabled/"
log_warn "  7. Enable services: sudo systemctl enable optimap optimap-worker"
log_warn "  8. Start services: sudo systemctl start optimap optimap-worker"

log_info "=== Base installation complete ==="
log_info "See ${OPTIMAP_HOME}/app/docs/deployment-plain.md for detailed instructions"
