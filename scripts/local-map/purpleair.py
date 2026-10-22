"""Nearby outdoor PurpleAir PM2.5, EPA-corrected, as a US AQI estimate.

Raw PurpleAir readings run high; the EPA's US-wide correction (2021) uses the
cf_1 channel and humidity. The AQI uses the 2024 PM2.5 breakpoints on current
readings, so it is an estimate, not an official 24-hour AQI. Each request spends
PurpleAir API points (fields x sensors), so the box and field list stay small."""
import datetime
import json
import math
import pathlib
import re
import statistics
import sys
import urllib.error
import urllib.parse
import urllib.request

SECRETS = pathlib.Path('/config/secrets.yaml')
FIELDS = 'name,latitude,longitude,pm2.5_cf_1,humidity'
BREAKPOINTS = [(0.0, 9.0, 0, 50), (9.1, 35.4, 51, 100), (35.5, 55.4, 101, 150),
               (55.5, 125.4, 151, 200), (125.5, 225.4, 201, 300), (225.5, 325.4, 301, 500)]


def api_key():
    path = SECRETS
    match = re.search(r'^purpleair_api_key:\s*["\']?([^"\'\s#]+)', path.read_text(), re.M) if path.exists() else None
    return match.group(1) if match else None


def corrected(cf1, humidity):
    if cf1 is None or humidity is None:
        return None
    value = 0.524 * cf1 - 0.0862 * humidity + 5.75 if cf1 < 343 else 0.46 * cf1 + 3.93e-4 * cf1 ** 2 + 2.97
    return max(value, 0.0)


def aqi(pm):
    pm = math.floor(pm * 10) / 10
    for low, high, aqi_low, aqi_high in BREAKPOINTS:
        if pm <= high:
            return round((aqi_high - aqi_low) / (high - low) * (pm - low) + aqi_low)
    return 500


def miles(home, lat, lon):
    return math.hypot(lat - home[0], (lon - home[1]) * math.cos(math.radians(home[0]))) * 69.05


def main():
    lat, lon, radius = map(float, sys.argv[1:4])
    checked = datetime.datetime.now(datetime.timezone.utc).isoformat()
    result = {'status': 'unavailable', 'aqi': None, 'pm25': None, 'sensors': [], 'checked_at': checked, 'error': None}
    key = api_key()
    if not key:
        result.update(status='needs_key', error='Add purpleair_api_key to secrets.yaml')
        print(json.dumps(result))
        return
    try:
        dlat, dlon = radius / 69.05, radius / (69.05 * math.cos(math.radians(lat)))
        query = urllib.parse.urlencode({'fields': FIELDS, 'location_type': 0, 'max_age': 3600,
                                        'nwlat': lat + dlat, 'selat': lat - dlat, 'nwlng': lon - dlon, 'selng': lon + dlon})
        request = urllib.request.Request(f'https://api.purpleair.com/v1/sensors?{query}', headers={'X-API-Key': key})
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.load(response)
        fields = data['fields']
        sensors = []
        for row in data['data']:
            item = dict(zip(fields, row))
            pm = corrected(item.get('pm2.5_cf_1'), item.get('humidity'))
            if pm is not None and item.get('latitude') is not None:
                sensors.append({'name': item.get('name'), 'pm25': round(pm, 1),
                                'miles': round(miles((lat, lon), item['latitude'], item['longitude']), 1)})
        sensors.sort(key=lambda s: s['miles'])
        nearest = sensors[:8]
        if nearest:
            pm = statistics.median(s['pm25'] for s in nearest)
            result.update(status='ok', pm25=round(pm, 1), aqi=aqi(pm), sensors=nearest)
        else:
            result['status'] = 'no_sensors'
    except urllib.error.HTTPError as error:
        result['error'] = f'HTTP {error.code}'
    except Exception as error:
        result['error'] = type(error).__name__
    print(json.dumps(result))


if __name__ == '__main__':
    main()
