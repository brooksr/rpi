#!/usr/bin/env bash
# Re-runnable local-map installation. Backups stay outside HA's public www path.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "${HERE}/../config.sh"
SSH=(ssh "${SSH_OPTS_BATCH[@]}" "${PI_TARGET}")
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
echo "Local Map installed: http://${PI_HOST}:8123/local-map/conditions"
