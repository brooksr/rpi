#!/usr/bin/env bash
# pi-info.sh — pull a read-only environment inventory from the Pi over SSH.
# No sudo required. Safe to run any time.
#
# Usage:  ./pi-info.sh
set -u
source "$(dirname "$0")/config.sh"

# Resolve a reachable host (mDNS name, then known IPs).
target=""
for host in "$PI_HOST" "$PI_IP_ETH" "$PI_IP_WIFI"; do
  [ -n "$host" ] && ping -c1 -W1 "$host" >/dev/null 2>&1 && { target="$host"; break; }
done
[ -z "$target" ] && { echo "Pi unreachable; try ./find-pi.sh" >&2; exit 1; }

ssh "${SSH_OPTS_BATCH[@]}" "${PI_USER}@${target}" 'bash -s' <<'REMOTE'
echo "========== IDENTITY / OS =========="
hostname
grep -E 'PRETTY|VERSION=' /etc/os-release
uname -a
echo
echo "========== HARDWARE =========="
grep -E 'Model' /proc/cpuinfo
echo "cores: $(nproc)  |  $(vcgencmd measure_temp 2>/dev/null)"
echo
echo "========== UPTIME / LOAD =========="
uptime
echo
echo "========== MEMORY =========="
free -h | head -2
echo
echo "========== DISK =========="
df -h / /boot* 2>/dev/null | grep -vE 'tmpfs'
echo
echo "========== NETWORK =========="
echo "IPs: $(hostname -I)"
for i in eth0 wlan0; do
  echo -n "  $i: "; cat /sys/class/net/$i/address 2>/dev/null | tr -d '\n'
  echo -n "  "; ip -4 addr show $i 2>/dev/null | grep -o 'inet [0-9.]*' || echo "(no IPv4)"
done
ip route | grep default
echo
echo "========== USERS =========="
grep -E 'sh$' /etc/passwd | cut -d: -f1,3,7
echo "sudo group: $(getent group sudo | cut -d: -f4)"
who
echo
echo "========== SERVICES / UPDATES =========="
echo "sshd:   $(systemctl is-active ssh 2>/dev/null)"
command -v pihole >/dev/null && echo "pihole: installed ($(pihole version 2>/dev/null | head -1))" || echo "pihole: not installed"
echo "pending apt upgrades: $(apt list --upgradable 2>/dev/null | grep -c upgradable)"
REMOTE
