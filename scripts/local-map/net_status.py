"""Internet health from the HA host: router and internet latency/loss, DNS through
Pi-hole and the router, and an HTTPS round trip. State: online, degraded or
offline (offline only when no internet target answers at all)."""
import datetime
import json
import re
import subprocess
import time
import urllib.request

GATEWAY = '@@GATEWAY@@'  # filled from .env by install.sh
PINGS = {'router': GATEWAY, 'cloudflare': '1.1.1.1', 'google': '8.8.8.8'}
PIHOLE = '@@PI_IP_ETH@@'  # Pi-hole's LAN address; HA may run on another host
DNS = {'pihole': PIHOLE, 'router': GATEWAY}
SLOW_MS, LOSSY_PERCENT = 150, 10


def ping(host, count=5):
    try:
        out = subprocess.run(['ping', '-c', str(count), '-W', '2', host], capture_output=True, text=True, timeout=20).stdout
    except subprocess.TimeoutExpired:
        return {'loss': 100, 'ms': None}
    loss = re.search(r'(\d+(?:\.\d+)?)% packet loss', out)
    rtt = re.search(r'= [\d.]+/([\d.]+)/', out)
    return {'loss': float(loss.group(1)) if loss else 100.0, 'ms': round(float(rtt.group(1)), 1) if rtt else None}


def lookup(server, name='example.com'):
    started = time.monotonic()
    try:
        out = subprocess.run(['dig', f'@{server}', name, '+short', '+time=2', '+tries=1'], capture_output=True, text=True, timeout=6).stdout
    except subprocess.TimeoutExpired:
        out = ''
    ok = bool(re.search(r'^\d+\.\d+\.\d+\.\d+$', out, re.M))
    return {'ok': ok, 'ms': round((time.monotonic() - started) * 1000) if ok else None}


def https(url='https://www.google.com/generate_204'):
    started = time.monotonic()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'HomeAssistant-LocalMap/1.0'}), timeout=8) as response:
            ok = response.status in (200, 204)
    except Exception:
        ok = False
    return {'ok': ok, 'ms': round((time.monotonic() - started) * 1000) if ok else None}


def status(result):
    internet = [result['ping'][k] for k in ('cloudflare', 'google')]
    if all(p['ms'] is None for p in internet) and not result['https']['ok']:
        return 'offline'
    worst_loss = max(p['loss'] for p in internet)
    best_ms = min((p['ms'] for p in internet if p['ms'] is not None), default=None)
    if worst_loss >= LOSSY_PERCENT or (best_ms or 0) >= SLOW_MS or not result['https']['ok'] \
            or not all(d['ok'] for d in result['dns'].values()):
        return 'degraded'
    return 'online'


def main():
    result = {'ping': {name: ping(host) for name, host in PINGS.items()},
              'dns': {name: lookup(server) for name, server in DNS.items()}, 'https': https(),
              'checked_at': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    result['status'] = status(result)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
