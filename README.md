# Raspberry Pi — setup notes & helper scripts

Working notes for the home Raspberry Pi and a set of reusable scripts for
finding it, connecting, taking inventory, and running the Pi-hole ad-blocker.

**Personal settings:** copy `.env.example` to `.env` (gitignored) and fill in
your Pi user, addresses, home location and household details.
`scripts/config.sh` exports them, and the install scripts fill the
`@@NAME@@` placeholders in staged files from them before deploying. Addresses
in these notes are examples. The family calendar list
(`scripts/local-map/calendar-dashboard.yaml`) and the recipe book copy
(`scripts/recipes/source.txt` and its generated files) are also local-only.

---

## The device (current state)

| | |
|---|---|
| **Model** | Raspberry Pi 3 Model B Rev 1.2 (4-core, aarch64) |
| **OS** | Raspberry Pi OS — **Debian 13 "Trixie", 64-bit** (freshly reimaged) |
| **Kernel** | 6.18.50+rpt-rpi-v8 |
| **Login user** | `pi` — set `PI_USER` in `.env` (uid 1000, in `sudo` group) — SSH **key auth** |
| **sudo** | password required (not passwordless — by design) |
| **Hostname** | `raspberrypi` → `raspberrypi.local` (mDNS) |
| **Storage** | 32 GB microSD, filesystem expanded (~21% used) |

### Network

| Interface | MAC | IP (DHCP) | Role |
|---|---|---|---|
| `eth0` (wired) | `<eth0 MAC>` | `192.168.1.151` | **preferred** (use for Pi-hole + DHCP reservation) |
| `wlan0` (Wi-Fi) | `<wlan0 MAC>` | `192.168.1.158` | backup |

- **Subnet:** `192.168.1.0/24` · **Gateway/router:** `192.168.1.254`
  (ISP gateway; admin UI only loads in a browser, not via probes)
- **IPs are still DHCP and have changed before** — pin `eth0` to `192.168.1.151`
  with a router DHCP reservation before relying on it (see below).

---

## What we did (history)

1. **Found it booting-but-headless.** Diagnosed via the on-board LEDs: solid red =
   power OK; blinking green = reading the SD card / booting; green idle = booted.
   It never joined the network at first because it was neither on Ethernet nor
   configured for the current Wi-Fi.
2. **Located it on the LAN** once wired to the router — `raspberrypi.local`
   resolved to `192.168.1.151`. (Check the router's actual subnet first —
   an early sweep failed by scanning the wrong one.)
3. **The old install:** Raspbian 8 "Jessie" (2017), default `pi`/`raspberry`,
   long past end-of-life and unpatched. Only SSH was exposed. Added an SSH key,
   inventoried it, found only old hobby projects (Minecraft/Sonic Pi/Node-RED) —
   nothing worth keeping.
4. **Reimaged** with Raspberry Pi Imager on the Mac (14" MacBook Pro has a
   built-in full-size SD slot; the microSD rode in an adapter). Preset in Imager:
   hostname, user + password, SSH key, Wi-Fi, locale. Result: the clean
   Trixie install above.
5. **Patched** it (`sudo apt update && sudo apt full-upgrade`).
6. **In progress:** installing **Pi-hole** network-wide ad blocking, with
   a work domain (`ALLOW_DOMAIN`) and its subdomains allowlisted so work tools keep working.

---

## Gotchas worth remembering

- **SSH to the *old* Jessie Pi** needed legacy crypto flags; the current Trixie
  install does **not**. The scripts target the current install (no legacy flags).
- **Interactive passwords can't be driven through automation** here — the macOS
  `ssh`/`sudo` password prompt needs a real TTY. Run `ssh-copy-id`, the Pi-hole
  installer, and anything needing `sudo` yourself in **Terminal.app**.
- macOS hid the Wi-Fi **SSID** from tooling (privacy redaction) — read it from
  the menu bar or run the `system_profiler` command yourself.
- A Pi booted from its SD card **cannot safely reimage that same card** — reflash
  from the Mac with the card in the SD slot.
- **After a reimage the Pi's SSH host key changes**, so SSH refuses to connect
  with "REMOTE HOST IDENTIFICATION HAS CHANGED". Clear the stale entries and
  reconnect (safe when you know you just reflashed it):
  ```bash
  ssh-keygen -R raspberrypi.local
  ssh-keygen -R 192.168.1.151
  ssh-keygen -R 192.168.1.158
  ```

---

## Scripts (`./scripts/`)

All read settings from `scripts/config.sh`. Override any value inline, e.g.
`PI_HOST=192.168.1.151 ./scripts/pi-info.sh`.

