#!/usr/bin/env bash
# Re-runnable camera install on the HA laptop: the two go2rtc containers, the
# office window snapshot and timelapse timers, and the HA camera packages.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "${HERE}/../config.sh"
SSH=(ssh "${SSH_OPTS_BATCH[@]}" "${HA_TARGET}")
"${SSH[@]}" 'mkdir -p ~/go2rtc ~/homeassistant/media/office-camera/timelapse ~/office-camera/frames'
scp -q "${SSH_OPTS_BATCH[@]}" "${HERE}/compose.yaml" "${HERE}/capture.yaml" "${HERE}/go2rtc.yaml" \
  "${HERE}/snapshot.sh" "${HERE}/timelapse.sh" "${HERE}/launch_recorder.py" "${HERE}/starlink.py" "${HA_TARGET}:go2rtc/"
# Units name the HA user (@@HA_USER@@); render a staged copy.
UNITS="$(mktemp -d "${TMPDIR:-/tmp}/ha-cameras.XXXXXX")"
trap 'rm -rf "${UNITS}"' EXIT
cp "${HERE}"/systemd/* "${UNITS}/"
HA_USER="${HA_USER}" python3 "${HERE}/../render_env.py" "${UNITS}"
scp -q "${SSH_OPTS_BATCH[@]}" "${UNITS}"/* "${HA_TARGET}:/tmp/"
"${SSH[@]}" 'mkdir -p ~/go2rtc/analyzer ~/go2rtc/analyzer-data'
scp -q "${SSH_OPTS_BATCH[@]}" "${HERE}"/analyzer/{Dockerfile,requirements.txt,analyzer.py} "${HA_TARGET}:go2rtc/analyzer/"
for package in office_window_camera baby_monitor starlink_trains; do
  "${SSH[@]}" "docker exec -i homeassistant sh -c 'cat > /config/packages/${package}.yaml'" < "${HERE}/${package}.yaml"
done
# Home coordinates for Starlink pass predictions (launch_recorder.py).
printf 'HOME_LAT=%s\nHOME_LON=%s\n' "${HOME_LAT}" "${HOME_LON}" | "${SSH[@]}" 'umask 077; cat > ~/go2rtc/home.env'
"${SSH[@]}" bash -s <<'REMOTE'
set -euo pipefail
# SGP4 for the Starlink predictions.
dpkg -s python3-sgp4 >/dev/null 2>&1 || sudo apt-get install -y -qq python3-sgp4
cd ~/go2rtc
# The first go2rtc was started with docker run; compose owns both containers now.
if [ -z "$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' go2rtc 2>/dev/null)" ]; then
  docker rm -f go2rtc >/dev/null 2>&1 || true
fi
docker compose up -d --build --remove-orphans
# Config files are bind-mounted, so compose does not notice edits to them.
docker compose restart
for unit in office-camera-snapshot office-camera-timelapse; do
  sudo install -m 644 "/tmp/${unit}.service" "/tmp/${unit}.timer" /etc/systemd/system/
  rm -f "/tmp/${unit}.service" "/tmp/${unit}.timer"
done
sudo install -m 644 /tmp/office-camera-launches.service /etc/systemd/system/
rm -f /tmp/office-camera-launches.service
sudo systemctl daemon-reload
sudo systemctl enable --now office-camera-snapshot.timer office-camera-timelapse.timer office-camera-launches.service
# Picks up a new launch_recorder.py (it waits between launches, so this is safe).
sudo systemctl restart office-camera-launches.service
REMOTE
"${SSH[@]}" 'docker exec homeassistant python -m homeassistant --script check_config -c /config' | tail -3
echo "Cameras installed; restart Home Assistant to load package changes. HA needs media_dirs (see README)."
