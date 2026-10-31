#!/usr/bin/env python3
"""Home observer: watch Home Assistant, flag what's unusual, explain it.

Runs on the HA laptop as the home-agent service. Every minute it reads the
latest states from HA's recorder database (read-only, no HA token), runs
simple detectors from config.yaml, and writes /config/.home-agent.json for
sensor.home_agent (the Jarvis page). When the set of findings changes, local
Qwen (Ollama) writes a short note. Once a day, a subscription CLI (claude or
codex) writes a digest from a cloud-safe summary; every payload it sends is
saved under cloud-log/ first.

Privacy is enforced here, not by prompt: only entities matching
privacy.cloud or privacy.local_only are ever read, and a finding reaches the
cloud only when all of its entities match privacy.cloud.
"""

import fnmatch
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from statistics import mean, pstdev
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
BASELINE_DAYS = 14
BASELINE_MIN_SAMPLES = 5


def matches(entity_id, patterns):
    return any(fnmatch.fnmatchcase(entity_id, p) for p in patterns or ())


def cloud_safe(entities, privacy):
    return bool(entities) and all(matches(e, privacy.get('cloud')) for e in entities)


def attribute(state, path):
    """Dotted attribute lookup, e.g. battery.percent."""
    value = state['attributes']
    for part in path.split('.'):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def number(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def fmt(value):
    return f'{value:.0f}' if abs(value) >= 10 else f'{value:.1f}'.rstrip('0').rstrip('.')


def clock(ts, tz):
    return datetime.fromtimestamp(ts, tz).strftime('%-I:%M %p')


def minutes_text(minutes):
    minutes = int(minutes)
    if minutes < 90:
        return f'{minutes} min'
    hours, rest = divmod(minutes, 60)
    return f'{hours} h {rest} min' if rest else f'{hours} h'


# --- Home Assistant recorder (read-only) ---------------------------------

def open_recorder(path):
    return sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=10)


def read_states(db, patterns):
    """Latest recorded state of every entity matching patterns."""
    metas = {mid: eid for mid, eid in db.execute('SELECT metadata_id, entity_id FROM states_meta')
             if matches(eid, patterns)}
    if not metas:
        return {}
    marks = ','.join('?' * len(metas))
    rows = db.execute(
        'SELECT s.metadata_id, s.state, COALESCE(s.last_changed_ts, s.last_updated_ts), s.last_updated_ts, '
        'a.shared_attrs FROM states s LEFT JOIN state_attributes a ON a.attributes_id = s.attributes_id '
        f'WHERE s.state_id IN (SELECT MAX(state_id) FROM states WHERE metadata_id IN ({marks}) '
        'GROUP BY metadata_id)', list(metas))
    states = {}
    for mid, state, changed, updated, attrs in rows:
        try:
            attributes = json.loads(attrs) if attrs else {}
        except ValueError:
            attributes = {}
        states[metas[mid]] = {'state': state, 'last_changed': changed, 'last_updated': updated,
                              'attributes': attributes}
    return states


def state_history(db, entity_id, since_ts):
    """Recorded states of one entity since since_ts, oldest first."""
    rows = db.execute(
        'SELECT s.state, s.last_updated_ts, a.shared_attrs FROM states s '
        'JOIN states_meta m ON m.metadata_id = s.metadata_id '
        'LEFT JOIN state_attributes a ON a.attributes_id = s.attributes_id '
        'WHERE m.entity_id = ? AND s.last_updated_ts >= ? ORDER BY s.last_updated_ts', (entity_id, since_ts))
    for state, updated, attrs in rows:
        try:
            attributes = json.loads(attrs) if attrs else {}
        except ValueError:
            attributes = {}
        yield {'state': state, 'last_updated': updated, 'attributes': attributes}


def hourly_means(db, entity_id, since_ts):
    """[(hour_start_ts, mean)] from HA's long-term statistics."""
    return db.execute(
        'SELECT s.start_ts, s.mean FROM statistics s JOIN statistics_meta m ON m.id = s.metadata_id '
        'WHERE m.statistic_id = ? AND s.start_ts >= ? AND s.mean IS NOT NULL ORDER BY s.start_ts',
        (entity_id, since_ts)).fetchall()


# --- Detectors -----------------------------------------------------------

def finding(kind, entity, title, detail, since, severity='info', extra=''):
    return {'key': f'{kind}:{entity}{extra}', 'severity': severity, 'title': title, 'detail': detail,
            'since': since, 'entities': [entity]}


def detect_stale(cfg, states, now):
    found = []
    for rule in cfg:
        state = states.get(rule['entity'])
        if state is None:
            continue
        if state['state'] in ('unavailable', 'unknown'):
            # Reloads and restarts make sensors briefly unavailable.
            if (now - state['last_changed']) / 60 >= rule.get('unavailable_minutes', 10):
                found.append(finding('stale', rule['entity'], rule['label'], 'Unavailable.',
                                     state['last_changed'], rule.get('severity', 'warning')))
            continue
        age = (now - state['last_updated']) / 60
        if age > rule['max_minutes']:
            found.append(finding('stale', rule['entity'], rule['label'],
                                 f'No update for {minutes_text(age)}.', state['last_updated'],
                                 rule.get('severity', 'warning')))
    return found


