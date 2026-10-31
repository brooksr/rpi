"""Visible passes of fresh Starlink "trains" over home, from CelesTrak orbits.

A batch of Starlinks flies in a tight line for a week or two after launch,
while it is still low (about 270-370 km) and before it spreads out climbing to
its working orbit. That line is bright enough to see by eye. A pass is visible
when the satellites are at least MIN_ELEVATION up, still in sunlight, and the
sky here is dark (sun DARK_SUN or more below the horizon), which only happens
in the hour or two after sunset or before sunrise.

Positions use SGP4 (python3-sgp4); TEME is treated as the true-of-date frame,
which is good to a fraction of a degree, plenty for "look west at 6:48".
"""
import datetime
import json
import math
import pathlib
import time
import urllib.request

from sgp4 import omm
from sgp4.api import Satrec, jday

GP = 'https://celestrak.org/NORAD/elements/gp.php?GROUP=last-30-days&FORMAT=json'
REFRESH_HOURS = 6  # CelesTrak asks for no more than one download every 2 hours
TRAIN_ALTITUDE = 400  # km; a batch's median altitude below this may still be a train
MIN_SATELLITES = 10
TRAIN_GAP = 1500  # km (about 3 minutes apart); neighbours closer than this are in the same train
PASS_GAP = 120  # seconds; a pause shorter than this doesn't split a pass
MIN_ELEVATION = 15  # degrees
DARK_SUN = -6  # degrees; civil twilight is over
STEP = 30  # seconds
# The office window camera's view, from landmarks (2026-10-28 aim): Fireworks
# Hill (269°) at the centre, Tarantula Hill (297°) at x≈1035 of 1280, so about
# 17 px a degree; the horizon sits near mid-frame.
CAMERA_LEFT, CAMERA_RIGHT, CAMERA_TOP = 233, 305, 21  # azimuth, azimuth, elevation (degrees)
CAMERA_BOTTOM = 3  # the ridge line
EARTH_RADIUS = 6378.137
MU = 398600.4418
# Spelled out: the announcement is spoken.
COMPASS = ['north', 'north-northeast', 'northeast', 'east-northeast', 'east', 'east-southeast', 'southeast', 'south-southeast',
           'south', 'south-southwest', 'southwest', 'west-southwest', 'west', 'west-northwest', 'northwest', 'north-northwest']


def load(cache):
    """CelesTrak's recent-launch orbits, downloaded at most every REFRESH_HOURS."""
    try:
        if time.time() - cache.stat().st_mtime < REFRESH_HOURS * 3600:
            return json.loads(cache.read_text())
    except (OSError, ValueError):
        pass
    try:
        request = urllib.request.Request(GP, headers={'User-Agent': 'HomeAssistant-LocalMap/1.0'})
        with urllib.request.urlopen(request, timeout=60) as response:
            records = json.load(response)
        cache.write_text(json.dumps(records))
        return records
    except (OSError, ValueError):
        # Keep using the old copy if CelesTrak is down.
        return json.loads(cache.read_text()) if cache.exists() else []


def altitude(record):
    """Mean altitude in km from mean motion (revolutions a day)."""
    n = record['MEAN_MOTION'] * 2 * math.pi / 86400
    return (MU / n ** 2) ** (1 / 3) - EARTH_RADIUS


