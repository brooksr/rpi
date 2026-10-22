"""Trash and street-sweeping dates for automations: a port of
household-schedule.mjs (keep the two in step; test_household.py replays the
JS tests). Prints the next dates and whether each is tomorrow, in Pacific time."""
import datetime
import json

SWEEP_DAYS_2026 = [[14, 28], [11, 25], [11, 25], [8, 22], [13], [10], [8], [12], [10], [14, 28], [11, 25], [9, 23]]
DAY = datetime.timedelta(days=1)


def js_day(day):
    """JavaScript getUTCDay(): Sunday 0 … Saturday 6."""
    return (day.weekday() + 1) % 7


def nth_weekday(year, month, weekday, n):
    first = datetime.date(year, month, 1)
    return first + datetime.timedelta(days=(weekday - js_day(first)) % 7 + 7 * (n - 1))


def holidays(year):
    memorial = nth_weekday(year, 5, 1, 5)
    if memorial.month != 5:
        memorial -= datetime.timedelta(days=7)
    days = [datetime.date(year, 1, 1), memorial, datetime.date(year, 7, 4), nth_weekday(year, 9, 1, 1),
            nth_weekday(year, 11, 4, 4), datetime.date(year, 12, 25)]
    return [d for d in days if 0 < js_day(d) < 6]


def holiday_shift(service):
    """Athens delays only routes on/after a weekday holiday within that same week."""
    monday = service - datetime.timedelta(days=(js_day(service) + 6) % 7)
    return 1 if any(monday <= h <= service for h in holidays(service.year)) else 0


def next_trash(today, hour=0):
    for offset in range(15):
        nominal = today + offset * DAY
        if js_day(nominal) != 2:
            continue
        shifted = holiday_shift(nominal)
        actual = nominal + shifted * DAY
        if actual > today or (actual == today and hour < 19):
            return {'date': actual.isoformat(), 'holidayDelayed': bool(shifted)}
    raise ValueError('No upcoming collection found')


def upcoming_trash(today, hour=0):
    previous = today - DAY
    if js_day(previous) == 2 and holiday_shift(previous) and hour < 19:
        return {'date': today.isoformat(), 'holidayDelayed': True}
    return next_trash(today, hour)


def next_sweeps(today, hour=0, count=3):
    found = []
    for year in (today.year, today.year + 1):
        for month in range(1, 13):
            if year == 2026:
                found += [{'date': datetime.date(year, month, d).isoformat(), 'verified': True} for d in SWEEP_DAYS_2026[month - 1]]
            else:
                for week in ([2] if 5 <= month <= 9 else [2, 4]):
                    nominal = nth_weekday(year, month, 3, week)
                    found.append({'date': (nominal + holiday_shift(nominal) * DAY).isoformat(), 'verified': False})
    iso = today.isoformat()
    return [d for d in found if d['date'] > iso or (d['date'] == iso and hour < 19)][:count]


def local_clock(now=None):
    import zoneinfo
    local = (now or datetime.datetime.now(datetime.timezone.utc)).astimezone(zoneinfo.ZoneInfo('America/Los_Angeles'))
    return local.date(), local.hour


def main():
    today, hour = local_clock()
    trash, sweeps = upcoming_trash(today, hour), next_sweeps(today, hour)
    tomorrow = (today + DAY).isoformat()
    print(json.dumps({'status': 'ok', 'today': today.isoformat(), 'next_trash': trash['date'],
                      'trash_holiday_delayed': trash['holidayDelayed'], 'trash_tomorrow': trash['date'] == tomorrow,
                      'next_sweep': sweeps[0]['date'] if sweeps else None,
                      'sweep_verified': sweeps[0]['verified'] if sweeps else None,
                      'sweep_tomorrow': bool(sweeps) and sweeps[0]['date'] == tomorrow}))


if __name__ == '__main__':
    main()
