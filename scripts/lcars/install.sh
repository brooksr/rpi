#!/usr/bin/env bash
# Install pinned upstream LCARS + UIX releases; configure UI resources afterward.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
source "${HERE}/../config.sh"
SSH=(ssh "${SSH_OPTS_BATCH[@]}" "${HA_TARGET}")
STAGE="$(mktemp -d "${TMPDIR:-/tmp}/ha-lcars.XXXXXX")"
echo "Staging release files in ${STAGE}"
curl -fsSL https://api.github.com/repos/th3jesta/ha-lcars/tarball/HA-LCARS-4.1.3 -o "${STAGE}/lcars.tar.gz"
curl -fsSL https://api.github.com/repos/Lint-Free-Technology/uix/tarball/v8.4.0 -o "${STAGE}/uix.tar.gz"
mkdir -p "${STAGE}/lcars" "${STAGE}/uix" "${STAGE}/config/themes/lcars" "${STAGE}/config/www/community/lcars" "${STAGE}/config/custom_components" "${STAGE}/config/packages"
tar -xzf "${STAGE}/lcars.tar.gz" -C "${STAGE}/lcars" --strip-components=1
tar -xzf "${STAGE}/uix.tar.gz" -C "${STAGE}/uix" --strip-components=1
cp "${STAGE}/lcars/themes/lcars.yaml" "${STAGE}/config/themes/lcars/lcars.yaml"
cp "${STAGE}/lcars/lcars.js" "${STAGE}/config/www/community/lcars/lcars.js"
cp "${HERE}/font-loader.js" "${STAGE}/config/www/community/lcars/font-loader.js"
curl -fsSL https://fonts.gstatic.com/s/antonio/v22/gNMbW3NwSYq_9WD34ngK5F8vR8T0PVxx8RtI.ttf -o "${STAGE}/config/www/community/lcars/antonio-400.ttf"
curl -fsSL https://fonts.gstatic.com/s/antonio/v22/gNMbW3NwSYq_9WD34ngK5F8vR8T0PVyW9htI.ttf -o "${STAGE}/config/www/community/lcars/antonio-700.ttf"
cp -R "${STAGE}/uix/custom_components/uix" "${STAGE}/config/custom_components/"
cp "${HERE}/package.yaml" "${STAGE}/config/packages/lcars.yaml"
"${SSH[@]}" 'docker exec homeassistant python -c '\''from pathlib import Path; s=Path("/config/configuration.yaml").read_text(); assert "themes: !include_dir_merge_named themes" in s and "packages: !include_dir_named packages" in s, "Enable theme and package directory includes first"'\'''
# Only overwrite changed files, keeping a dated backup next to each original.
tar -C "${STAGE}/config" -cf - . | "${SSH[@]}" "docker exec -i homeassistant python -c '
import datetime, pathlib, sys, tarfile
root = pathlib.Path(\"/config\")
stamp = datetime.datetime.now().strftime(\"%Y%m%d%H%M%S\")
archive = tarfile.open(fileobj=sys.stdin.buffer, mode=\"r|\")
for item in archive:
    if not item.isfile():
        continue
    name = pathlib.PurePosixPath(item.name)
    if name.is_absolute() or \"..\" in name.parts:
        raise ValueError(\"Unsafe archive path\")
    destination = root / name
    content = archive.extractfile(item).read()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.read_bytes() == content:
            continue
        destination.with_name(destination.name + \".bak-\" + stamp).write_bytes(destination.read_bytes())
    destination.write_bytes(content)
    print(\"Installed\", name)
'"
"${SSH[@]}" 'docker exec homeassistant python -m homeassistant --script check_config -c /config'
"${SSH[@]}" 'docker restart -t 60 homeassistant'
echo "After startup, add UI eXtension in Settings > Devices & services."
echo "Add dashboard resources: /local/community/lcars/lcars.js (JavaScript module)"
echo "Antonio fonts load globally from local files through the LCARS package."
echo "Then refresh the browser and select LCARS TNG in your profile, or use Backend-selected."
