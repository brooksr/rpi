"""Read-only spoken summaries of the existing Home Assistant dashboard feeds."""
import base64
import datetime as dt
import json
import sys
from zoneinfo import ZoneInfo

ZONE = ZoneInfo('America/Los_Angeles')
UTC = dt.timezone.utc


def date(value):
    try:
        result = dt.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return result if result.tzinfo else result.replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return None


def number(value, suffix=''):
    return f'{float(value):g}{suffix}' if isinstance(value, (float, int)) else 'unavailable'


def when(value, now):
    at = date(value)
    if not at:
        return 'an unknown time'
    local = at.astimezone(ZONE)
    day = local.date()
    today = now.astimezone(ZONE).date()
    prefix = 'today' if day == today else 'yesterday' if day == today - dt.timedelta(days=1) else local.strftime('%A, %B %-d')
    return f"{prefix} at {local.strftime('%-I:%M %p')}"


def ago(value, now):
    at = date(value)
    if not at or at > now:
        return ''
    minutes = int((now - at).total_seconds() / 60)
    if minutes < 1:
        return 'less than a minute ago'
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''}" + (f" and {minutes} minute{'s' if minutes != 1 else ''} ago" if minutes else ' ago')
    days = hours // 24
    return f"{days} day{'s' if days != 1 else ''} ago"


