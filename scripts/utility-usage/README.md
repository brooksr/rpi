# Utility usage

Hourly electricity (SCE), gas (SoCalGas) and water (EyeOnWater) use, and the
water meter's leak flag, on the Overview's **Home usage** section and as
statistics for the Energy dashboard. None of the three has an API or a working
HA integration, so a timer on the HA laptop
drives their account sites in Chrome on a virtual display (Xvfb; SoCalGas
rejects headless logins).

```
utility-usage.timer (07:20, 19:20)
  └─ fetch_usage.py run ─► Chrome, saved profile per site (~/utility-usage/profiles)
       │  page loads its own usage request → script copies its headers, replays it
       └─► ~/homeassistant/utility-usage/{sce,socalgas,eyeonwater}.json
             └─ utility_usage component (every 15 min, on change)
                  ├─► statistics utility_usage:sce (kWh), :socalgas (CCF), :eyeonwater (gal)
                  ├─► sensor.utility_usage_<site> + a notification when a login is needed
                  └─► binary_sensor.utility_usage_water_leak + a notification while on
```

| Site | Request | Notes |
|---|---|---|
| SCE | `POST prodms.dms.sce.com/myaccount/v1/usage`, Okta cookies + `oktaUid` header | One local day per call (`startDate` = `endDate`, `numberOfDays: null`). 23/25 ordered rows on DST days. 2+ years kept. ~1–2 days late. |
| SoCalGas | `POST socal.smartcmobile.com/connectorsso/api/usage/daily` from the analyze-usage iframe, `AccessToken` header | Any range up to ~90 days. `BillCycle.CCF` multiplies every reading (therms per CCF); the script sends 1 to get CCF. ~12 months kept (older: code 701). Hours after `LastUsage` are zero padding. |

| EyeOnWater | `POST eyeonwater.com/api/2/residential/consumption` (cookies), `aggregate: hourly`, `date: M/D/YYYY` | One local day per call, newest hour first; fall-back day has 24 rows. Years kept. `new_search` gives `register_0.flags` (Leak, EncoderLeak, ReverseFlow, Tamper, ...) and battery. The meter reports about once a day. The kdeyev/eyeonwater integration can't log in since EyeOnWater moved to Badger Meter's sign-in (its issue #180). |

Data stays local: the script only talks to the utilities' own sites.

## Install

```bash
scripts/utility-usage/install.sh
```

Then on the laptop fill in `~/utility-usage/secrets.env` (`SCE_USERNAME`,
`SCE_PASSWORD`, `SOCALGAS_USERNAME`, `SOCALGAS_PASSWORD`, `EYEONWATER_USERNAME`,
`EYEONWATER_PASSWORD`; mode 600), restart
HA once, and add the statistics under Settings → Dashboards → Energy.

## SCE for now: CSV downloads

SCE's MFA plus session-only cookies mean the scripted login can't stay signed
in, so the timer runs SoCalGas and EyeOnWater only. Electricity comes
from SCE's "Download my data" CSV (My Account → Usage → hourly, CSV):

```bash
scp ~/Downloads/SCE_Usage_*.csv <laptop>:/tmp/ && ssh <laptop> \
  '~/utility-usage/venv/bin/python ~/utility-usage/fetch_usage.py import-sce /tmp/SCE_Usage_*.csv && rm /tmp/SCE_Usage_*.csv'
```

Overlapping downloads are fine; hours are replaced, not added. The `Usage*.xlsx`
chart exports are daily/monthly totals and aren't used.

## Logins

`run` reuses each saved session and logs in with the stored password when it
has expired. SCE requires MFA, so its first login, and any later one where it
asks for a code, is done by hand:

```bash
ssh -t <laptop> '~/utility-usage/venv/bin/python ~/utility-usage/fetch_usage.py login sce'
```

It fills the password, then lists the page's buttons and fields: `c N` clicks,
`t N TEXT` types (the code), `done` continues to the fetch. A screenshot of each
step goes to `~/utility-usage/login.png`. SoCalGas (2FA off) and EyeOnWater log
in by themselves on every run; their sessions don't outlive the browser.

How long SCE's session lasts is unknown (being measured from 2026-11-03): watch
`sensor.utility_usage_sce`'s `last_success`.

## Tests

```bash
python3.14 -m unittest discover -s scripts/utility-usage -p 'test_*.py'
```
