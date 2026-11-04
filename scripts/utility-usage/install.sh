#!/usr/bin/env bash
# Re-runnable install of the utility usage fetcher on the HA laptop: the
# Playwright venv and timer, and the utility_usage component and its package.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "${HERE}/../config.sh"
SSH=(ssh "${SSH_OPTS_BATCH[@]}" "${HA_TARGET}")

STAGE="$(mktemp -d "${TMPDIR:-/tmp}/ha-utility-usage.XXXXXX")"
trap 'rm -rf "${STAGE}"' EXIT
cp "${HERE}/systemd/utility-usage.service" "${HERE}/systemd/utility-usage.timer" "${STAGE}/"
HA_USER="${HA_USER}" python3 "${HERE}/../render_env.py" "${STAGE}"

"${SSH[@]}" 'mkdir -p ~/utility-usage && chmod 700 ~/utility-usage'
scp -q "${SSH_OPTS_BATCH[@]}" "${HERE}/fetch_usage.py" "${HA_TARGET}:utility-usage/"
scp -q "${SSH_OPTS_BATCH[@]}" "${STAGE}/utility-usage.service" "${STAGE}/utility-usage.timer" "${HA_TARGET}:/tmp/"
tar -C "${HERE}/custom_components" --exclude __pycache__ -cf - utility_usage \
  | "${SSH[@]}" "docker exec -i homeassistant sh -c 'mkdir -p /config/custom_components && tar -C /config/custom_components -xf -'"
"${SSH[@]}" "docker exec -i homeassistant sh -c 'cat > /config/packages/utility_usage.yaml'" < "${HERE}/package.yaml"
"${SSH[@]}" bash -s <<'REMOTE'
set -euo pipefail
cd ~/utility-usage
# Chrome runs headed on a virtual display: SoCalGas rejects headless logins.
pkgs=()
python3 -c 'import ensurepip' 2>/dev/null || pkgs+=("python3.$(python3 -c 'import sys; print(sys.version_info[1])')-venv")
command -v xvfb-run >/dev/null || pkgs+=(xvfb)
[ ${#pkgs[@]} -eq 0 ] || sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q "${pkgs[@]}" >/dev/null
[ -x venv/bin/pip ] || { rm -rf venv; python3 -m venv venv; }
venv/bin/pip install -q --upgrade playwright
[ -f secrets.env ] || { install -m 600 /dev/null secrets.env; printf '%s\n' \
  'SCE_USERNAME=' 'SCE_PASSWORD=' 'SOCALGAS_USERNAME=' 'SOCALGAS_PASSWORD=' 'EYEONWATER_USERNAME=' 'EYEONWATER_PASSWORD=' > secrets.env; }
sudo install -d -o "$USER" -g "$USER" -m 755 ~/homeassistant/utility-usage
sudo install -m 644 /tmp/utility-usage.service /tmp/utility-usage.timer /etc/systemd/system/
rm -f /tmp/utility-usage.service /tmp/utility-usage.timer
sudo systemctl daemon-reload
sudo systemctl enable --now utility-usage.timer
REMOTE
"${SSH[@]}" 'docker exec homeassistant python -m homeassistant --script check_config -c /config' | tail -3
echo "Installed. Secrets: ~/utility-usage/secrets.env on the laptop. Restart HA after component changes."
