#!/usr/bin/env bash
# Runs the GNOME desktop only while the lid is open. Closing the lid for
# GRACE seconds stops gdm (ending the desktop session and its apps); opening it
# starts gdm again, which auto-logs in. HA, cameras and other services don't
# use the desktop and keep running either way.
set -uo pipefail
GRACE="${GRACE:-120}"
lid="$(ls /proc/acpi/button/lid/*/state | head -1)"
closed_since=""

# An external display means the laptop is being used docked; keep the desktop.
external_display() {
  local s
  for s in /sys/class/drm/card*-*/status; do
    case "$s" in *eDP*|*LVDS*) continue ;; esac
    [ "$(cat "$s" 2>/dev/null)" = connected ] && return 0
  done
  return 1
}

while :; do
  if grep -q open "$lid"; then
    closed_since=""
    if ! systemctl is-active -q gdm; then
      echo "lid open: starting desktop"
      systemctl start gdm
    fi
  else
    closed_since="${closed_since:-$(date +%s)}"
    if (( $(date +%s) - closed_since >= GRACE )) && systemctl is-active -q gdm && ! external_display; then
      echo "lid closed ${GRACE}s: stopping desktop"
      systemctl stop gdm
    fi
  fi
  sleep 5
done
