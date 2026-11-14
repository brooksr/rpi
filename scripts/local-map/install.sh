#!/usr/bin/env bash
# Re-runnable local-map installation. Backups stay outside HA's public www path.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "${HERE}/../config.sh"
SSH=(ssh "${SSH_OPTS_BATCH[@]}" "${HA_TARGET}")
STAGE="$(mktemp -d "${TMPDIR:-/tmp}/ha-local-map.XXXXXX")"
mkdir -p "${STAGE}/www/local-map/vendor" "${STAGE}/packages" "${STAGE}/dashboards" "${STAGE}/scripts"
mkdir -p "${STAGE}/custom_components/local_map"
cp "${HERE}/custom_components/local_map/__init__.py" "${HERE}/custom_components/local_map/manifest.json" "${STAGE}/custom_components/local_map/"
cp "${HERE}/vendor/leaflet.js" "${HERE}/vendor/leaflet.css" "${HERE}/vendor/LICENSE" "${STAGE}/www/local-map/vendor/"
cp "${HERE}/local-map-card.js" "${STAGE}/www/local-map/"
cp "${HERE}/overview-widgets.js" "${STAGE}/www/local-map/"
cp "${HERE}/household-schedule.mjs" "${STAGE}/www/local-map/"
cp "${HERE}/sky.mjs" "${STAGE}/www/local-map/"
cp "${HERE}/package.yaml" "${STAGE}/packages/local_map.yaml"
cp "${HERE}/dashboard.yaml" "${STAGE}/dashboards/local-map.yaml"
cp "${HERE}/energy-dashboard.yaml" "${STAGE}/dashboards/home-energy.yaml"
cp "${HERE}/travel-dashboard.yaml" "${STAGE}/dashboards/local-travel.yaml"
CALENDAR="${HERE}/calendar-dashboard.yaml"
[ -f "${CALENDAR}" ] || CALENDAR="${HERE}/calendar-dashboard.example.yaml"
cp "${CALENDAR}" "${STAGE}/dashboards/family-calendar.yaml"
cp "${HERE}/status.py" "${STAGE}/scripts/local-map-status.py"
cp "${HERE}/weather_status.py" "${STAGE}/scripts/local-weather-status.py"
cp "${HERE}/gas_prices.py" "${STAGE}/scripts/local-gas-prices.py"
cp "${HERE}/daytrip.py" "${STAGE}/scripts/local-daytrip.py"
cp "${HERE}/caltrans.py" "${STAGE}/scripts/local-caltrans.py"
cp "${HERE}/fire_incidents.py" "${STAGE}/scripts/local-fire-incidents.py"
cp "${HERE}/system_status.py" "${STAGE}/scripts/local-system-status.py"
cp "${HERE}/purpleair.py" "${STAGE}/scripts/local-purpleair.py"
cp "${HERE}/earthquakes.py" "${STAGE}/scripts/local-earthquakes.py"
cp "${HERE}/babysteps_today.py" "${STAGE}/scripts/local-babysteps-today.py"
cp "${HERE}/net_status.py" "${STAGE}/scripts/local-net-status.py"
cp "${HERE}/household.py" "${STAGE}/scripts/local-household.py"
cp "${HERE}/launches.py" "${STAGE}/scripts/local-launches.py"
python3 "${HERE}/../render_env.py" "${STAGE}"
"${SSH[@]}" 'docker exec homeassistant test -d /config/packages'
# The Pi posts its health to a webhook whose id is in secrets.yaml. package.yaml
# refers to it, so it has to exist before the config check below.
ensure_secret() {
  local value
  value="$("${SSH[@]}" "docker exec -i homeassistant python3 -c 'NAME=\"$1\"
import pathlib, re, secrets, shutil, time
path = pathlib.Path(\"/config/secrets.yaml\")
text = path.read_text() if path.exists() else \"\"
found = re.search(rf\"^{NAME}: *(\\S+)\", text, re.M)
if not found:
    if path.exists():
        shutil.copy(path, f\"{path}.bak-{time.strftime(\"%Y%m%d%H%M%S\")}\")
    value = secrets.token_hex(16)
    path.write_text(text + (\"\" if text.endswith(\"\\n\") or not text else \"\\n\") + f\"{NAME}: {value}\\n\")
    print(value)
else:
    print(found.group(1))
'")"
  echo "${value}"
}
webhook="$(ensure_secret pi_health_webhook)"
echomuse_webhook="$(ensure_secret echomuse_health_webhook)"
tar -C "${STAGE}" -cf - . | "${SSH[@]}" "docker exec -i homeassistant python3 -c '
import datetime, pathlib, subprocess, sys, tarfile
root = pathlib.Path(\"/config\")
backup = root / \"backups/local-map\" / datetime.datetime.now().strftime(\"%Y%m%d%H%M%S%f\")
changed = []
legacy = root / \"packages/local-map.yaml\"
if legacy.exists():
    old = legacy.read_bytes()
    saved = backup / \"packages/local-map.yaml\"
    saved.parent.mkdir(parents=True, exist_ok=True)
    saved.write_bytes(old)
    changed.append((legacy, old))
    legacy.unlink()
archive = tarfile.open(fileobj=sys.stdin.buffer, mode=\"r|\")
for item in archive:
    if not item.isfile():
        continue
    name = pathlib.PurePosixPath(item.name)
    if name.is_absolute() or \"..\" in name.parts:
        raise ValueError(\"Unsafe archive path\")
    destination = root / name
    content = archive.extractfile(item).read()
    old = destination.read_bytes() if destination.exists() else None
    if old == content:
        continue
    if old is not None:
        saved = backup / name
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_bytes(old)
    changed.append((destination, old))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    print(\"Installed\", name)
if changed:
    result = subprocess.run([sys.executable, \"-m\", \"homeassistant\", \"--script\", \"check_config\", \"-c\", str(root)], capture_output=True, text=True)
    output = result.stdout + result.stderr
    print(output)
    if result.returncode or \"Incorrect config\" in output:
        for destination, old in reversed(changed):
            if old is None:
                destination.unlink()
            else:
                destination.write_bytes(old)
        sys.exit(\"Configuration check failed; changes rolled back\")
    print(\"Configuration passed; backups:\", backup)
    (root / \".local-map-restart\").touch()
'"
if "${SSH[@]}" 'docker exec homeassistant test -f /config/.local-map-restart'; then
  "${SSH[@]}" 'docker exec homeassistant python3 -c '\''from pathlib import Path; Path("/config/.local-map-restart").unlink()'\''; docker restart -t 60 homeassistant'
fi

# With HA on another host, the Pi reports its own health: cron runs the same
# status script there every 10 minutes and posts it to HA (Device Health card).
PI_SSH=(ssh "${SSH_OPTS_BATCH[@]}" "${PI_TARGET}")
if [ "${HA_HOST}" != "${PI_HOST}" ]; then
  "${PI_SSH[@]}" 'mkdir -p ~/pi-health && chmod 700 ~/pi-health'
  scp -q "${SSH_OPTS_BATCH[@]}" "${HERE}/system_status.py" "${PI_TARGET}:pi-health/system_status.py"
  printf 'http://%s:8123/api/webhook/%s\n' "${HA_HOST}" "${webhook}" | "${PI_SSH[@]}" 'umask 077; cat > ~/pi-health/webhook-url'
  "${PI_SSH[@]}" bash -s <<'EOF'
set -euo pipefail
push='python3 $HOME/pi-health/system_status.py | curl -fsS -m 20 -H "Content-Type: application/json" --data-binary @- "$(cat $HOME/pi-health/webhook-url)" >/dev/null 2>>$HOME/pi-health/push.log'
{ crontab -l 2>/dev/null | grep -v 'pi-health/system_status.py' || true; echo "*/10 * * * * ${push}"; } | crontab -
# First reading now, once HA is back from any restart above.
url="$(cat ~/pi-health/webhook-url)"
for _ in $(seq 1 30); do curl -fs -m 5 -o /dev/null "${url%/api/webhook/*}/manifest.json" && break; sleep 3; done
# The webhook registers a little after the frontend answers; cron retries anyway.
for _ in $(seq 1 20); do eval "${push}" 2>/dev/null && break; sleep 3; done
EOF
  echo "Pi health: posted from ${PI_HOST} every 10 minutes"
else
  "${PI_SSH[@]}" "{ crontab -l 2>/dev/null | grep -v 'pi-health/system_status.py' || true; } | crontab -"
fi
# The EchoMuse controller runs on the HA laptop; post its speaker's health from there.
if "${SSH[@]}" 'test -f ~/echomuse/data/echomuse.db'; then
  "${SSH[@]}" 'mkdir -p ~/echomuse-health && chmod 700 ~/echomuse-health'
  scp -q "${SSH_OPTS_BATCH[@]}" "${HERE}/echomuse_status.py" "${HA_TARGET}:echomuse-health/echomuse_status.py"
  printf 'http://127.0.0.1:8123/api/webhook/%s\n' "${echomuse_webhook}" | "${SSH[@]}" 'umask 077; cat > ~/echomuse-health/webhook-url'
  "${SSH[@]}" bash -s <<'EOF'
set -euo pipefail
push='python3 $HOME/echomuse-health/echomuse_status.py $HOME/echomuse/data/echomuse.db | curl -fsS -m 20 -H "Content-Type: application/json" --data-binary @- "$(cat $HOME/echomuse-health/webhook-url)" >/dev/null 2>>$HOME/echomuse-health/push.log'
{ crontab -l 2>/dev/null | grep -v 'echomuse-health/echomuse_status.py' || true; echo "*/10 * * * * ${push}"; } | crontab -
# HA answers 200 even before the webhook registers, so wait for the frontend
# and a little longer before the first reading; cron covers any miss.
for _ in $(seq 1 30); do curl -fs -m 5 -o /dev/null http://127.0.0.1:8123/manifest.json && break; sleep 3; done
sleep 20
eval "${push}" || true
EOF
  echo "EchoMuse health: posted from ${HA_HOST} every 10 minutes"
fi
echo "Local Map installed: http://${HA_HOST}:8123/local-map/conditions"
