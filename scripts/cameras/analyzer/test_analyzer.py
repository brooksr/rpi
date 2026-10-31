"""Replays synthetic evenings through the tracker: put down, settling, asleep, woken by crying."""
import json
import pathlib
import tempfile
import unittest

import numpy as np

import analyzer

T0 = 1_800_000_000.0


def run(tracker, start, end, moving=lambda t: False, bright=100, seen=lambda t: True, cry=lambda t: 0.0, fuss=lambda t: 0.0):
    """Feeds frames at 4 fps, a detection every 5 s, audio every 0.5 s and ticks every 5 s."""
    t = start
    while t < end:
        tracker.frame(t, moving(t), bright)
        if t % 5 < 0.25:
            tracker.detection(t, seen(t))
            tracker.tick(t)
        if t % 0.5 < 0.25:
            tracker.audio(t, cry(t), fuss(t))
        t += 0.25
    return end


def every(seconds, length=1.0):
    """Moving for `length` seconds once every `seconds`."""
    return lambda t: (t - T0) % seconds < length


class TrackerTests(unittest.TestCase):
    def test_bedtime(self):
        tracker = analyzer.Tracker()
        t = run(tracker, T0, T0 + 600, moving=every(5))          # wriggling: 12 movements a minute
        self.assertEqual(tracker.state, 'awake')
        self.assertEqual(tracker.in_frame_at, T0)
        t = run(tracker, t, t + 300, moving=every(30))           # 2 a minute: settling
        self.assertEqual(tracker.state, 'settling')
        quiet_start = t
        t = run(tracker, t, t + 12 * 60)                          # still
        self.assertEqual(tracker.state, 'asleep')
        self.assertAlmostEqual(tracker.asleep_at, quiet_start, delta=90)
        snap = tracker.snapshot(t)
        self.assertEqual(snap['state'], 'asleep')
        self.assertAlmostEqual(snap['fell_asleep_seconds'], quiet_start - T0, delta=90)
        t = run(tracker, t, t + 3, cry=lambda t: 0.1)            # a sigh is not a wake-up
        self.assertEqual(tracker.state, 'asleep')
        t = run(tracker, t, t + 25, cry=lambda t: 0.8)           # crying wakes them
        self.assertEqual(tracker.state, 'awake')
        snap = tracker.snapshot(t)
        self.assertTrue(snap['crying'])
        self.assertIsNotNone(snap['last_sleep'])
        self.assertGreater(snap['last_cry']['seconds'], 10)
        self.assertEqual([e['type'] for e in snap['events']], ['in_frame', 'settling', 'asleep', 'woke'])
        [sleep] = snap['sleeps']
        self.assertFalse(sleep['logged'])
        self.assertEqual(sleep['start'], analyzer.iso(tracker.last_sleep['start']))
        self.assertTrue(tracker.mark_logged(sleep['id']))
        self.assertFalse(tracker.mark_logged('nope'))
        self.assertTrue(tracker.snapshot(t)['sleeps'][0]['logged'])

    def test_stirring_does_not_wake(self):
        tracker = analyzer.Tracker()
        t = run(tracker, T0, T0 + 200, moving=every(5))
        t = run(tracker, t, t + 15 * 60)
        self.assertEqual(tracker.state, 'asleep')
        t = run(tracker, t, t + 60, moving=every(20))            # a few stirs
        self.assertEqual(tracker.state, 'asleep')
        t = run(tracker, t, t + 150, moving=every(5))            # up and wriggling
        self.assertEqual(tracker.state, 'awake')
        self.assertEqual(tracker.last_sleep['fell_asleep_seconds'], round(tracker.last_sleep['start'] - T0))

    def test_cry_and_fuss_episodes(self):
        tracker = analyzer.Tracker()
        t = run(tracker, T0, T0 + 1, cry=lambda t: 0.9)          # too short to count
        t = run(tracker, t, t + 20)
        self.assertIsNone(tracker.last_cry)
        crying = lambda t: 0.9 if (t - T0) % 10 < 4 else 0.0     # bursts 6 s apart: one episode
        t = run(tracker, t, t + 40, cry=crying)
        t = run(tracker, t, t + 20)
        self.assertEqual(sum(e['type'] == 'cry' for e in tracker.events), 1)
        run(tracker, t, t + 5, fuss=lambda t: 0.5)
        self.assertTrue(tracker.snapshot(t + 5)['fussing'])

    def test_leaves_crib(self):
        tracker = analyzer.Tracker()
        t = run(tracker, T0, T0 + 120, moving=every(5))
        t = run(tracker, t, t + 11 * 60, seen=lambda t: False, bright=100, moving=lambda t: False)
        # Still and unseen for 10 minutes: settling or asleep, not gone.
        self.assertIn(tracker.state, ('settling', 'asleep'))
        tracker = analyzer.Tracker()
        t = run(tracker, T0, T0 + 120, moving=every(5))
        t = run(tracker, t, t + 11 * 60, seen=lambda t: False, moving=every(5, 0.5))
        t = run(tracker, t, t + 11 * 60, seen=lambda t: False)
        self.assertNotEqual(tracker.state, 'awake')

    def test_dark_holds_the_estimate(self):
        tracker = analyzer.Tracker()
        t = run(tracker, T0, T0 + 200, moving=every(5))
        t = run(tracker, t, t + 20 * 60, bright=3)
        self.assertEqual(tracker.state, 'awake')
        self.assertEqual(tracker.snapshot(t)['video'], 'dark')

    def test_long_pause_ends_sleep(self):
        tracker = analyzer.Tracker()
        t = run(tracker, T0, T0 + 200, moving=every(5))
        t = run(tracker, t, t + 15 * 60)
        self.assertEqual(tracker.state, 'asleep')
        tracker.pause(t, 'lid closed')
        self.assertEqual(tracker.snapshot(t + 60)['state'], 'paused')
        tracker.resume(t + 3600)
        self.assertEqual(tracker.state, 'absent')
        self.assertEqual(tracker.last_sleep['end'], t)

    def test_save_and_load(self):
        tracker = analyzer.Tracker()
        t = run(tracker, T0, T0 + 200, moving=every(5))
        t = run(tracker, t, t + 15 * 60)
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / 'state.json'
            tracker.save(path, t)
            json.loads(path.read_text())
            restored = analyzer.Tracker()
            restored.load(path, t + 60)
        self.assertEqual(restored.state, 'asleep')
        self.assertEqual(restored.sleeps, tracker.sleeps)
        self.assertEqual(restored.snapshot(t + 60)['state'], 'paused')
        restored.resume(t + 60)
        self.assertEqual(restored.snapshot(t + 61)['session_state'], 'asleep')


class MotionTests(unittest.TestCase):
    def test_motion(self):
        detect = analyzer.MotionDetector()
        frame = np.full((180, 320), 100, np.uint8)
        self.assertEqual(detect(frame), (False, 100.0))
        self.assertFalse(detect(frame.copy())[0])
        moved = frame.copy()
        moved[80:100, 150:170] = 200                              # a hand moves
        self.assertTrue(detect(moved)[0])
        self.assertFalse(detect(moved + 20)[0])                   # exposure shift only


if __name__ == '__main__':
    unittest.main()
