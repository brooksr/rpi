#!/usr/bin/env bash
# connect.sh — open an interactive SSH session to the Pi.
# Falls back from the mDNS name to the known wired/Wi-Fi IPs if needed.
#
# Usage:  ./connect.sh                 # interactive shell
#         ./connect.sh "uptime; df -h" # run a one-off command and exit
set -u
source "$(dirname "$0")/config.sh"

# Pick the first reachable target: mDNS name, then eth0 IP, then wlan0 IP.
target=""
for host in "$PI_HOST" "$PI_IP_ETH" "$PI_IP_WIFI"; do
  [ -n "$host" ] && ping -c1 -W1 "$host" >/dev/null 2>&1 && { target="$host"; break; }
done

if [ -z "$target" ]; then
  echo "Could not reach the Pi at ${PI_HOST}, ${PI_IP_ETH}, or ${PI_IP_WIFI}." >&2
  echo "Run ./find-pi.sh to locate it." >&2
  exit 1
fi

echo "Connecting to ${PI_USER}@${target} ..." >&2
if [ "$#" -gt 0 ]; then
  exec ssh "${SSH_OPTS[@]}" "${PI_USER}@${target}" "$@"
else
  exec ssh "${SSH_OPTS[@]}" "${PI_USER}@${target}"
fi
