"""Firm launches only, labelled by the sun at home; the alert targets the next dark-sky launch."""
import contextlib
import datetime
import io
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

import launches

HOME = (34.1764, -118.8489)  # Thousand Oaks Civic Arts Plaza
NOW = datetime.datetime(2026, 10, 18, 17, 0, tzinfo=datetime.timezone.utc)


def launch(lid, net, precision='Minute', status='Go'):
    return {'id': lid, 'name': f'Falcon 9 Block 5 | Mission {lid}', 'net': net, 'net_precision': {'name': precision},
            'status': {'abbrev': status}, 'rocket': {'configuration': {'name': 'Falcon 9'}},
            'mission': {'name': f'Mission {lid}'}, 'pad': {'name': 'SLC-4E'}}


class LaunchTests(unittest.TestCase):
    def test_sun_altitude(self):
        # Sunset at home on Oct 18, 2026 is 6:17 PM PDT (01:17Z); noon sun is about 45°.
        self.assertAlmostEqual(launches.sun_altitude(datetime.datetime(2026, 10, 19, 1, 17, tzinfo=datetime.timezone.utc), *HOME), -0.8, delta=0.6)
        self.assertGreater(launches.sun_altitude(datetime.datetime(2026, 10, 18, 19, 50, tzinfo=datetime.timezone.utc), *HOME), 40)

    def test_views_and_alert(self):
        result = launches.summarize([
            launch('day', '2026-10-20T22:14:00Z'),              # 3:14 PM: day
            launch('dusk', '2026-10-21T01:20:00Z'),             # just after sunset
            launch('twilight', '2026-10-21T01:50:00Z'),         # 6:50 PM: sun ~6° down
            launch('night', '2026-10-24T05:29:00Z'),            # 10:29 PM
            launch('vague', '2026-12-31T00:00:00Z', 'Month'),   # no firm time
        ], HOME, NOW)
        self.assertEqual([l['view'] for l in result['launches']], ['day', 'dusk', 'twilight', 'night'])
        self.assertEqual(result['alert']['id'], 'twilight')
        self.assertEqual(result['alert_at'], '2026-10-21T01:40:00+00:00')

    def test_only_go_launches_alert(self):
        result = launches.summarize([launch('tbd', '2026-10-24T05:29:00Z', status='TBD')], HOME, NOW)
        self.assertEqual(result['count'], 1)
        self.assertIsNone(result['alert'])

    def test_failure_uses_recent_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = pathlib.Path(folder, 'cache.json')
            def run(error=None, payload=None):
                out = io.StringIO()
                with patch.object(launches, 'CACHE', cache), patch('sys.argv', ['launches.py', *map(str, HOME)]), \
                        patch('urllib.request.urlopen', side_effect=error, return_value=io.StringIO(json.dumps(payload or {}))), \
                        contextlib.redirect_stdout(out):
                    launches.main()
                return json.loads(out.getvalue())
            future = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=2)).strftime('%Y-%m-%dT%H:%M:00Z')
            self.assertEqual(run(payload={'results': [launch('a', future)]})['count'], 1)
            stale = run(error=TimeoutError())
            self.assertEqual((stale['status'], stale['count']), ('ok', 1))
            self.assertIn('TimeoutError', stale['error'])
            cache.unlink()
            self.assertEqual(run(error=TimeoutError())['status'], 'unavailable')


if __name__ == '__main__':
    unittest.main()