def summarize(payload, now=None):
    now = now or dt.datetime.now(UTC)
    topic = payload['topic']
    sensors = payload.get('sensors', {})

    def sensor(name, max_minutes=90):
        item = sensors.get(name) or {}
        attrs = item.get('attributes') or {}
        checked = date(attrs.get('checked_at'))
        valid = item.get('state') not in (None, 'unknown', 'unavailable')
        fresh = checked and -300 <= (now - checked).total_seconds() <= max_minutes * 60
        return attrs if valid and fresh else None

    if topic == 'morning':
        lines = ['Morning']
        weather = (sensors.get('weather.forecast_home') or {})
        current = (weather.get('attributes') or {}).get('temperature') if weather.get('state') not in (None, 'unknown', 'unavailable') else None
        obs = sensors.get('sensor.nws_observation') or {}
        observed = date((obs.get('attributes') or {}).get('timestamp'))
        if observed and 0 <= (now - observed).total_seconds() < 5400:
            try:
                current = float(obs['state']) * 9 / 5 + 32
            except (ValueError, TypeError, KeyError):
                pass
        today = now.astimezone(ZONE).date()
        days = (payload.get('forecast') or {}).get('weather.forecast_home', {}).get('forecast') or []
        day = next((d for d in days if date(d.get('datetime')) and date(d['datetime']).astimezone(ZONE).date() == today), {})
        high = day.get('temperature')
        if current is not None:
            lines.append(f"{round(current)} degrees now" + (f", high {round(high)}" if high is not None else ", forecast high unavailable"))
        else:
            lines.append('current temperature unavailable' + (f", high {round(high)}" if high is not None else ', forecast high unavailable'))
        baby = sensor('sensor.babysteps_status', 15)
        if not baby:
            lines.append('BabySteps data unavailable or out of date')
        else:
            child = baby.get('child') or 'The baby'
            for kind, key in [('feed', 'lastFeed'), ('diaper', 'lastDiaper')]:
                item = baby.get(key) or {}
                at = date(item.get('at'))
                if not at or at > now:
                    lines.append(f'No valid recent {kind} record is available for {child}.')
                    continue
                ongoing = kind == 'feed' and item.get('method') in ('nursing', 'breast') and not item.get('endedAt') and not item.get('durationMinutes') and now - at <= dt.timedelta(minutes=90)
                if ongoing:
                    lines.append(f"{child} started nursing at {at.astimezone(ZONE).strftime('%-I:%M %p')}, not marked finished")
                    continue
                try:
                    hours = float((payload.get('intervals') or {}).get(kind, 3))
                except (ValueError, TypeError):
                    hours = 3
                hours = hours if 0.5 <= hours <= 12 else 3
                expected = at + dt.timedelta(hours=hours)
                minutes = max(0, int((expected - now).total_seconds() + 59) // 60)
                h, m = divmod(minutes, 60)
                duration = (f"{h} hour{'s' if h != 1 else ''}" if h else '')
                if m:
                    duration += (' and ' if h else '') + f"{m} minute{'s' if m != 1 else ''}"
                timing = 'in ' + duration if minutes else 'estimated now'
                clock = at.astimezone(ZONE).strftime('%-I:%M %p')
                lines.append(f"{child} last ate at {clock}, next feed {timing}" if kind == 'feed'
                             else f"diaper changed at {clock}, next change {timing}")
        alerts = sensor('sensor.local_weather_alerts', 25)
        if alerts is None:
            lines.append('Weather warning data is unavailable or out of date.')
        else:
            active = [a for a in alerts.get('alerts') or [] if (not date(a.get('expires')) or date(a['expires']) > now) and (not date(a.get('effective')) or date(a['effective']) <= now)]
            names = list(dict.fromkeys(a.get('event') for a in active if a.get('event')))
            if names:
                lines.append('Weather alert: ' + ', '.join(names[:4]))
        power = sensor('sensor.power_shutoff', 25)
        if power is None:
            lines.append('Power warning data is unavailable or out of date.')
        else:
            state = sensors['sensor.power_shutoff']['state']
            circuit = power.get('circuit') or 'the local'
            if state == 'power_shutoff':
                lines.append(f'Power warning: SCE lists an active power shutoff on {circuit} circuit.')
            elif state == 'under_consideration':
                lines.append(f'Power warning: SCE is considering a power shutoff on {circuit} circuit.')
        internet = sensor('sensor.internet', 60)
        if internet is not None and sensors['sensor.internet']['state'] in ('offline', 'degraded'):
            lines.append('The internet connection is ' + sensors['sensor.internet']['state'] + '.')
        for key, name in [('sensor.raspberry_pi', 'Home Assistant laptop'), ('sensor.pi_health', 'Raspberry Pi')]:
            health = sensor(key)
            if health:
                if health.get('undervoltage'):
                    lines.append(f'{name} reports undervoltage.')
                if (health.get('temperature_c') or 0) >= 80:
                    lines.append(f'{name} is hot.')
                if (health.get('memory_percent') or 0) >= 85 or (health.get('swap_percent') or 0) >= 85:
                    lines.append(f'{name} is low on memory.')
                if (health.get('disk_percent') or 0) >= 90:
                    lines.append(f'{name} storage is nearly full.')
                battery = health.get('battery') or {}
                if battery.get('ac_online') is False:
                    lines.append(f'{name} is running on battery at {number(battery.get("percent"))} percent.')
        return 'Morning, ' + '; '.join(line.rstrip('.') for line in lines[1:]) + '.'

    if topic.startswith('baby_'):
        a = sensor('sensor.babysteps_status', 15)
        if not a:
            return 'The BabySteps status is unavailable or out of date. Please check BabySteps.'
        child = a.get('child') or 'The baby'
        kind = topic.removeprefix('baby_')
        if kind == 'status':
            # Do not reuse the older briefing's medical or care timing suggestions.
            return ' '.join(summarize(dict(payload, topic='baby_' + k), now) for k in ('feed', 'diaper', 'sleep'))
        if kind == 'bath':
            at = a.get('last_bath')
            return f"{child}'s last recorded bath was {when(at, now)}, {ago(at, now)}." if at else f'No bath is recorded for {child} in the available BabySteps data.'
        item = a.get({'feed': 'lastFeed', 'diaper': 'lastDiaper', 'sleep': 'lastSleep'}[kind])
        if not item:
            return f'No {kind} is recorded for {child} in the available BabySteps data.'
        at = item.get('at')
        if kind == 'feed':
            detail = 'feed'
            if item.get('method') == 'nursing':
                detail = 'nursing session'
            elif item.get('method') == 'bottle' or item.get('amountOz') is not None:
                detail = f"{number(item['amountOz'])} ounce bottle" if item.get('amountOz') is not None else 'bottle'
            duration = item.get('durationMinutes')
            extra = f", lasting {number(duration)} minutes" if duration else ''
            return f"{child}'s last recorded {detail} started {when(at, now)}, {ago(at, now)}{extra}."
        if kind == 'diaper':
            detail = {'wet': 'wet', 'dirty': 'dirty', 'both': 'wet and dirty'}.get(item.get('kind'), '')
            return f"{child}'s last recorded diaper change was {when(at, now)}, {ago(at, now)}. " + (f'It was {detail}.' if detail else '')
        ended = item.get('endedAt')
        if not ended:
            return f"BabySteps shows {child} asleep since {when(at, now)}, {ago(at, now)}. That sleep has not been marked finished."
        return f"{child}'s last recorded sleep started {when(at, now)} and ended {when(ended, now)}, {ago(ended, now)}."

    if topic == 'weather':
        a = (sensors.get('weather.forecast_home') or {}).get('attributes') or {}
        observation = (sensors.get('sensor.nws_observation') or {})
        o = observation.get('attributes') or {}
        seen = date(o.get('timestamp'))
        try:
            temp = float(observation.get('state')) * 9 / 5 + 32
        except (ValueError, TypeError):
            temp = None
        if temp is not None and seen and 0 <= (now - seen).total_seconds() < 5400:
            return f"The local weather station reports {o.get('textDescription') or 'current conditions'}, {round(temp)} degrees Fahrenheit. Observed {when(seen, now)}."
        state = (sensors.get('weather.forecast_home') or {}).get('state')
        if state in (None, 'unavailable', 'unknown') or a.get('temperature') is None:
            return 'Current weather data is unavailable.'
        unit = a.get('temperature_unit', '°F')
        return f"The weather service reports {state.replace('-', ' ')}, {number(a['temperature'])} degrees {'Fahrenheit' if unit == '°F' else 'Celsius'}. Humidity is {number(a.get('humidity'))} percent."

    if topic.startswith('forecast'):
        days = (payload.get('forecast') or {}).get('weather.forecast_home', {}).get('forecast') or []
        today = now.astimezone(ZONE).date()
        target = today + dt.timedelta(days=1 if topic == 'forecast_tomorrow' else 0)
        days = [d for d in days if date(d.get('datetime')) and date(d['datetime']).astimezone(ZONE).date() >= target]
        if not days:
            return 'The weather forecast is unavailable right now.'
        answer = []
        for d in days[:1 if topic == 'forecast_tomorrow' else 3]:
            day = date(d['datetime']).astimezone(ZONE).date()
            label = 'Today' if day == today else 'Tomorrow' if day == today + dt.timedelta(days=1) else day.strftime('%A')
            text = f"{label}: {str(d.get('condition') or 'conditions unavailable').replace('-', ' ')}, high {number(d.get('temperature'))}"
            if d.get('templow') is not None:
                text += f", low {number(d['templow'])}"
            if d.get('precipitation_probability') is not None:
                text += f", {number(d['precipitation_probability'])} percent chance of rain"
            answer.append(text + '.')
        return 'Forecast in degrees Fahrenheit. ' + ' '.join(answer)

    if topic == 'home_check':
        result = []
        indoor = sensors.get('sensor.h5075_001b_temperature') or {}
        try:
            temp = float(indoor.get('state'))
            if (indoor.get('attributes') or {}).get('unit_of_measurement') == '°C':
                temp = temp * 9 / 5 + 32
            result.append(f'Office is {temp:g} degrees')
        except (TypeError, ValueError):
            result.append('Office temperature is unavailable')
        humidity = (sensors.get('sensor.h5075_001b_humidity') or {}).get('state')
        try:
            result.append(f'humidity {float(humidity):g} percent')
        except (TypeError, ValueError):
            result.append('humidity unavailable')
        lights = payload.get('lights') or []
        on = [light['name'] for light in lights if light.get('state') == 'on']
        missing = sum(light.get('state') in ('unknown', 'unavailable') for light in lights)
        if on:
            result.append('lights on: ' + ', '.join(on[:5]) + (f', and {len(on) - 5} more' if len(on) > 5 else ''))
        elif lights:
            result.append('no connected lights report being on')
        if missing:
            result.append(f'{missing} light readings unavailable')
        internet = sensor('sensor.internet', 60)
        result.append('internet ' + sensors['sensor.internet']['state'] if internet is not None else 'internet status unavailable')
        for key, label in [('sensor.raspberry_pi', 'laptop'), ('sensor.pi_health', 'Raspberry Pi')]:
            a = sensor(key)
            if not a:
                result.append(label + ' health unavailable')
                continue
            problems = []
            if a.get('undervoltage'):
                problems.append('undervoltage')
            if (a.get('temperature_c') or 0) >= 80:
                problems.append('high temperature')
            if (a.get('memory_percent') or 0) >= 85 or (a.get('swap_percent') or 0) >= 85:
                problems.append('low memory')
            if (a.get('disk_percent') or 0) >= 90:
                problems.append('storage nearly full')
            if (a.get('battery') or {}).get('ac_online') is False:
                problems.append('on battery')
            result.append(label + ': ' + (', '.join(problems) or 'no resource warnings'))
        return '; '.join(result) + '.'

    if topic == 'health':
        answers = []
        for key, name in [('sensor.raspberry_pi', 'Home Assistant laptop'), ('sensor.pi_health', 'Raspberry Pi')]:
            a = sensor(key)
            if not a:
                answers.append(f'{name} health data is unavailable or out of date.')
                continue
            text = f"{name}: CPU {number(a.get('cpu_percent'))} percent, memory {number(a.get('memory_percent'))} percent used, disk {number(a.get('disk_percent'))} percent used"
            if a.get('temperature_c') is not None:
                text += f", temperature {number(a['temperature_c'])} degrees Celsius"
            if a.get('undervoltage'):
                text += ', with an undervoltage warning'
            battery = a.get('battery') or {}
            if battery.get('ac_online') is False:
                text += f", running on battery at {number(battery.get('percent'))} percent"
            answers.append(text + '.')
        return ' '.join(answers)

    if topic in ('daytrip', 'ventura', 'malibu'):
        a = sensor('sensor.daytrip', 45)
        if not a:
            return 'Day trip conditions are unavailable or out of date.'
        result = []
        for d in a.get('destinations') or []:
            if topic != 'daytrip' and topic not in d.get('name', '').lower():
                continue
            details = []
            if d.get('drive_minutes') is not None:
                details.append(f"about {number(d['drive_minutes'])} minutes to drive with traffic")
            if d.get('air_temp') is not None:
                details.append(f"air {round(d['air_temp'])} degrees Fahrenheit")
            if d.get('water_temp') is not None:
                details.append(f"water {round(d['water_temp'])} degrees Fahrenheit")
            result.append(d['name'] + ': ' + (', '.join(details) or 'conditions unavailable') + '.')
        return ' '.join(result) + f" Checked {when(a.get('checked_at'), now)}."

    if topic == 'traffic':
        a = sensor('sensor.freeway_conditions', 25)
        if not a:
            return 'Local freeway data is unavailable or out of date.'
        result = ['For the nearby 101 and 23 freeways.']
        errors = a.get('errors') or {}
        active = a.get('in_place') or []
        if 'closures' in errors:
            result.append('The closure feed is unavailable.')
        elif active:
            for c in active[:2]:
                result.append(f"Reported closure on the {c['route']} {c.get('direction', '')}, near {c.get('from', 'an unspecified location')}: {c.get('type') or c.get('work') or 'road work'}.")
        else:
            result.append('Caltrans reports no crews on scene in this feed. That does not establish traffic speed or rule out incidents.')
        if 'signs' in errors:
            result.append('Message sign data is unavailable.')
        else:
            for s in (a.get('signs') or [])[:2]:
                message = s.get('message') or s.get('text') or ''
                message = ' '.join(message) if isinstance(message, list) else str(message)
                result.append(f"On the {s.get('route', 'freeway')}: {message}.")
        return ' '.join(result) + f" Checked {when(a.get('checked_at'), now)}."

    if topic == 'launch':
        a = sensor('sensor.vandenberg_launches', 90)
        if not a:
            return 'The Vandenberg launch schedule is unavailable or out of date.'
        launches = [l for l in a.get('launches') or [] if date(l.get('net')) and date(l['net']) > now]
        if not launches:
            return 'There is no future Vandenberg launch with a firm time in the current feed.'
        l = min(launches, key=lambda item: date(item['net']))
        text = f"The next scheduled Vandenberg launch is {l.get('rocket', 'a rocket')}, carrying {l.get('mission', 'an unspecified mission')}, {when(l['net'], now)} Pacific time. Status: {l.get('status') or 'not provided'}."
        if l.get('view') in ('night', 'twilight'):
            text += ' It may be visible from home looking west northwest, weather permitting.'
        return text + ' Launch times can change.'

    if topic == 'gas':
        a = sensor('sensor.local_gas_prices', 130)
        stations = (a or {}).get('stations') or []
        stations = [s for s in stations if isinstance(s.get('price'), (int, float))]
        if not stations:
            return 'Nearby gas prices are unavailable or out of date.'
        s = min(stations, key=lambda item: item['price'])
        text = f"The cheapest reported regular unleaded in the dashboard is {s['name']}, at {s['price']:.2f} dollars per gallon, {number(s.get('miles'))} miles away."
        if s.get('address'):
            text += ' ' + s['address'] + '.'
        text += f" Price reported {when(s['updated'], now)}." if date(s.get('updated')) else ' The price report has no update time.'
        return text + ' Prices may have changed.'
    return 'That dashboard question is not configured.'


if __name__ == '__main__':
    try:
        payload = json.loads(base64.b64decode(sys.argv[1]))
        print(summarize(payload))
    except Exception:
        print('I could not read that dashboard information right now. Please check Home Assistant.')
