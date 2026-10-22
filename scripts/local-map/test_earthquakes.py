"""24-hour count, alert only for strong recent quakes, failures unavailable."""
import contextlib
import datetime
import io
import json
import unittest
from unittest.mock import patch

import earthquakes


def quake(qid, mag, minutes_ago, lat=34.2, lon=-118.9):
    when = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=minutes_ago)
    return {'id': qid, 'geometry': {'coordinates': [lon, lat, 8.2]},
            'properties': {'mag': mag, 'place': f'{qid} place', 'time': when.timestamp() * 1000, 'url': f'https://usgs/{qid}'}}


class EarthquakeTests(unittest.TestCase):
    def read(self, features=None, error=None):
        output = io.StringIO()
        with patch('sys.argv', ['earthquakes.py', '34.176', '-118.849']), contextlib.redirect_stdout(output), \
                patch('urllib.request.urlopen', side_effect=error, return_value=io.StringIO(json.dumps({'features': features or []}))):
            earthquakes.main()
        return json.loads(output.getvalue())

    def test_counts_and_alert(self):
        result = self.read([quake('a', 4.4, 10), quake('b', 2.7, 300), quake('c', 5.1, 3 * 24 * 60)])
        self.assertEqual((result['count_24h'], result['week_count']), (2, 3))
        self.assertEqual(result['alert']['id'], 'a')
        self.assertEqual(result['largest_week']['id'], 'c')
        self.assertLess(result['quakes'][0]['miles'], 5)

    def test_no_alert_for_small_or_old(self):
        self.assertIsNone(self.read([quake('a', 3.9, 5), quake('b', 4.5, 45)])['alert'])

    def test_failure_is_unavailable(self):
        self.assertEqual(self.read(error=TimeoutError())['status'], 'unavailable')


if __name__ == '__main__':
    unittest.main()
