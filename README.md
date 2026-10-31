# Home server notes & scripts

Scripts and notes for the home network: a Raspberry Pi running Pi-hole and
BabySteps, and a laptop running Home Assistant and everything around it.
Addresses below are examples; real values live in `.env`.

**Setup:** copy `.env.example` to `.env` (gitignored) and fill in the Pi and HA
host, addresses, home location and household details. `scripts/config.sh`
loads it (source it from bash), and each installer fills `@@NAME@@` placeholders
from it before deploying. Also local-only: the family calendar list
(`scripts/local-map/calendar-dashboard.yaml`) and the recipe text
(`scripts/recipes/source.txt` and its generated files).

## What runs where

### Raspberry Pi (`raspberrypi.local`)

Raspberry Pi 3 Model B, Raspberry Pi OS (Debian 13 Trixie, 64-bit), 32 GB
microSD. Wired `eth0` at `192.168.1.151` is the address Pi-hole uses; Wi-Fi is a
backup. SSH by key; `sudo` without a password.

- **Pi-hole** v6 (`http://192.168.1.151/admin`), filtering the Samsung TV only.
  See [Pi-hole](#pi-hole).
- **BabySteps**, the real copy: the `babysteps` (nginx) and `babysteps-internal`
  containers, published by Tailscale Funnel at `https://<pi tailnet name>:8443/`.
  Deployed from the [baby-steps](https://github.com/brooksr/baby-steps) repo, which
  also backs it up nightly (cron 03:17).
- **Funnel :10000** forwards to Home Assistant on the laptop, for Google Home and
  the phone app. It targets the laptop's LAN IP, so reserve that IP in the router.
- **Health:** cron posts the Pi's status to HA every 10 minutes (Device Health card).
- The old Home Assistant container is stopped but kept as a rollback.

### HA laptop (`HA_HOST`)

ASUS N501VW, Ubuntu 26.04, always on with the lid closed. Never use its built-in
SD slot: a card in it has frozen the machine.

| What | Where | Docs |
|---|---|---|
| Home Assistant 2026.10 (Docker, `~/homeassistant`) | :8123 | below |
| Cameras: office window (timelapse, launches) and baby monitor | go2rtc ×2, `baby-monitor-analyzer` | [scripts/cameras](scripts/cameras/README.md) |
| Voice: Whisper, Piper, Ollama (Qwen3-4B) for "Hey Jarvis" | `voice-*`, `ollama` | [scripts/office-search](scripts/office-search/README.md) |
| Office web search and the Jarvis page / 5 AM briefing | `office-search-tool`, `office-searxng` | [scripts/office-search](scripts/office-search/README.md) |
| Music Assistant (YouTube Music) on the Office EchoMuse | :8095 | [scripts/music-assistant](scripts/music-assistant/README.md) |
| Home observer ("anything unusual?") | `home-agent.service` | [scripts/home-agent](scripts/home-agent/README.md) |
| Desktop only while the lid is open | `lid-desktop.service` | [scripts/lid-desktop](scripts/lid-desktop/README.md) |
| BabySteps test copy (separate data) | `babysteps*` containers, Funnel :8443 | baby-steps repo |

## Home Assistant

Dashboards in the sidebar:

- **Overview**: HA's generated dashboard plus local cards (weather and power
  warnings, conditions, AQI, gas, day trips, grid, freeways, fires, earthquakes,
  launches, baby care, device health, internet) and the Today timeline.
  [scripts/local-map](scripts/local-map/README.md)
- **Local Map**: power shutoffs, outages, radar, fire perimeters, AQI and parcels
  on a map. [scripts/local-map](scripts/local-map/README.md)
- **Calendar**: the family Google calendars. [scripts/local-map](scripts/local-map/README.md)
- **BabySteps**: tap-to-log tiles and the voice phrase guide (not the app itself).
- **Jarvis**: voice phrases, the 5 AM briefing settings, music controls and the
  home observer. [scripts/office-search](scripts/office-search/README.md)
- **Recipes**: the family recipe book (`RECIPE_BOOK_TITLE`), an index and 32
  recipe pages copied from the family Google Doc. Not synced: edit
  `scripts/recipes/source.txt` and reinstall.

Themes: **Clean** in light mode, **LCARS TNG** (HA-LCARS with UI eXtension and a
locally hosted Antonio font) in dark mode. Pick another in your HA profile to
change it for yourself.

### Installing and updating

Run from the Mac. The installers back up what they replace and run HA's config
check. Office search, the Jarvis page and Music Assistant are installed by the
steps in their READMEs.

| Command | Installs |
|---|---|
| `bash scripts/local-map/install.sh` | Overview cards, Local Map, Calendar, sensors and alerts |
| `bash scripts/cameras/install.sh` | cameras, timelapse, launch and Starlink recording |
| `bash scripts/home-agent/install.sh` | home observer |
| `bash scripts/lid-desktop/install.sh` | lid-controlled desktop |
| `bash scripts/recipes/install.sh` | recipe book |
| `bash scripts/lcars/install.sh` | LCARS theme |
| `bash scripts/clean-theme/install.sh` | Clean theme (and sets the defaults) |
| `bash scripts/babysteps/install.sh` | BabySteps HA package, voice intents, dashboard and Google Home exposure (the app itself deploys from the baby-steps repo) |
| `sudo scripts/setup-homeassistant.sh` (on a new host) | Home Assistant in Docker |

### Google Home

Google Home talks to HA through the Pi's Funnel on :10000 using the manual
Google Assistant integration (no Nabu Casa). It sees template switches such as
`switch.babysteps_wet` / `_dirty` / `_both` / `_bath`; turning one on logs to
BabySteps. Say **"Hey Google, in Google Home run BabySteps wet"**; without "in
Google Home", Gemini treats it as a web search. Google Home can't pass numbers,
so amounts and sleep go through Assist.

- The integration is a private test project, `babysteps-home`, in the Google
  Home Developer Console (personal account), linked in the Google Home app as
  "[test] BabySteps".
- After changing what's exposed (`scripts/babysteps/ha/google_assistant.yaml`),
  say **"Hey Google, sync my devices"**.

## Pi-hole

Pi-hole blocks ads for the **Samsung TV only**. Every blocklist belongs to the
`TV` group, whose only client is the TV (`TV_IP`, e.g. `192.168.1.10`). Other
devices are in `Default`, which has no lists. The router still hands out itself
as DNS. This Mac and the TV are pointed at the Pi by hand.

| Group | Clients | Blocklists |
|---|---|---|
| Default | everything else | none |
| TV | the Samsung TV | StevenBlack hosts, Perflyst SmartTV |

It blocks Samsung ads and telemetry and Netflix telemetry (about 30% of the TV's
queries). Ads inside streaming apps come from the same servers as the video and
still play.

- **If the Pi is down:** the TV has no DNS and no internet. On the TV, set IP and
  DNS back to Obtain automatically. On the Mac:
  `networksetup -setdnsservers Wi-Fi empty`.
- **Known false positives:** `www.samsungotn.net` (TV firmware updates) and
  `api.distribution.hulu.com`. Allow both for the TV:
  ```bash
  ssh pi@raspberrypi.local 'sudo pihole-FTL sqlite3 /etc/pihole/gravity.db' < scripts/pihole-tv-allow.sql
  ssh pi@raspberrypi.local 'sudo pihole reloadlists'
  ```
- **Allow another domain:** web UI → Domains → add an allow rule, then set its
  group to **TV** (new rules start in Default only).
- **See what the TV queries:** web UI → Query Log, filter by the TV's IP.
- **Allow a work domain and its subdomains:**
  `ssh pi@raspberrypi.local 'sudo bash -s example.com' < scripts/pihole-allow-domain.sh`
- **Rebuild the TV group** (or undo it with `pihole-tv-revert.sql`, then
  `sudo pihole disable`):
  ```bash
  set -a; . ./.env; set +a
  sed "s/@@TV_IP@@/$TV_IP/g" scripts/pihole-tv-group.sql | ssh pi@raspberrypi.local 'sudo pihole-FTL sqlite3 /etc/pihole/gravity.db'
  ssh pi@raspberrypi.local 'sudo pihole -g && sudo pihole enable'
  ```
- **Whole-network blocking (not done):** set the router's LAN DNS to the Pi. If
  the Pi goes down, DNS stops for every device until reverted. Don't add a public
  secondary DNS; clients use it freely and ads leak through.
- The admin password isn't in this repo; rotate it with `pihole setpassword`.

## Pi helper scripts

| Script | Does |
|---|---|
| `scripts/find-pi.sh` | Finds the Pi by mDNS, then by ARP sweep for Pi MAC prefixes |
| `scripts/connect.sh` | SSH in (or run one command), picking a reachable address |
| `scripts/pi-info.sh` | Read-only inventory over SSH |
| `scripts/verify-pihole.sh` | `dig` checks that ads are blocked and `ALLOW_DOMAIN` resolves |
| `scripts/gpio/` | GPIO starter projects for the Pi's header ([README](scripts/gpio/README.md)) |

Override any setting inline, e.g. `PI_HOST=192.168.1.151 ./scripts/pi-info.sh`.