def detect_bad_state(cfg, states, now):
    found = []
    for rule in cfg:
        state = states.get(rule['entity'])
        if state is None or state['state'] not in rule['states']:
            continue
        if (now - state['last_changed']) / 60 >= rule.get('for_minutes', 0):
            found.append(finding('state', rule['entity'], rule['label'],
                                 rule.get('detail', f"{state['state'].capitalize()}."),
                                 state['last_changed'], rule.get('severity', 'warning')))
    return found


def detect_on_too_long(cfg, states, now):
    found = []
    for rule in cfg:
        state = states.get(rule['entity'])
        if state is None or state['state'] not in rule.get('states', ['on']):
            continue
        minutes = (now - state['last_changed']) / 60
        if minutes >= rule['max_minutes']:
            found.append(finding('on', rule['entity'], rule['label'],
                                 f"{state['state'].capitalize()} for {minutes_text(minutes // 15 * 15)}.",
                                 state['last_changed'], rule.get('severity', 'info')))
    return found


def detect_threshold(cfg, states, now):
    found = []
    for rule in cfg:
        state = states.get(rule['entity'])
        if state is None:
            continue
        path = rule.get('attribute')
        raw = attribute(state, path) if path else state['state']
        suffix = f':{path}' if path else ''
        if 'equals' in rule:
            hit = raw == rule['equals']
            detail = rule['detail']
        else:
            value = number(raw)
            if value is None:
                continue
            hit = ('above' in rule and value > rule['above']) or ('below' in rule and value < rule['below'])
            detail = rule.get('detail', '{value}{unit}.').format(value=fmt(value), unit=rule.get('unit', ''))
        if hit:
            found.append(finding('threshold', rule['entity'], rule['label'], detail, state['last_updated'],
                                 rule.get('severity', 'warning'), suffix))
    return found


def baseline(points, hour, tz, before_ts):
    """Mean and spread of one local hour-of-day across earlier days."""
    values = [v for ts, v in points
              if ts < before_ts and datetime.fromtimestamp(ts, tz).hour == hour]
    if len(values) < BASELINE_MIN_SAMPLES:
        return None
    return mean(values), pstdev(values), len(values)


def detect_baseline(cfg, states, now, db, tz):
    found = []
    local = datetime.fromtimestamp(now, tz)
    since = now - BASELINE_DAYS * 86400
    for rule in cfg:
        state = states.get(rule['entity'])
        value = number(state['state']) if state else None
        if value is None:
            continue
        typical = baseline(hourly_means(db, rule['entity'], since), local.hour, tz, now - 12 * 3600)
        if typical is None:
            continue
        mu, sd, _ = typical
        delta = value - mu
        if abs(delta) < max(rule['min_delta'], 2.5 * sd):
            continue
        unit = state['attributes'].get('unit_of_measurement', '')
        unit = unit if unit.startswith('°') else f' {unit}' if unit else ''
        direction = 'above' if delta > 0 else 'below'
        found.append(finding(
            'baseline', rule['entity'], rule['label'],
            f'{fmt(value)}{unit}, {fmt(abs(delta))}{unit} {direction} its usual {fmt(mu)}{unit} at this hour.',
            state['last_changed'], rule.get('severity', 'info'), f':{direction}'))
    return found


def detect_hvac_outside(cfg, states, now):
    """A/C or heat running when opening a window would do the job."""
    found = []
    for rule in cfg:
        state = states.get(rule['entity'])
        outside = number(states.get(rule['outdoor'], {}).get('state'))
        if state is None or outside is None:
            continue
        inside = number(state['attributes'].get('current_temperature'))
        action = state['attributes'].get('hvac_action')
        margin = rule.get('margin', 3)
        if inside is None:
            continue
        if action == 'cooling' and outside <= inside - margin:
            title = 'A/C running, cooler outside'
        elif action == 'heating' and outside >= inside + margin:
            title = 'Heat running, warmer outside'
        else:
            continue
        item = finding('hvac', rule['entity'], title,
                       f'It is {outside:.0f}°F outside and {inside:.0f}°F inside.', now, 'info', f':{action}')
        item['entities'].append(rule['outdoor'])
        found.append(item)
    return found


SUNNY = ('sunny', 'clear-night')
WET_OR_GREY = ('rainy', 'pouring', 'lightning-rainy', 'cloudy', 'snowy', 'fog')


