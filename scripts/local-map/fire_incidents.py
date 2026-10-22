"""Active Ventura County Fire and EMS calls, nearest to home first.

The county feed lists open calls only, at block-level addresses. A failed
request is unavailable, never an empty all-clear."""
import datetime
import json
import math
import re
import sys
import urllib.request

FEED = 'https://firefeeds.venturacounty.gov/api/incidents'
# Burning fires only: "Fire Alarm", smoke checks and standbys are not fires.
FIRE = re.compile(r'fire|burn', re.I)
NOT_FIRE = re.compile(r'alarm|investigat|standby|watch|inspection|odor', re.I)


def is_fire(kind):
    return bool(FIRE.search(kind)) and not NOT_FIRE.search(kind)


def miles(home, lat, lon):
    return math.hypot(lat - home[0], (lon - home[1]) * math.cos(math.radians(home[0]))) * 69.05


# The feed gives Pacific wall-clock time; pass it on as such (no offset).
def responded(value):
    try:
        return datetime.datetime.strptime(value, '%m/%d/%y %H:%M').strftime('%Y-%m-%dT%H:%M')
    except (TypeError, ValueError):
        return None


def main():
    home = tuple(map(float, sys.argv[1:3]))
    checked = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        request = urllib.request.Request(FEED, headers={'User-Agent': 'HomeAssistant-LocalMap/1.0', 'Accept': 'application/json'})
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.load(response)
        if not isinstance(data, list):
            raise ValueError('Invalid incident feed')
        incidents = []
        for item in data:
            try:
                distance = round(miles(home, float(item['latitude']), float(item['longitude'])), 1)
            except (KeyError, TypeError, ValueError):
                distance = None
            kind = item.get('incidentType') or 'Incident'
            incidents.append({'type': kind, 'fire': is_fire(kind),
                              'address': ' '.join(filter(None, [item.get('block'), item.get('address')])),
                              'city': item.get('city'), 'status': item.get('status'), 'units': item.get('units'),
                              'responded': responded(item.get('responseDate')), 'miles': distance,
                              'number': item.get('incidentNumber')})
        incidents.sort(key=lambda i: (not i['fire'], i['miles'] if i['miles'] is not None else 999))
        result = {'status': 'ok', 'count': len(incidents), 'fires': sum(i['fire'] for i in incidents),
                  'incidents': incidents[:10], 'checked_at': checked, 'error': None}
    except Exception as error:
        result = {'status': 'unavailable', 'count': None, 'fires': None, 'incidents': [], 'checked_at': checked,
                  'error': type(error).__name__}
    print(json.dumps(result))


if __name__ == '__main__':
    main()
