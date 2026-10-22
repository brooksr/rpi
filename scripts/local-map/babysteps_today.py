"""Today's BabySteps entries for Home Assistant, from the internal backend.

HA enrolls once as a BabySteps "phone" device (the watch capability omits
baths): `enroll` prints a code to approve in BabySteps → Account with a
passkey, then `finish` exchanges it. Access tokens last 15 minutes; refresh
tokens rotate and a reused one revokes the device, so the new token is saved
(atomically) before anything else is done with it.

`log <base64 JSON>` saves one entry from Assist, a Google Home switch or a
script, using the same request format and rules as BabySteps' legacy events
API (src/domain/eventRequest.ts, ported below), and prints
{"ok": true, "message": ...} or {"ok": false, "errors": [...]}.

Usage: babysteps_today.py [enroll | finish | status | log <payload>]   (default: status)"""
import base64
import datetime
import fcntl
import json
import os
import pathlib
import re
import sys
import urllib.error
import uuid
import urllib.request
import zoneinfo

API = os.environ.get('BABYSTEPS_API', 'http://127.0.0.1:8790/api/v1')
STATE = pathlib.Path(os.environ.get('BABYSTEPS_STATE', '/config/.babysteps-native.json'))
PENDING = STATE.with_name('.babysteps-native-pending.json')
SOURCE_DEVICE = 'home-assistant'


