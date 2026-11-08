"""Train grouping and pass finding on synthetic orbits, and the geometry helpers."""
import datetime
import math
import unittest

import starlink

UTC = datetime.timezone.utc
EPOCH = datetime.datetime(2026, 10, 28, 12, 0, tzinfo=UTC)


def record(number, mean_anomaly, launch='2026-242', mean_motion=16.0, raan=0.0, inclination=53.0):
    """A circular orbit in OMM form; 16 revolutions a day is about 280 km up."""
    return {'OBJECT_NAME': f'STARLINK-{number}', 'OBJECT_ID': f'{launch}{chr(65 + number % 26)}', 'EPOCH': EPOCH.strftime('%Y-%m-%dT%H:%M:%S.%f'),
            'MEAN_MOTION': mean_motion, 'ECCENTRICITY': 0.0001, 'INCLINATION': inclination, 'RA_OF_ASC_NODE': raan,
            'ARG_OF_PERICENTER': 0, 'MEAN_ANOMALY': mean_anomaly, 'EPHEMERIS_TYPE': 0, 'CLASSIFICATION_TYPE': 'U',
            'NORAD_CAT_ID': 90000 + number, 'ELEMENT_SET_NO': 999, 'REV_AT_EPOCH': 1, 'BSTAR': 0.0001,
            'MEAN_MOTION_DOT': 0, 'MEAN_MOTION_DDOT': 0}


class TrainTest(unittest.TestCase):
    def test_bunched_low_batch_is_a_train(self):
        # 20 satellites 0.5 degrees apart: about 60 km.
        trains = starlink.trains([record(n, n * 0.5) for n in range(20)], EPOCH)
        self.assertEqual({k: len(v) for k, v in trains.items()}, {'2026-242': 20})

    def test_spread_out_or_high_batches_are_not(self):
        spread = [record(n, n * 18) for n in range(20)]  # about 2100 km apart
        high = [record(n, n * 0.5, launch='2026-100', mean_motion=15.05) for n in range(20)]  # about 550 km up
        self.assertEqual(starlink.trains(spread + high, EPOCH), {})

    def test_two_bunches_are_two_trains(self):
        batch = [record(n, n * 0.5) for n in range(12)] + [record(n, 180 + n * 0.5) for n in range(12, 24)]
        self.assertEqual(sorted(starlink.trains(batch, EPOCH)), ['2026-242', '2026-242#2'])


class GeometryTest(unittest.TestCase):
    def test_point_straight_up(self):
        home = starlink.Observer(0, 0, height=0)
        azimuth, elevation = home.look((starlink.EARTH_RADIUS + 500, 0, 0), 0)
        self.assertAlmostEqual(elevation, 90, places=3)

    def test_earth_shadow(self):
        sun = (1, 0, 0)
        self.assertTrue(starlink.sunlit((7000, 0, 0), sun))
        self.assertFalse(starlink.sunlit((-7000, 0, 0), sun))
        self.assertTrue(starlink.sunlit((-7000, 7000, 0), sun))

    def test_camera_view(self):
        self.assertTrue(starlink.in_camera(287, 10))  # over the Botanic Garden ridge, toward Vandenberg
        self.assertFalse(starlink.in_camera(287, 40))  # above the frame
        self.assertFalse(starlink.in_camera(200, 10))  # left of the frame
        self.assertFalse(starlink.in_camera(287, 1))  # behind the ridge

    def test_compass(self):
        self.assertEqual([starlink.compass(a) for a in (0, 290, 315, 359)], ['north', 'west-northwest', 'northwest', 'north'])


class PassTest(unittest.TestCase):
    def test_finds_dark_sunlit_passes_and_summarizes(self):
        # Sweep the node around so some pass crosses the sky after dusk.
        found = []
        for raan in range(0, 360, 30):
            trains = starlink.trains([record(n, n * 0.5, raan=raan) for n in range(12)], EPOCH)
            found += starlink.passes(trains, starlink.Observer(34.2, -118.8), EPOCH, hours=24)
        self.assertTrue(found)
        for p in found:
            # High enough to announce, or at least low across the camera's view.
            self.assertTrue(p['max_elevation'] >= starlink.MIN_ELEVATION or p['in_camera'])
            self.assertLessEqual(p['start'], p['peak'])
            self.assertLessEqual(p['peak'], p['end'])
            self.assertIn('in_camera', p)
            if p['in_camera']:
                # The recorded part sits inside the pass.
                self.assertLessEqual(p['start'], p['camera_start'])
                self.assertLessEqual(p['camera_start'], p['camera_end'])
                self.assertLessEqual(p['camera_end'], p['end'])
                self.assertLessEqual(p['camera_start'], p['camera_peak'])
                self.assertLessEqual(p['camera_peak'], p['camera_end'])
                self.assertLessEqual(p['camera_end'] - p['camera_start'], starlink.CAMERA_SPAN)
            else:
                self.assertIsNone(p['camera_start'])
        self.assertTrue(any(p['in_camera'] for p in found))
        summary = starlink.summary(found, ['2026-242'], EPOCH)
        announced = [p for p in found if p['max_elevation'] >= starlink.MIN_ELEVATION]
        self.assertEqual(summary['alert']['start'], min(announced, key=lambda p: p['start'])['start'].isoformat())
        self.assertEqual(summary['trains'], ['2026-242'])


if __name__ == '__main__':
    unittest.main()
