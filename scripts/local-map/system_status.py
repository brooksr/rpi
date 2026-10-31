"""Host health: inside the HA container (host /proc, /sys, disk, battery), or
on the Pi itself when HA runs elsewhere, where cron posts it to HA's
pi_health webhook."""
import datetime
import glob
import json
import os
import socket
import time

DB = '/config/home-assistant_v2.db'


def cpu_times():
    with open('/proc/stat') as stat:
        values = list(map(int, stat.readline().split()[1:]))
    return values[3] + values[4], sum(values)  # idle + iowait, total


def meminfo():
    rows = {}
    with open('/proc/meminfo') as info:
        for line in info:
            key, value = line.split(':', 1)
            rows[key] = int(value.split()[0]) * 1024
    return rows


def read(path, default=None):
    try:
        with open(path) as handle:
            return handle.read().strip()
    except OSError:
        return default


def battery():
    # A laptop server: charge, wear (full vs design capacity) and whether it is on AC.
    supplies = [os.path.dirname(p) for p in glob.glob('/sys/class/power_supply/*/type')]
    cells = [d for d in supplies if read(f'{d}/type') == 'Battery' and read(f'{d}/present', '1') == '1']
    if not cells:
        return None
    cell = cells[0]
    full = read(f'{cell}/energy_full') or read(f'{cell}/charge_full')
    design = read(f'{cell}/energy_full_design') or read(f'{cell}/charge_full_design')
    mains = [read(f'{d}/online') for d in supplies if read(f'{d}/type') == 'Mains']
    capacity, cycles = read(f'{cell}/capacity'), read(f'{cell}/cycle_count')
    return {
        'percent': int(capacity) if capacity else None,
        'health_percent': round(int(full) / int(design) * 100) if full and design and int(design) else None,
        'cycles': int(cycles) if cycles and int(cycles) > 0 else None,
        'status': read(f'{cell}/status'),
        'ac_online': mains[0] == '1' if mains else None,
    }


def main():
    idle1, total1 = cpu_times()
    time.sleep(1)
    idle2, total2 = cpu_times()
    memory, disk = meminfo(), os.statvfs('/config' if os.path.isdir('/config') else '/')
    temp = read('/sys/class/thermal/thermal_zone0/temp')
    # The firmware raises this alarm when supply voltage dips (a weak power supply).
    alarms = [read(p) for p in glob.glob('/sys/devices/platform/soc/soc:firmware/raspberrypi-hwmon/hwmon/hwmon*/in0_lcrit_alarm')]
    used = lambda total, free: round((total - free) / total * 100, 1) if total else None
    result = {
        'status': 'ok',
        'host': socket.gethostname(),
        'cpu_percent': round((1 - (idle2 - idle1) / max(total2 - total1, 1)) * 100, 1),
        'load': [float(v) for v in read('/proc/loadavg', '0 0 0').split()[:3]],
        'cpu_count': os.cpu_count(),
        'temperature_c': round(int(temp) / 1000, 1) if temp else None,
        'memory_percent': used(memory['MemTotal'], memory['MemAvailable']),
        'memory_available_mb': round(memory['MemAvailable'] / 2**20),
        'memory_total_mb': round(memory['MemTotal'] / 2**20),
        'swap_percent': used(memory.get('SwapTotal', 0), memory.get('SwapFree', 0)),
        'disk_percent': used(disk.f_blocks, disk.f_bavail),
        'disk_free_gb': round(disk.f_bavail * disk.f_frsize / 2**30, 1),
        'uptime_hours': round(float(read('/proc/uptime', '0').split()[0]) / 3600, 1),
        'undervoltage': any(a == '1' for a in alarms) if alarms else None,
        'battery': battery(),
        'database_mb': round(os.path.getsize(DB) / 2**20) if os.path.exists(DB) else None,
        'checked_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    print(json.dumps(result))


if __name__ == '__main__':
    main()
