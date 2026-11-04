#!/usr/bin/env python3
"""Records the office window camera around each Vandenberg launch and each
visible Starlink train pass, then makes a real-time replay, a sped-up timelapse
and (at night) a light-trail still.

Launch times come from the Home Assistant Vandenberg sensor's cache (the raw
Launch Library 2 answer, refreshed every 30 minutes). From 30 minutes before a
launch this also asks the API for that launch itself every 5 minutes, to follow
holds and slips; with HA's 2 calls an hour that stays under the 15-an-hour limit.

On the first recording (Starlink 15-18, Oct 30 2026) the minute snapshots show
the rocket over the ridge at T+1:26, as predicted, but the video only showed it
at T+12: it came from go2rtc's H.264 transcode, which the dashboard had kept
open and which had fallen 11 minutes behind. Recordings now take the camera's
own MJPEG from the capture instance. Raw recordings are kept for RAW_DAYS so they
can be reprocessed while tuning: `launch_recorder.py process <raw dir>`.

Starlink passes come from starlink.py, recomputed every 10 minutes; the next
36 hours of them go to Home Assistant through STARLINK_JSON for announcements.
A pass records from a minute before it starts to a minute after it ends, with
T0 at its highest point.
"""
import datetime
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
import urllib.request

import starlink

BEFORE = datetime.timedelta(minutes=1)
AFTER = datetime.timedelta(minutes=10)
FIRM = {'Second', 'Minute', 'Hour'}
DONE = {'Success', 'Failure', 'Partial Failure'}
HOME = pathlib.Path.home()
CACHE = HOME / 'homeassistant/.vandenberg-launches.json'
RAW = HOME / 'office-camera/launches'  # on /data
MEDIA = HOME / 'homeassistant/media/office-camera'  # launches/ and starlink/ inside
STARLINK_ORBITS = HOME / 'office-camera/starlink-orbits.json'
STARLINK_JSON = HOME / 'homeassistant/.starlink-trains.json'  # HA: /config/.starlink-trains.json
PASS_PAD = datetime.timedelta(minutes=1)
RAW_DAYS, OUT_DAYS = 30, 90
IMAGE = 'alexxit/go2rtc:1.9.14-hardware'
STREAM = 'rtsp://127.0.0.1:8556/office_window'  # capture instance, camera's MJPEG, no transcode
API = 'https://ll.thespacedevs.com/2.3.0/launches/{}/?format=json&mode=normal'
FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf'
SPEED = 8  # timelapse speed-up
NIGHT_LUMA = 100  # frame average; night sits at 60-70, day at 130-165


def now():
    return datetime.datetime.now(datetime.timezone.utc)


def log(message):
    print(message, flush=True)


def parse(item):
    """A firm, not yet flown launch from an LL2 result, or None."""
    precision = (item.get('net_precision') or {}).get('name')
    status = (item.get('status') or {}).get('abbrev')
    if precision not in FIRM or status in DONE:
        return None
    return {'id': item['id'], 'kind': 'launches', 'name': item.get('name', ''), 'status': status,
            'net': datetime.datetime.fromisoformat(item['net'].replace('Z', '+00:00'))}


def train_event(found):
    """A recordable event from a starlink.passes() pass. The id is the train, so a
    recomputed time for the same pass isn't recorded twice."""
    return {'id': f'starlink-{found["train"]}', 'kind': 'starlink', 'status': 'Visible',
            'name': f'Starlink train | Starlink-train-{found["train"].replace("#", "-")}',
            'net': found['peak'], 'start': found['start'], 'end': found['end']}


def window(event):
    if event['kind'] == 'starlink':
        return event['start'] - PASS_PAD, event['end'] + PASS_PAD
    return event['net'] - BEFORE, event['net'] + AFTER


def cached_launches():
    try:
        results = json.loads(CACHE.read_text())['results']
    except (OSError, ValueError, KeyError):
        return []
    return [launch for launch in map(parse, results) if launch]


