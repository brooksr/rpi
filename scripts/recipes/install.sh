#!/usr/bin/env bash
# Install the copied recipe book. Existing files are backed up before changes.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "${HERE}/../config.sh"
python3 "${HERE}/build.py"
SSH=(ssh "${SSH_OPTS_BATCH[@]}" "${HA_TARGET}")
"${SSH[@]}" 'docker exec homeassistant test -d /config/packages'
restart=0
install_file() {
  local source_file="$1" destination="$2"
  if "${SSH[@]}" "docker exec -i homeassistant sh -c 'cmp -s - $destination'" < "$source_file"; then
    return
  fi
  "${SSH[@]}" "docker exec homeassistant sh -c 'mkdir -p /config/packages /config/dashboards /config/www/recipes; if test -f $destination; then cp $destination $destination.bak-\$(date +%Y%m%d%H%M%S); fi'"
  "${SSH[@]}" "docker exec -i homeassistant sh -c 'cat > $destination'" < "$source_file"
  if [ "$destination" = /config/packages/recipes.yaml ]; then restart=1; fi
}
# Transfer all photos over one SSH connection; back up only changed images.
"${SSH[@]}" 'docker exec homeassistant mkdir -p /config/www/recipes'
tar -C "${HERE}/images" -cf - . | "${SSH[@]}" "docker exec -i homeassistant python3 -c '
import datetime, pathlib, sys, tarfile
root = pathlib.Path(\"/config/www/recipes\")
stamp = datetime.datetime.now().strftime(\"%Y%m%d%H%M%S\")
archive = tarfile.open(fileobj=sys.stdin.buffer, mode=\"r|\")
for item in archive:
    if not item.isfile():
        continue
    name = pathlib.PurePosixPath(item.name).name
    if not name.endswith(\".jpg\"):
        raise ValueError(\"Unexpected image filename\")
    content = archive.extractfile(item).read()
    destination = root / name
    if destination.exists():
        if destination.read_bytes() == content:
            continue
        destination.with_name(name + \".bak-\" + stamp).write_bytes(destination.read_bytes())
    destination.write_bytes(content)
print(\"Recipe photos installed\")
'"
install_file "${HERE}/dashboard.yaml" /config/dashboards/recipes.yaml
install_file "${HERE}/recipes.json" /config/www/recipes/recipes.json
install_file "${HERE}/package.yaml" /config/packages/recipes.yaml
"${SSH[@]}" 'docker exec homeassistant python -m homeassistant --script check_config -c /config'
if [ "$restart" = 1 ]; then
  "${SSH[@]}" 'docker restart -t 60 homeassistant'
fi
echo "Recipes installed: http://${HA_HOST}:8123/family-recipes/index"