def trains(records, when):
    """{'2026-242': [Satrec, ...]} for batches still flying bunched up as a train at
    `when`. A batch that has spread out is skipped; one split in two gets '#2'."""
    jd, fr = jday(when.year, when.month, when.day, when.hour, when.minute, when.second)
    batches = {}
    for record in records:
        if record.get('OBJECT_NAME', '').startswith('STARLINK'):
            batches.setdefault(record['OBJECT_ID'][:8], []).append(record)
    result = {}
    for launch, batch in batches.items():
        heights = sorted(altitude(record) for record in batch)
        if len(batch) >= MIN_SATELLITES and heights[len(heights) // 2] < TRAIN_ALTITUDE:
            satellites = []
            for record in batch:
                satellite = Satrec()
                omm.initialize(satellite, {key: str(value) for key, value in record.items()})
                error, position, _ = satellite.sgp4(jd, fr)
                if not error:
                    satellites.append((satellite, position))
            clusters = [c for c in chains(satellites) if len(c) >= MIN_SATELLITES]
            for n, cluster in enumerate(sorted(clusters, key=len, reverse=True), 1):
                result[launch if n == 1 else f'{launch}#{n}'] = cluster
    return result


def chains(satellites):
    """Groups (satellite, position) pairs linked by neighbours under TRAIN_GAP apart."""
    groups = []
    left = list(satellites)
    while left:
        group, frontier = [], [left.pop()]
        while frontier:
            satellite, position = frontier.pop()
            group.append(satellite)
            near = [other for other in left if math.dist(position, other[1]) < TRAIN_GAP]
            left = [other for other in left if other not in near]
            frontier += near
        groups.append(group)
    return groups


def sun_vector(jd):
    """Unit vector to the sun, equatorial frame of date (low precision)."""
    t = (jd - 2451545) / 36525
    mean_longitude = 280.46646 + 36000.76983 * t
    m = math.radians(357.52911 + 35999.05029 * t)
    longitude = math.radians(mean_longitude + 1.914602 * math.sin(m) + 0.019993 * math.sin(2 * m))
    obliquity = math.radians(23.439291 - 0.0130042 * t)
    return (math.cos(longitude), math.cos(obliquity) * math.sin(longitude), math.sin(obliquity) * math.sin(longitude))


def gmst(jd):
    return math.radians((280.46061837 + 360.98564736629 * (jd - 2451545)) % 360)


class Observer:
    def __init__(self, lat, lon, height=0.3):
        self.lat, self.lon = math.radians(lat), math.radians(lon)
        a, f = EARTH_RADIUS, 1 / 298.257223563
        e2 = f * (2 - f)
        n = a / math.sqrt(1 - e2 * math.sin(self.lat) ** 2)
        self.ecef = ((n + height) * math.cos(self.lat) * math.cos(self.lon),
                     (n + height) * math.cos(self.lat) * math.sin(self.lon),
                     (n * (1 - e2) + height) * math.sin(self.lat))

    def look(self, position, theta):
        """(azimuth, elevation) in degrees of an equatorial position at sidereal angle theta."""
        x, y, z = position
        ex, ey = math.cos(theta) * x + math.sin(theta) * y, -math.sin(theta) * x + math.cos(theta) * y
        dx, dy, dz = ex - self.ecef[0], ey - self.ecef[1], z - self.ecef[2]
        sl, cl, sp, cp = math.sin(self.lon), math.cos(self.lon), math.sin(self.lat), math.cos(self.lat)
        east = -sl * dx + cl * dy
        north = -sp * cl * dx - sp * sl * dy + cp * dz
        up = cp * cl * dx + cp * sl * dy + sp * dz
        return math.degrees(math.atan2(east, north)) % 360, math.degrees(math.atan2(up, math.hypot(east, north)))

    def sun_altitude(self, sun, theta):
        return self.look(tuple(c * 1.496e8 for c in sun), theta)[1]


def sunlit(position, sun):
    """Outside Earth's (cylindrical) shadow."""
    along = sum(p * s for p, s in zip(position, sun))
    if along > 0:
        return True
    return sum(p * p for p in position) - along * along > EARTH_RADIUS ** 2


def in_camera(azimuth, elevation):
    return CAMERA_LEFT <= azimuth <= CAMERA_RIGHT and CAMERA_BOTTOM <= elevation <= CAMERA_TOP


def compass(azimuth):
    return COMPASS[round(azimuth / 22.5) % 16]


def passes(trains_by_launch, observer, start, hours=36):
    """Visible train passes starting within `hours` of `start`, soonest first."""
    found = []
    steps = int(hours * 3600 / STEP)
    for launch, satellites in trains_by_launch.items():
        current = None
        for i in range(steps + 1):
            when = start + datetime.timedelta(seconds=i * STEP)
            jd, fr = jday(when.year, when.month, when.day, when.hour, when.minute, when.second)
            theta, sun = gmst(jd + fr), sun_vector(jd + fr)
            seen = []
            if observer.sun_altitude(sun, theta) <= DARK_SUN:
                for satellite in satellites:
                    error, position, _ = satellite.sgp4(jd, fr)
                    if error:
                        continue
                    azimuth, elevation = observer.look(position, theta)
                    # Low in the camera's view counts too: it gets recorded, not announced.
                    if (elevation >= MIN_ELEVATION or in_camera(azimuth, elevation)) and sunlit(position, sun):
                        seen.append((elevation, azimuth))
            if seen:
                top = max(seen)
                if current is None:
                    current = {'train': launch, 'start': when, 'start_azimuth': top[1], 'peak': when,
                               'max_elevation': top[0], 'peak_azimuth': top[1], 'satellites': len(seen), 'in_camera': False}
                if top[0] > current['max_elevation']:
                    current.update(peak=when, max_elevation=top[0], peak_azimuth=top[1])
                current.update(end=when, end_azimuth=top[1], satellites=max(current['satellites'], len(seen)),
                               in_camera=current['in_camera'] or any(in_camera(a, e) for e, a in seen))
            elif current and (when - current['end']).total_seconds() > PASS_GAP:
                found.append(current)
                current = None
        if current:
            found.append(current)
    found.sort(key=lambda p: p['start'])
    for p in found:
        p.update(max_elevation=round(p['max_elevation']), start_direction=compass(p['start_azimuth']),
                 peak_direction=compass(p['peak_azimuth']), end_direction=compass(p['end_azimuth']))
        for key in ('start_azimuth', 'peak_azimuth', 'end_azimuth'):
            p[key] = round(p[key])
    return found


def summary(found, train_names, now, error=None):
    """The JSON Home Assistant reads: upcoming passes and the next one to announce."""
    rows = [{**p, 'start': p['start'].isoformat(), 'peak': p['peak'].isoformat(), 'end': p['end'].isoformat()}
            for p in sorted(found, key=lambda p: p['start']) if p['end'] > now]
    # Passes that only skim the camera's corner are recorded but not announced.
    alert = next((row for row in rows if row['max_elevation'] >= MIN_ELEVATION), None)
    alert_at = (datetime.datetime.fromisoformat(alert['start']) - datetime.timedelta(minutes=5)).isoformat() if alert else None
    return {'status': 'ok' if error is None else 'unavailable', 'count': len(rows), 'passes': rows[:6],
            'trains': sorted(train_names), 'alert': alert, 'alert_at': alert_at,
            'checked_at': now.isoformat(), 'error': error}
