#!/usr/bin/env bash
# Raspberry Pi OS (with desktop) installer. Run as the normal user, not root:  ./install.sh
# NOTE: written for Raspberry Pi OS Bookworm; not yet verified on real hardware.
set -euo pipefail
if [ "$(id -u)" -eq 0 ]; then echo "הריצו בלי sudo: ./install.sh"; exit 1; fi
DIR="$(cd "$(dirname "$0")" && pwd)"
PORT=8080

echo "[1/4] מתקין חבילות מערכת…"
sudo apt-get update -qq
sudo apt-get install -y python3-venv fonts-noto-core curl
command -v chromium-browser >/dev/null || command -v chromium >/dev/null || sudo apt-get install -y chromium-browser || sudo apt-get install -y chromium

echo "[2/4] מתקין את התוכנה…"
python3 -m venv "$DIR/.venv"
"$DIR/.venv/bin/pip" install -q -r "$DIR/requirements.txt"
chmod +x "$DIR/kiosk.sh" "$DIR/run.sh"

echo "[3/4] מגדיר הפעלה אוטומטית של השרת…"
sudo tee /etc/systemd/system/signage.service >/dev/null <<UNIT
[Unit]
Description=Digital signage server
After=network.target

[Service]
User=$USER
WorkingDirectory=$DIR
Environment=SIGNAGE_PORT=$PORT
ExecStart=$DIR/.venv/bin/uvicorn --factory server.app:create_app --host 0.0.0.0 --port $PORT
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now signage.service

echo "[4/4] מגדיר פתיחה של המסך המלא אחרי הדלקה…"
mkdir -p "$HOME/.config/autostart"
cat > "$HOME/.config/autostart/signage-kiosk.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Signage display
Exec=$DIR/kiosk.sh
DESKTOP
# newer Raspberry Pi OS uses labwc; kiosk.sh holds a lock, so starting it twice is harmless
mkdir -p "$HOME/.config/labwc"
grep -qs "kiosk.sh" "$HOME/.config/labwc/autostart" || echo "$DIR/kiosk.sh &" >> "$HOME/.config/labwc/autostart"
sudo raspi-config nonint do_blanking 1 2>/dev/null || true   # keep the screen on

IP="$(hostname -I | awk '{print $1}')"
echo
echo "הותקן. דף הניהול: http://$IP:$PORT/admin"
echo "הפעילו מחדש (sudo reboot) והמסך יעלה לבד."
