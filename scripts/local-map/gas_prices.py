"""Cheapest nearby regular gas from Google Places; failures never look like data."""
import datetime
import json
import math
import pathlib
import re
import sys
import urllib.error
import urllib.request

SECRETS = pathlib.Path('/config/secrets.yaml')
FIELDS = 'places.id,places.displayName,places.formattedAddress,places.location,places.fuelOptions'


def api_key():
    path = SECRETS
    match = re.search(r'^google_places_api_key:\s*["\']?([^"\'\s#]+)', path.read_text(), re.M) if path.exists() else None
    return match.group(1) if match else None


def miles(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(a))


def regular_price(place):
    for fuel in (place.get('fuelOptions') or {}).get('fuelPrices', []):
        if fuel.get('type') == 'REGULAR_UNLEADED' and fuel.get('price'):
            price = fuel['price']
            return int(price.get('units', 0)) + price.get('nanos', 0) / 1e9, fuel.get('updateTime')
    return None, None


def describe(error):
    # Google's status (e.g. PERMISSION_DENIED for a disabled API) says what to fix.
    if isinstance(error, urllib.error.HTTPError):
        try:
            return f"HTTP {error.code} {json.load(error).get('error', {}).get('status', '')}".strip()
        except Exception:
            return f'HTTP {error.code}'
    return type(error).__name__


def main():
    lat, lon, radius_miles = map(float, sys.argv[1:4])
    checked = datetime.datetime.now(datetime.timezone.utc).isoformat()
    result = {'status': 'unavailable', 'stations': [], 'checked_at': checked, 'error': None}
    key = api_key()
    if not key:
        result.update(status='needs_key', error='Add google_places_api_key to secrets.yaml')
        print(json.dumps(result))
        return
    try:
        body = {'includedTypes': ['gas_station'], 'maxResultCount': 20, 'rankPreference': 'DISTANCE',
                'locationRestriction': {'circle': {'center': {'latitude': lat, 'longitude': lon},
                                                   'radius': radius_miles * 1609.344}}}
        request = urllib.request.Request(
            'https://places.googleapis.com/v1/places:searchNearby', data=json.dumps(body).encode(),
            headers={'Content-Type': 'application/json', 'X-Goog-Api-Key': key, 'X-Goog-FieldMask': FIELDS},
        )
        with urllib.request.urlopen(request, timeout=22) as response:
            data = json.load(response)
        if not isinstance(data, dict):
            raise ValueError('Invalid Places response')
        stations = []
        for place in data.get('places', []):
            price, updated = regular_price(place)
            location = place.get('location') or {}
            if price is None or 'latitude' not in location:
                continue
            stations.append({'name': (place.get('displayName') or {}).get('text') or 'Gas station',
                             'address': place.get('formattedAddress'), 'place_id': place.get('id'),
                             'price': round(price, 3), 'updated': updated,
                             'miles': round(miles(lat, lon, location['latitude'], location['longitude']), 1)})
        stations.sort(key=lambda s: (s['price'], s['miles']))
        result.update(status='ok' if stations else 'no_prices', stations=stations[:3])
    except Exception as error:
        result['error'] = describe(error)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
