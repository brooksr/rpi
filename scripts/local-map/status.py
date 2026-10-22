"""Read-only SCE PSPS status. Runs in HA's command_line integration."""
import concurrent.futures
import datetime
import json
import sys
import urllib.parse
import urllib.request

BASE = 'https://sce-outage-ags.esriemcs.com/arcgis/rest/services/43/psps/MapServer'


def query(layer, circuit):
    params = urllib.parse.urlencode({
        'where': "CIRCUIT_NAME='" + circuit.replace("'", "''") + "'",
        'outFields': 'CIRCUIT_NAME,PSPS,StartDate,EndDate,ERT,ERTNotes,POCNotes,PSPS_Details',
        'returnGeometry': 'false', 'f': 'json',
    })
    request = urllib.request.Request(f'{BASE}/{layer}/query?{params}', headers={'User-Agent': 'HomeAssistant-LocalMap/1.0'})
    with urllib.request.urlopen(request, timeout=18) as response:
        data = json.load(response)
    if 'error' in data or 'features' not in data or data.get('exceededTransferLimit'):
        raise ValueError('SCE returned an incomplete or invalid response')
    return [f['attributes'] for f in data['features']]


def summarize(monitored, active):
    return 'power_shutoff' if active else 'under_consideration' if monitored else 'no_psps_listed'


def main():
    circuit = sys.argv[1]
    checked = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            monitored_future = pool.submit(query, 0, circuit)
            active_future = pool.submit(query, 1, circuit)
            monitored, active = monitored_future.result(), active_future.result()
        result = {'status': summarize(monitored, active), 'circuit': circuit,
                  'checked_at': checked, 'events': active + monitored, 'error': None}
    except Exception as error:
        # A failed request must never be interpreted as an all-clear.
        result = {'status': 'unavailable', 'circuit': circuit, 'checked_at': checked,
                  'events': [], 'error': type(error).__name__}
    print(json.dumps(result))


if __name__ == '__main__':
    main()