def fetch(launch):
    """The launch's latest NET and status, or the old ones if the API fails."""
    try:
        request = urllib.request.Request(API.format(launch['id']), headers={'User-Agent': 'HomeAssistant-LocalMap/1.0'})
        with urllib.request.urlopen(request, timeout=60) as response:
            item = json.load(response)
    except Exception as error:
        log(f'LL2 lookup failed: {type(error).__name__}')
        return launch
    status = (item.get('status') or {}).get('abbrev')
    return {**launch, 'status': status,
            'net': datetime.datetime.fromisoformat(item['net'].replace('Z', '+00:00'))}


def folder_name(launch):
    local = launch['net'].astimezone()
    mission = launch['name'].split('|')[-1].strip() or 'launch'
    safe = ''.join(c if c.isalnum() or c in '-_' else '-' for c in mission).strip('-')
    return f'{local:%Y-%m-%d_%H%M}_{safe}'


def docker(*args, network=False, mounts=()):
    command = ['docker', 'run', '--rm', '--user', f'{os.getuid()}:{os.getgid()}', '--cpu-shares', '256']
    if network:
        command += ['--network', 'host']
    for host, inside in mounts:
        command += ['-v', f'{host}:{inside}']
    return command + ['--entrypoint', args[0], IMAGE, *args[1:]]


