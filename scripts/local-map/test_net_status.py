"""Offline only when nothing on the internet answers; slow, lossy or DNS failures are degraded."""
import unittest

import net_status


def result(cloudflare=(0, 12), google=(0, 14), https=True, pihole=True):
    p = lambda loss_ms: {'loss': loss_ms[0], 'ms': loss_ms[1]}
    return {'ping': {'router': p((0, 2)), 'cloudflare': p(cloudflare), 'google': p(google)},
            'dns': {'pihole': {'ok': pihole}, 'router': {'ok': True}}, 'https': {'ok': https}}


class NetStatusTests(unittest.TestCase):
    def test_states(self):
        self.assertEqual(net_status.status(result()), 'online')
        self.assertEqual(net_status.status(result(cloudflare=(20, 30))), 'degraded')
        self.assertEqual(net_status.status(result(cloudflare=(0, 400), google=(0, 380))), 'degraded')
        self.assertEqual(net_status.status(result(pihole=False)), 'degraded')
        self.assertEqual(net_status.status(result(cloudflare=(100, None), google=(100, None), https=False)), 'offline')
        self.assertEqual(net_status.status(result(cloudflare=(100, None), google=(0, 20))), 'degraded')


if __name__ == '__main__':
    unittest.main()
