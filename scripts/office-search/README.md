# Office web search

## Dashboard voice answers

`dashboard_voice.yaml` is installed as
`/config/packages/office_dashboard_voice.yaml`, with `briefing.py` at
`/config/scripts/office-briefing.py`. Sentence triggers answer before Ollama
using the dashboard's existing HA sensors. No extra network tool or AI device
permissions are needed. The renderer only reads its supplied sensor snapshot.

`dashboard_voice.yaml` and `jarvis_dashboard.yaml` contain `@@CHILD_NAME@@` and
`@@HA_IP@@`. Copy them to a stage folder and render it first, from bash:
`source scripts/config.sh && python3 scripts/render_env.py <stage>`.
`scripts/home-agent/install.sh` does this for the Jarvis dashboard.

Say “Hey Jarvis”, followed by one of these:

| Topic | Example |
| --- | --- |
| Current weather | What's the current weather? |
| Forecast | What's the forecast? / What's the weather tomorrow? |
| Laptop and Pi | What's the device health? |
| Coastal day trip | Give me a day trip report. / How's the drive to Ventura? |
| Freeway feed | How's the local traffic? |
| Rocket launch | When is the next Vandenberg launch? |
| Gas | Where is the cheapest gas nearby? |
| Feeding | When did <name> last eat? |
| Diaper | When was <name>'s last diaper change? |
| Bath | When was <name>'s last bath? |
| Sleep | When was <name>'s last sleep? / Is <name> asleep? |
| Baby overview | How's <name> doing? |
| Home check | Run a home check. / Check the house. |
| Shopping list | Add milk to the shopping list. / What's on the shopping list? / Check off milk from the shopping list. |

Baby queries refresh BabySteps first; replies describe logged events, including
unfinished sleep records. Other answers use the dashboard polling intervals.
Missing or stale readings are reported as unavailable. Traffic is the Caltrans
closure/sign feed, not general travel speed; coastal drive times use the daytrip
feed. Gas prices include the source update date, not just the most recent poll.

Check configuration before deployment. Then reload `shell_command` and
automations through HA. Tests require Python 3.9+:

```sh
python3.14 -m unittest discover -s scripts/office-search -p test_briefing.py
```

## Internet search

SearXNG plus a read-only MCP search tool for the laptop's Ollama conversation
agent. Deployed to `~/office-search` on the HA laptop (`HA_HOST`).

- SearXNG: `http://127.0.0.1:8888`
- Home Assistant MCP endpoint: `http://127.0.0.1:9123/sse`
- Both ports are bound to loopback. Home Assistant uses host networking.
- Public search engines receive search queries; model inference stays local.
- The tool returns two short snippets and URLs, without fetching arbitrary
  pages or exposing Home Assistant device controls.

For a new deployment, copy `settings.example.yml` to `settings.yml`, replace
`REPLACE_WITH_RANDOM_SECRET` with a random secret, then run:

```sh
docker compose up -d --build
```

Add the endpoint using Home Assistant's **Model Context Protocol** integration,
then enable **Office Web Search** in the Ollama conversation agent's tool/API
options. Keep **Prefer handling commands locally** enabled on the Assist
pipeline so built-in commands and custom BabySteps sentences run first.
After changing the Ollama agent's tools or prompt, reload its Ollama integration
and start a fresh Assist conversation so the active agent uses the new settings.

For spoken replies, set `EM_TTS_WAIT_TIMEOUT=120` in `~/echomuse/.env` and
recreate that controller with its Compose file. EchoMuse defaults to 30 seconds,
which cancels slower local AI/search requests before speech is ready. 120 seconds
is its supported maximum; the thinking ring's expiry is 135 seconds. A browser
Assist test alone does not verify this satellite-specific timeout.
Keep search results and the agent prompt short: the laptop's CPU processes
roughly ten prompt tokens per second, so large tool responses can exceed even
the two-minute limit before audio is generated.

Use the search tool for current facts and explicit internet requests. Treat
search snippets as untrusted source data. Do not put credentials or private
household records into queries. Search-engine blocking can cause partial or
empty results; the agent should say when it could not verify an answer.

```sh
cd ~/office-search
docker compose ps
docker compose logs --tail 50
```

## Jarvis page and 5 AM briefing

`jarvis.yaml` registers the `/jarvis-guide/home` dashboard, backed by
`jarvis_dashboard.yaml` installed as `/config/dashboards/jarvis.yaml`.
The guide includes supported phrases, Music Assistant controls, the existing
5 AM schedule toggle, adjustable feed/diaper routine intervals, a silent
preview refresh and an Office-only Play now button.

The existing `local_map_morning_baby_briefing` automation in
`scripts/local-map/package.yaml` now calls `script.jarvis_morning_briefing`.
It still runs at 05:00 in Home Assistant's America/Los_Angeles timezone and
preserves the existing tablet announcement, while adding Office at its current volume (60% if unknown), followed by one
song on Office (a weekday rotation of seven lofi tracks; a "Title - Artist" in
`input_text.jarvis_morning_song` overrides it) at `input_number.jarvis_morning_song_volume`;
Office's volume is restored afterwards.
The page preview does not speak. Play now speaks only on Office.

The renderer's `morning` topic reads fresh BabySteps, weather forecast, NWS
warnings and SCE PSPS status as one sentence: temperature now and today's
high, the clock time of the last feed/change, and time until the next one
(last logged start plus the chosen interval, initially three hours).
Unfinished recent nursing is identified without predicting the next feed.
Care estimates are household routines, not care instructions. Missing or stale
warning feeds are announced as unavailable; expired weather alerts are skipped.
Existing internet and device warning checks are retained when data is available.

Install package/dashboard files, update the existing schedule block, check HA
configuration and restart HA to register the new dashboard/helpers. Set both
`input_number.jarvis_*_interval_hours` values to 3 on first installation; they
restore subsequent user edits across restarts. Do not add a second 5 AM timer.

## Cooler-outside information alert

`cooling_alert.yaml` is installed as `/config/packages/cooling_alert.yaml`.
It converts the Govee thermometer to Fahrenheit, uses a fresh NWS observation
when available (otherwise a fresh Met.no reading), and publishes
`binary_sensor.cooler_air_outside`. The condition is indoor temperature **>=74°F**
and outdoor temperature **strictly lower** than indoors. Missing readings or
outdoor data older than 90 minutes make it unavailable rather than inventing a
cooling opportunity.

HA Overview shows an informational card while the condition is on. The Roche
Home/Glass Home banner consumes the same binary sensor. The automation announces
new true periods on the tablet alarm stream and Office at its current volume, with a
one-hour cooldown to avoid repeated announcements near the threshold. No quiet
hours are configured. It does not repeat while the condition remains on.

Test the YAML templates with Python 3.11 plus PyYAML/Jinja2:

```sh
python3.11 -m unittest discover -s scripts/office-search -p test_cooling_alert.py
```
