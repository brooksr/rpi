# Local Map, Overview cards and Calendar

Everything here installs with `bash scripts/local-map/install.sh` from the Mac.
It renders `@@NAME@@` placeholders from `.env`, backs up changed files under
`/config/backups/local-map` (outside the public www folder), runs HA's config
check, restores the old files if the check fails, and restarts HA.

| Installed as | From |
|---|---|
| `/config/packages/local_map.yaml` | `package.yaml` (sensors, automations, notifications) |
| `/config/dashboards/local-map.yaml` | `dashboard.yaml` |
| `/config/dashboards/family-calendar.yaml` | `calendar-dashboard.yaml` (gitignored; copy the `.example.yaml`) |
| `/config/www/local-map/` | the card JS, `overview-widgets.js`, `household-schedule.mjs`, `sky.mjs`, Leaflet |
| `/config/scripts/local-*.py` | the sensor scripts below |
| `/config/custom_components/local_map` | authenticated proxy for four SCE map feeds that block browser requests |

**Frontend changes:** bump `?v=` on the module URL in `package.yaml`, or phones
keep the old cached module. HA picks up the new URL on restart.

**Tests:**
```bash
python3.14 -m unittest discover -s scripts/local-map -p 'test_*.py'
node scripts/local-map/test-sky.mjs
node scripts/local-map/test-household-schedule.mjs
```

## Local Map dashboard

**Local Map** in the sidebar (`/local-map/conditions`) is a Leaflet 1.9.4 card
centred on the home parcel. Base maps: USGS topographic (default), streets,
satellite. **Home** zooms to the parcel and **Region** shows the surrounding
area. The card fills the screen below HA's header and the sidebar scrolls. On
phones, **Layers** opens the options and **Show map** returns.

Layers: SCE home circuit lines (`PSPS_CIRCUIT`), PSPS event areas, nearby
current and scheduled outages, NOAA radar, NWS warnings, NIFC fire perimeters,
AirNow AQI, Ventura County parcels (zoom 16+ only) and USGS shaded relief. Each
layer shows its checked time or feed error.

Coordinates stay in the authenticated dashboard YAML, not in public JS.
Circuit lines are SCE planning data, PSPS polygons are event footprints, and
nearby outage markers don't mean home is affected. Times are America/Los_Angeles.

**Power shutoff:** `sensor.power_shutoff` polls SCE every 10 minutes. A new
warning, an active shutoff, or a listed event being removed creates an HA
persistent notification (not phone push or SMS). A failed request is
`unavailable`, never an all-clear.

## Overview cards

`overview-widgets.js` adds sections to HA's generated Overview while keeping its
favourites and areas. The strategy hook may need adjusting after a frontend
upgrade. Every source fails on its own and shows a dash or hides its card rather
than a stale value.

| Card | Sensor / source | Refresh | Notes |
|---|---|---|---|
| Weather & power warnings | `sensor.local_weather_alerts` (NWS), `sensor.power_shutoff` | 10 min | Shown only while there is a warning or home-circuit shutoff |
| Current conditions | NWS Thousand Oaks station (`sensor.nws_observation`) if under 90 min old, else Met.no | — | AQI prefers PurpleAir, falls back to Open-Meteo |
| Air quality | `sensor.purpleair`: median of up to 8 outdoor sensors within 2 mi, EPA-corrected | 30 min | Needs `purpleair_api_key` in `secrets.yaml`; uses API points |
| | `sensor.local_air_quality`: Open-Meteo CAMS model | 15 min | No key; a model estimate, not a monitor |
| Cheapest gas | `sensor.local_gas_prices`: Google Places (New), 3 cheapest regular within 5 mi | 1 h | `google_places_api_key`; ~720 calls/month stays in free usage |
| Daytrip (Ventura, Malibu piers) | `sensor.daytrip`: Google Routes drive time, Open-Meteo air/sea temp, surf and wind, NOAA tides | 20 min | Same Google key with Routes API enabled; tide stations 9411189 and 9410840 |
| California grid | `sensor.caiso_grid`: CAISO Today's Outlook feed | 5 min | No key |
| Freeways: 101 & 23 | `sensor.freeway_conditions`: Caltrans D7 CWWP2 signs, lane closures (CSV), cameras | 10 min | "In place" = crews logged on scene (10-97) and not yet gone |
| Active fires | `sensor.fire_incidents`: Ventura County Fire incidents | 10 min | Shown only while a fire is burning; medical/alarm calls left out |
| Earthquakes | `sensor.earthquakes`: USGS, M2.5+ within 50 mi in 24 h | 10 min | See alerts below |
| Vandenberg launches | `sensor.vandenberg_launches`: Launch Library 2 | 30 min | Labelled twilight (best), night, dusk/dawn or day from the sun's altitude at home |
| Baby care | conditions + `sensor.babysteps_status` | — | General AAP/CDC guidance, not medical advice |
| Recipe of the day | `recipes.json` from `scripts/recipes` | daily | Shuffle and a link into Recipes |
| Device Health | `sensor.raspberry_pi` (HA host; the id predates the move) and `sensor.pi_health` | 30 / 10 min | The Pi posts its status by cron to webhook `pi_health_webhook` |
| Internet | `sensor.internet`: latency and loss, router, DNS via Pi-hole and router, HTTPS | 30 min | Offline only if nothing answers; ≥10% loss, ≥150 ms or a DNS/HTTPS failure is degraded |

