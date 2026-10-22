"""Verify that failed feeds cannot produce an all-clear notification."""
import contextlib
import io
import json
import unittest
from unittest.mock import patch

import status


class StatusTests(unittest.TestCase):
    def run_reader(self, results):
        output = io.StringIO()
        with patch.object(status, 'query', side_effect=results), patch('sys.argv', ['status.py', 'EXAMPLE']), contextlib.redirect_stdout(output):
            status.main()
        return json.loads(output.getvalue())

    def test_active_shutoff_takes_precedence(self):
        self.assertEqual(status.summarize([{'PSPS': 'Monitored'}], [{'PSPS': 'De-Energized'}]), 'power_shutoff')

    def test_clear_requires_both_successful_empty_feeds(self):
        self.assertEqual(self.run_reader([[], []])['status'], 'no_psps_listed')

    def test_either_failed_feed_reports_unavailable(self):
        for results in ([TimeoutError(), []], [[], TimeoutError()]):
            result = self.run_reader(results)
            self.assertEqual(result['status'], 'unavailable')
            self.assertEqual(result['events'], [])
            self.assertEqual(result['error'], 'TimeoutError')

    def test_event_details_are_preserved(self):
        event = {'CIRCUIT_NAME': 'EXAMPLE', 'PSPS': 'Monitored', 'StartDate': 1792069200000}
        result = self.run_reader([[event], []])
        self.assertEqual(result['status'], 'under_consideration')
        self.assertEqual(result['events'], [event])


if __name__ == '__main__':
    unittest.main()
