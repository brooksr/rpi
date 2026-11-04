"""Import hourly utility usage written by scripts/utility-usage/fetch_usage.py.

Each /config/utility-usage/<site>.json holds every hour fetched so far. The
utilities publish a day or two late, so the hours go in as external statistics
(utility_usage:<site>) at their real times, for the Energy dashboard. The whole
file is re-imported when it changes; sums restart from its first hour, which
keeps them consistent however much history the file has.

sensor.utility_usage_<site> reports the fetch status, and a notification
appears while a site needs a manual login. A site with meter flags (EyeOnWater)
also gets binary_sensor.utility_usage_water_leak, with a notification while on.
"""
from datetime import timedelta
import json
import logging
import pathlib

import voluptuous as vol
from homeassistant.components import persistent_notification
from homeassistant.components.recorder.models import StatisticData, StatisticMeanType, StatisticMetaData
from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.const import UnitOfEnergy, UnitOfVolume
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.start import async_at_started
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import EnergyConverter, VolumeConverter

DOMAIN = 'utility_usage'
CONFIG_SCHEMA = vol.Schema({vol.Optional(DOMAIN): vol.Schema({})}, extra=vol.ALLOW_EXTRA)
_LOGGER = logging.getLogger(__name__)
UNITS = {
    'kWh': (UnitOfEnergy.KILO_WATT_HOUR, EnergyConverter.UNIT_CLASS),
    'CCF': (UnitOfVolume.CENTUM_CUBIC_FEET, VolumeConverter.UNIT_CLASS),
    'gal': (UnitOfVolume.GALLONS, VolumeConverter.UNIT_CLASS),
}
ICONS = {'kWh': 'mdi:transmission-tower-import', 'CCF': 'mdi:fire', 'gal': 'mdi:water'}
LEAK_FLAGS = ('Leak', 'EncoderLeak')
OTHER_FLAGS = ('ReverseFlow', 'EncoderReverseFlow', 'Tamper', 'MagneticTamper', 'CoverRemoved', 'EmptyPipe', 'LowBattery')
LOGIN_HINT = ("Run `ssh -t {host} '~/utility-usage/venv/bin/python "
              "~/utility-usage/fetch_usage.py login {site}'` and finish the login.")


def _read(folder):
    files = {}
    for path in sorted(pathlib.Path(folder).glob('*.json')):
        try:
            files[path.stem] = (path.stat().st_mtime, json.loads(path.read_text()))
        except (OSError, ValueError) as exc:
            _LOGGER.warning('Skipping %s: %s', path, exc)
    return files


def _statistics(hours):
    total = 0.0
    rows = []
    for stamp, value in sorted(hours.items()):
        total += float(value)
        start = dt_util.parse_datetime(stamp)
        rows.append(StatisticData(start=start, state=float(value), sum=round(total, 4)))
    return rows


async def async_setup(hass, config):
    folder = hass.config.path('utility-usage')
    seen = {}

    async def refresh(_now=None):
        files = await hass.async_add_executor_job(_read, folder)
        for site, (mtime, data) in files.items():
            if seen.get(site) == mtime:
                continue
            seen[site] = mtime
            unit, unit_class = UNITS.get(data.get('unit'), (data.get('unit'), None))
            hours = data.get('hours') or {}
            if hours:
                async_add_external_statistics(hass, StatisticMetaData(
                    mean_type=StatisticMeanType.NONE, has_sum=True, name=data.get('name') or site,
                    source=DOMAIN, statistic_id=f'{DOMAIN}:{site}', unit_class=unit_class,
                    unit_of_measurement=unit), _statistics(hours))
            through = data.get('data_through')
            hass.states.async_set(f'sensor.utility_usage_{site}', data.get('status', 'unknown'), {
                'friendly_name': f'{data.get("name") or site} fetch',
                'icon': ICONS.get(data.get('unit'), 'mdi:meter-electric'),
                'message': data.get('message'),
                # Start of the last hour with data.
                'data_through': dt_util.as_local(dt_util.parse_datetime(through)).isoformat() if through else None,
                'last_success': data.get('last_success'),
                'checked': data.get('checked'),
                'hours': len(hours),
                'statistic_id': f'{DOMAIN}:{site}',
            })
            note_id = f'{DOMAIN}_{site}'
            if data.get('status') == 'needs_login':
                persistent_notification.async_create(
                    hass, f'{data.get("message")}\n\n' + LOGIN_HINT.format(host='the HA laptop', site=site),
                    title=f'{data.get("name") or site} needs a login', notification_id=note_id)
            else:
                persistent_notification.async_dismiss(hass, note_id)
            flags = data.get('flags')
            if flags is not None:
                leak = any(flags.get(k) for k in LEAK_FLAGS)
                others = [k for k in OTHER_FLAGS if flags.get(k)]
                hass.states.async_set('binary_sensor.utility_usage_water_leak', 'on' if leak else 'off', {
                    'friendly_name': 'Water leak', 'device_class': 'moisture',
                    'meter_alerts': others, 'battery': data.get('battery'), 'flags_time': flags.get('time')})
                if leak:
                    persistent_notification.async_create(
                        hass, 'The water meter reports a leak (continuous flow). Check EyeOnWater for the flow chart.',
                        title='Water leak', notification_id=f'{DOMAIN}_water_leak')
                else:
                    persistent_notification.async_dismiss(hass, f'{DOMAIN}_water_leak')

    async_at_started(hass, refresh)
    async_track_time_interval(hass, refresh, timedelta(minutes=15))
    return True
