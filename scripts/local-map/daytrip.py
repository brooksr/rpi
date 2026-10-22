"""Drive time, weather and wind, water temperature, surf and tides for day-trip beaches.

Each source fails on its own, so a Routes outage still leaves tides and
temperatures; a missing value is null, never a guess."""
import datetime
import json
import pathlib
import re
import sys
import urllib.parse
import urllib.error
import urllib.request

SECRETS = pathlib.Path('/config/secrets.yaml')
# Nearest NOAA prediction station: Santa Monica Pier is the closest to Malibu.
DESTINATIONS = [
    {'name': 'Ventura', 'place': 'Ventura Pier', 'lat': 34.2747, 'lon': -119.2905, 'tide_station': '9411189', 'tide_name': 'Ventura'},
    {'name': 'Malibu', 'place': 'Malibu Pier', 'lat': 34.0378, 'lon': -118.6773, 'tide_station': '9410840', 'tide_name': 'Santa Monica'},
]
HEADERS = {'User-Agent': 'HomeAssistant-LocalMap/1.0'}


def api_key():
    path = SECRETS
    match = re.search(r'^google_places_api_key:\s*["\']?([^"\'\s#]+)', path.read_text(), re.M) if path.exists() else None
    return match.group(1) if match else None


def fetch(url, body=None, headers=None):
    request = urllib.request.Request(url, data=json.dumps(body).encode() if body else None,
                                     headers={**HEADERS, **(headers or {})})
    with urllib.request.urlopen(request, timeout=6) as response:
        return json.load(response)


def drive(key, origin, place):
    point = lambda lat, lon: {'location': {'latLng': {'latitude': lat, 'longitude': lon}}}
    data = fetch('https://routes.googleapis.com/directions/v2:computeRoutes',
                 {'origin': point(*origin), 'destination': point(place['lat'], place['lon']),
                  'travelMode': 'DRIVE', 'routingPreference': 'TRAFFIC_AWARE'},
                 {'Content-Type': 'application/json', 'X-Goog-Api-Key': key,
                  'X-Goog-FieldMask': 'routes.duration,routes.distanceMeters'})
    route = data['routes'][0]
    return {'drive_minutes': round(int(route['duration'].rstrip('s')) / 60),
            'drive_miles': round(route['distanceMeters'] / 1609.344, 1)}


def weather(place):
    query = urllib.parse.urlencode({'latitude': place['lat'], 'longitude': place['lon'],
                                    'current': 'temperature_2m,wind_speed_10m,wind_direction_10m,wind_gusts_10m',
                                    'daily': 'temperature_2m_max', 'forecast_days': 1, 'temperature_unit': 'fahrenheit',
                                    'wind_speed_unit': 'mph', 'timezone': 'America/Los_Angeles'})
    data = fetch(f'https://api.open-meteo.com/v1/forecast?{query}')
    current = data['current']
    return {'air_temp': current['temperature_2m'], 'air_high': data['daily']['temperature_2m_max'][0],
            'wind_mph': current.get('wind_speed_10m'), 'wind_gust_mph': current.get('wind_gusts_10m'),
            'wind_dir': current.get('wind_direction_10m')}


SURF = ('wave_height', 'wave_period', 'swell_wave_height', 'swell_wave_period', 'swell_wave_direction')
SURF_KEYS = ('wave_ft', 'period_s', 'swell_ft', 'swell_period_s', 'swell_dir')


def water(place, now):
    # One marine call: water temperature, and waves and swell (feet, seconds,
    # degrees the swell comes from) now and every 3 hours for the next day.
    query = urllib.parse.urlencode({'latitude': place['lat'], 'longitude': place['lon'],
                                    'current': 'sea_surface_temperature,' + ','.join(SURF), 'hourly': ','.join(SURF),
                                    'temperature_unit': 'fahrenheit', 'length_unit': 'imperial', 'timezone': 'GMT',
                                    'forecast_days': 2})
    data = fetch(f'https://marine-api.open-meteo.com/v1/marine?{query}')
    current, hourly = data['current'], data.get('hourly') or {}
    surf = {key: current.get(name) for name, key in zip(SURF, SURF_KEYS)} if current.get('wave_height') is not None else None
    forecast = []
    for i, t in enumerate(hourly.get('time') or []):
        when = datetime.datetime.fromisoformat(t).replace(tzinfo=datetime.timezone.utc)
        if now - datetime.timedelta(hours=1) <= when <= now + datetime.timedelta(hours=24) and when.hour % 3 == 0:
            forecast.append({'t': t + ':00Z', **{key: hourly[name][i] for name, key in zip(SURF, SURF_KEYS)}})
    return {'water_temp': current['sea_surface_temperature'], 'surf': surf, 'surf_forecast': forecast}


def tides(place, now):
    # From yesterday so the chart can draw back to the previous extreme.
    query = urllib.parse.urlencode({'product': 'predictions', 'station': place['tide_station'], 'datum': 'MLLW',
                                    'interval': 'hilo', 'units': 'english', 'time_zone': 'gmt', 'format': 'json',
                                    'begin_date': (now - datetime.timedelta(days=1)).strftime('%Y%m%d'), 'range': 96,
                                    'application': 'HomeAssistant-LocalMap'})
    data = fetch(f'https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?{query}')
    return {'tides': [{'t': p['t'].replace(' ', 'T') + ':00Z', 'v': float(p['v']), 'type': p['type']} for p in data['predictions']]}


def describe(error):
    # Google's status (e.g. PERMISSION_DENIED for a disabled API) says what to fix.
    if isinstance(error, urllib.error.HTTPError):
        try:
            return f"HTTP {error.code} {json.load(error).get('error', {}).get('status', '')}".strip()
        except Exception:
            return f'HTTP {error.code}'
    return type(error).__name__


def main():
    origin = tuple(map(float, sys.argv[1:3]))
    now = datetime.datetime.now(datetime.timezone.utc)
    key = api_key()
    destinations = []
    for place in DESTINATIONS:
        entry = {k: place[k] for k in ('name', 'place', 'tide_name')}
        entry.update(drive_minutes=None, drive_miles=None, air_temp=None, air_high=None, wind_mph=None, wind_gust_mph=None,
                     wind_dir=None, water_temp=None, surf=None, surf_forecast=[], tides=[], errors={})
        sources = [('weather', lambda: weather(place)), ('water', lambda: water(place, now)), ('tides', lambda: tides(place, now))]
        if key:
            sources.insert(0, ('drive', lambda: drive(key, origin, place)))
        else:
            entry['errors']['drive'] = 'needs_key'
        for name, read in sources:
            try:
                entry.update(read())
            except Exception as error:
                entry['errors'][name] = describe(error)
        destinations.append(entry)
    ok = any(len(d['errors']) < 4 for d in destinations)
    print(json.dumps({'status': 'ok' if ok else 'unavailable', 'destinations': destinations, 'checked_at': now.isoformat()}))


if __name__ == '__main__':
    main()
