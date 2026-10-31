#!/usr/bin/env bash
# install.sh — host BabySteps on the Pi and add it to Home Assistant's sidebar.
#
# RUN FROM THE MAC (no sudo needed — the Pi user is in the docker group):
#   ./scripts/babysteps/install.sh
#
# Follow a different CI release than main's pi-latest:
#   BABYSTEPS_TAG=<tag> ./scripts/babysteps/install.sh
#
# What it sets up on the Pi:
#   ~/babysteps/update.sh        pulls CI's newest build (cron, every 5 min)
#   ~/babysteps/release-tag      which release it follows (pi-latest when absent)
#   ~/babysteps/www/current      the live build (symlink swapped by update.sh)
#   docker network "babysteps"   so nginx reaches the broker by name
#   docker "babysteps"           nginx:alpine serving it on port 8080, /api/ → broker
#   docker "babysteps-broker"    node:24-alpine running ~/babysteps/broker/token-broker.mjs
#                                (one-time Google sign-in). Needs the OAuth client
#                                secret in ~/babysteps/broker.env (chmod 600, never in
#                                a build); skipped until that file has one.
#   docker "babysteps-events"    node:24-alpine running ~/babysteps/events/events-api.mjs
#                                (POST /api/events, for voice assistants). Needs
#                                BABYSTEPS_SHEET_ID in ~/babysteps/events.env and a
#                                service account key at ~/babysteps/service-account.json;
#                                skipped until both exist. Its EVENTS_API_TOKEN is
#                                generated here, once.
#   /config/packages/babysteps.yaml, /config/custom_sentences/en/babysteps.yaml
#   /config/dashboards/babysteps_voice.yaml and `babysteps_events_auth` in
#   secrets.yaml                 voice logging through Assist, and the
#                                "BabySteps" sidebar dashboard (tiles + phrase guide)
#   /config/packages/google_assistant.yaml
#                                Google Home ("run BabySteps wet"); only once
#                                secrets.yaml has google_assistant_project_id
#                                (one-time setup in README)
#
# Re-runnable: everything is replaced in place; HA restarts only when its
# configuration actually changed.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
source "${HERE}/../config.sh"
SSH=(ssh "${SSH_OPTS_BATCH[@]}" "${PI_TARGET}")
HA_SSH=(ssh "${SSH_OPTS_BATCH[@]}" "${HA_TARGET}")

# Since the cutover the Pi runs BabySteps' internal backend, deployed from the
# baby-steps repo (deployment/internal/deploy-pi.sh). Steps 1-5 would put back
# the legacy nginx.conf, the update.sh cron (which swaps the site back to the
# legacy build) and the Sheets writers, so only the Home Assistant step runs.
if "${SSH[@]}" 'test -e ~/babysteps/internal/cutover-complete'; then
  echo "== 1-5/6 skipped: the Pi has cut over to the internal backend (deploy it from the baby-steps repo) =="
  legacy=0
else
  legacy=1
fi

if [ "${legacy}" = 1 ]; then
echo "== 1/6 Copying files to the Pi =="
"${SSH[@]}" 'mkdir -p ~/babysteps/www/releases ~/babysteps/broker ~/babysteps/events'
if [ -n "${BABYSTEPS_TAG:-}" ]; then
  "${SSH[@]}" "echo '${BABYSTEPS_TAG}' > ~/babysteps/release-tag"
fi
scp -q "${SSH_OPTS_BATCH[@]}" "${HERE}/update.sh" "${HERE}/nginx.conf" "${PI_TARGET}:babysteps/"

echo "== 2/6 Installing the newest CI build + cron job =="
"${SSH[@]}" bash -s <<'EOF'
set -euo pipefail
chmod 755 ~/babysteps/update.sh ~/babysteps ~/babysteps/www ~/babysteps/www/releases
~/babysteps/update.sh
line='*/5 * * * * $HOME/babysteps/update.sh >> $HOME/babysteps/update.log 2>&1'
{ crontab -l 2>/dev/null | grep -v 'babysteps/update.sh' || true; echo "$line"; } | crontab -
EOF

