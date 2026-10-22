"""EPA correction and 2024 AQI breakpoints; no key asks for one, failures stay unavailable."""
import contextlib
import io
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

import purpleair


class PurpleAirTests(unittest.TestCase):
    def read(self, payload=None, error=None, key='abc'):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as folder:
            secrets = pathlib.Path(folder, 'secrets.yaml')
            if key:
                secrets.write_text(f'purpleair_api_key: {key}\n')
            with patch.object(purpleair, 'SECRETS', secrets), patch('sys.argv', ['purpleair.py', '34.176', '-118.849', '2']), \
                    patch('urllib.request.urlopen', side_effect=error, return_value=io.StringIO(json.dumps(payload))), \
                    contextlib.redirect_stdout(output):
                purpleair.main()
        return json.loads(output.getvalue())

    def test_math(self):
        self.assertAlmostEqual(purpleair.corrected(20, 50), 11.92)
        self.assertEqual(purpleair.corrected(1, 90), 0.0)
        self.assertEqual([purpleair.aqi(v) for v in (0, 9.0, 9.1, 35.4, 55.5, 400)], [0, 50, 51, 100, 151, 500])

    def test_median_of_nearest(self):
        fields = ['sensor_index', 'name', 'latitude', 'longitude', 'pm2.5_cf_1', 'humidity']
        rows = [[1, 'Near', 34.177, -118.849, 20, 50], [2, 'Mid', 34.18, -118.854, 10, 50], [3, 'Far', 34.163, -118.834, 40, 50]]
        result = self.read({'fields': fields, 'data': rows})
        self.assertEqual(result['status'], 'ok')
        self.assertEqual([s['name'] for s in result['sensors']], ['Near', 'Mid', 'Far'])
        self.assertEqual(result['pm25'], 11.9)
        self.assertEqual(result['aqi'], 56)

    def test_states(self):
        self.assertEqual(self.read(key=None)['status'], 'needs_key')
        self.assertEqual(self.read(error=TimeoutError())['status'], 'unavailable')
        self.assertEqual(self.read({'fields': [], 'data': []})['status'], 'no_sensors')


if __name__ == '__main__':
    unittest.main()
