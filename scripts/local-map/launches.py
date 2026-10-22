"""Upcoming Vandenberg SFB launches with a firm time, from Launch Library 2.

Each launch is labelled by how it looks from home, from the sun's altitude here
at launch time: twilight (sun 4–18° below the horizon: dark sky, rocket plume
still sunlit, the "jellyfish"), night, dusk/dawn (sky still bright) or day.
The unauthenticated API allows 15 requests an hour; poll every 30 minutes.
`alert_at` is 10 minutes before the next twilight or night launch."""
import datetime
import json
import math
import pathlib
import sys
import urllib.request

API = 'https://ll.thespacedevs.com/2.3.0/launches/upcoming/?location__ids=11&limit=10&mode=normal&format=json'
FIRM = {'Second', 'Minute', 'Hour'}  # net_precision names; others are a day, month or quarter
# The API can take tens of seconds on a cold cache; keep the last good answer.
CACHE = pathlib.Path('/config/.vandenberg-launches.json')
CACHE_HOURS = 6


def sun_altitude(when, lat, lon):
    """Solar elevation in degrees (NOAA equations, as sky.mjs)."""
    jd = when.timestamp() / 86400 + 2440587.5
    t = (jd - 2451545) / 36525
    l0 = (280.46646 + t * (36000.76983 + t * 0.0003032)) % 360
    m = math.radians(357.52911 + t * (35999.05029 - 0.0001537 * t))
    e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    center = math.sin(m) * (1.914602 - t * (0.004817 + 0.000014 * t)) + math.sin(2 * m) * (0.019993 - 0.000101 * t) + math.sin(3 * m) * 0.000289
    omega = math.radians(125.04 - 1934.136 * t)
    lam = math.radians(l0 + center - 0.00569 - 0.00478 * math.sin(omega))
    obliquity = math.radians(23 + (26 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60) / 60 + 0.00256 * math.cos(omega))
    declination = math.asin(math.sin(obliquity) * math.sin(lam))
    y = math.tan(obliquity / 2) ** 2
    l0r = math.radians(l0)
    eq_time = 4 * math.degrees(y * math.sin(2 * l0r) - 2 * e * math.sin(m) + 4 * e * y * math.sin(m) * math.cos(2 * l0r)
                               - 0.5 * y * y * math.sin(4 * l0r) - 1.25 * e * e * math.sin(2 * m))
    minutes = when.hour * 60 + when.minute + when.second / 60  # UTC
    hour_angle = math.radians((minutes + eq_time + 4 * lon) / 4 - 180)
    lat_r = math.radians(lat)
    return math.degrees(math.asin(math.sin(lat_r) * math.sin(declination) + math.cos(lat_r) * math.cos(declination) * math.cos(hour_angle)))


def view(altitude):
    if altitude > 0:
        return 'day'
    if altitude > -4:
        return 'dusk'
    return 'twilight' if altitude > -18 else 'night'


def summarize(results, home, now):
    launches = []
    for item in results:
        precision = (item.get('net_precision') or {}).get('name')
        status = (item.get('status') or {}).get('abbrev')
        if precision not in FIRM or status in ('Success', 'Failure', 'Partial Failure'):
            continue
        net = datetime.datetime.fromisoformat(item['net'].replace('Z', '+00:00'))
        if net < now - datetime.timedelta(minutes=30):
            continue
        rocket = ((item.get('rocket') or {}).get('configuration') or {}).get('name') or item['name'].split('|')[0].strip()
        mission = (item.get('mission') or {}).get('name') or item['name'].split('|')[-1].strip()
        altitude = sun_altitude(net, *home)
        vids = item.get('vid_urls') or []
        launches.append({'id': item['id'], 'rocket': rocket, 'mission': mission, 'net': net.isoformat(),
                         'window_end': item.get('window_end'), 'status': status, 'precision': precision,
                         'pad': (item.get('pad') or {}).get('name'), 'view': view(altitude), 'sun_altitude': round(altitude, 1),
                         'webcast': vids[0].get('url') if vids and isinstance(vids[0], dict) else None,
                         'url': f"https://spacelaunchnow.me/launch/{item['slug']}/" if item.get('slug') else None})
    launches.sort(key=lambda launch: launch['net'])
    visible = next((l for l in launches if l['view'] in ('twilight', 'night') and l['status'] == 'Go'), None)
    alert_at = (datetime.datetime.fromisoformat(visible['net']) - datetime.timedelta(minutes=10)).isoformat() if visible else None
    return {'status': 'ok', 'count': len(launches), 'launches': launches[:5], 'alert': visible, 'alert_at': alert_at}


def main():
    home = tuple(map(float, sys.argv[1:3]))
    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        request = urllib.request.Request(API, headers={'User-Agent': 'HomeAssistant-LocalMap/1.0'})
        with urllib.request.urlopen(request, timeout=60) as response:
            results = json.load(response)['results']
        try:
            CACHE.write_text(json.dumps({'fetched_at': now.isoformat(), 'results': results}))
        except OSError:
            pass
        result = summarize(results, home, now)
        result.update(checked_at=now.isoformat(), error=None)
    except Exception as error:
        result = {'status': 'unavailable', 'count': None, 'launches': [], 'alert': None, 'alert_at': None,
                  'checked_at': now.isoformat(), 'error': type(error).__name__}
        try:
            cached = json.loads(CACHE.read_text())
            fetched = datetime.datetime.fromisoformat(cached['fetched_at'])
            if now - fetched <= datetime.timedelta(hours=CACHE_HOURS):
                # Re-summarized against now, so passed launches still drop off.
                result = summarize(cached['results'], home, now)
                result.update(checked_at=fetched.isoformat(), error=f'{type(error).__name__} (showing the {fetched:%H:%M} UTC copy)')
        except (OSError, ValueError, KeyError):
            pass
    print(json.dumps(result))


if __name__ == '__main__':
    main()