echo "== 3/6 (Re)creating the nginx container on port 8080 =="
"${SSH[@]}" bash -s <<'EOF'
set -euo pipefail
docker network inspect babysteps >/dev/null 2>&1 || docker network create babysteps >/dev/null
docker rm -f babysteps >/dev/null 2>&1 || true
docker run -d --name babysteps --restart=unless-stopped \
  --network babysteps \
  -p 8080:80 \
  -v "$HOME/babysteps/www:/srv:ro" \
  -v "$HOME/babysteps/nginx.conf:/etc/nginx/conf.d/default.conf:ro" \
  nginx:alpine >/dev/null
EOF

echo "== 4/6 (Re)creating the token broker container =="
"${SSH[@]}" "TAILNET_HOST=${TAILNET_HOST:?set TAILNET_HOST in .env} bash -s" <<'EOF'
set -euo pipefail
envfile="$HOME/babysteps/broker.env"
if [ ! -f "$envfile" ]; then
  (umask 077; cat >"$envfile" <<ENV
# BabySteps token broker. The secret is the OAuth web client's, from Google
# Cloud Console → Credentials. Keep this file chmod 600; it never leaves the Pi.
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
ALLOWED_ORIGINS=https://${TAILNET_HOST}:8443
ENV
  )
fi
chmod 600 "$envfile"
docker rm -f babysteps-broker >/dev/null 2>&1 || true
if ! grep -Eq '^GOOGLE_CLIENT_ID=.+' "$envfile" || ! grep -Eq '^GOOGLE_CLIENT_SECRET=.+' "$envfile"; then
  echo "   skipped: fill in GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in ~/babysteps/broker.env, then re-run"
  echo "   (until then the app signs in the old hourly way)"
elif [ ! -f "$HOME/babysteps/broker/token-broker.mjs" ]; then
  echo "   skipped: this release carries no token-broker.mjs"
else
  docker run -d --name babysteps-broker --restart=unless-stopped \
    --network babysteps \
    --env-file "$envfile" \
    -v "$HOME/babysteps/broker:/app:ro" \
    node:24-alpine node /app/token-broker.mjs >/dev/null
  sleep 3
  docker logs babysteps-broker 2>&1 | tail -n 2 | sed 's/^/   /'
fi
EOF

echo "== 5/6 (Re)creating the events API container =="
"${SSH[@]}" bash -s <<'EOF'
set -euo pipefail
envfile="$HOME/babysteps/events.env"
keyfile="$HOME/babysteps/service-account.json"
if [ ! -f "$envfile" ]; then
  # Generated once and kept: Home Assistant's copy has to match it.
  token="$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
  (umask 077; cat >"$envfile" <<ENV
# BabySteps events API (POST /api/events). The sheet id is the family's
# spreadsheet id (Settings → Storage in the app). Callers send
# "Authorization: Bearer <EVENTS_API_TOKEN>"; Home Assistant's copy is in its
# secrets.yaml. Keep this file chmod 600; it never leaves the Pi.
BABYSTEPS_SHEET_ID=
EVENTS_API_TOKEN=${token}
GOOGLE_SERVICE_ACCOUNT_FILE=/secrets/service-account.json
ENV
  )
fi
# The nursery phone's own token (POST /api/nursery), added to env files that
# predate it. Separate from EVENTS_API_TOKEN so the phone can only write the
# Nursery tabs. Read it on the Pi to enter it in the phone's Settings.
if ! grep -q '^NURSERY_API_TOKEN=' "$envfile"; then
  printf 'NURSERY_API_TOKEN=%s\n' "$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')" >>"$envfile"
fi
# The Android app's own token (/api/events/app). It reads and edits the whole
# tracker, so it is separate from the events token voice assistants hold. Read
# it on the Pi to enter it in the app's Settings.
if ! grep -q '^APP_API_TOKEN=' "$envfile"; then
  printf 'APP_API_TOKEN=%s\n' "$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')" >>"$envfile"
