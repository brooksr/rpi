import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime
from unittest import mock
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agent  # noqa: E402

TZ = ZoneInfo('America/Los_Angeles')
NOW = datetime(2026, 10, 30, 14, 10, tzinfo=TZ).timestamp()


class Recorder:
    """Just enough of HA's recorder schema."""

    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.executescript('''
            CREATE TABLE states_meta (metadata_id INTEGER PRIMARY KEY, entity_id TEXT);
            CREATE TABLE state_attributes (attributes_id INTEGER PRIMARY KEY, shared_attrs TEXT);
            CREATE TABLE states (state_id INTEGER PRIMARY KEY, metadata_id INTEGER, state TEXT,
              last_changed_ts REAL, last_updated_ts REAL, attributes_id INTEGER);
            CREATE TABLE statistics_meta (id INTEGER PRIMARY KEY, statistic_id TEXT);
            CREATE TABLE statistics (metadata_id INTEGER, start_ts REAL, mean REAL);
        ''')

    def meta(self, table, column, entity):
        row = self.db.execute(f'SELECT rowid FROM {table} WHERE {column} = ?', (entity,)).fetchone()
        if row:
            return row[0]
        return self.db.execute(f'INSERT INTO {table} ({column}) VALUES (?)', (entity,)).lastrowid

    def state(self, entity, state, updated=NOW - 60, changed=None, **attrs):
        mid = self.meta('states_meta', 'entity_id', entity)
        aid = self.db.execute('INSERT INTO state_attributes (shared_attrs) VALUES (?)',
                              (json.dumps(attrs),)).lastrowid
        self.db.execute('INSERT INTO states (metadata_id, state, last_changed_ts, last_updated_ts, attributes_id) '
                        'VALUES (?, ?, ?, ?, ?)', (mid, state, changed, updated, aid))
        self.db.commit()

    def hourly(self, entity, value_for_hour, days=10):
        mid = self.meta('statistics_meta', 'statistic_id', entity)
        start = NOW - NOW % 3600 - days * 86400
        for i in range(days * 24):
            ts = start + i * 3600
            self.db.execute('INSERT INTO statistics VALUES (?, ?, ?)',
                            (mid, ts, value_for_hour(datetime.fromtimestamp(ts, TZ).hour)))
        self.db.commit()


def make_config(tmp):
    return {
        'recorder_db': os.path.join(tmp, 'recorder.db'),
        'output': os.path.join(tmp, 'out.json'),
        'memory_db': os.path.join(tmp, 'memory.db'),
        'cloud_log_dir': os.path.join(tmp, 'cloud-log'),
        'cloud_workdir': os.path.join(tmp, 'cwd'),
        'privacy': {'cloud': ['sensor.office_*', 'sensor.laptop', 'media_player.tv'],
                    'local_only': ['sensor.babysteps_status']},
        'controls': {'note': 'input_button.note', 'digest': 'input_button.digest'},
        'ollama': {'url': 'http://ollama', 'model': 'qwen', 'min_minutes_between': 30},
        'cloud': {'cli': 'none'},
        'detectors': {
            'baseline': [{'entity': 'sensor.office_temperature', 'label': 'Office temperature', 'min_delta': 3}],
            'stale': [{'entity': 'sensor.babysteps_status', 'label': 'BabySteps feed', 'max_minutes': 45}],
            'threshold': [{'entity': 'sensor.laptop', 'attribute': 'battery.ac_online', 'equals': False,
                           'label': 'Laptop on battery', 'detail': 'Unplugged.'}],
            'on_too_long': [{'entity': 'media_player.tv', 'label': 'TV', 'states': ['on'], 'max_minutes': 240}],
        },
    }


class AgentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = make_config(self.tmp.name)
        self.rec = Recorder(self.config['recorder_db'])
        self.rec.hourly('sensor.office_temperature', lambda hour: 70 + (hour % 2) * 0.5)
        self.rec.state('sensor.office_temperature', '71', unit_of_measurement='°F')
        self.rec.state('sensor.laptop', 'ok', battery={'ac_online': True})
        self.rec.state('media_player.tv', 'off')
        self.rec.state('sensor.babysteps_status', 'ok')
        self.rec.state('sensor.secret', 'do-not-read')
        self.memory = agent.open_memory(self.config['memory_db'])

    def tearDown(self):
        self.memory.close()
        self.rec.db.close()
        self.tmp.cleanup()

    def states(self):
        db = agent.open_recorder(self.config['recorder_db'])
        patterns = [*self.config['privacy']['cloud'], *self.config['privacy']['local_only'],
                    *self.config['controls'].values()]
        try:
            return agent.read_states(db, patterns)
        finally:
            db.close()

    def detect(self):
        db = agent.open_recorder(self.config['recorder_db'])
        try:
            return agent.detect(self.config, agent.read_states(db, ['*']), NOW, db, TZ)
        finally:
            db.close()

    def tick(self, note='Office is warm.'):
        with mock.patch.object(agent, 'ollama_note', return_value=note) as qwen, \
                mock.patch.object(agent.time, 'time', return_value=NOW):
            agent.tick(self.config, self.memory, TZ, {})
        with open(self.config['output']) as f:
            return json.load(f), qwen

    def test_reads_only_listed_entities_and_latest_state(self):
        self.rec.state('sensor.office_temperature', '72', unit_of_measurement='°F')
        states = self.states()
        self.assertNotIn('sensor.secret', states)
        self.assertEqual(states['sensor.office_temperature']['state'], '72')
        self.assertEqual(states['sensor.office_temperature']['attributes']['unit_of_measurement'], '°F')

    def test_quiet_house_has_no_findings(self):
        self.assertEqual(self.detect(), [])

    def test_baseline_flags_large_deviation_only(self):
        self.rec.state('sensor.office_temperature', '72.5', unit_of_measurement='°F')
        self.assertEqual(self.detect(), [])
        self.rec.state('sensor.office_temperature', '79', unit_of_measurement='°F')
        [found] = self.detect()
        self.assertEqual(found['title'], 'Office temperature')
        self.assertIn('79°F, 9°F above its usual 70°F at this hour.', found['detail'])
        self.assertTrue(found['cloud'])

    def test_threshold_equals_on_nested_attribute(self):
        self.rec.state('sensor.laptop', 'ok', battery={'ac_online': False})
        [found] = self.detect()
        self.assertEqual((found['title'], found['detail'], found['severity']),
                         ('Laptop on battery', 'Unplugged.', 'warning'))

    def test_stale_and_local_only(self):
        self.rec.state('sensor.babysteps_status', 'ok', updated=NOW - 3 * 3600)
        [found] = self.detect()
        self.assertEqual(found['detail'], 'No update for 3 h.')
        self.assertFalse(found['cloud'])

    def test_on_too_long_uses_last_changed(self):
        self.rec.state('media_player.tv', 'on', updated=NOW - 60, changed=NOW - 5 * 3600)
        [found] = self.detect()
        self.assertEqual(found['detail'], 'On for 5 h.')

    def test_tick_writes_output_and_asks_qwen_only_when_needed(self):
        out, qwen = self.tick()
        self.assertEqual(out['findings'], [])
        self.assertEqual(out['note']['text'], 'Nothing unusual right now.')
        qwen.assert_not_called()

        self.rec.state('sensor.office_temperature', '79', unit_of_measurement='°F')
        out, qwen = self.tick()
        self.assertEqual(len(out['findings']), 1)
        # A rules note was written moments ago, so Qwen waits for the 30-minute spacing.
        qwen.assert_not_called()

        self.rec.state('input_button.note', '2026-10-30T21:00:00+00:00')
        self.tick()  # first sighting of the button only records it
        self.rec.state('input_button.note', '2026-10-30T21:09:00+00:00')
        out, qwen = self.tick()
        qwen.assert_called_once()
        self.assertEqual(out['note'], {'text': 'Office is warm.', 'source': 'qwen',
                                       'at': '2026-10-30T14:10:00-07:00'})

        # Once the finding clears, the Qwen note is replaced right away.
        self.rec.state('sensor.office_temperature', '71', unit_of_measurement='°F')
        out, qwen = self.tick()
        qwen.assert_not_called()
        self.assertEqual((out['findings'], out['note']['text']), ([], 'Nothing unusual right now.'))

    def test_digest_summary_excludes_local_only_findings(self):
        self.rec.state('sensor.office_temperature', '79', unit_of_measurement='°F')
        self.rec.state('sensor.babysteps_status', 'ok', updated=NOW - 3 * 3600)
        agent.record_findings(self.memory, self.detect(), NOW - 600)
        db = agent.open_recorder(self.config['recorder_db'])
        try:
            summary = agent.daily_summary(self.config, db, self.memory, self.states(), NOW, TZ)
        finally:
            db.close()
        text = json.dumps(summary)
        self.assertIn('Office temperature', text)
        self.assertNotIn('BabySteps', text)
        self.assertNotIn('babysteps', text)
        self.assertEqual(summary['sensors'][0]['typical']['days'], 9)

    def test_digest_runs_cli_and_logs_payload(self):
        self.config['cloud'] = {'cli': 'claude', 'digest_time': '13:00'}
        with mock.patch.object(agent, 'cli_path', return_value='/bin/claude'), \
                mock.patch.object(agent, 'run_cloud', return_value=('claude', '- Quiet day.')) as cloud:
            out, _ = self.tick()
            out_again, _ = self.tick()
        cloud.assert_called_once()
        prompt = cloud.call_args.args[1]
        self.assertIn('Office temperature', prompt)
        self.assertEqual((out['digest']['text'], out['digest']['source']), ('- Quiet day.', 'claude'))
        self.assertEqual(out['digest']['sent_bytes'], len(prompt.encode()))
        [logged] = os.listdir(self.config['cloud_log_dir'])
        with open(os.path.join(self.config['cloud_log_dir'], logged)) as f:
            self.assertEqual(f.read(), prompt)

    def test_missing_cli_reports_without_sending(self):
        self.config['cloud'] = {'cli': 'claude', 'digest_time': '13:00'}
        with mock.patch.object(agent, 'cli_path', return_value=None):
            out, _ = self.tick()
        self.assertIn('claude CLI', out['errors'][0])
        self.assertFalse(os.path.exists(self.config['cloud_log_dir']))

    def test_claude_command_has_no_tools(self):
        cmd, out = agent.cloud_command('claude', '/bin/claude')
        self.assertIsNone(out)
        self.assertEqual(cmd[cmd.index('--tools') + 1], '')
        self.assertIn('--strict-mcp-config', cmd)

    def test_falls_back_to_codex_when_claude_fails(self):
        bin_dir = os.path.join(self.tmp.name, 'bin')
        os.makedirs(bin_dir)
        scripts = {
            'claude': 'import sys; print("OAuth session expired", file=sys.stderr); sys.exit(1)',
            'codex': ('import sys; out = sys.argv[sys.argv.index("--output-last-message") + 1]; '
                      'open(out, "w").write("- From codex: " + sys.stdin.read()[:5])'),
        }
        for name, code in scripts.items():
            path = os.path.join(bin_dir, name)
            with open(path, 'w') as f:
                f.write(f'#!{sys.executable}\n{code}\n')
            os.chmod(path, 0o755)
        with mock.patch.dict(os.environ, {'PATH': bin_dir, 'HOME': self.tmp.name}):
            cli, text = agent.run_cloud({'cli': 'claude', 'fallback': 'codex'}, 'hello', self.config['cloud_workdir'])
        self.assertEqual((cli, text), ('codex', '- From codex: hello'))

    def test_sky_label_and_daylight(self):
        cfg = {'clear_blue': 75, 'overcast_blue': 35}
        self.assertEqual([agent.sky_label(b, cfg) for b in (120, 50, 10)], ['clear', 'partly cloudy', 'overcast'])
        # 2:10 PM: sunset 5:58 PM, next noon tomorrow 12:20 PM, so sunrise ~6:42 AM.
        states = {'sensor.sun_next_setting': {'state': '2026-10-31T00:58:00+00:00'},
                  'sensor.sun_next_noon': {'state': '2026-10-31T19:20:00+00:00'}}
        self.assertTrue(agent.daylight(states, NOW, 60))
        self.assertFalse(agent.daylight(states, NOW + 3 * 3600, 60))  # 5:10 PM, sun low in the west
        self.assertFalse(agent.daylight(states, NOW - 7 * 3600, 60))  # 7:10 AM, just after sunrise
        self.assertTrue(agent.daylight(states, NOW - 6 * 3600, 60))   # 8:10 AM
        self.assertFalse(agent.daylight({}, NOW, 60))

    def test_sky_disagreeing_with_forecast(self):
        self.config['sky'] = {'entity': 'local.sky'}
        self.config['privacy']['cloud'] += ['local.sky', 'weather.forecast_home']
        self.rec.state('weather.forecast_home', 'sunny')
        overcast = [(NOW - m * 60, 'overcast') for m in (30, 20, 10)]
        db = agent.open_recorder(self.config['recorder_db'])
        try:
            states = agent.read_states(db, ['*'])
            [found] = agent.detect(self.config, states, NOW, db, TZ, overcast)
            self.assertEqual(found['title'], 'Sky differs from forecast')
            self.assertTrue(found['cloud'])
            mixed = overcast[:2] + [(NOW - 60, 'partly cloudy')]
            self.assertEqual(agent.detect(self.config, states, NOW, db, TZ, mixed), [])
        finally:
            db.close()

    def test_digest_includes_shopping_list_and_sky(self):
        path = os.path.join(self.tmp.name, 'shopping.json')
        with open(path, 'w') as f:
            json.dump([{'name': 'Milk', 'complete': False}, {'name': 'Eggs', 'complete': True}], f)
        self.config.update(shopping_list=path, sky={'entity': 'local.sky'})
        self.memory.execute('INSERT INTO sky VALUES (?, ?, ?)', (NOW - 600, 'overcast', 12))
        db = agent.open_recorder(self.config['recorder_db'])
        try:
            summary = agent.daily_summary(self.config, db, self.memory, self.states(), NOW, TZ)
            self.assertNotIn('shopping_list', summary)  # not in privacy.cloud yet
            self.assertNotIn('sky_camera_by_hour', summary)
            self.config['privacy']['cloud'] += ['todo.shopping_list', 'local.sky']
            summary = agent.daily_summary(self.config, db, self.memory, self.states(), NOW, TZ)
        finally:
            db.close()
        self.assertEqual(summary['shopping_list'], ['Milk'])
        self.assertEqual(summary['sky_camera_by_hour'], {'Fri 2 PM': 'overcast'})
        self.assertIn('Sky from window camera', summary['available_data'])

    @unittest.skipUnless(__import__('importlib.util').util.find_spec('PIL'), 'needs Pillow')
    def test_measure_sky(self):
        from PIL import Image
        path = os.path.join(self.tmp.name, 'sky.jpg')
        Image.new('RGB', (1280, 720), (90, 140, 220)).save(path)
        self.assertAlmostEqual(agent.measure_sky(path, [0, 0, 1280, 280]), 130, delta=3)

    BABY_EVENTS = [
        {'time': '2026-10-30T08:13:00.000Z', 'type': 'feed', 'text': 'Nursing · 37 min left', 'endedAt': '2026-10-30T08:50:00.000Z'},
        {'time': '2026-10-30T09:05:00.000Z', 'type': 'sleep', 'text': 'Sleep', 'endedAt': '2026-10-30T10:35:00.000Z'},
        {'time': '2026-10-30T12:54:00.000Z', 'type': 'feed', 'text': 'Bottle · 4 oz', 'endedAt': None},
        {'time': '2026-10-30T13:20:00.000Z', 'type': 'sleep', 'text': 'Sleep', 'endedAt': '2026-10-30T14:20:00.000Z'},
        {'time': '2026-10-30T14:33:00.000Z', 'type': 'diaper', 'text': 'Diaper · wet', 'endedAt': None},
        {'time': '2026-10-30T15:00:00.000Z', 'type': 'pump', 'text': 'Pump', 'endedAt': None},
        {'time': '2026-10-30T16:02:00.000Z', 'type': 'sleep', 'text': 'Asleep', 'endedAt': None},
    ]

    def test_baby_day_summary(self):
        self.assertEqual(agent.baby_day_summary(self.BABY_EVENTS), {
            'feeds': 2, 'bottle_oz': 4.0, 'nursing_minutes': 37, 'longest_gap_between_feeds_h': 4.7,
            'naps_or_sleeps': 2, 'sleep_logged_h': 2.5, 'longest_sleep_h': 1.5,
            'diapers': {'wet': 1}, 'other': {'pump': 1}})

    def test_baby_days_kept_and_summarized_for_cloud(self):
        self.config['baby'] = {'entity': 'sensor.babysteps_status'}
        attrs = dict(child='Sam', birth_date='2026-08-13', days_since_bath=2,
                     lastFeed={'at': '2026-10-30T19:54:00.000Z'})
        # Yesterday's last snapshot, then today's: each day keeps its own entries.
        self.rec.state('sensor.babysteps_status', 'ok', updated=NOW - 86400, events=self.BABY_EVENTS[:2],
                       checked_at='2026-10-29T23:50:00-07:00', **attrs)
        self.rec.state('sensor.babysteps_status', 'ok', events=self.BABY_EVENTS, checked_at='2026-10-30T14:00:00-07:00', **attrs)
        self.tick()
        days = dict(self.memory.execute('SELECT day, events FROM baby_days'))
        self.assertEqual(sorted(days), ['2026-10-29', '2026-10-30'])
        db = agent.open_recorder(self.config['recorder_db'])
        try:
            summary = agent.daily_summary(self.config, db, self.memory, self.states(), NOW, TZ)
            self.assertNotIn('baby', summary)  # local_only in this config
            self.config['privacy']['cloud'].append('sensor.babysteps_status')
            summary = agent.daily_summary(self.config, db, self.memory, self.states(), NOW, TZ)
        finally:
            db.close()
        baby = summary['baby']
        self.assertEqual((baby['name'], baby['age'], baby['days_since_bath']), ('Sam', '11 weeks 1 days', 2))
        self.assertEqual(baby['last_feed'], '12:54 PM, 76 min ago')
        self.assertEqual(list(baby['by_day']), ['2026-10-29', '2026-10-30 (today so far)'])
        self.assertEqual(baby['by_day']['2026-10-29']['feeds'], 1)
        self.assertIn('BabySteps logs', summary['available_data'])

    def test_hvac_runtime_and_outside_check(self):
        self.config['privacy']['cloud'] += ['climate.nest', 'sensor.outside']
        for minutes_ago, action in ((300, 'idle'), (120, 'cooling'), (60, 'idle'), (20, 'cooling')):
            self.rec.state('climate.nest', 'cool', updated=NOW - minutes_ago * 60, current_temperature=76,
                           temperature=74, hvac_action=action)
        self.rec.state('sensor.outside', '68')
        self.config['detectors']['hvac_outside'] = [{'entity': 'climate.nest', 'outdoor': 'sensor.outside'}]
        db = agent.open_recorder(self.config['recorder_db'])
        try:
            runtime, first = agent.hvac_runtime(db, 'climate.nest', NOW - 86400, NOW)
            self.assertEqual(runtime, {'heating_minutes': 0, 'cooling_minutes': 80})
            [found] = agent.detect(self.config, agent.read_states(db, ['*']), NOW, db, TZ)
        finally:
            db.close()
        self.assertEqual((found['title'], found['detail']), ('A/C running, cooler outside', 'It is 68°F outside and 76°F inside.'))
        self.assertTrue(found['cloud'])

    def test_finding_keeps_its_first_seen_time(self):
        first = [agent.finding('hvac', 'climate.nest', 'A/C', 'x', NOW - 600)]
        first[0]['cloud'] = True
        agent.record_findings(self.memory, first, NOW - 600)
        later = [agent.finding('hvac', 'climate.nest', 'A/C', 'x', NOW)]
        later[0]['cloud'] = True
        agent.record_findings(self.memory, later, NOW)
        self.assertEqual(later[0]['since'], NOW - 600)

    def test_no_dirty_diaper_against_pediatrician_limit(self):
        self.config['baby'] = {'entity': 'sensor.babysteps_status', 'no_dirty_limit_days': 7,
                               'no_dirty_notice_days': 5, 'care_notes': 'Up to 7 days is OK.'}
        last = datetime.fromtimestamp(NOW - 4 * 86400, TZ).isoformat()
        self.rec.state('sensor.babysteps_status', 'ok', lastDirtyDiaper=last)
        self.assertEqual(self.detect(), [])
        last = datetime.fromtimestamp(NOW - 6.2 * 86400, TZ).isoformat()
        self.rec.state('sensor.babysteps_status', 'ok', lastDirtyDiaper=last)
        [found] = self.detect()
        self.assertEqual(found['severity'], 'warning')
        self.assertIn("6.2 days since the last dirty diaper (Sat Oct 24, 9:22 AM). "
                      "The pediatrician's 7-day limit is Sat Oct 31, 9:22 AM.", found['detail'])
        last = datetime.fromtimestamp(NOW - 8 * 86400, TZ).isoformat()
        self.rec.state('sensor.babysteps_status', 'ok', lastDirtyDiaper=last)
        [found] = self.detect()
        self.assertIn('call the pediatrician', found['detail'])
        summary = agent.baby_summary(self.memory, self.states()['sensor.babysteps_status'], NOW, TZ,
                                     cfg=self.config['baby'])
        self.assertEqual(summary['care_notes_from_parents'], 'Up to 7 days is OK.')
        self.assertEqual(summary['last_dirty_diaper'], 'Thu Oct 22 2:10 PM, 8.0 days ago')

    def test_unavailable_needs_ten_minutes(self):
        self.rec.state('sensor.babysteps_status', 'unavailable', updated=NOW - 120, changed=NOW - 120)
        self.assertEqual(self.detect(), [])
        self.rec.state('sensor.babysteps_status', 'unavailable', updated=NOW - 900, changed=NOW - 900)
        [found] = self.detect()
        self.assertEqual(found['detail'], 'Unavailable.')


if __name__ == '__main__':
    unittest.main()
