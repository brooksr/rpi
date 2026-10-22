"""Gas prices sort by price, skip stations without prices, and fail closed."""
import contextlib
import io
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

import gas_prices


def place(name, price, lat=34.18, lon=-118.844):
    fuel = {'fuelPrices': [{'type': 'REGULAR_UNLEADED', 'price': {'units': str(int(price)), 'nanos': round(price % 1 * 1e9)}}]} if price else None
    return {'id': name, 'displayName': {'text': name}, 'formattedAddress': f'{name} St',
            'location': {'latitude': lat, 'longitude': lon}, 'fuelOptions': fuel}


class GasPriceTests(unittest.TestCase):
    def read(self, payload=None, error=None, key='abc123'):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as folder:
            secrets = pathlib.Path(folder, 'secrets.yaml')
            if key:
                secrets.write_text(f'other: x\ngoogle_places_api_key: "{key}"\n')
            with patch.object(gas_prices, 'SECRETS', secrets), patch('sys.argv', ['gas_prices.py', '34.176', '-118.849', '5']), \
                    patch('urllib.request.urlopen', side_effect=error, return_value=io.StringIO(json.dumps(payload))), \
                    contextlib.redirect_stdout(output):
                gas_prices.main()
        return json.loads(output.getvalue())

    def test_three_cheapest_with_prices(self):
        result = self.read({'places': [place('A', 4.899), place('B', 4.599), place('C', None), place('D', 4.699), place('E', 4.799)]})
        self.assertEqual(result['status'], 'ok')
        self.assertEqual([s['name'] for s in result['stations']], ['B', 'D', 'E'])
        self.assertEqual(result['stations'][0]['price'], 4.599)
        self.assertLess(result['stations'][0]['miles'], 1)

    def test_missing_key_and_failures(self):
        self.assertEqual(self.read(key=None)['status'], 'needs_key')
        self.assertEqual(self.read(error=TimeoutError())['status'], 'unavailable')
        self.assertEqual(self.read({'places': [place('C', None)]})['status'], 'no_prices')


if __name__ == '__main__':
    unittest.main()
