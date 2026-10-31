#!/usr/bin/env bash
# config.sh — shared settings for the Raspberry Pi helper scripts.
# Source this from the other scripts:  source "$(dirname "$0")/config.sh"
#
# Override any value without editing this file, e.g.:
#   PI_HOST=192.168.1.50 ./pi-info.sh
#
# Personal values (user, addresses, home location, ...) come from the repo's
# gitignored .env; copy .env.example to .env and fill it in.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -f "${REPO_ROOT}/.env" ]; then
  set -a
  # shellcheck source=/dev/null
  source "${REPO_ROOT}/.env"
  set +a
fi

# ---- Connection -------------------------------------------------------------
# Prefer the mDNS name; it follows the Pi even if DHCP hands it a new address.
# Pin the IP with a router DHCP reservation (see README) to make these stable.
PI_USER="${PI_USER:-pi}"
PI_HOST="${PI_HOST:-raspberrypi.local}"

# Known addresses (set in .env) — handy as fallbacks.
PI_IP_ETH="${PI_IP_ETH:-}"     # eth0  (wired, preferred for Pi-hole)
PI_IP_WIFI="${PI_IP_WIFI:-}"   # wlan0 (Wi-Fi, backup)

# ---- Network facts ----------------------------------------------------------
LAN_SUBNET="${LAN_SUBNET:-192.168.1}"        # first three octets of the /24
GATEWAY="${GATEWAY:-192.168.1.1}"            # router
PI_MAC_ETH="${PI_MAC_ETH:-}"                 # eth0  — use THIS for DHCP reservation
PI_MAC_WIFI="${PI_MAC_WIFI:-}"               # wlan0

# ---- SSH options ------------------------------------------------------------
# The current OS (Raspberry Pi OS / Debian 13 Trixie, OpenSSH 10) needs no
# legacy crypto flags. accept-new trusts the host key on first connect only.
SSH_OPTS=(-o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new)

# BatchMode fails fast (never hangs on a password prompt) — use for scripted,
# non-interactive commands where key auth is expected to work.
SSH_OPTS_BATCH=("${SSH_OPTS[@]}" -o BatchMode=yes)

# Convenience: the user@host target, honoring overrides.
PI_TARGET="${PI_USER}@${PI_HOST}"

# ---- Home Assistant host ----------------------------------------------------
# HA can run on its own server while Pi-hole and BabySteps stay on the Pi. The
# HA installers (local-map, lcars, recipes, BabySteps' HA step) target this;
# unset, it is the Pi.
HA_USER="${HA_USER:-$PI_USER}"
HA_HOST="${HA_HOST:-$PI_HOST}"
HA_TARGET="${HA_USER}@${HA_HOST}"
