#!/usr/bin/env bash
# verify-pihole.sh — confirm Pi-hole is blocking ads AND allowing ALLOW_DOMAIN (from .env, if set).
# Runs from the Mac; queries the Pi's DNS directly (no sudo, read-only).
#
# Usage:  ./verify-pihole.sh
set -u
source "$(dirname "$0")/config.sh"

# Query the wired IP by default (that's where Pi-hole should live).
DNS="${PI_DNS:-$PI_IP_ETH}"

# A "blocked" answer from Pi-hole is 0.0.0.0 (or NXDOMAIN / empty).
check() {  # $1=label  $2=domain  $3=expect(block|allow)
  local ans
  ans=$(dig +short "@${DNS}" "$2" A 2>/dev/null | head -1)
  local shown="${ans:-<no answer>}"
  if [ "$3" = "block" ]; then
    if [ -z "$ans" ] || [ "$ans" = "0.0.0.0" ]; then
      echo "  ✅ BLOCKED  $2  -> ${shown}"
    else
      echo "  ⚠️  NOT blocked  $2  -> ${shown}"
    fi
  else
    if [ -n "$ans" ] && [ "$ans" != "0.0.0.0" ]; then
      echo "  ✅ ALLOWED  $2  -> ${shown}"
    else
      echo "  ⚠️  BLOCKED (should be allowed!)  $2  -> ${shown}"
    fi
  fi
}

echo "Querying Pi-hole DNS at ${DNS}"
if ! dig +short "@${DNS}" pi.hole >/dev/null 2>&1; then
  echo "  (heads up: ${DNS} isn't answering DNS — is Pi-hole installed and running?)"
fi

echo
echo "== Should be BLOCKED (known ad/tracker hosts) =="
check block "doubleclick.net"            block
check block "www.googleadservices.com"   block
check block "ads.yahoo.com"              block

echo
echo "== Should be ALLOWED (your work domain) =="
if [ -n "${ALLOW_DOMAIN:-}" ]; then
  check allow "${ALLOW_DOMAIN}"      allow
  check allow "www.${ALLOW_DOMAIN}"  allow
fi
# NOTE: only test subdomains that actually exist on public DNS, or you'll get a
# false "blocked" (NXDOMAIN looks the same). Compare against 1.1.1.1 if unsure.

echo
echo "If blocks fail, the client isn't using Pi-hole for DNS yet —"
echo "point the router's DNS at ${PI_IP_ETH} (see README), or test this Mac with:"
echo "  networksetup -setdnsservers Wi-Fi ${PI_IP_ETH}"
echo "  (undo with: networksetup -setdnsservers Wi-Fi empty)"
