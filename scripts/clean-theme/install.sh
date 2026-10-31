#!/usr/bin/env bash
# Install the Clean theme and make it the default light and dark theme.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "${HERE}/../config.sh"
SSH=(ssh "${SSH_OPTS_BATCH[@]}" "${HA_TARGET}")
"${SSH[@]}" 'docker exec homeassistant grep -q "themes: !include_dir_merge_named themes" /config/configuration.yaml' \
  || { echo "Enable 'frontend: themes: !include_dir_merge_named themes' first" >&2; exit 1; }
"${SSH[@]}" 'docker exec -i homeassistant sh -c "mkdir -p /config/themes/clean && cat > /config/themes/clean/clean.yaml"' < "${HERE}/clean.yaml"
"${SSH[@]}" 'docker exec homeassistant python -m homeassistant --script check_config -c /config'
# The default theme lives in .storage and is rewritten on shutdown, so edit it while HA is stopped.
"${SSH[@]}" 'docker stop -t 60 homeassistant >/dev/null && docker run --rm -v "$(docker inspect homeassistant --format "{{range .Mounts}}{{if eq .Destination \"/config\"}}{{.Source}}{{end}}{{end}}"):/config" --entrypoint python "$(docker inspect homeassistant --format "{{.Config.Image}}")" -c "
import json, pathlib, shutil, time
p = pathlib.Path(\"/config/.storage/frontend_theme\")
shutil.copy(p, f\"{p}.bak-{time.strftime(\"%Y%m%d%H%M%S\")}\")
d = json.loads(p.read_text())
d[\"data\"].update(frontend_default_theme=\"Clean\", frontend_default_dark_theme=\"Clean\")
p.write_text(json.dumps(d, indent=2))
" && docker start homeassistant >/dev/null'
echo "Clean is now the default. Devices set to Backend-selected pick it up after a refresh."
echo "Revert: Settings > Profile > Theme, or call frontend.set_theme with name: default."
