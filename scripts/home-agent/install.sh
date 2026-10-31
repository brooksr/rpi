#!/usr/bin/env bash
# Re-runnable install of the home observer on the HA laptop: the home-agent
# service, its HA package, and the Jarvis page that shows it.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "${HERE}/../config.sh"
SSH=(ssh "${SSH_OPTS_BATCH[@]}" "${HA_TARGET}")
"${SSH[@]}" 'mkdir -p ~/home-agent/cloud-cwd ~/home-agent/cloud-log && chmod 700 ~/home-agent'
scp -q "${SSH_OPTS_BATCH[@]}" "${HERE}/agent.py" "${HERE}/config.yaml" "${HA_TARGET}:home-agent/"
# The unit and the Jarvis dashboard have @@NAME@@ placeholders; render staged copies.
STAGE="$(mktemp -d "${TMPDIR:-/tmp}/ha-home-agent.XXXXXX")"
trap 'rm -rf "${STAGE}"' EXIT
cp "${HERE}/home_agent.yaml" "${HERE}/systemd/home-agent.service" \
  "${HERE}/../office-search/jarvis_dashboard.yaml" "${STAGE}/"
HA_USER="${HA_USER}" python3 "${HERE}/../render_env.py" "${STAGE}"
scp -q "${SSH_OPTS_BATCH[@]}" "${STAGE}/home-agent.service" "${HA_TARGET}:/tmp/"
"${SSH[@]}" "docker exec -i homeassistant sh -c 'cat > /config/packages/home_agent.yaml'" < "${STAGE}/home_agent.yaml"
"${SSH[@]}" "docker exec -i homeassistant sh -c 'cat > /config/dashboards/jarvis.yaml'" < "${STAGE}/jarvis_dashboard.yaml"
"${SSH[@]}" bash -s <<'REMOTE'
set -euo pipefail
sudo install -m 644 /tmp/home-agent.service /etc/systemd/system/
rm -f /tmp/home-agent.service
sudo systemctl daemon-reload
sudo systemctl enable home-agent.service
sudo systemctl restart home-agent.service
REMOTE
"${SSH[@]}" 'docker exec homeassistant python -m homeassistant --script check_config -c /config' | tail -3
echo "Home observer installed; restart Home Assistant the first time to load home_agent.yaml."