def detect_sky(cfg, readings, states, now):
    """Camera sky that disagrees with the forecast for half an hour (e.g. marine layer)."""
    recent = [(at, label) for at, label in readings if now - at <= 35 * 60]
    forecast = states.get('weather.forecast_home', {}).get('state')
    if not cfg or len(recent) < 3 or len({label for _, label in recent}) != 1 or forecast is None:
        return []
    label = recent[0][1]
    if label == 'overcast' and forecast in SUNNY:
        detail = 'The camera sees an overcast sky, but the forecast says sunny.'
    elif label == 'clear' and forecast in WET_OR_GREY:
        detail = f'The camera sees a clear sky, but the forecast says {forecast.replace("-", " ")}.'
    else:
        return []
    item = finding('sky', cfg['entity'], 'Sky differs from forecast', detail, recent[0][0])
    item['entities'].append('weather.forecast_home')
    return [item]


def detect(config, states, now, db, tz, sky_readings=()):
    rules = config.get('detectors', {})
    found = (detect_bad_state(rules.get('bad_state', []), states, now)
             + detect_threshold(rules.get('threshold', []), states, now)
             + detect_stale(rules.get('stale', []), states, now)
             + detect_on_too_long(rules.get('on_too_long', []), states, now)
             + detect_baseline(rules.get('baseline', []), states, now, db, tz)
             + detect_hvac_outside(rules.get('hvac_outside', []), states, now)
             + detect_no_dirty_diaper(config.get('baby'), states, now, tz)
             + detect_sky(config.get('sky'), sky_readings, states, now))
    privacy = config['privacy']
    for item in found:
        item['cloud'] = cloud_safe(item['entities'], privacy)
    found.sort(key=lambda f: (f['severity'] != 'warning', f['since']))
    return found


# --- Sky from the office window camera -------------------------------------
# Only a label leaves this machine; the image is read locally and never sent.

def measure_sky(path, crop):
    """Mean blue-minus-red of the sky crop: ~90-130 clear, ~0-30 overcast."""
    from PIL import Image, ImageStat  # python3-pil on the laptop
    with Image.open(path) as image:
        sky = image.convert('RGB').crop(tuple(crop)).resize((128, 28))
    red, _, blue = ImageStat.Stat(sky).mean
    return blue - red


def sky_label(blue, cfg):
    if blue >= cfg['clear_blue']:
        return 'clear'
    if blue <= cfg['overcast_blue']:
        return 'overcast'
    return 'partly cloudy'


def daylight(states, now, margin_minutes):
    """Sun well above the horizon: low sun into a west-facing camera washes out the sky.

    Sunrise is mirrored from solar noon and sunset, because sun.sun's last_changed
    resets whenever HA restarts.
    """
    try:
        sets = datetime.fromisoformat(states['sensor.sun_next_setting']['state']).timestamp()
        noon = datetime.fromisoformat(states['sensor.sun_next_noon']['state']).timestamp()
    except (KeyError, ValueError):
        return False
    if noon > sets:  # afternoon: the next noon is tomorrow's
        noon -= 86400
    rises = noon - (sets - noon)
    margin = margin_minutes * 60
    return rises + margin <= now <= sets - margin


def observe_sky(cfg, memory, states, now):
    """Record a sky label every few minutes in daylight; return the last hour of readings."""
    last = memory.execute('SELECT MAX(at) FROM sky').fetchone()[0] or 0
    path = cfg['image']
    if (now - last >= cfg.get('every_minutes', 10) * 60 and daylight(states, now, cfg.get('daylight_margin_minutes', 60))
            and os.path.exists(path) and now - os.path.getmtime(path) < 300):
        blue = measure_sky(path, cfg['crop'])
        memory.execute('INSERT INTO sky VALUES (?, ?, ?)', (now, sky_label(blue, cfg), round(blue, 1)))
        memory.execute('DELETE FROM sky WHERE at < ?', (now - 30 * 86400,))
        memory.commit()
    return memory.execute('SELECT at, label FROM sky WHERE at >= ? ORDER BY at', (now - 3600,)).fetchall()


# --- Baby (BabySteps) and thermostat history ------------------------------

OUNCES = re.compile(r'(\d+(?:\.\d+)?) ?oz')
MINUTES = re.compile(r'(\d+) min')


def save_baby_day(memory, state, tz):
    """Keep each local day's BabySteps entries; the sensor only holds today's."""
    attrs = state['attributes']
    if state['state'] != 'ok' or not isinstance(attrs.get('events'), list):
        return
    try:
        checked = datetime.fromisoformat(attrs['checked_at']).timestamp()
    except (KeyError, TypeError, ValueError):
        checked = state['last_updated']
    day = datetime.fromtimestamp(checked, tz).date().isoformat()
    memory.execute('INSERT OR REPLACE INTO baby_days VALUES (?, ?)', (day, json.dumps(attrs['events'])))


def backfill_baby_days(memory, db, entity, tz):
    """Once: rebuild earlier days from the recorder (it keeps about 5 days)."""
    if kv_get(memory, 'baby_backfilled'):
        return
    for state in state_history(db, entity, 0):
        save_baby_day(memory, state, tz)
    kv_set(memory, 'baby_backfilled', True)


