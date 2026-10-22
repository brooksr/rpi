"""Raspberry Pi health as seen from the HA container (host /proc, /sys, SD card)."""
import datetime
import glob
import json
import os
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


def main():
    idle1, total1 = cpu_times()
    time.sleep(1)
    idle2, total2 = cpu_times()
    memory, disk = meminfo(), os.statvfs('/config')
    temp = read('/sys/class/thermal/thermal_zone0/temp')
    # The firmware raises this alarm when supply voltage dips (a weak power supply).
    alarms = [read(p) for p in glob.glob('/sys/devices/platform/soc/soc:firmware/raspberrypi-hwmon/hwmon/hwmon*/in0_lcrit_alarm')]
    used = lambda total, free: round((total - free) / total * 100, 1) if total else None
    result = {
        'status': 'ok',
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
        'database_mb': round(os.path.getsize(DB) / 2**20) if os.path.exists(DB) else None,
        'checked_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    print(json.dumps(result))


if __name__ == '__main__':
    main()
