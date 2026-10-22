#!/usr/bin/env bash
# find-pi.sh — locate the Raspberry Pi on the LAN.
# Tries mDNS first, then an ARP sweep of the subnet filtered to Pi MAC prefixes.
#
# Usage:  ./find-pi.sh            # scan default subnet from config.sh
#         LAN_SUBNET=10.0.0 ./find-pi.sh
set -u
source "$(dirname "$0")/config.sh"

echo "== 1) mDNS lookup (${PI_HOST}) =="
if ping -c1 -W1 "$PI_HOST" >/dev/null 2>&1; then
  ip=$(ping -c1 "$PI_HOST" 2>/dev/null | sed -n 's/.*(\([0-9.]*\)).*/\1/p' | head -1)
  echo "   FOUND via mDNS -> ${ip:-$PI_HOST}"
else
  echo "   not resolvable (Pi may be off, booting, or mDNS disabled)"
fi

echo
echo "== 2) ARP sweep of ${LAN_SUBNET}.0/24 =="
echo "   pinging all hosts to populate the ARP table..."
for i in $(seq 1 254); do ping -c1 -W1 "${LAN_SUBNET}.${i}" >/dev/null 2>&1 & done
wait

# Raspberry Pi Foundation OUI prefixes (all Pi models to date).
PI_OUIS='b8:27:eb|dc:a6:32|e4:5f:01|2c:cf:67|28:cd:c1|d8:3a:dd|88:a2:9e'
echo "   Raspberry Pi candidates in the ARP table:"
if arp -an | grep -iE "$PI_OUIS"; then
  :
else
  echo "   (none matched a Pi OUI — dumping full table for a manual look)"
  arp -an
fi
