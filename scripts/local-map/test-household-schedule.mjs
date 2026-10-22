import assert from 'node:assert/strict';
import {upcomingTrash,nextSweeps,localClock} from './household-schedule.mjs';

assert.equal(upcomingTrash('2026-10-13',14).date,'2026-10-13');
assert.equal(upcomingTrash('2026-10-13',20).date,'2026-10-20');
assert.equal(upcomingTrash('2026-09-07',14).date,'2026-09-09');
assert.equal(upcomingTrash('2026-09-09',14).date,'2026-09-09');
assert.equal(upcomingTrash('2026-11-23',14).date,'2026-11-24');
assert.equal(upcomingTrash('2026-07-06',14).date,'2026-07-07');
assert.equal(nextSweeps('2026-10-13',14)[0].date,'2026-10-14');
assert.equal(nextSweeps('2026-10-14',20)[0].date,'2026-10-28');
assert.equal(nextSweeps('2026-09-01',14)[0].date,'2026-09-10');
assert.equal(nextSweeps('2026-05-14',14)[0].date,'2026-06-10');
assert.equal(nextSweeps('2027-01-01',14)[0].verified,false);
assert.equal(localClock(new Date('2026-10-14T02:00:00Z')).today,'2026-10-13');
console.log('Schedule, holiday, service cutoff and timezone checks passed');
