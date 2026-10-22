#!/usr/bin/env bash
# setup-homeassistant.sh — install Home Assistant (Container/Docker method) on
# the Pi, alongside Pi-hole. Does NOT wipe the OS or touch Pi-hole.
#
# RUN ON THE PI, WITH SUDO:
#   scp scripts/setup-homeassistant.sh pi@raspberrypi.local:~/   (from the Mac)
#   ssh pi@raspberrypi.local
#   sudo bash ~/setup-homeassistant.sh
#
# Re-runnable: if the container already exists it is recreated cleanly.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then echo "Run with sudo: sudo bash $0" >&2; exit 1; fi

# The human user (so config isn't owned by root and they can run docker later).
RUN_USER="${SUDO_USER:-$(id -un)}"
CONFIG_DIR="/home/${RUN_USER}/homeassistant"
TZ_VAL="$(timedatectl show -p Timezone --value 2>/dev/null || cat /etc/timezone 2>/dev/null || echo UTC)"
IMAGE="ghcr.io/home-assistant/home-assistant:stable"

echo "== 1/5 Installing Docker (Debian's docker.io package) =="
if ! command -v docker >/dev/null; then
  apt-get update -qq
  apt-get install -y docker.io
else
  echo "   docker already present: $(docker --version)"
fi
systemctl enable --now docker

echo "== 2/5 Letting '${RUN_USER}' use docker without sudo (takes effect next login) =="
usermod -aG docker "${RUN_USER}" || true

echo "== 3/5 Creating config dir: ${CONFIG_DIR} =="
mkdir -p "${CONFIG_DIR}"
chown "${RUN_USER}:${RUN_USER}" "${CONFIG_DIR}"

echo "== 4/5 Pulling Home Assistant image (this is the slow part on a Pi 3) =="
docker pull "${IMAGE}"

echo "== 5/5 (Re)creating the container =="
docker rm -f homeassistant 2>/dev/null || true
docker run -d \
  --name homeassistant \
  --restart=unless-stopped \
  --stop-timeout 60 \
  --privileged \
  -e TZ="${TZ_VAL}" \
  -v "${CONFIG_DIR}:/config" \
  -v /run/dbus:/run/dbus:ro \
  --network=host \
  "${IMAGE}"

IP="$(hostname -I | awk '{print $1}')"
echo
echo "✅ Home Assistant is starting (timezone: ${TZ_VAL})."
echo "   First boot takes a few minutes while it initializes — be patient."
echo "   Open:  http://${IP}:8123   (or http://raspberrypi.local:8123)"
echo
echo "   Watch startup:   docker logs -f homeassistant"
echo "   Stop / start:    docker stop homeassistant   /   docker start homeassistant"
echo "   Update later:    docker pull ${IMAGE} && sudo bash ~/setup-homeassistant.sh"
