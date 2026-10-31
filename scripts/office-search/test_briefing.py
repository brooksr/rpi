import datetime as dt
import unittest

from briefing import summarize

NOW = dt.datetime(2026, 10, 25, 16, 0, tzinfo=dt.timezone.utc)


def payload(topic, entity, attrs, state='ok'):
    return {'topic': topic, 'sensors': {entity: {'state': state, 'attributes': dict(checked_at=NOW.isoformat(), **attrs)}}}


class BriefingTests(unittest.TestCase):
    def morning(self):
        return {'topic': 'morning', 'sensors': {
            'weather.forecast_home': {'state': 'sunny', 'attributes': {'temperature': 58}},
            'sensor.babysteps_status': {'state': 'ok', 'attributes': {'checked_at': NOW.isoformat(), 'child': 'Sam',
                'lastFeed': {'at': '2026-10-25T15:50:00Z', 'method': 'bottle', 'amountOz': 4},
                'lastDiaper': {'at': '2026-10-25T15:40:00Z', 'kind': 'wet'}}},
            'sensor.local_weather_alerts': {'state': 'clear', 'attributes': {'checked_at': NOW.isoformat(), 'alerts': []}},
            'sensor.power_shutoff': {'state': 'no_psps_listed', 'attributes': {'checked_at': NOW.isoformat(), 'circuit': 'HOME'}}},
            'forecast': {'weather.forecast_home': {'forecast': [{'datetime': '2026-10-25T12:00:00Z', 'temperature': 80}]}},
            'intervals': {'feed': 3, 'diaper': 2}}

    def test_morning_recent_care_and_configurable_routine(self):
        text = summarize(self.morning(), NOW)
        self.assertIn('58 degrees now, high 80', text)
        self.assertIn('last ate at 8:50 AM', text)
        self.assertIn('diaper changed at 8:40 AM', text)
        self.assertIn('next feed in 2 hours and 50 minutes', text)
        self.assertIn('next change in 1 hour and 40 minutes', text)
        self.assertNotIn('Fahrenheit', text)
        self.assertNotIn('routine', text)
        self.assertNotIn('ago', text)
        self.assertEqual(text.count('.'), 1)
        self.assertNotIn('Power warning:', text)

    def test_morning_unknown_current_does_not_hide_high(self):
        data = self.morning()
        data['sensors']['weather.forecast_home']['state'] = 'unavailable'
        self.assertIn('high 80', summarize(data, NOW))

    def test_morning_unfinished_nursing_does_not_predict_next_feed(self):
        data = self.morning()
        data['sensors']['sensor.babysteps_status']['attributes']['lastFeed'] = {'at': '2026-10-25T15:50:00Z', 'method': 'nursing'}
        text = summarize(data, NOW)
        self.assertIn('not marked finished', text)
        self.assertNotIn('next feed', text)

    def test_morning_failed_warning_feeds_are_not_all_clear(self):
        data = self.morning()
        for name in ('sensor.local_weather_alerts', 'sensor.power_shutoff'):
            data['sensors'][name]['state'] = 'unavailable'
        text = summarize(data, NOW)
        self.assertIn('Weather warning data is unavailable', text)
        self.assertIn('Power warning data is unavailable', text)

    def test_morning_only_unexpired_alerts_and_power_warning(self):
        data = self.morning()
        data['sensors']['sensor.local_weather_alerts']['attributes']['alerts'] = [
            {'event': 'Red Flag Warning', 'expires': '2026-10-26T01:00:00Z'},
            {'event': 'Expired Warning', 'expires': '2026-10-25T15:00:00Z'}]
        data['sensors']['sensor.power_shutoff']['state'] = 'under_consideration'
        text = summarize(data, NOW)
        self.assertIn('Red Flag Warning', text)
        self.assertNotIn('Expired Warning', text)
        self.assertIn('considering a power shutoff on HOME', text)

    def test_home_check_reports_lights_and_health_without_guessing(self):
        data = {'topic': 'home_check', 'sensors': {
            'sensor.h5075_001b_temperature': {'state': '74', 'attributes': {}},
            'sensor.h5075_001b_humidity': {'state': '55'},
            'sensor.internet': {'state': 'online', 'attributes': {'checked_at': NOW.isoformat()}},
            'sensor.raspberry_pi': {'state': 'ok', 'attributes': {'checked_at': NOW.isoformat(), 'disk_percent': 95}}},
            'lights': [{'name': 'Kitchen', 'state': 'on'}, {'name': 'Porch', 'state': 'unavailable'}]}
        text = summarize(data, NOW)
        self.assertIn('Office is 74 degrees', text)
        self.assertIn('lights on: Kitchen', text)
        self.assertIn('1 light readings unavailable', text)
        self.assertIn('laptop: storage nearly full', text)
        self.assertIn('Raspberry Pi health unavailable', text)

    def test_morning_elapsed_estimate_says_now_without_negative_time(self):
        data = self.morning()
        data['intervals']['feed'] = 0.5
        data['sensors']['sensor.babysteps_status']['attributes']['lastFeed']['at'] = '2026-10-25T14:00:00Z'
        self.assertIn('next feed estimated now', summarize(data, NOW))

    def test_baby_last_event_from_previous_day_and_recorded_sleep(self):
        data = payload('baby_feed', 'sensor.babysteps_status', {
            'child': 'Sam', 'lastFeed': {'at': '2026-10-25T06:30:00Z', 'method': 'bottle', 'amountOz': 4},
            'lastSleep': {'at': '2026-10-25T06:45:00Z', 'endedAt': None}})
        self.assertIn('yesterday at 11:30 PM', summarize(data, NOW))
        self.assertIn('4 ounce bottle', summarize(data, NOW))
        self.assertIn('not been marked finished', summarize(dict(data, topic='baby_sleep'), NOW))

    def test_stale_baby_is_not_presented_as_current(self):
        data = payload('baby_feed', 'sensor.babysteps_status', {'lastFeed': {'at': NOW.isoformat()}})
        data['sensors']['sensor.babysteps_status']['attributes']['checked_at'] = '2026-10-25T15:00:00Z'
        self.assertIn('out of date', summarize(data, NOW))

    def test_missing_records_are_not_invented(self):
        data = payload('baby_bath', 'sensor.babysteps_status', {'child': 'Sam'})
        self.assertIn('No bath is recorded', summarize(data, NOW))

    def test_traffic_partial_failure_is_not_clear_traffic(self):
        data = payload('traffic', 'sensor.freeway_conditions', {'errors': {'closures': 'TimeoutError'}, 'signs': [
            {'route': '101', 'message': ['EXPECT', 'DELAYS']}]})
        answer = summarize(data, NOW)
        self.assertIn('closure feed is unavailable', answer)
        self.assertNotIn('no crews', answer)
        self.assertIn('EXPECT DELAYS', answer)

    def test_launch_skips_past_and_sorts_future(self):
        data = payload('launch', 'sensor.vandenberg_launches', {'launches': [
            {'net': '2026-10-25T15:45:00Z', 'mission': 'Past'},
            {'net': '2026-10-28T02:00:00Z', 'mission': 'Later'},
            {'net': '2026-10-27T02:00:00Z', 'mission': 'Next', 'rocket': 'Falcon 9', 'view': 'night', 'status': 'Go'}]}, '3')
        answer = summarize(data, NOW)
        self.assertIn('Next', answer)
        self.assertNotIn('Past', answer)
        self.assertNotIn('Later', answer)
        self.assertIn('Pacific time', answer)

    def test_gas_reports_source_time_not_recent_poll_time(self):
        data = payload('gas', 'sensor.local_gas_prices', {'stations': [
            {'name': 'Costly', 'price': 5.8},
            {'name': 'Cheapest', 'price': 5.499, 'miles': 2, 'updated': '2026-10-23T17:00:00Z'}]})
        answer = summarize(data, NOW)
        self.assertIn('Cheapest', answer)
        self.assertIn('5.50 dollars', answer)
        self.assertIn('Friday, October 23 at 10:00 AM', answer)
        self.assertIn('may have changed', answer)

    def test_tomorrow_forecast_uses_local_day(self):
        data = {'topic': 'forecast_tomorrow', 'forecast': {'weather.forecast_home': {'forecast': [
            {'datetime': '2026-10-25T12:00:00Z', 'temperature': 80, 'condition': 'sunny'},
            {'datetime': '2026-10-26T12:00:00Z', 'temperature': 75, 'templow': 50, 'condition': 'rainy', 'precipitation_probability': 80}]}}}
        answer = summarize(data, NOW)
        self.assertIn('Tomorrow: rainy, high 75', answer)
        self.assertNotIn('high 80', answer)

    def test_stale_observation_falls_back_to_weather_service(self):
        data = {'topic': 'weather', 'sensors': {
            'sensor.nws_observation': {'state': '5', 'attributes': {'timestamp': '2026-10-25T10:00:00Z'}},
            'weather.forecast_home': {'state': 'sunny', 'attributes': {'temperature': 71, 'temperature_unit': '°F', 'humidity': 40}}}}
        self.assertIn('sunny, 71 degrees Fahrenheit', summarize(data, NOW))


if __name__ == '__main__':
    unittest.main()
