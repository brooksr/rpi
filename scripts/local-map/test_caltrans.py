"""Closures count as in place only between 10-97 and 10-98; other roads are ignored."""
import csv
import io
import json
import unittest

import caltrans

NOW = 1792340000
COLUMNS = ['beginRoute', 'beginCounty', 'beginLongitude', 'travelFlowDirection', 'beginLocationName', 'endLocationName',
           'beginNearbyPlace', 'facility', 'typeOfClosure', 'lanesClosed', 'totalExistingLanes', 'typeOfWork',
           'estimatedDelay', 'closureStartEpoch', 'closureEndEpoch', 'isClosureEndIndefinite', 'isCode1097', 'isCode1098']


def closure_csv(*rows):
    out = io.StringIO()
    writer = csv.DictWriter(out, COLUMNS)
    writer.writeheader()
    for overrides in rows:
        row = dict.fromkeys(COLUMNS, '')
        row.update(beginRoute='US-101', beginCounty='Ventura', beginLongitude='-118.9', travelFlowDirection='North',
                   beginLocationName='Lynn Rd', closureStartEpoch=str(NOW - 3600), closureEndEpoch=str(NOW + 3600),
                   isClosureEndIndefinite='false', isCode1097='false', isCode1098='false')
        row.update(overrides)
        writer.writerow(row)
    return out.getvalue()


class CaltransTests(unittest.TestCase):
    def test_closure_states(self):
        in_place, scheduled, count = caltrans.closures(closure_csv(
            {'isCode1097': 'true'},
            {'beginLocationName': 'Wendy Dr'},
            {'beginLocationName': 'Done', 'isCode1097': 'true', 'isCode1098': 'true'},
            {'beginLocationName': 'Ended', 'closureEndEpoch': str(NOW - 60)},
            {'beginLocationName': 'Next week', 'closureStartEpoch': str(NOW + 7 * 86400)},
            {'beginRoute': 'I-405', 'beginCounty': 'Los Angeles', 'beginLongitude': '-118.4'},
            {'beginCounty': 'Los Angeles', 'beginLongitude': '-118.7', 'beginLocationName': 'Agoura'},
        ), NOW)
        self.assertEqual([c['from'] for c in in_place], ['Lynn Rd'])
        self.assertEqual([c['from'] for c in scheduled], ['Wendy Dr', 'Agoura'])
        self.assertEqual(count, 2)

    def test_only_signs_with_messages(self):
        def sign(route, display, line):
            phase = {'phase1Line1': line, 'phase1Line2': '', 'phase1Line3': ''}
            return {'cms': {'location': {'route': route, 'county': 'Ventura', 'longitude': '-118.9', 'direction': 'North',
                                         'locationName': 'WESTLAKE BLVD'},
                            'message': {'display': display, 'phase1': phase, 'phase2': {}}}}
        text = json.dumps({'data': [sign('US-101', 'Blank', ''), sign('US-101', '1 Page', 'CRASH AHEAD'), sign('SR-118', '1 Page', 'X')]})
        self.assertEqual(caltrans.signs(text), [{'route': 'US-101', 'direction': 'North', 'location': 'Westlake Blvd', 'message': ['CRASH AHEAD']}])


def camera(n, route, lat):
    return {'cctv': {'inService': 'true', 'imageData': {'static': {'currentImageURL': f'https://cam/{n}.jpg'}},
                     'location': {'route': route, 'locationName': f'{route} : ({n}) Cam {n}', 'direction': 'North',
                                  'latitude': str(lat), 'longitude': '-118.85'}}}


class CameraTest(unittest.TestCase):
    def test_down_cameras_give_way_to_the_next_closest(self):
        text = json.dumps({'data': [camera(1, 'SR-23', 34.181), camera(2, 'SR-23', 34.182), camera(3, 'SR-23', 34.183),
                                    camera(4, 'US-101', 34.181)]})
        picked = caltrans.cameras(text, (34.18, -118.85), check=lambda url: not url.endswith('/1.jpg'))
        self.assertEqual([c['name'] for c in picked], ['Cam 4', 'Cam 2', 'Cam 3'])

    def test_white_card_is_a_placeholder(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest('Pillow not installed')
        def jpeg(color):
            out = io.BytesIO()
            Image.new('RGB', (320, 260), color).save(out, 'JPEG')
            return out.getvalue()
        self.assertTrue(caltrans.placeholder(jpeg('white')))
        self.assertFalse(caltrans.placeholder(jpeg((90, 110, 90))))


if __name__ == '__main__':
    unittest.main()
