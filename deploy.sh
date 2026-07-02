#!/usr/bin/env bash
# =============================================================================
# deploy.sh — PolitiScan Streamlit deployment on fresh Ubuntu 26.04 (Hetzner)
#
# Usage: Run as root on a brand-new server:
#   bash deploy.sh
#
# After the script finishes:
#   1. Edit /opt/politiscan/.env and fill in real API keys
#   2. Run: systemctl restart politiscan
# =============================================================================

set -euo pipefail   # exit on any error, treat unset vars as errors

# ---------------------------------------------------------------------------
# 0. Sanity check — must be root
# ---------------------------------------------------------------------------
if [[ $EUID -ne 0 ]]; then
    echo "Error: this script must be run as root (sudo bash deploy.sh)" >&2
    exit 1
fi

echo "======================================================================"
echo " PolitiScan — deployment starting"
echo "======================================================================"

# ---------------------------------------------------------------------------
# 1. Update and upgrade Ubuntu packages (non-interactive)
# ---------------------------------------------------------------------------
echo ""
echo "[1/11] Updating and upgrading Ubuntu packages..."

export DEBIAN_FRONTEND=noninteractive

apt-get update -y
apt-get upgrade -y \
    -o Dpkg::Options::="--force-confdef" \
    -o Dpkg::Options::="--force-confold"

# ---------------------------------------------------------------------------
# 2. Install Python 3.12 and pip
#    Ubuntu 26.04 may ship a newer Python by default; we pin 3.12 explicitly.
#    The deadsnakes PPA provides it if not already available.
# ---------------------------------------------------------------------------
echo ""
echo "[2/11] Installing Python 3.12 and pip..."

apt-get install -y software-properties-common

# Add deadsnakes PPA for guaranteed Python 3.12 availability
add-apt-repository -y ppa:deadsnakes/ppa
apt-get update -y

apt-get install -y python3.12 python3.12-venv python3.12-dev

# Bootstrap pip for Python 3.12 using the get-pip script
curl -sS https://bootstrap.pypa.io/get-pip.py | python3.12

# System deps required by requirements.txt packages:
#   pytesseract  → tesseract-ocr
#   pdf2image    → poppler-utils
#   newspaper3k  → libxml2, libxslt1, libjpeg (for image handling)
echo ""
echo "[2/11] Installing system libraries required by Python packages..."

apt-get install -y \
    tesseract-ocr \
    poppler-utils \
    libxml2-dev \
    libxslt1-dev \
    libjpeg-dev \
    libssl-dev \
    libffi-dev \
    curl

# ---------------------------------------------------------------------------
# 3. Install git
# ---------------------------------------------------------------------------
echo ""
echo "[3/11] Installing git..."

apt-get install -y git

# ---------------------------------------------------------------------------
# 4. Clone the GitHub repository into /opt/politiscan
# ---------------------------------------------------------------------------
echo ""
echo "[4/11] Cloning repository into /opt/politiscan..."

REPO_URL="https://github.com/nvfprf-arch/politiscan"
INSTALL_DIR="/opt/politiscan"

if [[ -d "$INSTALL_DIR/.git" ]]; then
    echo "  Directory already contains a git repo — pulling latest instead of cloning."
    git -C "$INSTALL_DIR" pull --ff-only
else
    git clone "$REPO_URL" "$INSTALL_DIR"
fi

# ---------------------------------------------------------------------------
# 5. Create a Python virtual environment and install requirements
# ---------------------------------------------------------------------------
echo ""
echo "[5/11] Creating virtual environment and installing Python requirements..."

VENV_DIR="$INSTALL_DIR/.venv"

python3.12 -m venv "$VENV_DIR"

# Upgrade pip inside the venv before installing packages
"$VENV_DIR/bin/pip" install --upgrade pip

# Install all project dependencies
"$VENV_DIR/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

# ---------------------------------------------------------------------------
# 6. Create the .env file with placeholder API keys
#    IMPORTANT: fill these in before starting the service!
#    Email is handled by Resend (not SendGrid).
# ---------------------------------------------------------------------------
echo ""
echo "[6/11] Creating .env file with placeholder values..."

ENV_FILE="$INSTALL_DIR/.env"

# Only create if it doesn't already exist, to avoid overwriting real keys
if [[ -f "$ENV_FILE" ]]; then
    echo "  .env already exists — skipping creation to preserve existing keys."
else
    cat > "$ENV_FILE" << 'EOF'
# PolitiScan — API Keys
# Fill in real values before running: systemctl restart politiscan

# Anthropic Claude API (summaries, ranking, classification)
ANTHROPIC_API_KEY=your_anthropic_api_key_here

# NewsData.io (primary news source)
NEWSDATA_API_KEY=your_newsdata_api_key_here

# Sarvam AI (Indian language translation)
SARVAM_API_KEY=your_sarvam_api_key_here

# Resend (transactional email for OTP login)
RESEND_API_KEY=your_resend_api_key_here
RESEND_FROM_EMAIL=noreply@yourdomain.com

# YouTube Data API v3 (YouTube monitoring page)
YOUTUBE_API_KEY=your_youtube_api_key_here
EOF

    # Restrict permissions — keys are sensitive
    chmod 600 "$ENV_FILE"
    echo "  .env created at $ENV_FILE (mode 600)"
fi

