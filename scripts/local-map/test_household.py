"""The same cases as test-household-schedule.mjs, so the Python port matches the card."""
import datetime
import unittest

import household

d = datetime.date.fromisoformat


class HouseholdTests(unittest.TestCase):
    def test_matches_js_schedule(self):
        self.assertEqual(household.upcoming_trash(d('2026-10-13'), 14)['date'], '2026-10-13')
        self.assertEqual(household.upcoming_trash(d('2026-10-13'), 20)['date'], '2026-10-20')
        self.assertEqual(household.upcoming_trash(d('2026-09-07'), 14)['date'], '2026-09-09')
        self.assertEqual(household.upcoming_trash(d('2026-09-09'), 14)['date'], '2026-09-09')
        self.assertEqual(household.upcoming_trash(d('2026-11-23'), 14)['date'], '2026-11-24')
        self.assertEqual(household.upcoming_trash(d('2026-07-06'), 14)['date'], '2026-07-07')
        self.assertEqual(household.next_sweeps(d('2026-10-13'), 14)[0]['date'], '2026-10-14')
        self.assertEqual(household.next_sweeps(d('2026-10-14'), 20)[0]['date'], '2026-10-28')
        self.assertEqual(household.next_sweeps(d('2026-09-01'), 14)[0]['date'], '2026-09-10')
        self.assertEqual(household.next_sweeps(d('2026-05-14'), 14)[0]['date'], '2026-06-10')
        self.assertFalse(household.next_sweeps(d('2027-01-01'), 14)[0]['verified'])


if __name__ == '__main__':
    unittest.main()
