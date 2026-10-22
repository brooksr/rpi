"""Authenticated, read-only access to SCE's public map feeds.

SCE's feed omits browser CORS headers. Keep queries behind HA authentication
and allow only the four known map layers, not arbitrary proxy URLs.
"""
import asyncio
import json
import time

import aiohttp
import voluptuous as vol
from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.helpers.aiohttp_client import async_get_clientsession

DOMAIN = 'local_map'
CONFIG_SCHEMA = vol.Schema({vol.Optional(DOMAIN): vol.Schema({})}, extra=vol.ALLOW_EXTRA)
BASE = 'https://sce-outage-ags.esriemcs.com/arcgis/rest/services/43'
SOURCES = {
    'psps0': f'{BASE}/psps/MapServer/0/query',
    'psps1': f'{BASE}/psps/MapServer/1/query',
    'outages': f'{BASE}/outage/MapServer/0/query',
    'scheduled': f'{BASE}/outage/MapServer/1/query',
}
ALLOWED_PARAMS = {
    'where', 'outFields', 'outSR', 'returnGeometry', 'f', 'geometryPrecision',
    'resultRecordCount', 'resultOffset', 'geometry', 'geometryType', 'inSR',
    'spatialRel', 'maxAllowableOffset',
}


class LocalMapView(HomeAssistantView):
    url = '/api/local_map/{layer}'
    name = 'api:local_map:feed'
    requires_auth = True

    def __init__(self, hass):
        self.hass = hass
        self.cache = {}

    async def get(self, request, layer):
        if layer not in SOURCES:
            raise web.HTTPNotFound()
        if set(request.query) - ALLOWED_PARAMS:
            raise web.HTTPBadRequest(text='Unsupported map parameter')
        params = dict(request.query)
        # Format and size limits are enforced regardless of caller parameters.
        params.update(f='geojson', outSR='4326', resultRecordCount='1000')
        key = (layer, tuple(sorted(params.items())))
        cached = self.cache.get(key)
        if cached and time.monotonic() - cached[0] < 60:
            return web.Response(body=cached[1], content_type='application/json')
        try:
            session = async_get_clientsession(self.hass)
            async with session.get(SOURCES[layer], params=params,
                                   timeout=aiohttp.ClientTimeout(total=22)) as response:
                response.raise_for_status()
                chunks = []
                size = 0
                async for chunk in response.content.iter_chunked(65536):
                    size += len(chunk)
                    if size > 8 * 1024 * 1024:
                        raise ValueError('Map response too large')
                    chunks.append(chunk)
                body = b''.join(chunks)
                data = json.loads(body)
                if data.get('error') or not isinstance(data.get('features'), list):
                    raise ValueError('Invalid SCE map response')
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            return web.json_response({'error': {'message': 'SCE map feed unavailable'}}, status=502)
        # Bound cache memory on the Pi; a minute of reuse avoids duplicate clients.
        now = time.monotonic()
        self.cache = {k: v for k, v in self.cache.items() if now - v[0] < 60}
        if len(self.cache) >= 8:
            self.cache.pop(next(iter(self.cache)))
        self.cache[key] = (now, body)
        return web.Response(body=body, content_type='application/json')


async def async_setup(hass, config):
    hass.http.register_view(LocalMapView(hass))
    return True
