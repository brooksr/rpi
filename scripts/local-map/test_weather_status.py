"""A failed NWS response must not become a no-warning status."""
import contextlib
import io
import json
import unittest
from unittest.mock import patch

import weather_status


class WeatherStatusTests(unittest.TestCase):
    def read(self, payload=None, error=None):
        output=io.StringIO()
        with patch('sys.argv',['weather_status.py','34.1764','-118.8489']), contextlib.redirect_stdout(output):
            with patch('urllib.request.urlopen',side_effect=error,return_value=io.StringIO(json.dumps(payload))):
                weather_status.main()
        return json.loads(output.getvalue())

    def test_clear_only_when_feed_succeeds(self):
        self.assertEqual(self.read({'features':[]})['status'],'clear')

    def test_failed_or_invalid_feed_is_unavailable(self):
        self.assertEqual(self.read(error=TimeoutError())['status'],'unavailable')
        self.assertEqual(self.read({'error':'bad response'})['status'],'unavailable')

    def test_warning_details_are_preserved(self):
        result=self.read({'features':[{'properties':{'event':'Red Flag Warning','headline':'Fire weather warning','instruction':'Avoid sparks'}}]})
        self.assertEqual(result['status'],'active')
        self.assertEqual(result['count'],1)
        self.assertEqual(result['alerts'][0]['instruction'],'Avoid sparks')


if __name__=='__main__':unittest.main()
