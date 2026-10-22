"""Read active NWS warnings for the home point; failed feeds stay unavailable."""
import datetime
import json
import sys
import urllib.request


def main():
    lat, lon = map(float, sys.argv[1:3])
    checked = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        request = urllib.request.Request(
            f'https://api.weather.gov/alerts/active?point={lat},{lon}',
            headers={'User-Agent': 'HomeAssistant-LocalMap/1.0', 'Accept': 'application/geo+json'},
        )
        with urllib.request.urlopen(request, timeout=22) as response:
            data = json.load(response)
        if not isinstance(data.get('features'), list):
            raise ValueError('Invalid NWS response')
        keys = ('event', 'headline', 'severity', 'effective', 'ends', 'expires', 'instruction', 'description')
        alerts = [{k: feature['properties'].get(k) for k in keys} for feature in data['features']]
        result = {'status': 'active' if alerts else 'clear', 'count': len(alerts),
                  'alerts': alerts, 'checked_at': checked, 'error': None}
    except Exception as error:
        result = {'status': 'unavailable', 'count': None, 'alerts': [],
                  'checked_at': checked, 'error': type(error).__name__}
    print(json.dumps(result))


if __name__ == '__main__':
    main()