fi
chmod 600 "$envfile"
if [ -f "$keyfile" ]; then chmod 600 "$keyfile"; fi
docker rm -f babysteps-events >/dev/null 2>&1 || true
if ! grep -Eq '^BABYSTEPS_SHEET_ID=.+' "$envfile"; then
  echo "   skipped: fill in BABYSTEPS_SHEET_ID in ~/babysteps/events.env, then re-run"
elif [ ! -s "$keyfile" ]; then
  echo "   skipped: copy the service account's JSON key to ~/babysteps/service-account.json"
  echo "   (and share the family sheet with its client_email as an editor), then re-run"
elif [ ! -f "$HOME/babysteps/events/events-api.mjs" ]; then
  echo "   skipped: this release carries no events-api.mjs yet"
else
  docker run -d --name babysteps-events --restart=unless-stopped \
    --network babysteps \
    --env-file "$envfile" \
    -v "$HOME/babysteps/events:/app:ro" \
    -v "$keyfile:/secrets/service-account.json:ro" \
    node:24-alpine node /app/events-api.mjs >/dev/null
  sleep 3
  docker logs babysteps-events 2>&1 | tail -n 2 | sed 's/^/   /'
fi
EOF
fi

echo "== 6/6 Adding the BabySteps dashboard and voice logging to Home Assistant (${HA_HOST}) =="
"${HA_SSH[@]}" 'mkdir -p ~/babysteps/ha'
scp -q "${SSH_OPTS_BATCH[@]}" "${HERE}/ha/babysteps.yaml" "${HERE}/ha/custom_sentences_en.yaml" "${HERE}/ha/google_assistant.yaml" "${HERE}/ha/babysteps_voice_dashboard.yaml" "${HA_TARGET}:babysteps/ha/"
# The events token lives on the Pi; HA may be on another host, so it travels
# in on stdin rather than on a command line.
token="$("${SSH[@]}" "sed -n 's/^EVENTS_API_TOKEN=//p' ~/babysteps/events.env 2>/dev/null || true")"
{ printf 'token=%q\n' "${token}"; cat <<'EOF'; } | "${HA_SSH[@]}" bash -s
set -euo pipefail
# configuration.yaml belongs to root (HA wrote it), so edit it from inside the
# container rather than asking for sudo. HA restarts once at the end, and only
# if something here changed.
cfg=/config/configuration.yaml
changed=0
backup() { docker exec homeassistant cp "$1" "$1.bak-$(date +%Y%m%d%H%M%S)"; }

# The sidebar used to be an iframe of the app (panel_custom). It had to sign in
# to Google again on every open, so it is gone: the BabySteps dashboard took its
# place and its URL. Take the old block out of an install that still has it.
if docker exec homeassistant grep -q 'babysteps-panel' "$cfg"; then
  backup "$cfg"
  docker exec -i homeassistant python3 - <<'PY'
p = '/config/configuration.yaml'
lines = open(p).read().split('\n')
start = next(i for i, line in enumerate(lines) if line.startswith('# BabySteps (served by'))
end = next(i for i, line in enumerate(lines) if i > start and line.strip().startswith('url: https://raspberrypi'))
del lines[start:end + 1]
open(p, 'w').write('\n'.join(lines).replace('\n\n\n', '\n\n'))
PY
  docker exec homeassistant rm -f /config/www/babysteps-panel.js
  echo "   removed the old iframe panel"
  changed=1
fi

# Voice logging lives in a package so it never collides with a top-level key
# (rest_command:, script:) the configuration already has. Packages need one
# line under `homeassistant:` — appended when there is no such block, and left
# to a person when there is one, since editing YAML in place is how it breaks.
if docker exec homeassistant grep -Eq '^[[:space:]]+packages:' "$cfg"; then
  :
