"""Launch parsing, recording windows, folder names and the T-clock filter."""
import datetime
import unittest

import launch_recorder

UTC = datetime.timezone.utc


def item(net='2026-10-30T04:02:00Z', precision='Minute', status='Go', name='Falcon 9 Block 5 | Starlink Group 15-18'):
    return {'id': 'abc', 'name': name, 'net': net, 'net_precision': {'name': precision}, 'status': {'abbrev': status}}


class ParseTest(unittest.TestCase):
    def test_firm_launch(self):
        launch = launch_recorder.parse(item())
        self.assertEqual(launch['net'], datetime.datetime(2026, 10, 30, 4, 2, tzinfo=UTC))
        self.assertEqual(launch['status'], 'Go')

    def test_vague_or_flown_launches_are_skipped(self):
        self.assertIsNone(launch_recorder.parse(item(precision='Month')))
        self.assertIsNone(launch_recorder.parse(item(status='Success')))


class WindowTest(unittest.TestCase):
    def test_launch_window_is_around_net(self):
        launch = launch_recorder.parse(item())
        start, end = launch_recorder.window(launch)
        self.assertEqual(launch['net'] - start, launch_recorder.BEFORE)
        self.assertEqual(end - launch['net'], launch_recorder.AFTER)

    def test_train_pass_is_padded_and_keyed_by_train(self):
        t = datetime.datetime(2026, 11, 1, 2, 30, tzinfo=UTC)
        event = launch_recorder.train_event({'train': '2026-242#2', 'start': t, 'peak': t + datetime.timedelta(minutes=3),
                                             'end': t + datetime.timedelta(minutes=6)})
        self.assertEqual(event['id'], 'starlink-2026-242#2')
        self.assertEqual(event['net'], t + datetime.timedelta(minutes=3))
        self.assertEqual(launch_recorder.window(event), (t - launch_recorder.PASS_PAD, t + datetime.timedelta(minutes=6) + launch_recorder.PASS_PAD))
        self.assertTrue(launch_recorder.folder_name(event).endswith('_Starlink-train-2026-242-2'))

    def test_train_records_only_its_time_in_camera(self):
        t = datetime.datetime(2026, 11, 1, 2, 30, tzinfo=UTC)
        minutes = lambda m: t + datetime.timedelta(minutes=m)
        event = launch_recorder.train_event({'train': '2026-246', 'start': t, 'peak': minutes(10), 'end': minutes(25),
                                             'camera_start': minutes(14), 'camera_peak': minutes(16), 'camera_end': minutes(19)})
        self.assertEqual(event['net'], minutes(16))
        self.assertEqual(launch_recorder.window(event), (minutes(14) - launch_recorder.PASS_PAD, minutes(19) + launch_recorder.PASS_PAD))


class FolderTest(unittest.TestCase):
    def test_local_time_and_mission(self):
        launch = launch_recorder.parse(item())
        local = launch['net'].astimezone()
        self.assertEqual(launch_recorder.folder_name(launch), f'{local:%Y-%m-%d_%H%M}_Starlink-Group-15-18')


class ClockTest(unittest.TestCase):
    def test_counts_from_net_at_speed(self):
        text = launch_recorder.clock(-300, 8)
        self.assertIn("enable='lt((t*8+-300.000),0)'", text)
        self.assertIn('T-%{eif', text)
        self.assertIn('T+%{eif', text)


if __name__ == '__main__':
    unittest.main()
