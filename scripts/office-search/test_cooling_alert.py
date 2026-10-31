"""Exercise the deployed YAML templates at the threshold and with stale feeds."""
import datetime as dt
import math
from pathlib import Path
from types import SimpleNamespace
import unittest

import jinja2
import yaml

NOW = dt.datetime(2026, 10, 25, 18, tzinfo=dt.timezone.utc)
PACKAGE = yaml.safe_load(Path(__file__).with_name('cooling_alert.yaml').read_text())
INDOOR, OUTDOOR = PACKAGE['template'][0]['sensor']
CONDITION = PACKAGE['template'][1]['binary_sensor'][0]


def timestamp(value, default=None):
    try:
        return (value if isinstance(value, dt.datetime) else dt.datetime.fromisoformat(value.replace('Z', '+00:00'))).timestamp()
    except (TypeError, ValueError, AttributeError):
        return default


def numeric(value):
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def render(source, entities):
    class States:
        def __call__(self, name):
            return entities.get(name, {}).get('state', 'unknown')

        def __getattr__(self, domain):
            return SimpleNamespace(**{key.split('.', 1)[1]: SimpleNamespace(**value) for key, value in entities.items() if key.startswith(domain + '.')})
    env = jinja2.Environment()
    env.globals.update(states=States(), state_attr=lambda name, attr: entities.get(name, {}).get('attributes', {}).get(attr),
                       is_number=numeric, now=lambda: NOW, as_timestamp=timestamp)
    return env.from_string(source).render().strip()


class CoolingAlertTests(unittest.TestCase):
    def test_exact_threshold_and_strict_outdoor_comparison(self):
        for inside, outside, expected in [(74, 73.9, True), (74, 74, False), (74, 75, False), (73.9, 60, False), (80, 79, True), ('unknown', 60, False), (74, 'unavailable', False)]:
            with self.subTest(inside=inside, outside=outside):
                entities = {'sensor.cooling_indoor_temperature': {'state': inside}, 'sensor.cooling_outdoor_temperature': {'state': outside}}
                self.assertEqual(render(CONDITION['state'], entities), str(expected))

    def test_indoor_celsius_is_converted(self):
        entities = {'sensor.h5075_001b_temperature': {'state': 25, 'attributes': {'unit_of_measurement': '°C'}}}
        self.assertEqual(float(render(INDOOR['state'], entities)), 77)

    def feeds(self, nws_age=10, weather_age=10):
        return {
            'sensor.nws_observation': {'state': 20, 'attributes': {'timestamp': (NOW - dt.timedelta(minutes=nws_age)).isoformat()}},
            'weather.forecast_home': {'state': 'sunny', 'attributes': {'temperature': 70, 'temperature_unit': '°F'},
                                      'last_reported': NOW - dt.timedelta(minutes=weather_age)}}

    def test_fresh_station_wins_and_is_converted(self):
        entities = self.feeds()
        self.assertEqual(render(OUTDOOR['availability'], entities), 'True')
        self.assertEqual(float(render(OUTDOOR['state'], entities)), 68)

    def test_stale_station_falls_back_to_fresh_weather(self):
        entities = self.feeds(nws_age=120)
        self.assertEqual(render(OUTDOOR['availability'], entities), 'True')
        self.assertEqual(float(render(OUTDOOR['state'], entities)), 70)

    def test_both_stale_is_unavailable(self):
        self.assertEqual(render(OUTDOOR['availability'], self.feeds(120, 120)), 'False')


if __name__ == '__main__':
    unittest.main()
