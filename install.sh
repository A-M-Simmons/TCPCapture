#!/bin/bash
#
# Idempotent installer for tcpdump_service
# Copies pre-existing files into place if changed, ensures dependencies exist,
# and enables the systemd service
#

set -euo pipefail

SERVICE_NAME="tcpdump-capture"
CONFIG_FILE="/etc/tcpdump_service.conf"
PY_SCRIPT="/usr/local/bin/tcpdump_service.py"
UNIT_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
LOG_DIR="/var/log/tcpdump"

SRC_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# ---------- Dependency Checks ----------
echo "[*] Installing base dependencies (tcpdump, python3, pip)..."
apt update -y
apt install -y tcpdump python3 python3-pip

echo "[*] Checking Python version..."
if ! command -v python3 >/dev/null 2>&1; then
    echo "[-] python3 is not installed or not in PATH" >&2
    exit 1
fi
python3 -V

# Python package requirements
PYTHON_PACKAGES=(configparser)

echo "[*] Ensuring required Python packages are installed..."
for pkg in "${PYTHON_PACKAGES[@]}"; do
    if ! python3 -c "import $pkg" 2>/dev/null; then
        echo "  -> Installing Python package: $pkg"
        pip3 install --break-system-packages "$pkg"
    else
        echo "  -> Python package already available: $pkg"
    fi
done

# ---------- Directory Setup ----------
echo "[*] Ensuring log directory at $LOG_DIR..."
if [ ! -d "$LOG_DIR" ]; then
    mkdir -p "$LOG_DIR"
    chmod 750 "$LOG_DIR"
    chown root:root "$LOG_DIR"
    echo "  -> Created log directory"
else
    echo "  -> Log directory already exists"
fi

# ---------- File Installation Helper ----------
install_if_changed() {
    local src="$1"
    local dest="$2"
    local mode="$3"

    if [ ! -f "$src" ]; then
        echo "[-] Missing source file: $src" >&2
        exit 1
    fi

    if [ ! -f "$dest" ] || ! cmp -s "$src" "$dest"; then
        install -m "$mode" "$src" "$dest"
        echo "  -> Installed/updated $dest"
        return 0
    else
        echo "  -> No change to $dest"
        return 1
    fi
}

# ---------- Install Files ----------
echo "[*] Installing config..."
install_if_changed "$SRC_DIR/tcpdump_service.conf" "$CONFIG_FILE" 644
CONFIG_UPDATED=$?

echo "[*] Installing Python service..."
install_if_changed "$SRC_DIR/tcpdump_service.py" "$PY_SCRIPT" 755
PY_UPDATED=$?

echo "[*] Installing systemd unit..."
install_if_changed "$SRC_DIR/tcpdump-capture.service" "$UNIT_FILE" 644
UNIT_UPDATED=$?

# ---------- Systemd Setup ----------
if (( CONFIG_UPDATED || PY_UPDATED || UNIT_UPDATED )); then
    echo "[*] Reloading systemd daemon..."
    systemctl daemon-reload

    echo "[*] Restarting $SERVICE_NAME service..."
    systemctl enable --now "$SERVICE_NAME"
    systemctl restart "$SERVICE_NAME"
else
    echo "[*] No changes detected in service files, skipping restart"
    systemctl enable --now "$SERVICE_NAME"
fi

echo "[+] Installation complete."
systemctl status "$SERVICE_NAME" --no-pager
