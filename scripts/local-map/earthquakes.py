"""USGS earthquakes near home: the past 7 days at M2.5+ within 50 miles.

The state is the count in the last 24 hours (the Overview card shows only then).
`alert` is set for a quake strong and close enough to announce, while it is
recent, so a later poll or restart does not announce old shaking.
USGS posts events minutes after they happen; this is not early warning."""
import datetime
import json
import math
import sys
import urllib.parse
import urllib.request

RADIUS_MILES = 50
ALERT_MAGNITUDE = 4.0
ALERT_WINDOW_MINUTES = 30


def miles(home, lat, lon):
    return math.hypot(lat - home[0], (lon - home[1]) * math.cos(math.radians(home[0]))) * 69.05


def main():
    home = tuple(map(float, sys.argv[1:3]))
    now = datetime.datetime.now(datetime.timezone.utc)
    result = {'status': 'unavailable', 'count_24h': None, 'quakes': [], 'week_count': None, 'alert': None,
              'checked_at': now.isoformat(), 'error': None}
    try:
        query = urllib.parse.urlencode({'format': 'geojson', 'latitude': home[0], 'longitude': home[1],
                                        'maxradiuskm': round(RADIUS_MILES * 1.609344, 2), 'minmagnitude': 2.5,
                                        'orderby': 'time', 'starttime': (now - datetime.timedelta(days=7)).strftime('%Y-%m-%dT%H:%M:%S')})
        request = urllib.request.Request(f'https://earthquake.usgs.gov/fdsnws/event/1/query?{query}',
                                         headers={'User-Agent': 'HomeAssistant-LocalMap/1.0'})
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.load(response)
        quakes = []
        for feature in data['features']:
            p, (lon, lat, depth) = feature['properties'], feature['geometry']['coordinates'][:3]
            when = datetime.datetime.fromtimestamp(p['time'] / 1000, datetime.timezone.utc)
            quakes.append({'id': feature['id'], 'magnitude': round(p['mag'], 1), 'place': p['place'],
                           'time': when.isoformat(), 'miles': round(miles(home, lat, lon), 1),
                           'depth_km': round(depth, 1) if depth is not None else None, 'url': p['url'],
                           'felt': p.get('felt'), 'tsunami': bool(p.get('tsunami'))})
        day = [q for q in quakes if now - datetime.datetime.fromisoformat(q['time']) <= datetime.timedelta(hours=24)]
        recent = [q for q in quakes if q['magnitude'] >= ALERT_MAGNITUDE
                  and now - datetime.datetime.fromisoformat(q['time']) <= datetime.timedelta(minutes=ALERT_WINDOW_MINUTES)]
        result.update(status='ok', count_24h=len(day), quakes=day[:8], week_count=len(quakes),
                      largest_week=max(quakes, key=lambda q: q['magnitude']) if quakes else None,
                      alert=max(recent, key=lambda q: q['magnitude']) if recent else None)
    except Exception as error:
        result['error'] = type(error).__name__
    print(json.dumps(result))


if __name__ == '__main__':
    main()