# ---------------------------------------------------------------------------
# 7. Create the systemd service file
#    - Runs Streamlit on port 8501, bound to all interfaces
#    - Loads /opt/politiscan/.env as environment variables
#    - Restarts automatically on crash (5-second delay)
# ---------------------------------------------------------------------------
echo ""
echo "[7/11] Creating systemd service: politiscan.service..."

SERVICE_FILE="/etc/systemd/system/politiscan.service"

cat > "$SERVICE_FILE" << EOF
[Unit]
Description=PolitiScan — Political Intelligence Dashboard (Streamlit)
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=$INSTALL_DIR

# Load API keys from the .env file (KEY=value lines, no "export" prefix)
EnvironmentFile=$ENV_FILE

# Launch Streamlit; port 8501 is reverse-proxied by nginx on port 80
ExecStart=$VENV_DIR/bin/streamlit run app.py \\
    --server.port 8501 \\
    --server.address 0.0.0.0 \\
    --server.headless true \\
    --server.enableCORS false \\
    --server.enableXsrfProtection false

# Restart the service if it exits unexpectedly
Restart=on-failure
RestartSec=5s

# Give the process time to start up
TimeoutStartSec=60

# Log to journald (view with: journalctl -u politiscan -f)
StandardOutput=journal
StandardError=journal
SyslogIdentifier=politiscan

[Install]
WantedBy=multi-user.target
EOF

echo "  Service file written to $SERVICE_FILE"

# Give www-data ownership of the install directory so the service can write to it
chown -R www-data:www-data "$INSTALL_DIR"
# Restore key file permissions after chown
chmod 600 "$ENV_FILE"

# ---------------------------------------------------------------------------
# 8. Enable and start the systemd service
# ---------------------------------------------------------------------------
echo ""
echo "[8/11] Enabling and starting politiscan.service..."

systemctl daemon-reload
systemctl enable politiscan
systemctl start politiscan

echo "  Service status:"
systemctl is-active politiscan && echo "  politiscan is RUNNING" || echo "  WARNING: politiscan is NOT running — check: journalctl -u politiscan -n 50"

# ---------------------------------------------------------------------------
# 9. Install nginx
# ---------------------------------------------------------------------------
echo ""
echo "[9/11] Installing nginx..."

apt-get install -y nginx

# ---------------------------------------------------------------------------
# 10. Create the nginx reverse-proxy configuration
#     Proxies HTTP (port 80) → Streamlit (port 8501).
#     WebSocket headers are required for Streamlit's live updates.
# ---------------------------------------------------------------------------
echo ""
echo "[10/11] Configuring nginx reverse proxy..."

NGINX_CONF="/etc/nginx/sites-available/politiscan"

cat > "$NGINX_CONF" << 'EOF'
# PolitiScan — nginx reverse proxy
# Forwards incoming HTTP on port 80 to Streamlit on localhost:8501
# WebSocket proxying is required for Streamlit's real-time UI updates.

server {
    listen 80;
    listen [::]:80;

    # Replace with your domain name once DNS is pointed at this server.
    # Use "_" to accept all hostnames until then.
    server_name _;

    # Security headers
    add_header X-Frame-Options       "SAMEORIGIN"   always;
    add_header X-Content-Type-Options "nosniff"      always;
    add_header Referrer-Policy       "no-referrer"   always;

    # Increase body size limit for PDF uploads
    client_max_body_size 50M;

    location / {
        proxy_pass         http://127.0.0.1:8501;
        proxy_http_version 1.1;

        # WebSocket support — required by Streamlit
        proxy_set_header   Upgrade    $http_upgrade;
        proxy_set_header   Connection "upgrade";

        # Standard proxy headers
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;

        # Timeouts — Streamlit scans can take 60-90 seconds
        proxy_read_timeout  120s;
        proxy_send_timeout  120s;
        proxy_connect_timeout 10s;
    }

    # Streamlit's health check endpoint
    location /healthz {
        proxy_pass http://127.0.0.1:8501/healthz;
    }
}
EOF

# Enable the site by symlinking into sites-enabled
ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/politiscan

# Remove the default nginx placeholder site if it's still there
if [[ -L /etc/nginx/sites-enabled/default ]]; then
    rm /etc/nginx/sites-enabled/default
    echo "  Removed default nginx site."
fi

# Validate the config before restarting
nginx -t

# ---------------------------------------------------------------------------
# 11. Enable and restart nginx
# ---------------------------------------------------------------------------
echo ""
echo "[11/11] Enabling and restarting nginx..."

systemctl enable nginx
systemctl restart nginx

echo "  nginx status:"
systemctl is-active nginx && echo "  nginx is RUNNING" || echo "  WARNING: nginx is NOT running"

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
echo "======================================================================"
echo " Deployment complete!"
echo "======================================================================"
echo ""
echo " Next steps:"
echo "   1. Add your real API keys:"
echo "      nano /opt/politiscan/.env"
echo ""
echo "   2. Restart the app to pick up the keys:"
echo "      systemctl restart politiscan"
echo ""
echo "   3. Watch live logs:"
echo "      journalctl -u politiscan -f"
echo ""
echo "   4. (Optional) Add HTTPS with Let's Encrypt:"
echo "      apt install certbot python3-certbot-nginx"
echo "      certbot --nginx -d yourdomain.com"
echo ""
echo "   App is accessible at: http://$(curl -s ifconfig.me 2>/dev/null || echo '<server-ip>')"
echo ""