elif docker exec homeassistant grep -Eq '^homeassistant:' "$cfg"; then
  echo "   ACTION NEEDED: add this under the existing homeassistant: block in"
  echo "   configuration.yaml, then re-run:   packages: !include_dir_named packages"
else
  backup "$cfg"
  docker exec -i homeassistant sh -c "cat >> $cfg" <<'YAML'

# Packages: one file per feature in /config/packages (BabySteps voice logging).
homeassistant:
  packages: !include_dir_named packages
YAML
  changed=1
fi

install_ha_file() {
  if docker exec -i homeassistant sh -c "cmp -s - '$2'" <"$1"; then
    return 0
  fi
  docker exec homeassistant mkdir -p "$(dirname "$2")"
  docker exec -i homeassistant sh -c "cat > '$2'" <"$1"
  echo "   installed $2"
  changed=1
}
install_ha_file "$HOME/babysteps/ha/babysteps.yaml" /config/packages/babysteps.yaml
install_ha_file "$HOME/babysteps/ha/custom_sentences_en.yaml" /config/custom_sentences/en/babysteps.yaml
install_ha_file "$HOME/babysteps/ha/babysteps_voice_dashboard.yaml" /config/dashboards/babysteps_voice.yaml

# Google Home needs a Developer Console project first (README); until its id is
# in secrets.yaml the package would fail HA's config check, so it waits.
if docker exec homeassistant grep -q '^google_assistant_project_id:' /config/secrets.yaml 2>/dev/null; then
  install_ha_file "$HOME/babysteps/ha/google_assistant.yaml" /config/packages/google_assistant.yaml
else
  echo "   Google Home: skipped until secrets.yaml has google_assistant_project_id (see README)"
fi

# The token HA sends comes from the events API's own env file on the Pi (read
# above), so there is one source of truth and a re-run can never leave the two
# disagreeing.
secrets=/config/secrets.yaml
line="babysteps_events_auth: \"Bearer ${token}\""
if [ -z "$token" ]; then
  echo "   no EVENTS_API_TOKEN yet; voice logging will be refused until install.sh runs again"
elif ! docker exec homeassistant grep -qxF "$line" "$secrets" 2>/dev/null; then
  docker exec homeassistant touch "$secrets"
  backup "$secrets"
  docker exec homeassistant sh -c "grep -v '^babysteps_events_auth:' $secrets > $secrets.tmp; mv $secrets.tmp $secrets"
  printf '%s\n' "$line" | docker exec -i homeassistant sh -c "cat >> $secrets"
  echo "   wrote babysteps_events_auth to secrets.yaml"
  changed=1
fi

# HA's own checker first: a restart onto a broken configuration takes whole
# integrations down with it. Silence past its banner means the config is good.
if [ "$changed" = 1 ]; then
  problems="$(docker exec homeassistant python -m homeassistant --script check_config -c /config 2>&1 \
    | sed 's/\x1b\[[0-9;]*m//g' | grep -vE '^[[:space:]]*$|^Testing configuration' || true)"
  if [ -n "$problems" ]; then
    echo "   NOT restarting Home Assistant: its config check failed"
    printf '%s\n' "$problems" | sed 's/^/     /'
    exit 1
  fi
  echo "   restarting Home Assistant (a few minutes on a Pi 3)"
  docker restart -t 60 homeassistant >/dev/null
else
  echo "   Home Assistant already up to date"
fi
EOF

echo
echo "✅ BabySteps: http://${PI_HOST}:8080/   ·   in Home Assistant: http://${HA_HOST}:8123/baby-steps"
echo "   Update log on the Pi: ~/babysteps/update.log"
echo "   Events API: curl https://${TAILNET_HOST}:8443/api/events/health"
echo "   Nursery phone: https://${TAILNET_HOST}:8443/api/nursery with NURSERY_API_TOKEN from ~/babysteps/events.env"
echo "   Android app: https://${TAILNET_HOST}:8443/api/events/app with APP_API_TOKEN from ~/babysteps/events.env"
