import unittest
from datetime import date

import fetch_usage as fu


def sce_rows(day, values):
    return [{'startDateTime': f'{day} {i:02d}:00', 'value': str(v), 'serviceMeasurementTypeCode': 'KWH_DEL'}
            for i, v in enumerate(values)]


class SceTest(unittest.TestCase):
    def test_normal_day_is_pacific_daylight(self):
        points = fu.sce_day_points(date(2026, 10, 20), sce_rows('2026-10-20', [1] * 24))
        self.assertEqual(len(points), 24)
        self.assertEqual(min(points), '2026-10-20T07:00:00Z')
        self.assertEqual(max(points), '2026-10-21T06:00:00Z')

    def test_fall_back_day_has_25_distinct_hours(self):
        rows = sce_rows('2026-11-01', range(25))
        points = fu.sce_day_points(date(2026, 11, 1), rows)
        self.assertEqual(len(points), 25)
        # The repeated 1 AM: 08:00Z is PDT, 09:00Z is PST.
        self.assertEqual(points['2026-11-01T08:00:00Z'], 1)
        self.assertEqual(points['2026-11-01T09:00:00Z'], 2)
        self.assertEqual(max(points), '2026-11-02T07:00:00Z')

    def test_spring_forward_day_has_23_hours(self):
        points = fu.sce_day_points(date(2026, 3, 8), sce_rows('2026-03-08', [1] * 23))
        self.assertEqual(len(points), 23)
        self.assertEqual(max(points), '2026-03-09T06:00:00Z')

    def test_extra_rows_and_bad_values_are_dropped(self):
        rows = sce_rows('2026-10-20', [1] * 25)
        rows[3]['value'] = None
        points = fu.sce_day_points(date(2026, 10, 20), rows)
        self.assertEqual(len(points), 23)

    def test_rows_not_starting_at_midnight_are_ignored(self):
        rows = sce_rows('2026-10-20', [1] * 24)[1:]
        self.assertEqual(fu.sce_day_points(date(2026, 10, 20), rows), {})


class SceCsvTest(unittest.TestCase):
    PREAMBLE = ['\ufeffEnergy Usage Information', '', 'Detailed Usage',
                'Date,Energy Consumption time Period Start,Energy Consumption time Period End,Delivered,Received']

    def row(self, day, start, end, kwh):
        return f'"{day} ","{day} {start} ","{day} {end} ","{kwh}","0.000"'

    def test_day_rows_become_utc_hours(self):
        times = ['12:00AM', '01:00AM'] + [f'{h}:00AM' for h in range(2, 12)] + ['12:00PM'] + [f'{h}:00PM' for h in range(1, 12)]
        lines = self.PREAMBLE + [self.row('10/01/2026', t, '', 0.5) for t in times]
        points = fu.sce_csv_points(lines)
        self.assertEqual(len(points), 24)
        self.assertEqual(points['2026-10-01T07:00:00Z'], 0.5)
        self.assertEqual(max(points), '2026-10-02T06:00:00Z')

    def test_rejects_other_files(self):
        with self.assertRaises(ValueError):
            fu.sce_csv_points(['a,b,c', '1,2,3'])


class SceXlsxTest(unittest.TestCase):
    HEAD = [['Account Number : 1'], ['* note']]

    def test_daily_rows_across_new_year(self):
        rows = [['Range : Dec-20-2025 Jan-18-2026']] + self.HEAD + [['Date', 'Total Usage'],
                ['Jan 02  ', '20.5'], ['Dec 31  Event:Season Change Occurred', '18'], ['Totals', '38.5 kWh']]
        hourly, daily = fu.sce_xlsx_points(rows)
        self.assertEqual(hourly, {})
        self.assertEqual(daily, {date(2026, 1, 2): 20.5, date(2025, 12, 31): 18.0})

    def test_one_day_hourly(self):
        # Fall-back day: one 1 AM row, but Totals includes both.
        rows = [['Range : Nov-01-2026']] + self.HEAD + [['Time', 'Total Usage']] + \
               [[t, '1.0'] for t in ['12:00 AM', '01:00 AM'] + [f'{h:02d}:00 AM' for h in range(2, 12)] +
                ['12:00 PM'] + [f'{h:02d}:00 PM' for h in range(1, 12)]] + [['Totals', '24.5 kWh']]
        hourly, daily = fu.sce_xlsx_points(rows)
        self.assertEqual(len(hourly), 25)
        self.assertEqual(hourly['2026-11-01T09:00:00Z'], 0.5)
        self.assertEqual(daily, {})


class SoCalGasTest(unittest.TestCase):
    def test_hours_after_last_usage_are_dropped(self):
        payload = {'LastUsage': '2026-11-01T01:00:00', 'HourlyUsage': [
            {'ForDate': '2026-11-01T00:00:00', 'Usage': 0.02},
            {'ForDate': '2026-11-01T01:00:00', 'Usage': 0.04},
            {'ForDate': '2026-11-01T02:00:00', 'Usage': 0},
        ]}
        self.assertEqual(fu.socalgas_points(payload), {
            '2026-11-01T07:00:00Z': 0.02, '2026-11-01T08:00:00Z': 0.04})

    def test_skipped_spring_hour_is_added_to_the_next(self):
        payload = {'HourlyUsage': [
            {'ForDate': '2026-03-08T02:00:00', 'Usage': 0.02},
            {'ForDate': '2026-03-08T03:00:00', 'Usage': 0.04},
        ]}
        self.assertEqual(fu.socalgas_points(payload), {'2026-03-08T10:00:00Z': 0.06})


class EyeOnWaterTest(unittest.TestCase):
    def test_hourly_gallons_in_utc(self):
        payload = {'timeseries': {'m,0': {'series': [
            {'date': '2026-11-03 05:00:00', 'value': 4.86, 'unit': 'GAL'},
            {'date': '2026-11-03 04:00:00', 'value': 0, 'unit': 'GAL'},
            {'date': '2026-11-03 03:00:00', 'value': None, 'unit': 'GAL'},
        ]}}}
        self.assertEqual(fu.eyeonwater_points(payload), {
            '2026-11-03T13:00:00Z': 4.86, '2026-11-03T12:00:00Z': 0})


class ScheduleTest(unittest.TestCase):
    def test_empty_file_backfills(self):
        self.assertEqual(fu.first_day_to_fetch({}, date(2026, 11, 3), 365), date(2025, 11, 3))

    def test_existing_file_refetches_recent_days(self):
        hours = {'2026-11-02T06:00:00Z': 1}  # 11 PM Nov 1 local
        self.assertEqual(fu.first_day_to_fetch(hours, date(2026, 11, 3), 365), date(2026, 10, 29))

    def test_hours_in_day(self):
        self.assertEqual(fu.hours_in_day(date(2026, 11, 1)), 25)
        self.assertEqual(fu.hours_in_day(date(2026, 3, 8)), 23)
        self.assertEqual(fu.hours_in_day(date(2026, 6, 1)), 24)


if __name__ == '__main__':
    unittest.main()
