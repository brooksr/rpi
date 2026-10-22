"""One failing day-trip source must not hide the others or invent values."""
import contextlib
import io
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

import daytrip

RESPONSES = {
    'routes.googleapis.com': {'routes': [{'duration': '3120s', 'distanceMeters': 61000}]},
    'api.open-meteo.com': {'current': {'temperature_2m': 71.2, 'wind_speed_10m': 8.1, 'wind_direction_10m': 280,
                                       'wind_gusts_10m': 14.0}, 'daily': {'temperature_2m_max': [78.0]}},
    'marine-api.open-meteo.com': {
        'current': {'sea_surface_temperature': 66.4, 'wave_height': 3.3, 'wave_period': 11.2, 'swell_wave_height': 2.6,
                    'swell_wave_period': 13.0, 'swell_wave_direction': 265},
        'hourly': {'time': ['2026-10-18T12:00', '2026-10-18T13:00', '2026-10-18T15:00'], 'wave_height': [3.0, 3.1, 3.4],
                   'wave_period': [11.0, 11.1, 11.5], 'swell_wave_height': [2.4, 2.5, 2.8],
                   'swell_wave_period': [13.0, 13.0, 12.5], 'swell_wave_direction': [265, 265, 260]}},
    'api.tidesandcurrents.noaa.gov': {'predictions': [{'t': '2026-10-18 14:27', 'v': '3.709', 'type': 'H'}]},
}


class DaytripTests(unittest.TestCase):
    def read(self, key='abc123', failing=()):
        def fetch(url, body=None, headers=None):
            host = url.split('/')[2]
            if host in failing:
                raise TimeoutError()
            return RESPONSES[host]
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as folder:
            secrets = pathlib.Path(folder, 'secrets.yaml')
            if key:
                secrets.write_text(f'google_places_api_key: {key}\n')
            with patch.object(daytrip, 'SECRETS', secrets), patch.object(daytrip, 'fetch', fetch), \
                    patch('sys.argv', ['daytrip.py', '34.176', '-118.849']), contextlib.redirect_stdout(output):
                daytrip.main()
        return json.loads(output.getvalue())

    def test_all_sources(self):
        ventura = self.read()['destinations'][0]
        self.assertEqual((ventura['drive_minutes'], ventura['drive_miles']), (52, 37.9))
        self.assertEqual((ventura['air_temp'], ventura['water_temp']), (71.2, 66.4))
        self.assertEqual(ventura['tides'][0], {'t': '2026-10-18T14:27:00Z', 'v': 3.709, 'type': 'H'})
        self.assertEqual(ventura['errors'], {})
        self.assertEqual((ventura['wind_mph'], ventura['wind_dir']), (8.1, 280))
        self.assertEqual(ventura['surf'], {'wave_ft': 3.3, 'period_s': 11.2, 'swell_ft': 2.6, 'swell_period_s': 13.0,
                                           'swell_dir': 265})

    def test_surf_forecast_every_three_hours_from_now(self):
        with patch.object(daytrip.datetime, 'datetime', wraps=daytrip.datetime.datetime) as clock:
            clock.now.return_value = daytrip.datetime.datetime(2026, 10, 18, 12, 30, tzinfo=daytrip.datetime.timezone.utc)
            forecast = self.read()['destinations'][0]['surf_forecast']
        self.assertEqual([f['t'] for f in forecast], ['2026-10-18T12:00:00Z', '2026-10-18T15:00:00Z'])
        self.assertEqual(forecast[1]['wave_ft'], 3.4)

    def test_failures_stay_separate(self):
        result = self.read(key=None, failing=('marine-api.open-meteo.com',))
        malibu = result['destinations'][1]
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(malibu['errors'], {'drive': 'needs_key', 'water': 'TimeoutError'})
        self.assertIsNone(malibu['water_temp'])
        self.assertIsNone(malibu['surf'])
        self.assertEqual(malibu['air_temp'], 71.2)

    def test_everything_down_is_unavailable(self):
        self.assertEqual(self.read(failing=tuple(RESPONSES))['status'], 'unavailable')


if __name__ == '__main__':
    unittest.main()
