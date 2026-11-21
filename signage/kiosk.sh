#!/usr/bin/env bash
# Opens the display full-screen. Started automatically after login on the Pi.
PORT="${SIGNAGE_PORT:-80}"
exec 9>"/tmp/signage-kiosk.lock"
flock -n 9 || exit 0                      # already running (two autostart mechanisms may both fire)
until curl -fs "http://127.0.0.1:$PORT/api/playlist" >/dev/null; do sleep 1; done
BROWSER="$(command -v chromium-browser || command -v chromium)"
exec "$BROWSER" --kiosk --noerrdialogs --disable-infobars --disable-session-crashed-bubble \
  --no-first-run --check-for-update-interval=31536000 --password-store=basic \
  --autoplay-policy=no-user-gesture-required "http://127.0.0.1:$PORT/"