| Script | Runs on | sudo | What it does |
|---|---|---|---|
| `config.sh` | — | — | Shared vars (user, host, IPs, MACs, SSH opts). Sourced by the rest. |
| `find-pi.sh` | Mac | no | mDNS lookup, then ARP-sweeps the subnet for Pi MAC prefixes. |
| `connect.sh` | Mac | no | Interactive SSH (or one-off command), auto-picking a reachable address. |
| `pi-info.sh` | Mac | no | Full read-only environment inventory over SSH. |
| `pihole-allow-domain.sh` | **Pi** | **yes** | Allowlists a domain + all its subdomains in Pi-hole. |
| `verify-pihole.sh` | Mac | no | `dig`-tests that ads are blocked and `ALLOW_DOMAIN` is allowed. |
| `pihole-tv-group.sql` / `-allow.sql` / `-revert.sql` | Pi (via ssh) | **yes** | Pi-hole filtering for the Samsung TV only, its allow rules, and the undo (see below). |
| `setup-homeassistant.sh` | **Pi** | **yes** | Installs Home Assistant in Docker (coexists with Pi-hole; doesn't wipe the OS). |
| `babysteps/install.sh` | Mac | no | Hosts BabySteps on the Pi (port 8080, auto-updated from CI), its token broker and events API, and adds it plus voice logging to Home Assistant. |
| `gpio/blink.py`, `gpio/dim.py` | **Pi** | no | GPIO starter projects (LED blink / PWM dimmer). See `gpio/README.md`. |

```bash
cd scripts
./find-pi.sh            # where is it?
./connect.sh            # shell in
./pi-info.sh            # what's on it?
./verify-pihole.sh      # is Pi-hole doing its job?
```

---

## Remaining steps for network-wide ad blocking

1. **Reserve the IP (router).** The gateway has **DHCP Auto Reservation** on, so
   `eth0` (MAC `<eth0 MAC>`) is already auto-pinned to `192.168.1.151`
   (listed as `raspberrypi-75`). **Convert that Auto entry to a manual one**
   (delete the Auto row, re-add the same MAC → `.151`) so it can't vanish if Auto
   Reservation is ever disabled — Pi-hole's reliability depends on this address.
   The Wi-Fi interface (`.158`) needs no reservation: Pi-hole runs on the wired
   side, and SSH uses `raspberrypi.local` (mDNS follows the Pi to any IP).
2. **Install Pi-hole** (in Terminal — interactive, needs sudo):
   ```bash
   ssh pi@raspberrypi.local
   curl -sSL https://install.pi-hole.net | sudo bash
   # if it rejects Trixie: ...| sudo PIHOLE_SKIP_OS_CHECK=true bash
   ```
   Choose `eth0`, static IP `192.168.1.151/24`, gateway `192.168.1.254`,
   an upstream DNS (Cloudflare 1.1.1.1 / Quad9), default blocklist, web UI on,
   logging on. **Save the admin password it prints.**
3. **Allowlist your work domain** (from the Mac, enter sudo password when asked):
   ```bash
   ssh pi@raspberrypi.local 'sudo bash -s example.com' < scripts/pihole-allow-domain.sh
   ```
4. **Point clients at Pi-hole.**
   - **CURRENT STATE: Mac and Samsung TV use the Pi; only the TV is filtered.**
     The router still hands out itself (`192.168.1.254`) as DNS. This Mac's
     Wi-Fi DNS is set to `192.168.1.151`
     (`networksetup -setdnsservers Wi-Fi 192.168.1.151`) but it's in the
     **Default** group, which has no blocklists, so it resolves everything. The
     TV is set to the Pi by hand and is filtered; see
     [Pi-hole for the Samsung TV only](#pi-hole-for-the-samsung-tv-only).
     **Undo / fix if Pi is down:** `networksetup -setdnsservers Wi-Fi empty`.
   - **Whole network (later):** set the router's LAN DNS to `192.168.1.151`.
     Trade-off: if the Pi goes down, DNS stops network-wide until reverted (~30s
     fix in the router). Do NOT add a public secondary DNS — clients use it
     freely and ad-blocking leaks.
5. **Verify:** `./scripts/verify-pihole.sh` (or `dig doubleclick.net` → `0.0.0.0`).

### Pi-hole facts
- Version **v6.4.3** (core) · admin UI: `http://192.168.1.151/admin`
- Upstream DNS: Cloudflare (1.1.1.1) · runs on `eth0` / `.151`
- The work domain is on the allowlist (apex). For all subdomains, add a regex
  allow like `(\.|^)example\.com$` (web UI, or `scripts/pihole-allow-domain.sh`).
- Admin password is NOT stored in this repo — keep it in a password manager;
  rotate with `pihole setpassword` over SSH.
- Blocking is **on** (2026-10-21), but every blocklist is assigned to the **TV**
  group only, so it filters the Samsung TV and nothing else.

### Pi-hole for the Samsung TV only

Set up 2026-10-21 for the living-room TV (Samsung UN55NU6900, running a custom
home dashboard app). Pi-hole's groups do
the scoping:

| Group | id | Clients | Blocklists |
|---|---|---|---|
| Default | 0 | every device not listed (this Mac, …) | none |
| TV | 1 | `192.168.1.10` "Samsung TV" | StevenBlack hosts, Perflyst SmartTV |

**How it was built** (gravity.db backed up first to
`/etc/pihole/gravity.db.bak-20261021` on the Pi):
1. Web UI → Group Management → Groups: add `TV` (got id 1).
2. Assign the TV and lists (`scripts/pihole-tv-group.sql`; `TV_IP` comes from
   `.env`, e.g. `set -a; . ./.env; set +a`), download the lists, turn blocking on:
   ```bash
   sed "s/@@TV_IP@@/$TV_IP/g" scripts/pihole-tv-group.sql | ssh pi@raspberrypi.local 'sudo pihole-FTL sqlite3 /etc/pihole/gravity.db'
   ssh pi@raspberrypi.local 'sudo pihole -g'
   ssh pi@raspberrypi.local 'sudo pihole enable'
   ```
3. On the TV: Settings → General → Network → Network Status → IP Settings. Setting
   DNS manually forces IP to manual too (fields reset to 0.0.0.0), so enter
   IP `192.168.1.10`, mask `255.255.255.0`, gateway `192.168.1.254`,
   DNS `192.168.1.151`. Reserve `<TV MAC>` → `.10` in the router.

**Result on day one:** ~30% of the TV's queries blocked: Samsung ads
(`config.samsungads.com`, `tvx.adgrx.com`, `rtb.adgrx.com`), Samsung notices
and telemetry, and Netflix telemetry (`ichnaea.netflix.com`,
`customerevents.netflix.com`). Ads inside streaming apps are not affected (same
servers as the video).

**Known false positives:** `www.samsungotn.net` (Samsung's **firmware update**
server: blocks TV software updates) and `api.distribution.hulu.com` (may
break Hulu). To allow both for the TV:
```bash
ssh pi@raspberrypi.local 'sudo pihole-FTL sqlite3 /etc/pihole/gravity.db' < scripts/pihole-tv-allow.sql
ssh pi@raspberrypi.local 'sudo pihole reloadlists'
```
Other domains: Web UI → Domains → add as an allow rule, then set its group to
**TV** (new rules start in Default only, which doesn't apply to the TV).

**See what the TV is doing:** Web UI → Query Log, filter client `192.168.1.10`.

**Caveat:** the TV's only DNS server is the Pi. If the Pi is down, the TV has
no internet; set the TV's DNS back to Obtain automatically.

**Revert:**
- Just stop filtering the TV: on the TV, set IP and DNS to **Obtain automatically**.
- Undo the Pi-hole changes (lists back to Default, TV client and Smart TV list
  removed), then rebuild, and turn blocking off again if it should stay off:
  ```bash
  sed "s/@@TV_IP@@/$TV_IP/g" scripts/pihole-tv-revert.sql | ssh pi@raspberrypi.local 'sudo pihole-FTL sqlite3 /etc/pihole/gravity.db'
  ssh pi@raspberrypi.local 'sudo pihole -g'
  ssh pi@raspberrypi.local 'sudo pihole disable'
  ```
  Or restore the backup: `sudo cp -p /etc/pihole/gravity.db.bak-20261021 /etc/pihole/gravity.db && sudo pihole reloadlists`.

---

## Home Assistant memory tuning (Pi 3, 1GB)

The Pi 3 has 905MB of RAM, and HA alone used ~476MB (most of it in swap on the
SD card). As of 2026-10-22:

- The desktop is off (`lightdm` disabled; boots to console).
- `/config/configuration.yaml` (on the Pi, not in this repo) lists the
  `default_config` integrations explicitly minus `cloud`, `go2rtc` and `stream`
  (no Nabu Casa, no cameras), and sets `recorder` to `purge_keep_days: 5`,
  `commit_interval: 30`. Restore `default_config:` to undo.
- Removed in Settings → Devices & services: `mcp_server`, `dlna_dmr` (a
  duplicate of the Samsung TV), `radio_browser`, `analytics`, `go2rtc`.
- Local-map script sensors poll every 10–30 minutes instead of 2–15.

**To re-enable the MCP server** (e.g. to let Claude monitor HA and suggest
updates): Settings → Devices & services → Add integration → *Model Context
Protocol Server*. On a larger host, drop all of the above.

## LCARS TNG theme in Home Assistant

Home Assistant uses **LCARS TNG** as its backend-selected default in dark mode,
with the Next Generation amber, lavender, and black palette. The installed
[HA-LCARS](https://github.com/th3jesta/ha-lcars) release is **4.1.3**, with
[UI eXtension](https://github.com/Lint-Free-Technology/uix) **8.4.0** for styling.
The Antonio font is downloaded from Google Fonts and hosted locally, with a
global loader so built-in dashboards receive it too. Sounds and textures start off; their
helpers and border sizes are available under Settings → Devices & services →
Helpers. The header clock uses `sensor.time`, excluded from Recorder and
Activity so its minute updates do not fill the history or activity feed.

Reinstall with `bash scripts/lcars/install.sh` from the Mac. It backs up changed
files, checks HA configuration, and restarts HA. On a fresh installation, add
**UI eXtension for Home Assistant** in Devices & services, then add these
dashboard resources in Settings → Dashboards → menu → Resources:

- `/local/community/lcars/lcars.js` — JavaScript module

Refresh the browser after installation. Profile → Theme can select **LCARS TNG**
explicitly or **Backend-selected** to follow the default. Choose another theme
in your profile to change the look locally; remove
`/config/packages/lcars.yaml` and restart to remove the LCARS default automation
and helpers. Existing dashboard content remains in place.

## Local conditions map in Home Assistant

**Local Map** in the sidebar opens
`http://raspberrypi.local:8123/local-map/conditions`, centered on the home parcel
in Thousand Oaks. It uses a locally hosted Leaflet 1.9.4 card with the LCARS
theme. USGS topographic maps are the default; street maps and satellite imagery
are selectable. Home zooms to parcel level; Region shows the surrounding area.

Layer toggles include SCE home circuit lines (`PSPS_CIRCUIT`), PSPS event areas, nearby
current and scheduled outages, NOAA radar, NWS warnings for home, NIFC wildfire
perimeters, EPA AirNow AQI categories, Ventura County parcel boundaries, and
USGS shaded relief. Parcels load only at zoom 16 or closer to keep requests
small. Feed errors and checked times appear beside the layers. The official
AirNow fire/smoke and SCE alert pages are linked from the map.

On phones, **Layers** opens the scrollable overlay options; **Show map** returns
to the map. The circuit status stays in the header, and **Map notes & data
freshness** expands the footer. The card fits HA's panel height so controls and
notes remain reachable. Bump the card resource version in `package.yaml` when
deploying frontend changes so phones do not retain the old cached module.

`sensor.power_shutoff` polls SCE every ten minutes. A transition to a warning,
active shutoff, or the removal of a previously listed event creates or updates
a Home Assistant persistent notification. These are **HA notifications**, not
phone push, SMS, or an SCE subscription. Failed requests produce `unavailable`,
never an all-clear. Nearby conventional outage markers are context; they do
not establish that home is affected. Circuit lines are SCE distribution
planning data; the PSPS polygons are event footprints, not a permanent circuit
service boundary. All displayed times use America/Los_Angeles.

Reinstall: `bash scripts/local-map/install.sh`. It copies the dashboard,
package, status reader, local library assets, and the small `local_map` custom
integration. The integration provides authenticated access to four fixed SCE
map feeds because those feeds do not support direct browser requests. Existing
files are backed up under `/config/backups/local-map`, outside the public www
directory. The installer checks HA configuration and restores files on a
validation error before restarting. Coordinates stay in the authenticated
dashboard YAML, not in the public JavaScript assets. Layer feeds and base-map
tiles require internet access; fire perimeters and AQI observations may lag
their check time.

Source code: `scripts/local-map/`. The HA package is
`/config/packages/local_map.yaml`, dashboard
`/config/dashboards/local-map.yaml`, and status reader
`/config/scripts/local-map-status.py`. Remove the package and restart to
unregister this dashboard and its notifications. Run status-reader checks with
`python3 -m unittest discover -s scripts/local-map -p 'test_*.py'`.

The built-in **Overview** also shows a combined weather/power warnings card and
an expanded native weather forecast card above its usual sections. The
`overview-widgets.js` frontend module adds these sections to HA's generated
Overview strategy while retaining its favorites, areas, and summaries. The
strategy hook may need adjustment after a Home Assistant frontend upgrade.
`sensor.local_weather_alerts` polls NWS for home every ten minutes, preserving
warning details and instructions. A failed or stale feed is labeled
unavailable. Power warnings use the existing PSPS sensor (`sensor.power_shutoff`); conventional
outage context remains on Local Map and the official SCE page. Forecasts use
the existing weather integration, with the daily forecast when supported.

**Trash and street sweeping dates** (no separate card; they drive the Today
timeline and the sunset reminders) come from `household-schedule.mjs` and
its Python port `household.py`. The 2026 city calendar lists our street (`HOME_STREET`) on the second and fourth Wednesday in
October–April and the second Wednesday in May–September. Its exact dates are
kept in `household-schedule.mjs`, including September's holiday exception.
Trash dates adjust for Athens' six weekday service holidays; weekend holidays
do not shift collection. Dates roll forward after 7 PM in Pacific time.
Sweeping dates beyond the verified 2026 calendar are labeled estimated and
should be updated from the next city calendar.

**Current conditions** on Overview shows temperature, humidity and dew point,
wind, pressure, cloud cover and UV from the Met.no weather entity, plus US AQI
and PM2.5 from `sensor.local_air_quality`. That sensor polls Open-Meteo's
air-quality API every 15 minutes (no key). Its values are a CAMS model estimate
for the home point, not an AirNow monitor reading, and it goes unavailable when
the request fails.

**Sun and moon** on the Today timeline: first light (civil dawn, sun 6° below
the horizon), sunrise and sunset for HA's home location, plus a strip with the
moon's phase, illumination and next full or new moon. `sky.mjs` computes them in the browser
(NOAA solar equations; low-precision lunar longitude), so no Moon integration
is needed. `sun.sun` only exposes the *next* event, which is tomorrow's once
an event passes. Sun times match astral within a minute, and phase timings fall
within about 20 minutes of published 2026 dates. Run
`node scripts/local-map/test-sky.mjs` to check them.

**Cheapest gas nearby** on Overview lists the three lowest regular-unleaded
prices within 5 miles, with each station's name, address and straight-line
distance. `sensor.local_gas_prices` (`/config/scripts/local-gas-prices.py`)
calls Google Places Nearby Search hourly and reads `google_places_api_key` from
`/config/secrets.yaml`. Until that key exists, the card asks for it. The key
needs **Places API (New)** enabled. Fuel prices are an Enterprise field, so
about 720 calls a month should stay within the monthly free usage. Stations
that don't report prices to Google are skipped.

**Daytrip** on Overview covers Ventura Pier and Malibu Pier. For each it shows
the drive time with current traffic, air temperature and today's high, sea
surface temperature, and a tide chart from 3 hours ago to 21 hours ahead with
the current level and next high or low. `sensor.daytrip`
(`/config/scripts/local-daytrip.py`) refreshes every 20 minutes:
- Surf and wind (added 2026-10-21 for the TV weather page; the
  Overview card doesn't show them yet): `surf` (wave height ft, period s, swell
  height, period and direction now) and `surf_forecast` (every 3 hours for 24
  hours) come from the same Open-Meteo Marine call as the water temperature;
  `wind_mph`, `wind_gust_mph` and `wind_dir` from the Open-Meteo forecast call.
  No key. Deployed alone over `/config/scripts/local-daytrip.py` (old copy in
  `/config/backups/local-map/`).
- Drive times come from the Google Routes API, using the same
  `google_places_api_key` (enable **Routes API** on it). Four thousand or so
  traffic-aware calls a month should stay within Google's monthly free usage.
- Temperatures come from Open-Meteo, with no key.
- Tides come from NOAA high/low predictions joined by half-cosine curves. The
  stations are Ventura (9411189) and Santa Monica (9410840), the nearest to
  Malibu.

Each source fails separately and shows a dash, never a stale or guessed value.

**California grid** on Overview shows CAISO's grid status (Normal, Restricted
Maintenance Operations, Flex Alert or an emergency stage). It also shows
current demand against today's forecast peak, reserves, the renewable share,
and a bar of the current supply by source. `sensor.caiso_grid` is a REST
sensor on CAISO's public Today's Outlook feed
(`https://www.caiso.com/outlook/current/stats.txt`), polled every 5 minutes
with no key. Home Assistant has no CAISO integration; this is the same feed
the gridstatus library reads. Batteries appear in the mix only while
discharging.

**Freeways: 101 & 23** on Overview covers US-101 and SR-23 in Ventura County,
plus the 101 through Agoura Hills and Calabasas. It shows any message-sign
text, lane closures with crews on scene, closures scheduled now or within 24
hours, and stills from the two nearest working cameras on each freeway.
`sensor.freeway_conditions` (`/config/scripts/local-caltrans.py`) reads
Caltrans District 7's public CWWP2 feeds every 10 minutes, with no key.

- **Message signs:** read from the sign feed.
- **Lane closures:** read from the CSV feed, 2 MB instead of the 14 MB JSON.
  "In place" means Caltrans logged crews on scene (code 10-97) and hasn't logged
  them leaving (10-98). Scheduled closures often don't happen.
- **Camera images:** load straight from Caltrans in the browser and reload
  every 2 minutes.

**Active fires** (Right now) appears only while Ventura County Fire lists a
burning fire, from `https://firefeeds.venturacounty.gov/api/incidents`, nearest
first. Medical calls, fire alarms and smoke investigations are left out.
`sensor.fire_incidents` (`local-fire-incidents.py`, every 10 minutes) has the
active-fire count as its state. The weather and power warnings card likewise
appears only while NWS lists a warning for home or SCE lists a home-circuit power
shutoff. If either feed fails, its card stays hidden; the PSPS notification
automation is unchanged.

**Earthquakes** (Right now) appears only after an M2.5+ quake within 50
miles in the last 24 hours. It shows magnitude, place, distance, depth, felt
reports and a USGS link. `sensor.earthquakes` (`local-earthquakes.py`, every 10
minutes) queries the USGS FDSN event API for the past 7 days, with no key; its
state is the 24-hour count.
- **Spoken alert:** automation `local_map_earthquake_announcement` speaks on
  `media_player.family_room_speaker` (Google Translate TTS) and posts an HA
  notification for M4.0+ within 50 miles.
- **Tablet alert:** the same alert is spoken on the tablet
  (`notify.mobile_app_tablet`, a Galaxy Note 10.1 GT-N8013 on LineageOS 19.1).
  It runs the F-Droid "minimal" Companion app with Persistent connection set
  to Always, and RHVoice (from F-Droid) as Android's text-to-speech engine. It
  plays on the alarm stream, so it works with the screen off and on silent.
  Sign in by IP (`http://192.168.1.151:8123`); Android can't resolve
  `raspberrypi.local`. If speech stops after the TTS engine changes,
  force-stop and reopen the Companion app.
- **Once per quake:** it uses the `alert` attribute, set only for 30 minutes
  after the quake, so later polls or a restart don't repeat it.
- **Not early warning:** USGS posts quakes minutes after they happen. For
  warning before the shaking arrives, use ShakeAlert through the MyShake app.

**Observed conditions:** Current conditions prefers the NWS Thousand Oaks
station (TO, Moorpark Rd, about 1 mile away) when its latest observation is
under 90 minutes old, falling back to Met.no's model. `sensor.nws_observation`
is a REST sensor; values arrive in SI units and the card converts them. For
AQI the card prefers **PurpleAir**: `sensor.purpleair` (`local-purpleair.py`,
every 30 minutes) takes the median of up to 8 outdoor sensors within 2 miles,
corrected with the EPA's US-wide formula and converted with the 2024 PM2.5
breakpoints. It needs a free key from develop.purpleair.com, stored as
`purpleair_api_key` in `/config/secrets.yaml`. Each request spends PurpleAir
API points; until a key is added, the Open-Meteo model is used.

**Baby care** shows suggestions based on today's conditions: heat, the day's
UV peak, AQI, active warnings, fire calls within 5 miles, cold, a walk window and safe-sleep guidance for tonight's low. It is general
AAP/CDC guidance, not medical advice. The card reads `sensor.babysteps_status`
for last feed, diaper and sleep once one exists (see BabySteps below).

**Recipe of the day** picks one family recipe per day, with Shuffle
and an Open link into the Recipes dashboard. `scripts/recipes/build.py` writes
`recipes.json`, which `install.sh` copies to `/config/www/recipes/`.

**Raspberry Pi** (right column) shows CPU and load, SoC temperature, the
undervoltage alarm, memory and swap, SD card use, HA database size and uptime.
`sensor.raspberry_pi` (`local-system-status.py`, every 30 minutes) reads host
`/proc` and `/sys` from inside the HA container. HA's built-in System Monitor
integration is an alternative, added in Settings → Devices & services.

**Internet** (right column, under Raspberry Pi) shows online, degraded or
offline. It also shows internet latency and loss (Cloudflare and Google),
router latency, DNS through Pi-hole and the router, and an HTTPS round trip.
`sensor.internet` (`local-net-status.py`) checks from the Pi every 30 minutes. It
is offline only when nothing on the internet answers; loss of 10% or more,
latency of 150 ms or more, or a DNS or HTTPS failure is degraded.

The template sensors `sensor.internet_uptime` (100 online or degraded, 0
offline) and `sensor.internet_latency` have `state_class: measurement`, so
HA keeps their hourly long-term statistics indefinitely, past the recorder's
10-day history. The card reads those statistics for uptime and average
latency over 24 hours, 7 days and 30 days, and compares current latency with
each average. The windows fill as hours are recorded (from October 18, 2026).

**Today** (top of the Today section) is a timeline with a line marking the
current time. It shows:
- BabySteps entries, and sunrise and sunset.
- Fixed times: 5:00 wake-up, Dad time 5:00–8:30, breakfast 8:30, work time
  8:30–3:30 (Monday to Friday), lunch 12:30 and dinner 5:30.
- Bath time at 7:00, only when BabySteps shows 3+ days since the last bath.
- Let the dog out at 7:30, the baby's bedtime (`CHILD_NAME`) at 8:00, Mom's at 8:30 and Dad's
  at 9:00.

The schedule is the `ROUTINE` list in `overview-widgets.js`. Automation
`local_map_evening_routine` speaks the bath, dog and the baby's bedtime (`CHILD_NAME`) items on
the tablet. `local_map_morning_baby_briefing` speaks a 5 AM status: crying,
feeding, asleep or awake, then the last feed and diaper, whether either is
due (3 hours), and cries the nursery heard in the last hour.

**BabySteps for HA:** `sensor.babysteps_status`
(`local-babysteps-today.py`, every 10 minutes) reads the internal backend at
`127.0.0.1:8790/api/v1`. HA is enrolled as a BabySteps "phone" device,
because the watch level omits baths.
- **Credentials:** `/config/.babysteps-native.json` (mode 600). Refresh
  tokens rotate, and reusing one revokes the device.
- **Re-enroll:** run
  `docker exec homeassistant python3 /config/scripts/local-babysteps-today.py enroll`,
  approve the printed code in BabySteps → Account, then run the same command
  with `finish`.
- **Revoke:** from Account in BabySteps.

**Voice logging** (Assist, the Google Home `switch.babysteps_*`, and the
bottle script) uses `shell_command.babysteps_log`. It runs
`local-babysteps-today.py log <base64 JSON>`, which saves the entry through
HA's enrolled BabySteps device. The script ports BabySteps'
`src/domain/eventRequest.ts`: the same request fields, refusals and spoken
confirmations as the retired events API (which now returns 410).
- Each save carries a fresh operation id, so a retry can't save it twice.
- A file lock stops the status sensor and logging from refreshing the
  rotating token at the same time, which would revoke the device.
- `scripts/babysteps/ha/babysteps.yaml` is installed directly as
  `/config/packages/babysteps.yaml`. `scripts/babysteps/install.sh` still
  manages the retired legacy containers.

**Trash and street-sweeping reminders:** `sensor.household_schedule`
(`local-household.py`, a Python port of `household-schedule.mjs` checked
against the same test cases) says whether trash pickup or street sweeping
is tomorrow. At sunset the evening before, `local_map_trash_sweeping_reminder`
speaks on the tablet, and the Today timeline shows "Take the trash out" or
"Check the driveway" at sunset.

The Today timeline is drawn to scale, 0.8 px per minute from 4 AM to 10 PM,
widened for anything earlier or later. Spans such as Dad time show as bars;
labels in a crowded stretch move down, with a lead line back to their time.

**5 AM message**, in order:
1. Whether today will be hot (85°F+), warm (75+), mild (60+) or cold, with
   the current temperature and the forecast high.
2. The baby status.
3. Any active Overview warnings: an NWS weather warning, a home-circuit power
   shutoff, the internet down or degraded, and Raspberry Pi problems
   (undervoltage, 80 °C or hotter, memory or swap at 85%+, SD card at 90%+,
   or no status).

Earthquake announcements are quiet from 9 PM to 5 AM; the HA notification is
still created.

**Vandenberg launches** (after Day trip) lists the next launches from
Vandenberg SFB with a firm time, from Launch Library 2 (The Space Devs; free,
15 requests an hour without a key). `sensor.vandenberg_launches`
(`local-launches.py`) polls every 30 minutes. Each launch shows local time,
countdown, rocket, mission, status, and Space Launch Now and webcast links.

It is labelled by how it should look from home, from the sun's altitude in
Thousand Oaks at launch time:
- **Twilight** (sun 4–18° below the horizon): dark sky with a sunlit plume,
  the "jellyfish". The best kind.
- **Night**, **dusk or dawn**, or **day**.

Launches on today's date also appear on the Today timeline. Automation
`local_map_launch_announcement` speaks on the tablet 10 minutes before the
next twilight or night launch marked Go. Like earthquakes, it is quiet from
9 PM to 5 AM. A slipped launch moves `alert_at`, so the announcement follows
the new time.

**Caltrans PeMS (not used):** PeMS loop-detector speeds and counts need a
registered PeMS account, and the Clearinghouse provides files, not a live
public API. Drive times on Daytrip already reflect live traffic through Google.

**SCE energy usage (researched October 18, 2026, not installed):** no HACS
integration was found that signs in to SCE's customer portal for hourly usage,
and the Opower library behind HA's Opower integration does not list SCE.
Working SCE setups use the smart meter's Home Area Network instead. Register
the device on SCE's HAN site (about one business day), then use a Rainforest
EMU-2 or Eagle, or an Emporia Vue Utility Connect, with its HACS or ESPHome
integration. Green Button downloads from sce.com are another manual source.

**Calendar** in the sidebar (`/family-calendar/agenda`) combines the provided
Google embeds for Ventura County Events and the family's private calendars. Tabs
offer Agenda, Month, Household schedules, and source links. It uses the Google
viewer's existing account permissions; private events are not copied into
Home Assistant or public static files. Sign in to Google on each viewing
device if private events are missing. The public ICS links for the private
calendars returned 404 on October 13, 2026, while their embeds were
accessible with the browser's Google sign-in. The dashboard config is
`/config/dashboards/family-calendar.yaml`, installed from the gitignored
`scripts/local-map/calendar-dashboard.yaml` (copy the `.example.yaml`).

## Family recipes in Home Assistant

**Recipes** in the sidebar opens the family recipe book (`RECIPE_BOOK_TITLE`) at
`http://raspberrypi.local:8123/family-recipes/index`: an alphabetical index and
32 individual recipe pages with ingredients on the left, instructions on the
right, and a representative example photo with a source credit. On phones,
the columns stack vertically. The alphabetical index uses native sections
with equal mobile gutters. Family notes remain with the instructions.
The recipe text was copied from the
family Google Doc (`RECIPES_DOC_URL`) into the gitignored
`scripts/recipes/source.txt` on October 12, 2026, including Walnut Pepper Biscotti (missing from the Doc's
table of contents). This is a local copy, not an automatic sync.

`scripts/recipes/source.txt` keeps the copied text; `build.py` generates the
native dashboard without custom cards. `images.json` records photo sources
and licensing; downloaded photos are kept in `scripts/recipes/images` and
installed in `/config/www/recipes`. `fetch_images.py` can fetch the selected
photos again if needed. To update or reinstall, edit the copied text and run
`bash scripts/recipes/install.sh`. It backs up changed files,
installs `/config/dashboards/recipes.yaml` and `/config/packages/recipes.yaml`,
checks HA's configuration, and restarts HA only when dashboard registration
changes. Recipe content and photo updates appear after a page refresh.

## BabySteps (hosted on the Pi)

The [baby-steps](https://github.com/brooksr/baby-steps) PWA, served next to the
GitHub Pages copy and always on the latest build of `main`.

- **Open:** `https://raspberrypi.<tailnet>.ts.net:8443/` (works anywhere; sign-in
  works here). Plain `http://raspberrypi.local:8080/` works on the LAN but cannot
  sign in. **BabySteps** in the Home Assistant sidebar
  (`http://raspberrypi.local:8123/baby-steps`) is not the app: it is the
  tap-to-log tiles and the voice guide (below).
- **How it updates:** the repo's `deploy.yml` has a `pi` job that builds `main`
  with base `/` and uploads `babysteps-pi.tar.gz` to the rolling **`pi-latest`**
  release. A cron job on the Pi (`~/babysteps/update.sh`, every 5 min) installs
  any new asset and swaps the `~/babysteps/www/current` symlink. The build's
  commit is shown at `http://raspberrypi.local:8080/version.json`, and the
  log is `~/babysteps/update.log`. The Pi only pulls; no inbound access or runner.
- **Which build:** `~/babysteps/release-tag` names the release `update.sh`
  follows — `pi-latest` (main) when absent. It is the only release CI publishes;
  `BABYSTEPS_TAG=<tag> ./scripts/babysteps/install.sh` sets another.
- **Serving:** Docker container `babysteps` (`nginx:alpine`, `--restart=unless-stopped`)
  using `scripts/babysteps/nginx.conf`, on the docker network `babysteps`.
  `/api/events` is proxied to the events API and the rest of `/api/` to the
  token broker.
- **One-time sign-in (token broker):** container `babysteps-broker`
  (`node:24-alpine`) runs `~/babysteps/broker/token-broker.mjs`, which CI ships
  as a release asset and `update.sh` installs (restarting the container) when it
  changes. It holds the OAuth client **secret** in `~/babysteps/broker.env`
  (chmod 600 — `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `ALLOWED_ORIGINS`);
  `install.sh` creates that file empty and skips the container until it is
  filled in. Stateless: it keeps no tokens. The OAuth client also needs
  `https://raspberrypi.<tailnet>.ts.net:8443/` as an **Authorized redirect URI**.
  (HA used to show the app in an iframe sidebar panel; Google will not sign in
  inside a frame, so it fell back to the hourly popup and asked constantly. The
  panel was removed — `install.sh` takes it out of an older install.)
  Check it: `curl https://raspberrypi.<tailnet>.ts.net:8443/api/token/health`.
- **Voice logging (events API):** container `babysteps-events` (`node:24-alpine`)
  runs `~/babysteps/events/events-api.mjs`, shipped and updated by CI exactly like
  the broker; nginx sends `/api/events` to it. Integrations `POST` JSON such as
  `{"type":"feed","amount":4,"unit":"oz"}` with `Authorization: Bearer <token>`,
  and it writes the row to the family sheet. Contract: baby-steps `AGENTS.md`,
  "Logging from outside the app".
  - **One-time setup:** in Google Cloud (the same project) create a **service
    account**, add a JSON key, and copy it to `~/babysteps/service-account.json`
    on the Pi. **Share the family sheet with the account's `client_email` as an
    Editor.** Put the sheet id in `~/babysteps/events.env` (`BABYSTEPS_SHEET_ID=`)
    and re-run `install.sh`. The `EVENTS_API_TOKEN` in that file is generated on
    the first run and copied into HA's `secrets.yaml`; to rotate it, change it
    there and re-run.
  - **Nursery sensor:** the same container serves `POST /api/nursery` (nginx
    route `= /api/nursery`) for the `oneplus` nursery phone, which upserts
    nightly summaries, 15-minute sound levels and likely sound episodes into the
    sheet's four Nursery tabs. It uses its own `NURSERY_API_TOKEN`, which
    `install.sh` adds to `events.env`; enter it on the phone with the URL
    `https://raspberrypi.<tailnet>.ts.net:8443/api/nursery`. Contract: baby-steps
    `AGENTS.md`, "Nursery sensor delivery".
  - **Home Assistant:** `install.sh` installs `scripts/babysteps/ha/babysteps.yaml`
    as `/config/packages/babysteps.yaml` (a `rest_command`, Assist intents, and
    scripts) and `ha/custom_sentences_en.yaml` as
    `/config/custom_sentences/en/babysteps.yaml`, and the **BabySteps**
    sidebar dashboard at `/baby-steps` (HA needs a hyphen in dashboard URLs) (`ha/babysteps_voice_dashboard.yaml`): tap-to-log tiles
    plus the full phrase guide — that page is the user documentation. Assist
    covers bottle, nursing, diaper (+ poop size), sleep, bath, pump, tummy
    time, mood and note ("log 4 oz bottle", "log large dirty diaper", "note
    rolled over"); one intent, `BabyStepsLog`, handles them all.
  - **Speaking to Assist:** this Pi 3 has no speech-to-text (no room for
    Whisper), so the phone listens: keyboard dictation in the Assist box, or on
    iPhone a Siri Shortcut (Dictate Text → HA "Assist" → Speak Text).
  - **Google Home** cannot hand HA a number, so amounts and sleep go through
    Assist. Diapers work by voice: **"Hey Google, in Google Home run BabySteps
    wet"** (or `dirty` / `both`). Without "in Google Home", Gemini tends to
    answer it as a web search.
  - Check: `curl https://raspberrypi.<tailnet>.ts.net:8443/api/events/health` ·
    log: `docker logs babysteps-events`.
- **Google Home (manual Google Assistant integration, no Nabu Casa):** Google
  calls HA at `https://raspberrypi.<tailnet>.ts.net:10000`, a second Funnel
  (`sudo tailscale funnel --bg --https=10000 http://127.0.0.1:8123`).
  - What Google sees: template switches `switch.babysteps_wet` / `_dirty` /
    `_both` / `_dirty_small` / `_dirty_medium` / `_dirty_large` / `_bath` (in
    `ha/babysteps.yaml`). Turning one on POSTs to the events API; the switch
    always reads off. They were
    scenes first, but Google linked the scenes and then never sent HA a command
    (endless spinner, phrases went to web search). Only these three are exposed
    (`ha/google_assistant.yaml`, installed by `install.sh` once secrets.yaml has
    `google_assistant_project_id`).
  - **HA must trust the Funnel as a proxy**, or every request through it is a
    400. From HA 2026.x the http settings live in HA's own store, **not YAML** (an
    `http:` block is ignored): Settings → System → Network → use
    X-Forwarded-For, trusted proxies `127.0.0.1` and `::1`, login attempts
    threshold `5`; restart, then confirm within 5 minutes or HA reverts.
    Tailscale passes the caller's real IP, so the ban hits the right address
    (`/config/ip_bans.yaml`; delete a line to lift one).
  - **Developer Console** (console.home.google.com, personal account
    a personal Gmail account — the Workspace account cannot create projects):
    project `babysteps-home`, cloud-to-cloud integration "BabySteps", type
    Scene, client id `https://oauth-redirect.googleusercontent.com/r/babysteps-home`,
    any client secret, authorization `…:10000/auth/authorize`, token
    `…:10000/auth/token`, fulfillment `…:10000/api/google_assistant`, scopes
    `email` + `name`. It stays a private test integration.
  - Linked in the Google Home app (Works with Google → "[test] BabySteps",
    sign in to HA). After changing what is exposed or renamed, say "Hey
    Google, sync my devices" — HA cannot push changes without a service account
    (the log's "No configuration for request_sync" error is that, and harmless).
  - Debugging: drop a package with `logger: logs:
    homeassistant.components.google_assistant: debug` into `/config/packages`
    and restart; every SYNC/QUERY/EXECUTE and HA's reply land in the log.
- **HA config edits:** `configuration.yaml` is owned by root, so `install.sh`
  edits it through `docker exec` and keeps a `.bak-*` copy next to it. It runs
  HA's config check before any restart and refuses to restart on a failure.
- **Re-install / change anything:** edit `scripts/babysteps/*`, then run
  `./scripts/babysteps/install.sh` from the Mac (no sudo; re-runnable).
- **Public HTTPS (for Google sign-in):** `https://raspberrypi.<tailnet>.ts.net:8443/`,
  a **Tailscale Funnel** in front of port 8080 (port 8443 because Pi-hole holds 443).
  Google only accepts HTTPS origins on public domains, so `raspberrypi.local`
  can never sign in. This origin is in the OAuth client's authorized JavaScript
  origins.
  Tailscale was set up with `tailscale up --accept-dns=false` so it leaves the
  Pi's DNS alone (Pi-hole). The app shell is public; family data stays behind
  Google sign-in. Check: `tailscale funnel status` · turn off:
  `sudo tailscale funnel --https=8443 off`. A second Funnel on **:10000**
  publishes Home Assistant itself (its login page) for Google Home — see above;
  `sudo tailscale funnel --https=10000 off` takes it down.
- **Planned:** replace Google with HA login plus a database on the Pi.
