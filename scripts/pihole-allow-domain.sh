#!/usr/bin/env bash
# pihole-allow-domain.sh — allowlist a domain and all its subdomains in Pi-hole.
#
# Work and ad-tech domains often land on Pi-hole blocklists. This allows the
# apex domain AND every subdomain via a regex allow (the most version-stable
# mechanism), plus an explicit apex allow.
#
# RUN THIS ON THE PI, WITH SUDO. Two ways:
#   On the Pi:     sudo ./pihole-allow-domain.sh example.com
#   From the Mac:  ssh pi@raspberrypi.local 'sudo bash -s example.com' < pihole-allow-domain.sh
#                  (you'll be prompted for the sudo password)
set -u

DOMAIN="${1:?usage: pihole-allow-domain.sh <domain>}"
# Matches the domain and anything.domain, anchored so it can't match
# e.g. notexample.com or example.com.evil.example.
REGEX="(\\.|^)${DOMAIN//./\\.}\$"

if ! command -v pihole >/dev/null 2>&1; then
  echo "ERROR: pihole not found. Install Pi-hole first (see README)." >&2
  exit 1
fi
if [ "$(id -u)" -ne 0 ]; then
  echo "ERROR: run with sudo (Pi-hole changes need root)." >&2
  exit 1
fi

echo "== Allowing apex domain: ${DOMAIN} =="
pihole allow "${DOMAIN}" 2>/dev/null || pihole -w "${DOMAIN}"

echo "== Allowing all subdomains via regex: ${REGEX} =="
# Pi-hole renamed this between versions; try the known forms, stop on success.
if   pihole --white-regex "${REGEX}" 2>/dev/null; then echo "   (added via --white-regex)"
elif pihole allow-regex   "${REGEX}" 2>/dev/null; then echo "   (added via allow-regex)"
elif pihole --white-wild  "${DOMAIN}" 2>/dev/null; then echo "   (added via --white-wild)"
else
  echo "   Could not add the regex automatically. Add it in the web UI:" >&2
  echo "   Domains -> Add to allowlist (regex):  ${REGEX}" >&2
  exit 1
fi

echo
echo "== Current allowlist =="
pihole allow --list 2>/dev/null || pihole -w --list 2>/dev/null || true
echo
echo "Done. Verify from the Mac with:  ./verify-pihole.sh"
