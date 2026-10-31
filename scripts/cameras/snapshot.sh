#!/usr/bin/env bash
# Saves an office window frame each minute: latest.jpg gives the Overview card an
# instant first paint, and the dated copy feeds the nightly timelapse.
set -euo pipefail
media="${HOME}/homeassistant/media/office-camera"
frames="${HOME}/office-camera/frames/$(date +%F)"
mkdir -p "${media}" "${frames}"
tmp="$(mktemp "${media}/.latest.XXXXXX")"
trap 'rm -f "${tmp}"' EXIT
# The capture instance serves the camera's own JPEG, so no transcode is needed.
curl -fsS -m 20 -o "${tmp}" "http://127.0.0.1:1985/api/frame.jpeg?src=office_window"
# A freshly opened camera can hand back a junk first frame; keep only real JPEGs.
[ "$(head -c 2 "${tmp}" | od -An -tx1 | tr -d " ")" = "ffd8" ]
chmod 644 "${tmp}"
cp "${tmp}" "${frames}/$(date +%H%M).jpg"
mv "${tmp}" "${media}/latest.jpg"
