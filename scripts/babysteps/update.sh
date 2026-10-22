#!/usr/bin/env bash
# update.sh — install the newest BabySteps build CI has published.
#
# RUNS ON THE PI, as the normal user (no sudo). install.sh puts it in cron every
# 5 minutes. CI (babysteps .github/workflows/deploy.yml, job "pi") uploads each
# build of main to the rolling GitHub release "pi-latest";
# ~/babysteps/release-tag can point this Pi at another. This checks the asset's
# id and, when it changed, unpacks it next to the old one and swaps the
# `current` symlink — so nginx never serves a half-extracted site.
#
# The release can also carry token-broker.mjs (one-time Google sign-in) and
# events-api.mjs (POST /api/events, for voice assistants). When either asset
# changes it is copied to ~/babysteps/broker/ or ~/babysteps/events/ and its
# container ("babysteps-broker" / "babysteps-events") restarted onto it.
set -euo pipefail

REPO="${BABYSTEPS_REPO:-brooksr/baby-steps}"
ROOT="${BABYSTEPS_ROOT:-$HOME/babysteps}"
WWW="${ROOT}/www"
TAG="${BABYSTEPS_TAG:-$(cat "${ROOT}/release-tag" 2>/dev/null || echo pi-latest)}"
ASSET_NAME="babysteps-pi.tar.gz"
BROKER_ASSET="token-broker.mjs"
EVENTS_ASSET="events-api.mjs"
KEEP=3

mkdir -p "${WWW}/releases"
exec 9>"${ROOT}/.update.lock"
flock -n 9 || exit 0   # a previous run is still going

release="$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/tags/${TAG}")"
id="$(jq -r --arg n "${ASSET_NAME}" '.assets[] | select(.name == $n) | .id' <<<"${release}")"
url="$(jq -r --arg n "${ASSET_NAME}" '.assets[] | select(.name == $n) | .browser_download_url' <<<"${release}")"

if [ -z "${id}" ]; then
  echo "$(date -Is) no ${ASSET_NAME} on ${TAG} yet" >&2
  exit 1
fi

# The two server scripts, independently of the site and of each other: any of
# the three can change alone. Each is copied into its own directory and its
# container restarted onto it.
install_script() {
  local asset="$1" dir="$2" container="$3" marker="$4"
  local asset_id asset_url tmp
  asset_id="$(jq -r --arg n "${asset}" '.assets[] | select(.name == $n) | .id' <<<"${release}")"
  asset_url="$(jq -r --arg n "${asset}" '.assets[] | select(.name == $n) | .browser_download_url' <<<"${release}")"

  if [ -z "${asset_id}" ] || [ "${asset_id}" = "$(cat "${ROOT}/${marker}" 2>/dev/null)" ]; then
    return 0
  fi

  mkdir -p "${ROOT}/${dir}"
  tmp="$(mktemp "${ROOT}/${dir}/.incoming.XXXXXX")"
  if curl -fsSL "${asset_url}" -o "${tmp}" && [ -s "${tmp}" ]; then
    chmod 644 "${tmp}"
    mv "${tmp}" "${ROOT}/${dir}/${asset}"
    echo "${asset_id}" >"${ROOT}/${marker}"
    if docker restart "${container}" >/dev/null 2>&1; then
      echo "$(date -Is) installed ${asset} ${asset_id}, restarted ${container}"
    else
      echo "$(date -Is) installed ${asset} ${asset_id} (container not running yet — see install.sh)"
    fi
  else
    rm -f "${tmp}"
    echo "$(date -Is) could not download ${asset}" >&2
  fi
}

install_script "${BROKER_ASSET}" broker babysteps-broker installed-broker
install_script "${EVENTS_ASSET}" events babysteps-events installed-events

if [ "${id}" = "$(cat "${ROOT}/installed-asset" 2>/dev/null)" ] && [ -e "${WWW}/current" ]; then
  exit 0
fi

incoming="$(mktemp -d "${WWW}/releases/.incoming.XXXXXX")"
trap 'rm -rf "${incoming}"' EXIT
curl -fsSL "${url}" | tar -xz -C "${incoming}"
test -f "${incoming}/index.html"
chmod 755 "${incoming}"

rm -rf "${WWW}/releases/${id}"
mv "${incoming}" "${WWW}/releases/${id}"
ln -sfn "releases/${id}" "${WWW}/current.new"
mv -T "${WWW}/current.new" "${WWW}/current"
echo "${id}" >"${ROOT}/installed-asset"

# Prune all but the newest few builds (never the one just installed).
ls -1t "${WWW}/releases" | { grep -vx "${id}" || true; } | tail -n +"${KEEP}" \
  | while read -r old; do rm -rf "${WWW}/releases/${old}"; done

echo "$(date -Is) installed asset ${id} ($(jq -r .sha "${WWW}/current/version.json" 2>/dev/null | cut -c1-7))"
