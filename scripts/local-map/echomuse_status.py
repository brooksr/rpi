"""EchoMuse speaker health for the Device Health card (sensor.echomuse_health).

Runs on the HA laptop by cron and reads the EchoMuse controller's SQLite
database read-only: the latest hourly metrics, last check-in and boot time.
Prints one JSON object per device shaped like system_status.py's output, plus
Wi-Fi, so pi-health-card can show it. Usage: echomuse_status.py DB [DEVICE_ID]
"""
import datetime
import json
import sqlite3
import sys
import time

OFFLINE_AFTER_S = 300  # The controller updates last_seen every minute or so.


def iso(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).isoformat() if ts else None


def status(conn, device_id=None, now=None):
    now = now or time.time()
    conn.row_factory = sqlite3.Row
    query = 'SELECT device_id, label, last_seen, firmware_ver FROM devices WHERE approved = 1'
    rows = conn.execute(query + (' AND device_id = ?' if device_id else '') + ' ORDER BY label', (device_id,) if device_id else ()).fetchall()
    if not rows:
        return {'status': 'error', 'checked_at': iso(now)}
    d = rows[0]
    m = conn.execute('SELECT * FROM device_metrics WHERE device_id = ? ORDER BY hour_ts DESC LIMIT 1', (d['device_id'],)).fetchone()
    boot = conn.execute('SELECT first_seen FROM device_boots WHERE device_id = ? ORDER BY first_seen DESC LIMIT 1', (d['device_id'],)).fetchone()
    avg = lambda total, n: total / n if total is not None and n else None
    pct = lambda used, total: round(used / total * 100, 1) if used is not None and total else None
    rnd = lambda v, n=1: round(v, n) if v is not None else None
    result = {
        'status': 'ok' if d['last_seen'] and now - d['last_seen'] < OFFLINE_AFTER_S else 'offline',
        'host': f"{d['label']} · EchoMuse {d['firmware_ver'] or ''}".strip(),
        'checked_at': iso(d['last_seen']),
        'uptime_hours': rnd((now - boot['first_seen']) / 3600) if boot else None,
        'undervoltage': None, 'battery': None, 'database_mb': None, 'swap_percent': None, 'load': None,
    }
    if m:
        n = m['samples']
        mem_used = avg(m['mem_used_sum'], n)
        result.update({
            'cpu_percent': rnd(avg(m['cpu_sum'], n)),
            'cpu_count': m['cores_total'],
            'cores_online': m['cores_online_last'],
            'temperature_c': rnd(avg(m['cpu_temp_sum'], m['cpu_temp_samples'])),
            'memory_percent': pct(mem_used, m['mem_total_mb']),
            'memory_available_mb': round(m['mem_total_mb'] - mem_used) if mem_used is not None and m['mem_total_mb'] else None,
            'memory_total_mb': m['mem_total_mb'],
            'disk_percent': pct(m['storage_used_mb'], m['storage_total_mb']),
            'disk_free_gb': rnd((m['storage_total_mb'] - m['storage_used_mb']) / 1024, 2) if m['storage_total_mb'] else None,
            'wifi': {
                'rssi': rnd(avg(m['rssi_sum'], m['rssi_samples']), 0),
                'ghz': rnd(m['wifi_freq_last'] / 1000) if m['wifi_freq_last'] else None,
                'mbps': m['link_speed_last'],
                'rtt_ms': rnd(avg(m['rtt_sum_ms'], m['rtt_samples']), 0),
            },
        })
    return result


def main():
    conn = sqlite3.connect(f'file:{sys.argv[1]}?mode=ro', uri=True, timeout=10)
    print(json.dumps(status(conn, sys.argv[2] if len(sys.argv) > 2 else None)))


if __name__ == '__main__':
    main()
