#!/usr/bin/env bash
# Re-runnable install of the lid-controlled desktop on the HA laptop: gdm
# auto-login plus the lid-desktop watcher. Pass --start to start the watcher
# now; with the lid closed that ends the current desktop session after GRACE.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "${HERE}/../config.sh"
SSH=(ssh "${SSH_OPTS_BATCH[@]}" "${HA_TARGET}")
scp -q "${SSH_OPTS_BATCH[@]}" "${HERE}/lid-desktop.sh" "${HERE}/lid-desktop.service" "${HA_TARGET}:/tmp/"
"${SSH[@]}" START="${1:-}" HA_USER="${HA_USER}" bash -s <<'REMOTE'
set -euo pipefail
sudo install -m 755 /tmp/lid-desktop.sh /usr/local/bin/
sudo install -m 644 /tmp/lid-desktop.service /etc/systemd/system/
rm -f /tmp/lid-desktop.sh /tmp/lid-desktop.service
# Auto-login, so opening the lid goes straight to the desktop.
conf=/etc/gdm3/custom.conf
if ! grep -q '^AutomaticLoginEnable *= *true' "$conf"; then
  sudo cp -p "$conf" "$conf.before-autologin"
  sudo sed -i "/^\[daemon\]/a AutomaticLoginEnable = true\nAutomaticLogin = ${HA_USER}" "$conf"
fi
sudo systemctl daemon-reload
sudo systemctl enable lid-desktop.service
if [ "${START}" = --start ]; then sudo systemctl restart lid-desktop.service; fi
systemctl is-active lid-desktop.service || true
REMOTE
