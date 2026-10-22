// Today's sun times (NOAA solar equations) and the moon's phase (low-precision
// lunar longitude). Accurate to about a minute for the sun and an hour or two
// for moon phase timing, which is enough for a household card.
const DAY = 86400000, RAD = Math.PI / 180;
const sin = d => Math.sin(d * RAD), cos = d => Math.cos(d * RAD);
const norm = d => ((d % 360) + 360) % 360;
const julian = time => time / DAY + 2440587.5;

// Solar declination and equation of time (minutes) at a moment.
function solar(time) {
  const t = (julian(time) - 2451545) / 36525;
  const l0 = norm(280.46646 + t * (36000.76983 + t * 0.0003032));
  const m = 357.52911 + t * (35999.05029 - 0.0001537 * t);
  const e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t);
  const center = sin(m) * (1.914602 - t * (0.004817 + 0.000014 * t)) + sin(2 * m) * (0.019993 - 0.000101 * t) + sin(3 * m) * 0.000289;
  const omega = 125.04 - 1934.136 * t;
  const lambda = l0 + center - 0.00569 - 0.00478 * sin(omega);
  const obliquity = 23 + (26 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60) / 60 + 0.00256 * cos(omega);
  const declination = Math.asin(sin(obliquity) * sin(lambda)) / RAD;
  const y = Math.tan(obliquity / 2 * RAD) ** 2;
  const eqTime = 4 / RAD * (y * sin(2 * l0) - 2 * e * sin(m) + 4 * e * y * sin(m) * cos(2 * l0) - 0.5 * y * y * sin(4 * l0) - 1.25 * e * e * sin(2 * m));
  return {declination, eqTime};
}

// When the sun's centre crosses `zenith` degrees on a calendar day (YYYY-MM-DD).
// Returns null on days it never does (polar day or night).
function crossing(day, latitude, longitude, zenith, rising) {
  const midnight = Date.parse(`${day}T00:00:00Z`);
  let time = midnight + (720 - 4 * longitude) * 60000;
  for (let pass = 0; pass < 3; pass++) {
    const {declination, eqTime} = solar(time);
    const cosHour = cos(zenith) / (cos(latitude) * cos(declination)) - Math.tan(latitude * RAD) * Math.tan(declination * RAD);
    if (Math.abs(cosHour) > 1) return null;
    const hour = Math.acos(cosHour) / RAD * (rising ? 1 : -1);
    time = midnight + (720 - 4 * (longitude + hour) - eqTime) * 60000;
  }
  return new Date(Math.round(time / 60000) * 60000);
}

// First light is civil dawn: the sun 6° below the horizon.
export function sunTimes(day, latitude, longitude) {
  return {
    firstLight: crossing(day, latitude, longitude, 96, true),
    sunrise: crossing(day, latitude, longitude, 90.833, true),
    sunset: crossing(day, latitude, longitude, 90.833, false),
  };
}

// Moon minus sun ecliptic longitude: 0 new, 90 first quarter, 180 full.
export function elongation(time) {
  const d = julian(time) - 2451545;
  const sunMean = 357.529 + 0.98560028 * d;
  const sun = 280.459 + 0.98564736 * d + 1.915 * sin(sunMean) + 0.02 * sin(2 * sunMean);
  const moonMean = 134.963 + 13.064993 * d, elong = 297.850 + 12.190749 * d, node = 93.272 + 13.22935 * d;
  const moon = 218.316 + 13.176396 * d + 6.289 * sin(moonMean) + 1.274 * sin(2 * elong - moonMean) + 0.658 * sin(2 * elong) +
    0.214 * sin(2 * moonMean) - 0.186 * sin(sunMean) - 0.114 * sin(2 * node);
  return norm(moon - sun);
}

const PHASES = ['New moon','Waxing crescent','First quarter','Waxing gibbous','Full moon','Waning gibbous','Last quarter','Waning crescent'];
// Named quarters cover the day either side of the exact moment (±6°).
function phaseName(angle) {
  for (let quarter = 0; quarter < 4; quarter++) {
    const off = norm(angle - quarter * 90 + 180) - 180;
    if (Math.abs(off) <= 6) return PHASES[quarter * 2];
  }
  return PHASES[Math.floor(angle / 90) * 2 + 1];
}

// The next moment elongation reaches `target` degrees after `time`.
export function nextPhase(time, target) {
  const ahead = t => norm(target - elongation(t));
  let low = time, high = time + 6 * 3600000;
  while (ahead(high) < ahead(low) || ahead(low) < 1e-9) { low = high; high += 6 * 3600000; }
  // ahead() drops to 0 then wraps to ~360 at the crossing; bisect to a minute.
  while (high - low > 60000) { const mid = (low + high) / 2; if (ahead(mid) <= ahead(low)) low = mid; else high = mid; }
  return new Date(high);
}

export function moonPhase(time = Date.now()) {
  const angle = elongation(time);
  return {
    angle,
    name: phaseName(angle),
    illumination: (1 - cos(angle)) / 2,
    waxing: angle < 180,
    nextFull: nextPhase(time, 180),
    nextNew: nextPhase(time, 0),
  };
}
