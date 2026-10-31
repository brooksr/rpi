# Home observer

An always-on service on the HA laptop that watches Home Assistant, flags what's
unusual, and explains it on the **Jarvis** page (top section) and by voice
("Hey Jarvis, anything unusual?").

```
HA recorder DB (read-only) ──► detectors every minute ──► /config/.home-agent.json ──► sensor.home_agent
                                     │ findings changed (≤ 1 per 30 min) or Refresh
                                     ├──► local Qwen (Ollama): one- or two-sentence note
                                     │ 7:30 PM daily or "Digest now"
                                     └──► claude -p (subscription): digest from a cloud-safe summary
```

- **No HA token.** It reads the latest states and hourly statistics straight from
  `home-assistant_v2.db` in read-only mode. It can't control anything.
- **Detectors** (`config.yaml`): baseline (same hour on earlier days, from HA
  long-term statistics), bad states, thresholds (including the laptop running on
  battery, which suggests a power cut), stale feeds, TVs left on, and a sky that
  disagrees with the forecast for half an hour.
- **Sky from the window camera.** Every 10 minutes in daylight (from 1 h after
  sunrise to 1 h before sunset; the camera faces west), the agent measures the
  sky band of `latest.jpg` locally and labels it clear, partly cloudy or overcast.
  Calibrated on 2026-10-27..30 against Met.no cloud cover: the blue-minus-red
  value is ~90–130 on clear days and ~0–30 under overcast or rain. Only the label
  reaches the digest. Readings are in `memory.db` (`sky` table) if the
  thresholds need tuning.
- **Shopping list:** open items from `/config/.shopping_list.json` go into the
  digest (`todo.shopping_list` is in `privacy.cloud`).
- **Baby:** each local day's BabySteps entries (`sensor.babysteps_status` holds
  only today's) are kept in `memory.db` (`baby_days`). On first run, earlier days
  are backfilled from the recorder's ~5 days. The digest gets per-day feeds,
  bottle oz, nursing minutes, sleep and diapers for the last 7 days, plus age
  (from the BabySteps `birth_date`), and gives care tips for that age. Diapers are
  counted by BabySteps' `kind` (wet, dirty or both); its quick-add dialog
  defaults to "wet".
- **Thermostat:** `climate.family_room_nest` mode, setpoint and 24 h
  heating/cooling minutes (from `hvac_action` history) go into the digest. A
  finding is raised when the A/C runs while it's 3°F cooler outside, or the heat
  runs while it's warmer outside. The `household` text in `config.yaml` tells both
  models what equipment the house has.
- **Privacy is enforced in code.** Only entities in `privacy.cloud` or
  `privacy.local_only` are read. A finding goes into the digest only when all of
  its entities are in `privacy.cloud`. The digest receives only hourly
  min/mean/max values and finding text, never raw history or attributes. Every
  payload is saved to `~/home-agent/cloud-log/` (kept 30 days) before it is sent.
- **Qwen shares the CPU with Assist.** A note takes about 40 s, so Qwen runs only
  when the set of findings changes (at most every 30 min) or when you press
  Refresh. When the house is quiet, the "Nothing unusual" note comes from the
  rules and Qwen isn't called.
- Claude runs with `--tools '' --strict-mcp-config --no-session-persistence` in
  an empty directory: text in, text out. If it fails (expired sign-in, usage
  limit), `codex exec --sandbox read-only` gets the same prompt.
- On a quiet day the digest suggests one sensor or data source to add, chosen
  from what isn't in `available_data`.

## Install

```sh
bash scripts/home-agent/install.sh    # service, HA package, Jarvis dashboard
```

Restart HA the first time (new `command_line` sensor and input buttons).

### Daily digest sign-in (one-time, on the laptop)

```sh
ssh HA_USER@HA_HOST
curl -fsSL https://claude.ai/install.sh | bash   # Claude Code CLI to ~/.local/bin
claude setup-token                               # browser sign-in with the Claude subscription
echo 'CLAUDE_CODE_OAUTH_TOKEN=<token>' > ~/home-agent/secrets.env && chmod 600 ~/home-agent/secrets.env
sudo systemctl restart home-agent
```

Until then, the page says the digest is off. Everything else works without it.
Codex (`codex login --device-auth`) is the fallback; `cloud.cli: codex` makes it
the primary.

## Operate

```sh
systemctl status home-agent
journalctl -u home-agent -n 50
cat ~/homeassistant/.home-agent.json
ls ~/home-agent/cloud-log/               # exactly what went to the cloud
sqlite3 ~/home-agent/memory.db 'select * from findings order by started desc limit 20'
```

Tests (Python 3.9+, no PyYAML needed):

```sh
python3.14 -m unittest discover -s scripts/home-agent -p test_agent.py
```

## Next steps

- Weekly digest with the past week's findings, to look for patterns.
- Spoken alerts for warnings (needs quiet hours and an HA token or webhook).
- Allowlisted actions, such as turning off a TV or nudging the Nest setpoint,
  with approval from the page.