def call(path, body=None, token=None):
    headers = {'Accept': 'application/json'}
    if body is not None:
        headers['Content-Type'] = 'application/json'
    if token:
        headers['Authorization'] = f'Bearer {token}'
    request = urllib.request.Request(f'{API}{path}', data=None if body is None else json.dumps(body).encode(),
                                     headers=headers, method='GET' if body is None else 'POST')
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value))
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def access_token():
    # The status sensor and voice logging share one refresh token; two refreshes
    # at once would reuse it and revoke the device, so they take turns.
    with open(STATE.with_name('.babysteps-native.lock'), 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _access_token()


def _access_token():
    state = json.loads(STATE.read_text())
    expires = datetime.datetime.fromisoformat(state['expiresAt'].replace('Z', '+00:00'))
    if expires - datetime.datetime.now(datetime.timezone.utc) > datetime.timedelta(minutes=2):
        return state
    tokens = call('/native/refresh', {'refreshToken': state['refreshToken']})
    state.update(token=tokens['token'], refreshToken=tokens['refreshToken'], expiresAt=tokens['expiresAt'])
    save(STATE, state)
    return state


def describe(event):
    kind = event.get('type')
    if kind == 'feed':
        method = event.get('method') or ''
        if event.get('amountOz'):
            return f"{method.capitalize() or 'Feed'} · {event['amountOz']:g} oz"
        if event.get('durationMinutes'):
            return f"{method.capitalize() or 'Feed'} · {event['durationMinutes']} min{' ' + event['side'] if event.get('side') else ''}"
        return method.capitalize() or 'Feed'
    if kind == 'diaper':
        return f"Diaper · {event.get('kind') or event.get('contents') or 'change'}"
    if kind == 'sleep':
        return 'Sleep' if event.get('endedAt') else 'Asleep'
    return (kind or 'Entry').replace('_', ' ').capitalize()


def summarize(data, now):
    # As in BabySteps' getProfileKind: anything not a parent/caregiver is a child.
    profiles = [p for p in data.get('profiles') or [data.get('profile')]
                if p and p.get('kind') not in ('parent', 'caregiver') and not p.get('archivedAt')]
    child = profiles[0] if profiles else (data.get('profile') or {})
    zone = zoneinfo.ZoneInfo(child.get('timezone') or 'America/Los_Angeles')
    today = now.astimezone(zone).date()
    events = [e for e in data.get('events', []) if not child.get('id') or e.get('babyId') == child.get('id')]
    events.sort(key=lambda e: e['startedAt'], reverse=True)
    local = lambda e: datetime.datetime.fromisoformat(e['startedAt'].replace('Z', '+00:00')).astimezone(zone)
    latest = lambda kind: next((e for e in events if e.get('type') == kind), None)
    bath = latest('bath')
    feed, diaper, sleep = latest('feed'), latest('diaper'), latest('sleep')
    todays = [{'time': e['startedAt'], 'type': e['type'], 'text': describe(e), 'endedAt': e.get('endedAt')}
              for e in reversed(events) if local(e).date() == today]
    return {
        'status': 'ok', 'child': (child.get('name') or '').split(' ')[0], 'timezone': str(zone),
        'events': todays[-30:], 'event_count': len(todays),
        'last_bath': bath['startedAt'] if bath else None,
        'days_since_bath': (today - local(bath).date()).days if bath else None,
        'lastFeed': {k: feed.get(k) for k in ('startedAt', 'endedAt', 'method', 'amountOz', 'durationMinutes')} | {'at': feed['startedAt']} if feed else None,
        'lastDiaper': {'at': diaper['startedAt'], 'kind': diaper.get('kind')} if diaper else None,
        'lastSleep': {'at': sleep['startedAt'], 'endedAt': sleep.get('endedAt')} if sleep else None,
    }


# Thresholds for the spoken briefing. A nursing session started but not
# stopped counts as feeding; bottles have no end time, so they never do.
FEED_DUE = datetime.timedelta(hours=3)
DIAPER_DUE = datetime.timedelta(hours=3)
CRYING_NOW = datetime.timedelta(minutes=10)


def parse(value):
    return datetime.datetime.fromisoformat(value.replace('Z', '+00:00'))


def crying(nursery, now):
    cries = [e for e in (nursery or {}).get('episodes', []) if e.get('label') == 'baby_cry']
    if not cries:
        return {'last_cry': None, 'crying_now': False, 'cries_last_hour': 0}
    last = max(cries, key=lambda e: e['startedAt'])
    ended = parse(last.get('endedAt') or last['startedAt'])
    return {'last_cry': last['startedAt'], 'crying_now': now - ended <= CRYING_NOW,
            'cries_last_hour': sum(now - parse(e['startedAt']) <= datetime.timedelta(hours=1) for e in cries)}


def spoken_duration(delta):
    minutes = int(delta.total_seconds() // 60)
    hours, minutes = divmod(minutes, 60)
    if not hours:
        return f'{minutes} minutes'
    return f"{hours} hour{'s' if hours != 1 else ''}" + (f' {minutes} minutes' if minutes else '')


def briefing(summary, now):
    """One spoken status line: crying, feeding, asleep or awake, then what's due."""
    zone = zoneinfo.ZoneInfo(summary['timezone'])
    name = summary.get('child') or 'The baby'
    at = lambda value: parse(value).astimezone(zone).strftime('%-I:%M %p')
    feed, diaper, sleep = summary.get('lastFeed'), summary.get('lastDiaper'), summary.get('lastSleep')
    feeding = feed and not feed.get('endedAt') and not feed.get('durationMinutes') and not feed.get('amountOz') \
        and now - parse(feed['at']) <= datetime.timedelta(minutes=90)
    if summary.get('crying_now'):
        lines = [f'{name} is crying now.']
    elif feeding:
        lines = [f"{name} is feeding, since {at(feed['at'])}."]
    elif sleep and not sleep.get('endedAt'):
        lines = [f"{name} is asleep, since {at(sleep['at'])}, about {spoken_duration(now - parse(sleep['at']))}."]
    else:
        lines = [f'{name} is awake.' if sleep else f'No sleep logged for {name}.']
    if feed and not feeding:
        since = now - parse(feed['at'])
        what = f"a {feed['amountOz']:g} ounce bottle" if feed.get('amountOz') else 'nursing' if feed.get('method') in ('nursing', 'breast') else 'a feed'
        lines.append(f"Last feed was {what} at {at(feed['at'])}, {spoken_duration(since)} ago" + ('; a feed is due.' if since >= FEED_DUE else '.'))
    if diaper:
        since = now - parse(diaper['at'])
        lines.append(f"Last diaper change at {at(diaper['at'])}" + ('; a change may be needed.' if since >= DIAPER_DUE else '.'))
    if not summary.get('crying_now') and summary.get('last_cry'):
        cries = summary.get('cries_last_hour', 0)
        lines.append(f"The nursery heard crying {cries} time{'s' if cries != 1 else ''} in the last hour." if cries else 'No crying in the last hour.')
    return ' '.join(lines)



# --- Logging: a port of BabySteps src/domain/eventRequest.ts -----------------
MAX_FEED_OZ, MAX_FEED_MINUTES, MAX_SLEEP_MINUTES, MAX_TUMMY_MINUTES = 16, 4 * 60, 16 * 60, 2 * 60
MAX_FUTURE, MAX_PAST, MAX_NOTES = datetime.timedelta(minutes=5), datetime.timedelta(days=30), 500
ML_PER_OZ = 29.5735295625
VOLUME_UNITS = {'fl oz': 'oz', 'milliliter': 'ml', 'milliliters': 'ml', 'millilitre': 'ml', 'millilitres': 'ml',
                'ml': 'ml', 'ounce': 'oz', 'ounces': 'oz', 'oz': 'oz'}
DIAPER_KINDS = {'both': 'both', 'dirty': 'dirty', 'mixed': 'both', 'pee': 'wet', 'poo': 'dirty', 'poop': 'dirty',
                'poopy': 'dirty', 'wet': 'wet'}
FEED_METHODS = {'bottle': 'bottle', 'breast': 'nursing', 'breastfeed': 'nursing', 'nursing': 'nursing'}
CONTENTS, SIDES, POOP_SIZES = ['breastmilk', 'formula', 'mixed', 'other'], ['both', 'left', 'right'], ['large', 'medium', 'small']
MOOD_LABELS = {1: 'Content', 2: 'Quiet alert', 3: 'Fussy', 4: 'Crying', 5: 'Inconsolable'}  # mood-scale.csv
MOOD_WORDS = {**{label.lower(): level for level, label in MOOD_LABELS.items()},
              'alert': 2, 'calm': 1, 'cranky': 3, 'crying': 4, 'happy': 1, 'settled': 1, 'upset': 4}
TYPE_ALIASES = {'tummy': 'tummytime', 'tummy time': 'tummytime', 'tummy_time': 'tummytime'}
TYPES = ['bath', 'diaper', 'feed', 'mood', 'note', 'pump', 'sleep', 'tummytime']


def iso(when):
    return when.astimezone(datetime.timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def present(body, key):
    return body.get(key) not in (None, '')


def number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value if value == value and abs(value) != float('inf') else None
    try:
        return float(value) if isinstance(value, str) and value.strip() else None
    except ValueError:
        return None


def pick(body, keys, allowed, errors, label, required=False):
    key = next((k for k in keys if present(body, k)), None)
    if key is None:
        if required:
            errors.append(f"{label} is required ({', '.join(allowed)}).")
        return None
    word = body[key].strip().lower() if isinstance(body[key], str) else ''
    if word not in allowed:
        errors.append(f"{label} must be one of: {', '.join(allowed)}.")
        return None
    return allowed[word]


def started(body):
    return body.get('started') in (True, 'true')


def amount_oz(body, errors):
    if not present(body, 'amount'):
        if body.get('unit') is not None:
            errors.append('unit was given without an amount.')
        return None
    amount = number(body['amount'])
    unit = VOLUME_UNITS.get(body['unit'].strip().lower().rstrip('.')) if isinstance(body.get('unit'), str) else None
    if amount is None:
        errors.append('amount must be a number.')
        return None
    if not unit:
        errors.append('unit is required with an amount (oz or ml).')
        return None
    ounces = amount / ML_PER_OZ if unit == 'ml' else amount
    if ounces <= 0 or ounces > MAX_FEED_OZ:
        errors.append(f'amount must be more than 0 and at most {MAX_FEED_OZ} oz ({round(MAX_FEED_OZ * ML_PER_OZ)} ml).')
        return None
    return ounces


def minutes(body, key, maximum, errors):
    if not present(body, key):
        return None
    value = number(body[key])
    if value is None or value <= 0 or value > maximum:
        errors.append(f'{key} must be a number of minutes above 0 and at most {maximum}.')
        return None
    return value


def timestamp(body, keys, now, errors):
    key = next((k for k in keys if present(body, k)), None)
    if key is None:
        return None
    raw = body[key].strip() if isinstance(body[key], str) else ''
    when = None
    if re.match(r'^\d{4}-\d{2}-\d{2}T.*(Z|[+-]\d{2}:?\d{2})$', raw, re.I):
        try:
            when = parse(raw)
        except ValueError:
            pass
    if when is None:
        errors.append(f'{key} must be an ISO 8601 time with an offset, like 2026-10-12T14:32:00-07:00.')
    elif when > now + MAX_FUTURE:
        errors.append(f'{key} is in the future.')
    elif when < now - MAX_PAST:
        errors.append(f'{key} is more than 30 days ago.')
    else:
        return when
    return None


def start_of(at, now, duration):
    return at or now - datetime.timedelta(minutes=duration or 0)


def build(kind, body, at, now, errors):
    if kind == 'diaper':
        diaper = pick(body, ['diaperType', 'kind'], DIAPER_KINDS, errors, 'diaperType', True)
        size = pick(body, ['poopSize'], {v: v for v in POOP_SIZES}, errors, 'poopSize')
        if size and diaper == 'wet':
            errors.append('poopSize only applies to a dirty or both diaper.')
        return {'kind': diaper, **({'poopSize': size} if size else {}), 'startedAt': iso(at or now), 'type': 'diaper'} if diaper else None
    if kind == 'feed':
        amount = amount_oz(body, errors)
        duration = minutes(body, 'durationMinutes', MAX_FEED_MINUTES, errors)
        named = pick(body, ['method'], FEED_METHODS, errors, 'method')
        contents = pick(body, ['contents'], {v: v for v in CONTENTS}, errors, 'contents')
        side = pick(body, ['side'], {v: v for v in SIDES}, errors, 'side')
        method = named or ('nursing' if amount is None and duration is not None else 'bottle')
        if amount is None and duration is None and not errors:
            if not started(body):
                errors.append('A feed needs an amount (with a unit) or a durationMinutes — or "started": true to fill it in later.')
            elif not named:
                errors.append('A started feed needs a method (bottle or nursing).')
        if side and method != 'nursing':
            errors.append('side only applies to a nursing feed.')
        if contents and method != 'bottle':
            errors.append('contents only applies to a bottle feed.')
        return {**({'amountOz': amount} if amount is not None else {}), **({'contents': contents} if contents else {}),
                **({'durationMinutes': duration} if duration is not None else {}), 'method': method,
                **({'side': side} if side else {}), 'startedAt': iso(start_of(at, now, duration)), 'type': 'feed'}
    if kind == 'bath':
        return {'startedAt': iso(at or now), 'type': 'bath'}
    if kind == 'mood':
        raw = body.get('level', body.get('mood'))
        word = raw.strip().lower() if isinstance(raw, str) else ''
        level = MOOD_WORDS[word] if word in MOOD_WORDS else number(raw)
        if level is None or level != int(level) or not 1 <= level <= 5:
            errors.append(f"level must be 1–5 or one of: {', '.join(sorted(MOOD_WORDS))}.")
            return None
        return {'level': int(level), 'startedAt': iso(at or now), 'type': 'mood'}
    if kind == 'note':
        text = body['text'] if isinstance(body.get('text'), str) and body['text'].strip() else body.get('notes')
        if not isinstance(text, str) or not text.strip():
            errors.append('A note needs its text (notes or text).')
            return None
        if len(text) > MAX_NOTES:
            errors.append(f'A note must be at most {MAX_NOTES} characters.')
            return None
        return {'notes': text.strip(), 'startedAt': iso(at or now), 'type': 'note'}
    if kind == 'pump':
        amount = amount_oz(body, errors)
        side = pick(body, ['side'], {v: v for v in SIDES}, errors, 'side') or 'both'
        if amount is None:
            if not errors and started(body):
                return {'amountOz': 0, 'side': side, 'startedAt': iso(at or now), 'type': 'pump'}
            if not errors:
                errors.append('A pump needs an amount with a unit (oz or ml) — or "started": true to fill it in later.')
            return None
        return {'amountOz': amount, 'side': side, 'startedAt': iso(at or now), 'type': 'pump'}
    if kind == 'sleep':
        duration = minutes(body, 'durationMinutes', MAX_SLEEP_MINUTES, errors)
        start = timestamp(body, ['startedAt', 'start', 'startTime'], now, errors)
        end = timestamp(body, ['endedAt', 'end', 'endTime'], now, errors)
        if errors:
            return None
        if duration is not None:
            if start and (end or at):
                errors.append('Give a sleep a durationMinutes or a start and end, not all three.')
                return None
            ended = start + datetime.timedelta(minutes=duration) if start else end or at or now
            return span(start or ended - datetime.timedelta(minutes=duration), ended, now, errors)
        if not start:
            if started(body):
                return {'startedAt': iso(at or now), 'type': 'sleep'}
            errors.append('A sleep needs a durationMinutes or a startedAt — or "started": true to fill it in later.')
            return None
        return span(start, end, now, errors) if end else {'startedAt': iso(start), 'type': 'sleep'}
    if kind == 'tummytime':
        duration = minutes(body, 'durationMinutes', MAX_TUMMY_MINUTES, errors)
        if duration is None:
            if not errors and started(body):
                return {'durationMinutes': 0, 'startedAt': iso(at or now), 'type': 'tummytime'}
            if not errors:
                errors.append('Tummy time needs a durationMinutes — or "started": true to fill it in later.')
            return None
        return {'durationMinutes': duration, 'startedAt': iso(start_of(at, now, duration)), 'type': 'tummytime'}


def span(start, end, now, errors):
    length = (end - start).total_seconds() / 60
    if length <= 0:
        errors.append('A sleep must end after it starts.')
    elif length > MAX_SLEEP_MINUTES:
        errors.append(f'A sleep longer than {MAX_SLEEP_MINUTES // 60} hours is a timer left running, not a sleep.')
    elif end > now + MAX_FUTURE:
        errors.append('A sleep cannot end in the future.')
    else:
        return {'endedAt': iso(end), 'startedAt': iso(start), 'type': 'sleep'}
    return None


def parse_event_request(body, now):
    if not isinstance(body, dict):
        return None, ['The request body must be a JSON object.']
    named = body['type'].strip().lower() if isinstance(body.get('type'), str) else ''
    kind = TYPE_ALIASES.get(named, named)
    if kind not in TYPES:
        return None, [f"type must be one of: {', '.join(TYPES)}."]
    errors = []
    at = timestamp(body, ['timestamp'], now, errors)
    notes = None
    if kind != 'note' and body.get('notes') is not None:
        if not isinstance(body['notes'], str) or len(body['notes']) > MAX_NOTES:
            errors.append(f'notes must be text of at most {MAX_NOTES} characters.')
        else:
            notes = body['notes'].strip() or None
    event = build(kind, body, at, now, errors)
    if errors or not event:
        return None, errors
    return ({**event, 'notes': notes} if notes else event), []


def first_name(profile):
    return (profile.get('name') or '').strip().split(' ')[0]


def resolve_child(profiles, ref):
    children = [p for p in profiles if p.get('kind') not in ('parent', 'caregiver') and not p.get('archivedAt')]
    if ref is not None and not isinstance(ref, str):
        return None, ['child must be a string.']
    wanted = (ref or '').strip().lower()
    if not wanted:
        if len(children) == 1:
            return children[0], []
        return None, [f"Name the child: {', '.join(first_name(c) for c in children)}." if children else 'This family has no children to log for.']
    firsts = [c for c in children if first_name(c).lower() == wanted]
    match = next((c for c in children if c['id'].lower() == wanted), None) or \
        next((c for c in children if c.get('name', '').strip().lower() == wanted), None) or (firsts[0] if len(firsts) == 1 else None)
    return (match, []) if match else (None, [f'No child named "{ref.strip()}".'])


def volume(ounces, child):
    if (child.get('preferredUnits') or {}).get('system') == 'metric':
        return f'{round(ounces * ML_PER_OZ)} mL'
    return f"{ounces:.2f}".rstrip('0').rstrip('.') + ' oz'


def describe_logged(event, child):
    zone = zoneinfo.ZoneInfo(child.get('timezone') or 'America/Los_Angeles')
    name, spoken = first_name(child), lambda v: parse(v).astimezone(zone).strftime('%-I:%M %p')
    time, kind = spoken(event['startedAt']), event['type']
    if kind == 'diaper':
        return f"Logged a {event['kind']} diaper for {name} at {time}."
    if kind == 'feed':
        what = 'nursing' if event['method'] == 'nursing' else 'a bottle'
        if 'amountOz' not in event and 'durationMinutes' not in event:
            return f"Started {what} for {name} at {time}. Add the {'length' if event['method'] == 'nursing' else 'amount'} in BabySteps when it's done."
        amount = f"{volume(event['amountOz'], child)} " if 'amountOz' in event else ''
        length = f" for {event['durationMinutes']:g} minutes" if 'durationMinutes' in event else ''
        return f"Logged a {amount}{'nursing feed' if event['method'] == 'nursing' else 'bottle'}{length} for {name} at {time}."
    if kind == 'bath':
        return f'Logged a bath for {name} at {time}.'
    if kind == 'mood':
        return f"Logged {name}'s mood as {MOOD_LABELS[event['level']].lower()} at {time}."
    if kind == 'note':
        return f'Saved a note for {name} at {time}.'
    if kind == 'pump':
        if event['amountOz'] == 0:
            return f"Started pumping at {time}. Add the amount in BabySteps when it's done."
        return f"Logged {volume(event['amountOz'], child)} pumped{'' if event['side'] == 'both' else ' on the ' + event['side'] + ' side'} at {time}."
    if kind == 'tummytime':
        if event['durationMinutes'] == 0:
            return f"Started tummy time for {name} at {time}. Add the length in BabySteps when it's done."
        return f"Logged {event['durationMinutes']:g} minutes of tummy time for {name}, starting {time}."
    if event.get('endedAt'):
        total = round((parse(event['endedAt']) - parse(event['startedAt'])).total_seconds() / 60)
        hours, mins = divmod(total, 60)
        length = ' '.join(p for p in [f"{hours} hour{'s' if hours != 1 else ''}" if hours else '',
                                      f"{mins} minute{'s' if mins != 1 else ''}" if mins else ''] if p) or 'under a minute'
        return f"Logged {length} of sleep for {name}, from {time} to {spoken(event['endedAt'])}."
    return f'Logged {name} asleep since {time}.'


def log_entry(body, now):
    event, errors = parse_event_request(body, now)
    if errors:
        return {'ok': False, 'errors': errors}
    state = access_token()
    boot = call(f"/families/{state['familyId']}/bootstrap", token=state['token'])
    data = boot.get('data', boot)
    child, errors = resolve_child(data.get('profiles') or [data.get('profile') or {}], body.get('child'))
    if errors:
        return {'ok': False, 'errors': errors}
    entry_id = str(uuid.uuid4())
    call(f"/families/{state['familyId']}/mutations", {'action': 'save', 'collection': 'events', 'expectedRevision': 0,
         'id': entry_id, 'operationId': str(uuid.uuid4()), 'patch': {**event, 'id': entry_id, 'babyId': child['id']}},
         token=state['token'])
    return {'ok': True, 'message': describe_logged(event, child), 'id': entry_id}


def main(mode='status', payload=None):
    now = datetime.datetime.now(datetime.timezone.utc)
    if mode == 'log':
        try:
            result = log_entry(json.loads(base64.b64decode(payload)), now)
        except urllib.error.HTTPError as error:
            result = {'ok': False, 'errors': [f"BabySteps refused it (HTTP {error.code})."]}
        except Exception as error:
            result = {'ok': False, 'errors': [f"BabySteps couldn't be reached ({type(error).__name__})."]}
        print(json.dumps(result))
        return 0  # HA reads ok/errors from stdout; a failing exit would hide them
    if mode == 'enroll':
        grant = call('/native/start', {'purpose': 'phone', 'sourceDeviceId': SOURCE_DEVICE})
        save(PENDING, grant)
        print(f"Approve code {grant['userCode']} in BabySteps → Account before {grant['expiresAt']}")
        return
    if mode == 'finish':
        grant = json.loads(PENDING.read_text())
        tokens = call('/native/exchange', {'deviceCode': grant['deviceCode'], 'deviceSecret': grant['deviceSecret']})
        if tokens.get('pending'):
            print('Not approved yet')
            return 1
        save(STATE, {k: tokens[k] for k in ('token', 'refreshToken', 'expiresAt', 'familyId', 'installationId')})
        PENDING.unlink()
        print('Home Assistant is connected to BabySteps')
        return
    result = {'status': 'unavailable', 'checked_at': now.isoformat(), 'error': None}
    try:
        if not STATE.exists():
            result.update(status='not_connected', error='Run babysteps_today.py enroll')
        else:
            state = access_token()
            boot = call(f"/families/{state['familyId']}/bootstrap", token=state['token'])
            result.update(summarize(boot.get('data', boot), now))
            try:
                nursery = call(f"/families/{state['familyId']}/nursery", token=state['token']).get('nursery')
                result.update(crying(nursery, now))
            except Exception as error:
                result['nursery_error'] = type(error).__name__
            result['briefing'] = briefing(result, now)
    except urllib.error.HTTPError as error:
        result['error'] = f'HTTP {error.code}'
        if error.code == 401:
            result['status'] = 'not_connected'
    except Exception as error:
        result['error'] = type(error).__name__
    print(json.dumps(result))


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:3]))
