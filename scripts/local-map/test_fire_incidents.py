"""Fires sort first, then nearest; a bad feed is unavailable, not zero calls."""
import contextlib
import io
import json
import unittest
from unittest.mock import patch

import fire_incidents


def call(kind, lat, lon):
    return {'incidentType': kind, 'block': '700', 'address': 'Bright Star St', 'city': 'Thousand Oaks', 'status': 'On scene',
            'units': 'ME34', 'responseDate': '10/18/26 7:35', 'latitude': str(lat), 'longitude': str(lon)}


class FireIncidentTests(unittest.TestCase):
    def read(self, payload=None, error=None):
        output = io.StringIO()
        with patch('sys.argv', ['fire_incidents.py', '34.176', '-118.849']), contextlib.redirect_stdout(output), \
                patch('urllib.request.urlopen', side_effect=error, return_value=io.StringIO(json.dumps(payload))):
            fire_incidents.main()
        return json.loads(output.getvalue())

    def test_fires_first_then_nearest(self):
        result = self.read([call('Medical', 34.30, -118.9), call('Medical', 34.18, -118.854), call('Vegetation Fire', 34.40, -119.2)])
        self.assertEqual([i['type'] for i in result['incidents']], ['Vegetation Fire', 'Medical', 'Medical'])
        self.assertLess(result['incidents'][1]['miles'], result['incidents'][2]['miles'])
        self.assertEqual((result['count'], result['fires']), (3, 1))
        self.assertEqual(result['incidents'][0]['responded'], '2026-10-18T07:35')
        self.assertEqual(result['incidents'][0]['address'], '700 Bright Star St')

    def test_only_burning_fires_count(self):
        kinds = ['Vegetation Fire', 'Structure Fire', 'Vehicle Fire', 'Illegal Burn', 'Fire Alarm', 'Smoke Investigation', 'Medical']
        self.assertEqual([fire_incidents.is_fire(k) for k in kinds], [True, True, True, True, False, False, False])

    def test_failures_are_unavailable(self):
        self.assertEqual(self.read(error=TimeoutError())['status'], 'unavailable')
        self.assertEqual(self.read({'error': 'x'})['status'], 'unavailable')
        self.assertEqual(self.read([])['count'], 0)


if __name__ == '__main__':
    unittest.main()
