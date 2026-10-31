# Notes for agents working in this repo

README.md describes what runs where; each `scripts/*/README.md` covers its
component. This file is how to change things safely.

## Hosts and access

- `scripts/config.sh` loads `.env` and defines `PI_TARGET`, `HA_TARGET`,
  `SSH_OPTS_BATCH`, and so on. Source it from **bash**; zsh gets the wrong values.
- Pi: `PI_USER@raspberrypi.local`, key auth, passwordless sudo. Pi-hole is a
  native install, not a container.
- HA laptop: `HA_USER@HA_HOST`, key auth, passwordless sudo. HA's config is
  `~/homeassistant` on the host and `/config` in the `homeassistant` container.
- There is no HA API token in the repo or on the hosts. You can't reload YAML or
  call services yourself: ask the user to reload (Developer Tools → YAML) or
  restart the container, and say which.
- Interactive passwords (`ssh-copy-id`, the Pi-hole installer) need a real
  terminal. Ask the user to run them with `! <command>`.
- After a reimage the host key changes: `ssh-keygen -R <host>` for its name and IPs.

## Deploying to Home Assistant

- Prefer the component's `install.sh`. Each one renders `@@NAME@@` placeholders
  with `scripts/render_env.py`, which reads the **environment**, so it only works
  after `config.sh` has been sourced. Running it alone reports every placeholder
  as missing.
- Copying a single file by hand: render it first, and never deploy a file that
  still contains `@@`. `packages/`, `dashboards/` and `www/` on the laptop are
  root-owned, so write with `sudo tee` or `docker exec -i homeassistant sh -c 'cat > …'`.
  Keep a `*.before-<change>-<timestamp>` copy next to anything you replace.
- Diff the deployed file against the repo before overwriting; the live copy has
  been edited in place before.
- Always run the config check before a reload or restart:
  `docker exec homeassistant python -m homeassistant --script check_config -c /config`.
- Card JS is cached hard by browsers and phones: bump the `?v=` on its module URL
  (e.g. in `scripts/local-map/package.yaml`) with every change. The new URL takes
  effect when HA restarts.
- HA keeps its `http:` settings (trusted proxies, X-Forwarded-For) in
  `.storage/http`; a YAML `http:` block is ignored. Edit it with HA stopped. The
  default theme lives in `.storage/frontend_theme`, likewise.
- `configuration.yaml` is root-owned; edit it with sudo and keep a `.bak-*`.

## Known traps

- **Panel views no longer set a card's height** (HA 2026.10). A full-page card
  must size itself (`height: calc(100dvh - var(--header-height))`), or inner
  scroll areas never scroll.
- **HA's go2rtc client (0.4.0)** rejects streams whose producer has no URL, so
  cameras use two go2rtc instances: one owns the devices, one re-streams over
  RTSP for HA. See `scripts/cameras/README.md`.
- **`input_text` / `input_number` helpers** start as `unknown` (text) or their
  `min` (number) until someone sets them. Templates must treat those as unset;
  a bare `states(...)` once made Music Assistant search for the word "unknown".
- **Music Assistant announcements** set an absolute `announce_volume` and may
  leave the player at the announcement level afterwards. Set the volume
  explicitly before playing music.
- **BabySteps refresh tokens rotate**; reusing one revokes HA's device. Only
  `local-babysteps-today.py` should touch `/config/.babysteps-native.json`.
- **Laptop SD slot:** never use it; a card there froze the machine three times.
- **Laptop desktop:** `lid-desktop.service` kills the desktop session two minutes
  after the lid closes. Run long jobs over SSH, not in a desktop terminal.
- The Pi's Funnel :10000 forwards to the laptop's LAN IP. If the laptop's DHCP
  address changes, Google Home and the phone app break.

## Privacy

The user wants baby, location and phone data kept local. The home observer's
cloud digest is the agreed exception (shopping list and baby data, logged in
`~/home-agent/cloud-log`). Don't add new cloud calls with personal data, and
keep coordinates out of public `www/` files.

## Tests

The Mac's default `python3` is 3.8, which is too old; use `python3.14`. The
office-search and cameras suites also need `jinja2`, `pyyaml` and `sgp4`, so run
them from a scratch venv (`python3.14 -m venv … && pip install jinja2 pyyaml sgp4`).

```bash
python3.14 -m unittest discover -s scripts/local-map -p 'test_*.py'
python3.14 -m unittest discover -s scripts/home-agent -p 'test_*.py'
node scripts/local-map/test-sky.mjs
node scripts/local-map/test-household-schedule.mjs
"$VENV"/bin/python -m unittest discover -s scripts/office-search -p 'test_*.py'
"$VENV"/bin/python -m unittest discover -s scripts/cameras -p 'test_*.py'
```

## Researched, not installed

- **SCE hourly energy use:** no integration signs in to SCE's portal, and Opower
  doesn't support SCE. The working route is the smart meter's Home Area Network
  (register on SCE's HAN site, then a Rainforest EMU-2/Eagle or Emporia Vue
  Utility Connect). Green Button downloads are the manual alternative.
- **Caltrans PeMS:** needs a registered account and offers files, not a live API.
  Daytrip already gets live traffic from Google.