def baby_day_summary(events):
    def ts(value):
        return datetime.fromisoformat(value).timestamp()

    feeds = [e for e in events if e.get('type') == 'feed']
    feed_times = sorted(ts(e['time']) for e in feeds)
    gaps = [b - a for a, b in zip(feed_times, feed_times[1:])]
    sleeps = [(ts(e['endedAt']) - ts(e['time'])) / 60 for e in events
              if e.get('type') == 'sleep' and e.get('endedAt')]
    diapers = {}
    for e in events:
        if e.get('type') == 'diaper':
            kind = e.get('text', '').split('·')[-1].strip() or 'change'
            diapers[kind] = diapers.get(kind, 0) + 1
    other = {}
    for e in events:
        if e.get('type') not in ('feed', 'sleep', 'diaper'):
            other[e.get('type')] = other.get(e.get('type'), 0) + 1
    summary = {
        'feeds': len(feeds),
        'bottle_oz': sum(float(m.group(1)) for e in feeds if (m := OUNCES.search(e.get('text', '')))),
        'nursing_minutes': sum(int(m.group(1)) for e in feeds
                               if 'Nursing' in e.get('text', '') and (m := MINUTES.search(e['text']))),
        'longest_gap_between_feeds_h': round(max(gaps) / 3600, 1) if gaps else None,
        'naps_or_sleeps': len(sleeps),
        'sleep_logged_h': round(sum(sleeps) / 60, 1),
        'longest_sleep_h': round(max(sleeps) / 60, 1) if sleeps else None,
        'diapers': diapers,
    }
    if other:
        summary['other'] = other
    return summary


def detect_no_dirty_diaper(cfg, states, now, tz):
    """Days since the last dirty diaper, against the pediatrician's limit in config."""
    state = states.get(cfg['entity']) if cfg else None
    last = state and state['attributes'].get('lastDirtyDiaper')
    if not last or 'no_dirty_limit_days' not in cfg:
        return []
    at = datetime.fromisoformat(last).timestamp()
    days = (now - at) / 86400
    if days < cfg.get('no_dirty_notice_days', cfg['no_dirty_limit_days'] - 2):
        return []
    limit = at + cfg['no_dirty_limit_days'] * 86400
    when = datetime.fromtimestamp(limit, tz).strftime('%a %b %-d, %-I:%M %p')
    detail = (f"{days:.1f} days since the last dirty diaper ({datetime.fromtimestamp(at, tz).strftime('%a %b %-d, %-I:%M %p')}). "
              + (f"The pediatrician's {cfg['no_dirty_limit_days']}-day limit is {when}." if now < limit
                 else f"Past the pediatrician's {cfg['no_dirty_limit_days']}-day limit since {when}; call the pediatrician."))
    return [finding('baby', cfg['entity'], 'No dirty diaper', detail, at,
                    'warning' if now >= limit - 86400 else 'info', ':no_dirty')]


def baby_summary(memory, state, now, tz, days=7, cfg=None):
    attrs = state['attributes']
    today = datetime.fromtimestamp(now, tz).date()
    summary = {'name': attrs.get('child')}
    if cfg and cfg.get('care_notes'):
        summary['care_notes_from_parents'] = cfg['care_notes']
    if attrs.get('lastDirtyDiaper'):
        at = datetime.fromisoformat(attrs['lastDirtyDiaper']).timestamp()
        summary['last_dirty_diaper'] = (f"{datetime.fromtimestamp(at, tz).strftime('%a %b %-d %-I:%M %p')}, "
                                        f"{(now - at) / 86400:.1f} days ago")
    if attrs.get('birth_date'):
        born = datetime.fromisoformat(attrs['birth_date'])
        born = (born.astimezone(tz) if born.tzinfo else born).date()
        age = (today - born).days
        summary['age'] = f'{age // 7} weeks {age % 7} days'
    summary['by_day'] = {}
    rows = memory.execute('SELECT day, events FROM baby_days WHERE day >= ? ORDER BY day',
                          ((today - timedelta(days=days - 1)).isoformat(),))
    for day, events in rows:
        label = day + (' (today so far)' if day == today.isoformat() else '')
        summary['by_day'][label] = baby_day_summary(json.loads(events))
    for key, label in (('lastFeed', 'last_feed'), ('lastDiaper', 'last_diaper'), ('lastSleep', 'last_sleep')):
        last = attrs.get(key)
        if isinstance(last, dict) and last.get('at'):
            at = datetime.fromisoformat(last['at']).timestamp()
            summary[label] = f'{clock(at, tz)}, {minutes_text((now - at) / 60)} ago'
    if attrs.get('days_since_bath') is not None:
        summary['days_since_bath'] = attrs['days_since_bath']
    return summary


