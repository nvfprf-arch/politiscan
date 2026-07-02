#!/usr/bin/env bash
# =============================================================================
# update.sh — Pull latest PolitiScan code and restart the service
#
# Usage: Run as root on the server:
#   bash /opt/politiscan/update.sh
#
# What it does:
#   - Pulls the latest code from GitHub (main branch)
#   - Installs any new Python dependencies from requirements.txt
#   - Restarts the politiscan systemd service
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Sanity check — must be root
# ---------------------------------------------------------------------------
if [[ $EUID -ne 0 ]]; then
    echo "Error: this script must be run as root (sudo bash update.sh)" >&2
    exit 1
fi

INSTALL_DIR="/opt/politiscan"
VENV_DIR="$INSTALL_DIR/.venv"

echo "======================================================================"
echo " PolitiScan — updating to latest code"
echo "======================================================================"

# ---------------------------------------------------------------------------
# Pull latest code from GitHub
# ---------------------------------------------------------------------------
echo ""
echo "[1/3] Pulling latest code from GitHub..."

git -C "$INSTALL_DIR" pull --ff-only

echo "  Code updated."

# ---------------------------------------------------------------------------
# Install any new or changed Python requirements
# ---------------------------------------------------------------------------
echo ""
echo "[2/3] Syncing Python dependencies..."

"$VENV_DIR/bin/pip" install --upgrade -r "$INSTALL_DIR/requirements.txt"

# Re-apply ownership in case new files were added by git pull
chown -R www-data:www-data "$INSTALL_DIR"
# Preserve .env permissions
chmod 600 "$INSTALL_DIR/.env"

echo "  Dependencies up to date."

# ---------------------------------------------------------------------------
# Restart the systemd service to pick up the new code
# ---------------------------------------------------------------------------
echo ""
echo "[3/3] Restarting politiscan service..."

systemctl restart politiscan

# Brief wait for the process to come up
sleep 3

if systemctl is-active --quiet politiscan; then
    echo "  politiscan is RUNNING."
else
    echo ""
    echo "  WARNING: politiscan failed to start. Last 30 log lines:"
    journalctl -u politiscan -n 30 --no-pager
    exit 1
fi

echo ""
echo "======================================================================"
echo " Update complete!"
echo " Live logs: journalctl -u politiscan -f"
echo "======================================================================"
