"""Today's entries in the child's time zone, days since bath, token rotation saved first."""
import datetime
import json
import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch

try:
    import zoneinfo  # noqa: F401  (Python 3.9+, as in the HA container)
    import babysteps_today
except ImportError:
    babysteps_today = None

NOW = datetime.datetime(2026, 10, 18, 17, 0, tzinfo=datetime.timezone.utc)  # 10 AM Pacific


@unittest.skipIf(babysteps_today is None, 'needs Python 3.9+ zoneinfo')
class BabyStepsTodayTests(unittest.TestCase):
    def test_summary(self):
        data = {'profiles': [{'id': 'p', 'kind': 'parent', 'name': 'Parent'},
                             {'id': 'b', 'name': 'Ava Example', 'timezone': 'America/Los_Angeles'}],
                'events': [
                    {'babyId': 'b', 'type': 'feed', 'method': 'bottle', 'amountOz': 4, 'startedAt': '2026-10-18T15:30:00Z'},
                    {'babyId': 'b', 'type': 'diaper', 'kind': 'wet', 'startedAt': '2026-10-18T08:00:00Z'},  # 1 AM today
                    {'babyId': 'b', 'type': 'sleep', 'startedAt': '2026-10-18T05:00:00Z'},  # 10 PM yesterday
                    {'babyId': 'b', 'type': 'bath', 'startedAt': '2026-10-15T02:00:00Z'},  # Oct 14, 7 PM Pacific
                ]}
        result = babysteps_today.summarize(data, NOW)
        self.assertEqual(result['child'], 'Ava')
        self.assertEqual([e['text'] for e in result['events']], ['Diaper · wet', 'Bottle · 4 oz'])
        self.assertEqual(result['days_since_bath'], 4)
        self.assertEqual(result['lastSleep'], {'at': '2026-10-18T05:00:00Z', 'endedAt': None})

    def test_briefing(self):
        base = {'child': 'Sam', 'timezone': 'America/Los_Angeles', 'last_cry': '2026-10-18T09:00:00Z', 'cries_last_hour': 0}
        asleep = dict(base, lastSleep={'at': '2026-10-18T10:00:00Z', 'endedAt': None},
                      lastFeed={'at': '2026-10-18T09:30:00Z', 'amountOz': 4, 'method': 'bottle'},
                      lastDiaper={'at': '2026-10-18T09:35:00Z', 'kind': 'wet'})
        now = datetime.datetime(2026, 10, 18, 12, 0, tzinfo=datetime.timezone.utc)  # 5 AM Pacific
        self.assertEqual(babysteps_today.briefing(asleep, now),
                         'Sam is asleep, since 3:00 AM, about 2 hours. Last feed was a 4 ounce bottle at 2:30 AM, '
                         '2 hours 30 minutes ago. Last diaper change at 2:35 AM. No crying in the last hour.')
        due = dict(asleep, lastFeed={'at': '2026-10-18T08:00:00Z', 'amountOz': 3}, lastDiaper={'at': '2026-10-18T08:00:00Z'})
        self.assertIn('a feed is due', babysteps_today.briefing(due, now))
        self.assertIn('a change may be needed', babysteps_today.briefing(due, now))
        self.assertTrue(babysteps_today.briefing(dict(asleep, crying_now=True), now).startswith('Sam is crying now.'))
        nursing = dict(asleep, lastFeed={'at': '2026-10-18T11:40:00Z', 'method': 'nursing'})
        self.assertTrue(babysteps_today.briefing(nursing, now).startswith('Sam is feeding, since 4:40 AM.'))

    def test_crying(self):
        now = datetime.datetime(2026, 10, 18, 12, 0, tzinfo=datetime.timezone.utc)
        nursery = {'episodes': [{'label': 'baby_cry', 'startedAt': '2026-10-18T11:52:00Z', 'endedAt': '2026-10-18T11:53:00Z'},
                                {'label': 'baby_cry', 'startedAt': '2026-10-18T11:20:00Z', 'endedAt': '2026-10-18T11:21:00Z'},
                                {'label': 'speech', 'startedAt': '2026-10-18T11:59:00Z', 'endedAt': '2026-10-18T11:59:30Z'}]}
        self.assertEqual(babysteps_today.crying(nursery, now), {'last_cry': '2026-10-18T11:52:00Z', 'crying_now': True, 'cries_last_hour': 2})
        self.assertFalse(babysteps_today.crying(nursery, now + datetime.timedelta(minutes=20))['crying_now'])

    def test_event_requests(self):
        parse = lambda body: babysteps_today.parse_event_request(body, NOW)
        self.assertEqual(parse({'type': 'feed', 'amount': 4, 'unit': 'oz'})[0],
                         {'amountOz': 4, 'method': 'bottle', 'startedAt': '2026-10-18T17:00:00.000Z', 'type': 'feed'})
        self.assertEqual(parse({'type': 'feed', 'durationMinutes': '20', 'side': 'left'})[0]['startedAt'], '2026-10-18T16:40:00.000Z')
        self.assertEqual(parse({'type': 'feed', 'durationMinutes': 20})[0]['method'], 'nursing')
        self.assertIn('unit is required with an amount (oz or ml).', parse({'type': 'feed', 'amount': 4})[1])
        self.assertIn('A started feed needs a method (bottle or nursing).', parse({'type': 'feed', 'started': True})[1])
        self.assertEqual(parse({'type': 'diaper', 'diaperType': 'poop', 'poopSize': 'large'})[0]['kind'], 'dirty')
        self.assertIn('poopSize only applies to a dirty or both diaper.', parse({'type': 'diaper', 'diaperType': 'wet', 'poopSize': 'small'})[1])
        self.assertEqual(parse({'type': 'sleep', 'durationMinutes': 45})[0],
                         {'endedAt': '2026-10-18T17:00:00.000Z', 'startedAt': '2026-10-18T16:15:00.000Z', 'type': 'sleep'})
        self.assertEqual(parse({'type': 'sleep', 'started': 'true'})[0], {'startedAt': '2026-10-18T17:00:00.000Z', 'type': 'sleep'})
        self.assertEqual(parse({'type': 'mood', 'level': 'fussy'})[0]['level'], 3)
        self.assertEqual(parse({'type': 'note', 'text': ' rolled over '})[0]['notes'], 'rolled over')
        self.assertEqual(parse({'type': 'tummy time', 'started': True})[0]['durationMinutes'], 0)
        self.assertEqual(parse({'type': 'pump', 'amount': 120, 'unit': 'ml'})[0]['side'], 'both')
        self.assertTrue(parse({'type': 'juggle'})[1][0].startswith('type must be one of'))

    def test_children_and_messages(self):
        sam = {'id': 'b', 'name': 'Sam Example', 'timezone': 'America/Los_Angeles'}
        profiles = [{'id': 'p', 'kind': 'parent', 'name': 'Mom'}, sam]
        self.assertEqual(babysteps_today.resolve_child(profiles, None), (sam, []))
        self.assertEqual(babysteps_today.resolve_child(profiles, 'sam')[0], sam)
        self.assertEqual(babysteps_today.resolve_child(profiles, 'Ava')[1], ['No child named "Ava".'])
        say = lambda body: babysteps_today.describe_logged(babysteps_today.parse_event_request(body, NOW)[0], sam)
        self.assertEqual(say({'type': 'feed', 'amount': 3.5, 'unit': 'oz'}), 'Logged a 3.5 oz bottle for Sam at 10:00 AM.')
        self.assertEqual(say({'type': 'diaper', 'diaperType': 'wet'}), 'Logged a wet diaper for Sam at 10:00 AM.')
        self.assertEqual(say({'type': 'sleep', 'durationMinutes': 75}), 'Logged 1 hour 15 minutes of sleep for Sam, from 8:45 AM to 10:00 AM.')
        self.assertEqual(say({'type': 'feed', 'method': 'nursing', 'started': True}),
                         "Started nursing for Sam at 10:00 AM. Add the length in BabySteps when it's done.")
        self.assertEqual(say({'type': 'mood', 'level': 4}), "Logged Sam's mood as crying at 10:00 AM.")

    def test_log_saves_one_entry(self):
        sam = {'id': 'b', 'name': 'Sam Example', 'timezone': 'America/Los_Angeles'}
        calls = []
        def fake_call(path, body=None, token=None):
            calls.append((path, body))
            return {'data': {'profiles': [sam]}} if path.endswith('/bootstrap') else {'revision': 1}
        with patch.object(babysteps_today, 'access_token', return_value={'familyId': 'f', 'token': 't'}), \
                patch.object(babysteps_today, 'call', side_effect=fake_call):
            result = babysteps_today.log_entry({'type': 'bath'}, NOW)
        self.assertTrue(result['ok'])
        path, body = calls[-1]
        self.assertEqual(path, '/families/f/mutations')
        self.assertEqual((body['action'], body['collection'], body['expectedRevision']), ('save', 'events', 0))
        self.assertEqual(body['patch'], {'startedAt': '2026-10-18T17:00:00.000Z', 'type': 'bath', 'id': body['id'], 'babyId': 'b'})
        with patch.object(babysteps_today, 'call') as call:
            self.assertFalse(babysteps_today.log_entry({'type': 'feed'}, NOW)['ok'])
            call.assert_not_called()

    def test_refresh_saves_rotated_token(self):
        with tempfile.TemporaryDirectory() as folder:
            state = pathlib.Path(folder, 'state.json')
            state.write_text(json.dumps({'token': 'old', 'refreshToken': 'r1', 'expiresAt': '2020-01-01T00:00:00Z', 'familyId': 'f'}))
            with patch.object(babysteps_today, 'STATE', state), \
                    patch.object(babysteps_today, 'call', return_value={'token': 'new', 'refreshToken': 'r2', 'expiresAt': '2099-01-01T00:00:00Z'}) as call:
                self.assertEqual(babysteps_today.access_token()['token'], 'new')
                call.assert_called_once_with('/native/refresh', {'refreshToken': 'r1'})
            self.assertEqual(json.loads(state.read_text())['refreshToken'], 'r2')
            self.assertEqual(oct(os.stat(state).st_mode & 0o777), '0o600')


if __name__ == '__main__':
    unittest.main()