def hvac_runtime(db, entity, since, now):
    """Minutes heating and cooling since `since`, from the climate entity's hvac_action."""
    totals = {'heating': 0.0, 'cooling': 0.0}
    first = None
    prev_ts = prev_action = None
    for state in state_history(db, entity, since - 86400):
        first = first or state['last_updated']
        at = max(state['last_updated'], since)
        if prev_action in totals:
            totals[prev_action] += at - prev_ts
        prev_ts, prev_action = at, state['attributes'].get('hvac_action')
    if prev_action in totals:
        totals[prev_action] += now - prev_ts
    return {f'{k}_minutes': round(v / 60) for k, v in totals.items()}, first


def thermostat_summary(db, entity, state, now, tz):
    attrs = state['attributes']
    runtime, first = hvac_runtime(db, entity, now - 86400, now)
    summary = {'mode': state['state'], 'action_now': attrs.get('hvac_action'),
               'indoor_f': attrs.get('current_temperature'), 'indoor_humidity': attrs.get('current_humidity'),
               'setpoint_f': attrs.get('temperature') or [attrs.get('target_temp_low'), attrs.get('target_temp_high')],
               'last_24h': runtime}
    if first and first > now - 86400:
        summary['history_since'] = datetime.fromtimestamp(first, tz).strftime('%a %-I:%M %p')
    return summary


# --- Agent memory --------------------------------------------------------

def open_memory(path):
    db = sqlite3.connect(path)
    db.executescript('''
        CREATE TABLE IF NOT EXISTS findings (
          key TEXT, severity TEXT, title TEXT, detail TEXT, entities TEXT, cloud INTEGER,
          started REAL, ended REAL);
        CREATE INDEX IF NOT EXISTS findings_open ON findings (key, ended);
        CREATE TABLE IF NOT EXISTS notes (at REAL, kind TEXT, source TEXT, text TEXT, sent_bytes INTEGER);
        CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS sky (at REAL, label TEXT, blue REAL);
        CREATE TABLE IF NOT EXISTS baby_days (day TEXT PRIMARY KEY, events TEXT);
    ''')
    return db


def kv_get(db, key, default=None):
    row = db.execute('SELECT value FROM kv WHERE key = ?', (key,)).fetchone()
    return json.loads(row[0]) if row else default


def kv_set(db, key, value):
    db.execute('INSERT OR REPLACE INTO kv VALUES (?, ?)', (key, json.dumps(value)))
    db.commit()


def record_findings(db, found, now):
    """Open new findings and close ones that cleared; returns True on change."""
    active = {f['key']: f for f in found}
    open_keys = {k for (k,) in db.execute('SELECT key FROM findings WHERE ended IS NULL')}
    for key in open_keys - set(active):
        db.execute('UPDATE findings SET ended = ? WHERE key = ? AND ended IS NULL', (now, key))
    for key in set(active) - open_keys:
        f = active[key]
        db.execute('INSERT INTO findings VALUES (?, ?, ?, ?, ?, ?, ?, NULL)',
                   (key, f['severity'], f['title'], f['detail'], json.dumps(f['entities']),
                    int(f['cloud']), f['since']))
    db.commit()
    # Report each finding from when it first appeared.
    for key, started in db.execute('SELECT key, started FROM findings WHERE ended IS NULL'):
        if key in active:
            active[key]['since'] = started
    return open_keys != set(active)


def last_note(db, kind):
    row = db.execute('SELECT at, source, text, sent_bytes FROM notes WHERE kind = ? ORDER BY at DESC, rowid DESC LIMIT 1',
                     (kind,)).fetchone()
    return dict(zip(('at', 'source', 'text', 'sent_bytes'), row)) if row else None


def save_note(db, kind, source, text, now, sent_bytes=None):
    db.execute('INSERT INTO notes VALUES (?, ?, ?, ?, ?)', (now, kind, source, text, sent_bytes))
    db.commit()


# --- Local note (Qwen) ---------------------------------------------------

NOTE_PROMPT = (
    'You watch over a family home and write for a wall dashboard. Write one or two plain '
    'sentences about the findings: what matters most, then one practical suggestion if there '
    'is an obvious one, such as opening a window, adjusting the thermostat or turning something '
    'off. Every sentence must be about a finding; the background line is only context. Use only '
    'the facts given. No labels, no greeting, no markdown.')


def finding_line(f, tz):
    return f"- [{f['severity']}] {f['title']}: {f['detail']} (since {clock(f['since'], tz)})"


