import assert from 'node:assert/strict';
import {sunTimes,moonPhase} from './sky.mjs';

// Reference values from astral (HA's sun library) and published 2026 lunar phases.
const near = (actual, expected, minutes) => assert.ok(Math.abs(actual - Date.parse(expected)) <= minutes * 60000, `${actual.toISOString()} vs ${expected}`);
const home = sunTimes('2026-10-18', 34.1764, -118.8489);
near(home.firstLight, '2026-10-18T13:37:30Z', 2);
near(home.sunrise, '2026-10-18T14:03:30Z', 2);
near(home.sunset, '2026-10-19T01:17:30Z', 2);
near(sunTimes('2026-06-21', 34.1764, -118.8489).sunset, '2026-06-22T03:10:30Z', 2);
assert.equal(sunTimes('2026-06-21', 78, 15).sunset, null);
const moon = moonPhase(Date.parse('2026-10-18T19:00:00Z'));
assert.equal(moon.name, 'First quarter');
assert.ok(moon.waxing && Math.abs(moon.illumination - 0.5) < 0.03);
near(moon.nextFull, '2026-10-26T04:12:00Z', 60);
near(moonPhase(Date.parse('2026-01-01T00:00:00Z')).nextFull, '2026-01-03T10:03:00Z', 60);
assert.equal(moonPhase(Date.parse('2026-10-26T04:12:00Z')).name, 'Full moon');
assert.equal(moonPhase(Date.parse('2026-10-14T00:00:00Z')).name, 'Waxing crescent');
console.log('Sun time and moon phase checks passed');
