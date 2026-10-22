"""US-101 and SR-23 conditions near home from Caltrans District 7 public feeds.

Lane closures use the CSV feed (about 2 MB) instead of the 14 MB JSON one.
A closure is "in place" only after Caltrans logs crews on scene (code 10-97)
and before they leave (10-98); others are scheduled and may not happen."""
import csv
import datetime
import io
import json
import math
import sys
import time
import urllib.error
import urllib.request

FEEDS = 'https://cwwp2.dot.ca.gov/data/d7'
ROUTES = ('US-101', 'SR-23')
# Ventura County plus the 101 through Agoura Hills and Calabasas.
WEST_OF = -118.65


def fetch(path):
    request = urllib.request.Request(f'{FEEDS}/{path}', headers={'User-Agent': 'HomeAssistant-LocalMap/1.0'})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read().decode('utf-8-sig')


def nearby(route, county, longitude):
    return route in ROUTES and (county == 'Ventura' or (longitude or 0) < WEST_OF)


def number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def miles(home, lat, lon):
    return math.hypot(lat - home[0], (lon - home[1]) * math.cos(math.radians(home[0]))) * 69.05


def signs(text):
    result = []
    for item in json.loads(text)['data']:
        sign = item['cms']
        place, message = sign['location'], sign['message']
        if not nearby(place['route'], place['county'], number(place['longitude'])) or message['display'] == 'Blank':
            continue
        lines = [message[phase].get(f'{phase}Line{n}', '').strip() for phase in ('phase1', 'phase2') for n in (1, 2, 3)]
        lines = [line for line in lines if line]
        if lines:
            result.append({'route': place['route'], 'direction': place['direction'], 'location': place['locationName'].title(),
                           'message': lines})
    return result


def closures(text, now):
    in_place, scheduled, seen = [], [], set()
    for row in csv.DictReader(io.StringIO(text)):
        if not nearby(row['beginRoute'], row['beginCounty'], number(row['beginLongitude'])) or row['isCode1098'] == 'true':
            continue
        start, end = number(row['closureStartEpoch']), number(row['closureEndEpoch'])
        indefinite = row['isClosureEndIndefinite'] == 'true'
        if end and end < now and not indefinite:
            continue
        active = row['isCode1097'] == 'true'
        if not active and (not start or start > now + 86400):
            continue
        key = (row['beginRoute'], row['travelFlowDirection'], row['beginLocationName'], row['endLocationName'], row['closureStartEpoch'])
        if key in seen:
            continue
        seen.add(key)
        entry = {'route': row['beginRoute'], 'direction': row['travelFlowDirection'], 'from': row['beginLocationName'],
                 'to': row['endLocationName'], 'place': row['beginNearbyPlace'], 'facility': row['facility'],
                 'type': row['typeOfClosure'], 'lanes': row['lanesClosed'], 'total_lanes': row['totalExistingLanes'],
                 'work': row['typeOfWork'], 'delay': row['estimatedDelay'],
                 'start': datetime.datetime.fromtimestamp(start, datetime.timezone.utc).isoformat() if start else None,
                 'end': None if indefinite or not end else datetime.datetime.fromtimestamp(end, datetime.timezone.utc).isoformat()}
        (in_place if active else scheduled).append(entry)
    scheduled.sort(key=lambda c: c['start'] or '')
    return in_place[:8], scheduled[:8], len(scheduled)


def cameras(text, home, per_route=2):
    found = []
    for item in json.loads(text)['data']:
        camera = item['cctv']
        place = camera['location']
        lat, lon = number(place['latitude']), number(place['longitude'])
        image = camera['imageData']['static'].get('currentImageURL')
        if place['route'] in ROUTES and camera['inService'] == 'true' and lat and lon and image:
            found.append({'route': place['route'], 'name': place['locationName'].split(':', 1)[-1].split(')', 1)[-1].strip(),
                          'direction': place['direction'], 'image': image, 'miles': round(miles(home, lat, lon), 1)})
    found.sort(key=lambda c: c['miles'])
    return [c for route in ROUTES for c in [c for c in found if c['route'] == route][:per_route]]


def main():
    home = tuple(map(float, sys.argv[1:3]))
    now = time.time()
    result = {'status': 'ok', 'signs': [], 'in_place': [], 'scheduled': [], 'scheduled_count': 0, 'cameras': [],
              'checked_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'errors': {}}
    sources = [('signs', lambda: {'signs': signs(fetch('cms/cmsStatusD07.json'))}),
               ('closures', lambda: dict(zip(('in_place', 'scheduled', 'scheduled_count'), closures(fetch('lcs/lcsStatusD07.csv'), now)))),
               ('cameras', lambda: {'cameras': cameras(fetch('cctv/cctvStatusD07.json'), home)})]
    for name, read in sources:
        try:
            result.update(read())
        except Exception as error:
            result['errors'][name] = f'HTTP {error.code}' if isinstance(error, urllib.error.HTTPError) else type(error).__name__
    if len(result['errors']) == len(sources):
        result['status'] = 'unavailable'
    print(json.dumps(result))


if __name__ == '__main__':
    main()