def ollama_note(cfg, found, context, tz):
    lines = [finding_line(f, tz) for f in found]
    body = {
        'model': cfg['model'], 'stream': False,
        'options': {'temperature': 0.2, 'num_predict': 90},
        'messages': [{'role': 'system', 'content': f"{NOTE_PROMPT} About the home: {cfg.get('household', '')}"},
                     {'role': 'user', 'content': '\n'.join(['Findings:', *lines, f'Background: {context}'])}],
    }
    request = urllib.request.Request(f"{cfg['url']}/api/chat", json.dumps(body).encode(),
                                     {'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=cfg.get('timeout_seconds', 240)) as response:
        return json.load(response)['message']['content'].strip()


def context_line(states, now, tz, sky=None):
    parts = [datetime.fromtimestamp(now, tz).strftime('It is %A %-I:%M %p.')]
    for entity, label in (('sensor.cooling_indoor_temperature', 'Office'),
                          ('sensor.cooling_outdoor_temperature', 'outside')):
        value = number(states.get(entity, {}).get('state'))
        if value is not None:
            parts.append(f'{label} {value:.0f}°F.')
    if sky:
        parts.append(f'Sky (window camera): {sky}.')
    return ' '.join(parts)


# --- Cloud digest (claude / codex CLI) -----------------------------------

DIGEST_PROMPT = (
    'You review one day of summarized sensor data from a family home. The JSON below is all the '
    'data you have; sky_camera_by_hour is estimated from a west-facing window camera. Write '
    'short plain-text bullet points starting with "- ", under 180 words in all:\n'
    '1. Up to 4 notable home patterns or changes versus typical, with at most two practical '
    'suggestions. If nothing stands out, say so in one bullet and suggest one sensor or data '
    'source not in available_data that would make these observations more useful, and why.\n'
    '2. If baby data is present: one bullet on how the baby\'s logged feeding, sleep and diapers '
    'compare across the days shown, then one or two practical care tips suited to the baby\'s '
    'age and to what the logs show. Logs may be incomplete; say "logged" rather than assuming '
    'every event was recorded. care_notes_from_parents include what the pediatrician told them; '
    'follow it rather than generic thresholds. These are general tips, not medical advice; if '
    'something looks concerning, suggest checking with the pediatrician.')


def daily_summary(config, db, memory, states, now, tz):
    """Cloud-safe summary of the last 24 hours. Only privacy.cloud entities."""
    privacy = config['privacy']
    local = datetime.fromtimestamp(now, tz)
    day_start = now - 86400
    summary = {'date': local.strftime('%A %Y-%m-%d'), 'time': local.strftime('%-I:%M %p'),
               'sensors': [], 'findings_last_24h': [], 'current': {}}
    for rule in config.get('detectors', {}).get('baseline', []):
        entity = rule['entity']
        if not matches(entity, privacy.get('cloud')):
            continue
        points = hourly_means(db, entity, now - BASELINE_DAYS * 86400)
        today = [v for ts, v in points if ts >= day_start]
        earlier = [v for ts, v in points if ts < day_start]
        if not today:
            continue
        unit = states.get(entity, {}).get('attributes', {}).get('unit_of_measurement', '')
        entry = {'label': rule['label'], 'unit': unit, 'last_24h': {
            'min': round(min(today), 1), 'mean': round(mean(today), 1), 'max': round(max(today), 1)}}
        if len(earlier) >= 24:
            entry['typical'] = {'min': round(min(earlier), 1), 'mean': round(mean(earlier), 1),
                                'max': round(max(earlier), 1), 'days': round(len(earlier) / 24)}
        summary['sensors'].append(entry)
    rows = memory.execute('SELECT severity, title, detail, entities, started, ended FROM findings '
                          'WHERE cloud = 1 AND (ended IS NULL OR ended >= ?) ORDER BY started',
                          (day_start,))
    for severity, title, detail, entities, started, ended in rows:
        if not cloud_safe(json.loads(entities), privacy):
            continue
        summary['findings_last_24h'].append({
            'severity': severity, 'title': title, 'detail': detail, 'start': clock(started, tz),
            'end': clock(ended, tz) if ended else 'still active',
            'minutes': round(((ended or now) - started) / 60)})
    for item in config.get('digest_context', []):
        entity = item['entity']
        state = states.get(entity)
        if state is None or not matches(entity, privacy.get('cloud')):
            continue
        value = {'state': state['state']}
        for name in item.get('attributes', []):
            if attribute(state, name) is not None:
                value[name] = attribute(state, name)
        summary['current'][item['label']] = value
    sky = config.get('sky')
    if sky and matches(sky['entity'], privacy.get('cloud')):
        by_hour = {}
        for at, label in memory.execute('SELECT at, label FROM sky WHERE at >= ? ORDER BY at', (day_start,)):
            by_hour.setdefault(datetime.fromtimestamp(at, tz).strftime('%a %-I %p'), []).append(label)
        summary['sky_camera_by_hour'] = {hour: max(set(labels), key=labels.count)
                                         for hour, labels in by_hour.items()}
    if config.get('shopping_list') and matches('todo.shopping_list', privacy.get('cloud')):
        summary['shopping_list'] = read_shopping_list(config['shopping_list'])
    baby = config.get('baby')
    if baby and matches(baby['entity'], privacy.get('cloud')) and baby['entity'] in states:
        summary['baby'] = baby_summary(memory, states[baby['entity']], now, tz, cfg=baby)
    thermostat = config.get('thermostat')
    if thermostat and matches(thermostat, privacy.get('cloud')) and thermostat in states:
        summary['thermostat'] = thermostat_summary(db, thermostat, states[thermostat], now, tz)
    rules = [rule for group in config.get('detectors', {}).values() for rule in group]
    summary['available_data'] = sorted(
        {rule['label'] for rule in rules + config.get('digest_context', [])
         if 'label' in rule and matches(rule['entity'], privacy.get('cloud'))}
        | ({'BabySteps logs'} if 'baby' in summary else set())
        | ({'Nest thermostat'} if 'thermostat' in summary else set())
        | ({'Sky from window camera'} if 'sky_camera_by_hour' in summary else set()))
    return summary


def read_shopping_list(path):
    """Open items in HA's shopping list (the file appears with the first item)."""
    try:
        with open(path) as f:
            return [item['name'] for item in json.load(f) if not item.get('complete')]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def cli_path(name):
    return shutil.which(name, path=os.pathsep.join(
        [os.path.expanduser('~/.local/bin'), os.environ.get('PATH', '')]))


def cloud_clis(cfg):
    """Installed CLIs to try, in order: cli, then fallback."""
    names = [cfg.get('cli', 'none'), cfg.get('fallback') or 'none']
    return [(name, cli_path(name)) for name in dict.fromkeys(names)
            if name != 'none' and cli_path(name)]


def cloud_command(cli, path, model=None):
    if cli == 'codex':
        handle, out = tempfile.mkstemp(prefix='home-agent-', suffix='.txt')
        os.close(handle)
        cmd = [path, 'exec', '--skip-git-repo-check', '--sandbox', 'read-only',
               '--output-last-message', out, '-']
        return cmd, out
    # No tools, no MCP servers, nothing saved: text in, text out.
    cmd = [path, '-p', '--output-format', 'text', '--tools', '', '--strict-mcp-config',
           '--no-session-persistence']
    if model:
        cmd += ['--model', model]
    return cmd, None


def run_cloud(cfg, prompt, workdir):
    """(cli, text) from the first CLI that succeeds."""
    os.makedirs(workdir, exist_ok=True)
    errors = []
    for cli, path in cloud_clis(cfg):
        cmd, out = cloud_command(cli, path, cfg.get('model') if cli == 'claude' else None)
        try:
            result = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=workdir,
                                    timeout=cfg.get('timeout_seconds', 240))
            if result.returncode == 0:
                if out:
                    with open(out) as f:
                        return cli, f.read().strip()
                return cli, result.stdout.strip()
            errors.append(f"{cli}: {(result.stderr or result.stdout).strip()[-200:] or 'failed'}")
        except subprocess.TimeoutExpired:
            errors.append(f'{cli}: timed out')
        finally:
            if out and os.path.exists(out):
                os.unlink(out)
    raise RuntimeError('; '.join(errors) or 'no CLI installed')


def write_cloud_log(log_dir, payload, now):
    os.makedirs(log_dir, exist_ok=True)
    name = datetime.fromtimestamp(now).strftime('%Y-%m-%dT%H%M%S.txt')
    with open(os.path.join(log_dir, name), 'w') as f:
        f.write(payload)
    cutoff = now - 30 * 86400
    for old in os.listdir(log_dir):
        path = os.path.join(log_dir, old)
        if os.path.getmtime(path) < cutoff:
            os.unlink(path)


# --- Main loop -----------------------------------------------------------

def button_pressed(memory, states, entity):
    """True once per new press of an HA input_button (its state is the press time)."""
    state = states.get(entity)
    if state is None:
        return False
    seen = kv_get(memory, f'button:{entity}')
    kv_set(memory, f'button:{entity}', state['state'])
    return seen is not None and seen != state['state'] and state['state'] not in ('unknown', 'unavailable')


def due_digest(cfg, memory, now, tz):
    hour, minute = map(int, cfg.get('digest_time', '19:30').split(':'))
    local = datetime.fromtimestamp(now, tz)
    scheduled = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    last = last_note(memory, 'digest')
    return local >= scheduled and (last is None or last['at'] < scheduled.timestamp())


def write_output(path, data):
    tmp = f'{path}.tmp'
    with open(tmp, 'w') as f:
        json.dump(data, f)
    os.replace(tmp, path)


def note_view(note, tz):
    if note is None:
        return None
    view = {'text': note['text'], 'source': note['source'],
            'at': datetime.fromtimestamp(note['at'], tz).isoformat(timespec='seconds')}
    if note.get('sent_bytes'):
        view['sent_bytes'] = note['sent_bytes']
    return view


def tick(config, memory, tz, status):
    now = time.time()
    privacy = config['privacy']
    controls = config.get('controls', {})
    patterns = list(privacy.get('cloud', [])) + list(privacy.get('local_only', [])) + list(controls.values())
    db = open_recorder(config['recorder_db'])
    try:
        states = read_states(db, patterns)
        baby = config.get('baby')
        if baby and baby['entity'] in states:
            backfill_baby_days(memory, db, baby['entity'], tz)
            save_baby_day(memory, states[baby['entity']], tz)
            memory.commit()
        sky_readings = []
        if config.get('sky'):
            try:
                sky_readings = observe_sky(config['sky'], memory, states, now)
                status.pop('sky_error', None)
            except Exception as e:
                status['sky_error'] = f'Sky camera check failed: {e}'[:200]
        sky_now = sky_readings[-1] if sky_readings and now - sky_readings[-1][0] < 1800 else None
        found = detect(config, states, now, db, tz, sky_readings)
        changed = record_findings(memory, found, now)
        want_note = button_pressed(memory, states, controls.get('note', ''))
        want_digest = button_pressed(memory, states, controls.get('digest', ''))

        local_cfg = config['ollama']
        last = last_note(memory, 'note')
        quiet = last is not None and now - last['at'] < local_cfg.get('min_minutes_between', 30) * 60
        if not found:
            if want_note or last is None or last['source'] != 'rules':
                save_note(memory, 'note', 'rules', 'Nothing unusual right now.', now)
        elif want_note or last is None or (changed and not quiet):
            try:
                text = ollama_note(dict(local_cfg, household=config.get('household', '')), found,
                                   context_line(states, now, tz, sky_now and sky_now[1]), tz)
                save_note(memory, 'note', 'qwen', text, now)
                status.pop('note_error', None)
            except Exception as e:  # keep observing when Ollama is busy or down
                status['note_error'] = f'Local AI unavailable: {e}'[:200]

        cloud_cfg = config['cloud']
        attempted = kv_get(memory, 'digest_attempt', 0)
        spaced = now - attempted >= cloud_cfg.get('min_minutes_between', 30) * 60
        if cloud_cfg.get('cli', 'none') == 'none':
            status.pop('digest_error', None)
        elif not cloud_clis(cloud_cfg):
            status['digest_error'] = f"Daily digest is off until the {cloud_cfg['cli']} CLI is installed and signed in."
        elif spaced and (want_digest or due_digest(cloud_cfg, memory, now, tz)):
            kv_set(memory, 'digest_attempt', now)
            summary = daily_summary(config, db, memory, states, now, tz)
            prompt = (f"{DIGEST_PROMPT}\n\nAbout the home: {config.get('household', '')}\n\n"
                      f'{json.dumps(summary, indent=1, ensure_ascii=False)}')
            write_cloud_log(config['cloud_log_dir'], prompt, now)
            try:
                cli, text = run_cloud(cloud_cfg, prompt, config['cloud_workdir'])
                save_note(memory, 'digest', cli, text, now, len(prompt.encode()))
                status.pop('digest_error', None)
            except Exception as e:  # retried after min_minutes_between
                status['digest_error'] = f'Digest failed: {e}'[:300]
    finally:
        db.close()

    write_output(config['output'], {
        'status': 'ok', 'checked_at': datetime.fromtimestamp(time.time(), tz).isoformat(timespec='seconds'),
        'findings': [{k: f[k] for k in ('title', 'detail', 'severity', 'cloud')}
                     | {'since': datetime.fromtimestamp(f['since'], tz).isoformat(timespec='minutes')}
                     for f in found],
        'note': note_view(last_note(memory, 'note'), tz),
        'digest': note_view(last_note(memory, 'digest'), tz),
        'sky': {'label': sky_now[1], 'at': datetime.fromtimestamp(sky_now[0], tz).isoformat(timespec='minutes')}
        if sky_now else None,
        'errors': [v for k, v in sorted(status.items())],
    })


def load_config(path):
    import yaml  # python3-yaml on the laptop; tests pass dicts instead
    with open(path) as f:
        config = yaml.safe_load(f)
    for key in ('recorder_db', 'output', 'memory_db', 'cloud_log_dir', 'cloud_workdir', 'shopping_list'):
        if config.get(key):
            config[key] = os.path.expanduser(config[key])
    if config.get('sky'):
        config['sky']['image'] = os.path.expanduser(config['sky']['image'])
    return config


def main():
    config = load_config(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, 'config.yaml'))
    tz = ZoneInfo(config.get('timezone', 'America/Los_Angeles'))
    memory = open_memory(config['memory_db'])
    status = {}
    while True:
        try:
            tick(config, memory, tz, status)
            status.pop('tick_error', None)
        except Exception as e:
            print(f'home-agent: {e!r}', file=sys.stderr, flush=True)
            status['tick_error'] = f'Observer error: {e}'[:200]
        time.sleep(config.get('poll_seconds', 60))


if __name__ == '__main__':
    main()