def probe_duration(path):
    out = subprocess.run(docker('ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0',
                                f'/raw/{path.name}', mounts=[(path.parent, '/raw')]),
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def record(launch):
    """Records the event's window; a launch's follows slips. Returns the raw dir
    with meta.json, or None if a launch moved away before liftoff."""
    raw = RAW / folder_name(launch)
    raw.mkdir(parents=True, exist_ok=True)
    checked = now()
    log(f'Recording {launch["name"]} (T0 {launch["net"]:%H:%M:%S} UTC) into {raw}')
    while now() < window(launch)[1]:
        seconds = (window(launch)[1] - now()).total_seconds()
        part = raw / f'part-{int(time.time())}.mkv'
        # The camera delivers about 7 fps but the stream claims 25, so stamp
        # frames with arrival time or the video runs fast.
        process = subprocess.Popen(docker('ffmpeg', '-hide_banner', '-loglevel', 'error', '-use_wallclock_as_timestamps', '1',
                                          '-rtsp_transport', 'tcp',
                                          '-i', STREAM, '-t', f'{seconds:.0f}', '-c', 'copy', f'/raw/{part.name}',
                                          network=True, mounts=[(raw, '/raw')]))
        while process.poll() is None:
            time.sleep(15)
            if launch['kind'] == 'launches' and now() - checked >= datetime.timedelta(minutes=5):
                checked = now()
                moved = fetch(launch)
                if moved['net'] != launch['net']:
                    log(f'NET moved to {moved["net"]:%H:%M:%S} UTC ({moved["status"]})')
                launch = moved
                if launch['net'] - BEFORE > now() + datetime.timedelta(minutes=10):
                    # A hold or scrub: drop what was recorded and wait for the new time.
                    process.terminate()
                    process.wait()
                    shutil.rmtree(raw)
                    log('Launch slipped; recording discarded')
                    return None
        if process.returncode:
            log(f'ffmpeg exited {process.returncode}; retrying')
            time.sleep(5)
    parts = []
    for part in sorted(raw.glob('part-*.mkv')):
        try:
            duration = probe_duration(part)
        except (subprocess.CalledProcessError, ValueError):
            continue
        # The file's last write is the end of its recording.
        parts.append({'file': part.name, 'start': part.stat().st_mtime - duration, 'duration': duration})
    start, end = window(launch)
    meta = {'id': launch['id'], 'kind': launch['kind'], 'name': launch['name'], 'status': launch['status'],
            'net': launch['net'].isoformat(), 'start': start.isoformat(), 'end': end.isoformat(),
            # The trail stacks from liftoff, or from the start of a pass.
            'trail_start': launch.get('start', launch['net']).isoformat(), 'parts': parts}
    (raw / 'meta.json').write_text(json.dumps(meta, indent=1))
    return raw


def clock(offset, speed=1):
    """drawtext filters showing T-mm:ss / T+mm:ss. `offset` is the recording's start
    minus NET in seconds; `speed` is how much the video is sped up."""
    style = f"fontfile={FONT}:fontsize=28:fontcolor=white:borderw=2:bordercolor=black@0.7:x=16:y=h-th-16"
    real = f"(t*{speed}+{offset:.3f})"  # seconds from NET
    before = f"ceil(-{real})"  # seconds to go
    after = f"floor({real})"  # seconds since
    text = lambda sign, s: f"T{sign}%{{eif\\:floor({s}/60)\\:d\\:2}}\\:%{{eif\\:mod({s},60)\\:d\\:2}}"
    return (f"drawtext={style}:enable='lt({real},0)':text='{text('-', before)}',"
            f"drawtext={style}:enable='gte({real},0)':text='{text('+', after)}'")


def process(raw):
    """Builds replay.mp4, timelapse.mp4 and (at night) trail.jpg from a raw dir."""
    meta = json.loads((raw / 'meta.json').read_text())
    parts = meta['parts']
    if not parts:
        log('No usable recording')
        return
    net = datetime.datetime.fromisoformat(meta['net']).timestamp()
    # Older recordings started earlier than BEFORE; skip what's before it.
    begin = parts[0]['start']
    if meta.get('kind', 'launches') == 'launches':
        begin = max(begin, net - BEFORE.total_seconds())
    parts = [p for p in parts if p['start'] + p['duration'] > begin]
    if not parts:
        log('No usable recording')
        return
    begin = max(begin, parts[0]['start'])
    offset = begin - net
    trail_from = max(0, datetime.datetime.fromisoformat(meta.get('trail_start', meta['net'])).timestamp() - begin)
    # Joining parts drops any gap between them, so times after a gap run early.
    (raw / 'parts.txt').write_text(''.join(
        f"file '{p['file']}'\n" + (f"inpoint {begin - p['start']:.3f}\n" if i == 0 and begin > p['start'] else '')
        for i, p in enumerate(parts)))
    out = MEDIA / meta.get('kind', 'launches') / raw.name
    out.mkdir(parents=True, exist_ok=True)
    mounts = [(raw, '/raw'), (out, '/out')]
    # Is it dark at T0? Decides the night treatment and the trail.
    luma = subprocess.run(docker('ffmpeg', '-hide_banner', '-ss', f'{max(0, -offset):.1f}', '-f', 'concat', '-i',
                                 '/raw/parts.txt', '-frames:v', '1', '-vf', 'signalstats,metadata=print', '-f', 'null', '-',
                                 mounts=mounts), capture_output=True, text=True).stderr
    yavg = next((float(line.split('=')[1]) for line in luma.splitlines() if 'signalstats.YAVG=' in line), 255.0)
    night = yavg < NIGHT_LUMA
    # Chroma-heavy denoise as in the daily timelapse; it keeps night video small.
    graph = [f"[0:v]hqdn3d=3:10:6:15,split={3 if night else 2}[r][t]{'[s]' if night else ''}",
             f"[r]{clock(offset)},format=yuv420p[replay]",
             # At night, lagfun leaves a fading streak behind a plume or satellite.
             # It keeps each pixel's brightest value, chroma noise included, which
             # turns the (already purple) night picture into purple grain; the night
             # timelapse and trail are luma only.
             f"[t]tmix=frames={SPEED},setpts=PTS/{SPEED},fps=30{',format=gray,lagfun=decay=0.97' if night else ''},"
             f"{clock(offset, SPEED)},format=yuv420p[lapse]"]
    outputs = ['-map', '[replay]', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '26', '-movflags', '+faststart', '/out/.replay.mp4',
               '-map', '[lapse]', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '24', '-movflags', '+faststart', '/out/.timelapse.mp4']
    if night:
        # Every frame from liftoff (or the pass's start) stacked by brightest pixel:
        # the whole arc in one picture. Written every 10 s and overwritten, so the
        # file ends as the final stack.
        # Averaging 8 frames first keeps the stack from collecting the noise peaks.
        graph.append(f"[s]trim=start={trail_from:.3f},tmix=frames=8,hqdn3d=4:4:6:6,format=gray,"
                     f"lagfun=decay=1,fps=0.1[trail]")
        outputs += ['-map', '[trail]', '-q:v', '2', '-update', '1', '/out/.trail.jpg']
    log(f'Processing {raw.name} (T0 luma {yavg:.0f}, {"night" if night else "day"})')
    subprocess.run(docker('ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'concat', '-i', '/raw/parts.txt',
                          '-filter_complex', ';'.join(graph), *outputs, mounts=mounts), check=True)
    for name in ('replay.mp4', 'timelapse.mp4', 'trail.jpg'):
        if (out / f'.{name}').exists():
            (out / f'.{name}').replace(out / name)
    log(f'Done: {out}')


def prune():
    for root, days in ((RAW, RAW_DAYS), (MEDIA / 'launches', OUT_DAYS), (MEDIA / 'starlink', OUT_DAYS)):
        cutoff = time.time() - days * 86400
        for folder in root.glob('*/'):
            if folder.stat().st_mtime < cutoff:
                shutil.rmtree(folder, ignore_errors=True)


def train_passes(home, found):
    """Recomputes visible Starlink train passes and hands them to Home Assistant.
    Returns the passes, or `found` (the last good ones) if this fails."""
    try:
        records = starlink.load(STARLINK_ORBITS)
        trains = starlink.trains(records, now())
        found = starlink.passes(trains, home, now() - datetime.timedelta(minutes=30))
        result = starlink.summary(found, trains, now())
    except Exception as error:  # a bad orbit file mustn't stop launch recording
        log(f'Starlink prediction failed: {type(error).__name__}: {error}')
        result = starlink.summary(found, [], now(), error=type(error).__name__)
    temporary = STARLINK_JSON.with_suffix('.tmp')
    temporary.write_text(json.dumps(result))
    temporary.replace(STARLINK_JSON)
    return found


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    for kind in ('launches', 'starlink'):
        (MEDIA / kind).mkdir(parents=True, exist_ok=True)
    home = starlink.Observer(float(os.environ['HOME_LAT']), float(os.environ['HOME_LON']))
    known = {}  # id -> latest launch, from the cache or our own lookups
    checked = {}
    found, predicted = [], None
    # id -> end of its last recording; an event starting well after that (a
    # launch after a scrub, a train's next orbit) records again
    recorded = {}
    for meta in RAW.glob('*/meta.json'):
        try:
            item = json.loads(meta.read_text())
            recorded[item['id']] = datetime.datetime.fromisoformat(item['end'])
        except (OSError, ValueError, KeyError):
            pass
    while True:
        if predicted is None or now() - predicted >= datetime.timedelta(minutes=10):
            found, predicted = train_passes(home, found), now()
        for launch in cached_launches():
            if launch['id'] not in checked:
                known[launch['id']] = launch
        for launch_id, launch in list(known.items()):
            until = launch['net'] - now()
            if datetime.timedelta(0) < until <= datetime.timedelta(minutes=30) and \
                    now() - checked.get(launch_id, now() - datetime.timedelta(hours=1)) >= datetime.timedelta(minutes=5):
                checked[launch_id] = now()
                known[launch_id] = fetch(launch)
            if now() > window(known[launch_id])[1]:
                known.pop(launch_id)
        # Only passes that cross the camera's view are worth recording.
        for event in list(known.values()) + [train_event(p) for p in found if p['in_camera']]:
            start, end = window(event)
            if event['id'] in recorded and start < recorded[event['id']] + datetime.timedelta(minutes=45):
                continue
            if start <= now() < end:
                raw = record(event)
                if raw:
                    recorded[event['id']] = datetime.datetime.fromisoformat(json.loads((raw / 'meta.json').read_text())['end'])
                    try:
                        process(raw)
                    except subprocess.CalledProcessError as error:
                        log(f'Processing failed: {error}')
                break  # time has passed; re-read the schedule
        prune()
        time.sleep(30)


if __name__ == '__main__':
    if sys.argv[1:2] == ['process']:
        process(pathlib.Path(sys.argv[2]).resolve())
    else:
        main()