`sensor.internet_uptime` and `sensor.internet_latency` keep long-term hourly
statistics, so the Internet card shows 24 h, 7 day and 30 day averages beyond
the recorder's 10-day history.

## Today timeline

A to-scale timeline (0.8 px per minute, 4 AM–10 PM, widened when needed) with a
now line. It shows BabySteps entries, first light, sunrise and sunset, the
moon's phase, today's launches, and the household routine (`ROUTINE` in
`overview-widgets.js`): 5:00 wake-up, Dad time 5:00–8:30, breakfast, work time
8:30–3:30 on weekdays, lunch, dinner, bath at 7:00 when BabySteps shows 3+ days
since the last bath, dog at 7:30, then bedtimes at 8:00, 8:30 and 9:00.

Sun and moon come from `sky.mjs` in the browser (NOAA solar equations,
low-precision lunar longitude) because `sun.sun` only exposes the next event.

**Trash and street sweeping:** `household-schedule.mjs` (and its Python port
`household.py`, which drives `sensor.household_schedule`) holds the 2026 city
calendar for `HOME_STREET` and Athens' trash holidays. Dates roll forward after
7 PM. Sweeping dates past 2026 are labelled estimated; update them from the next
city calendar.

## Spoken alerts

All speak on the tablet (`notify.mobile_app_tablet`, alarm stream, works on
silent). The tablet is a Galaxy Note 10.1 on LineageOS with the F-Droid
"minimal" Companion app (persistent connection: Always) and RHVoice as its TTS
engine. Sign it in to HA by IP; Android can't resolve `.local` names. If speech
stops after a TTS engine change, force-stop and reopen the Companion app.

| Automation | When |
|---|---|
| `local_map_morning_baby_briefing` | 05:00: runs `script.jarvis_morning_briefing` (see `scripts/office-search`) |
| `local_map_evening_routine` | Bath (7:00, if due), dog (7:30), the baby's bedtime (8:00) |
| `local_map_trash_sweeping_reminder` | Sunset the evening before trash or sweeping day |
| `local_map_launch_announcement` | 10 min before a Go twilight or night launch; quiet 9 PM–5 AM |
| `local_map_earthquake_announcement` | M4.0+ within 50 mi, once per quake; quiet 9 PM–5 AM (the HA notification is still made) |
| `local_map_power_shutoff_notification` | PSPS changes (HA notification) |

USGS posts quakes minutes after they happen. For warning before shaking, use
ShakeAlert through the MyShake app.

## BabySteps in HA

`sensor.babysteps_status` (`local-babysteps-today.py`, every 10 minutes) reads
the BabySteps backend on the Pi at `https://TAILNET_HOST:8443/api/v1`. HA is
enrolled as a BabySteps "phone" device (the watch level omits baths).

- Credentials: `/config/.babysteps-native.json` (mode 600). Refresh tokens
  rotate, and reusing one revokes the device. A file lock keeps the sensor and
  voice logging from refreshing it at the same time.
- Re-enrol: `docker exec homeassistant python3 /config/scripts/local-babysteps-today.py enroll`,
  approve the code in BabySteps → Account, then run it again with `finish`.
- Voice logging (Assist, Google Home switches, the bottle script) goes through
  `shell_command.babysteps_log`, which runs the same script with `log`.

## Calendar

**Calendar** in the sidebar (`/family-calendar/agenda`) embeds the Ventura County
Events calendar and the family's private Google calendars, with Agenda, Month,
Household schedules and source-link tabs. It relies on each viewing browser's
Google sign-in; nothing is copied into HA. The private calendars' public ICS
links return 404, which is why it uses embeds.
