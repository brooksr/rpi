"""Baby monitor analyzer for the BabySteps dashboard.

Watches the laptop webcam and microphone (the go2rtc capture stream) and
estimates whether the baby is in frame, how much they move, crying and fussing
(YAMNet), and when sleep started. Home Assistant polls GET /state
(packages/baby_monitor.yaml); POST /monitoring {"on": false} pauses it.
"""
import collections
import datetime
import json
import os
import pathlib
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

STREAM = os.environ.get('STREAM', 'rtsp://127.0.0.1:8556/baby_monitor')
LID = pathlib.Path(os.environ.get('LID_STATE', '/host/lid/state'))
DATA = pathlib.Path(os.environ.get('DATA_DIR', '/data'))
MODELS = pathlib.Path(os.environ.get('MODELS_DIR', '/models'))
PORT = int(os.environ.get('PORT', '8791'))
# Crib area as fractions of the frame (left, top, right, bottom). Motion and
# people outside it are ignored, so an adult walking past doesn't count.
ROI = tuple(float(v) for v in os.environ.get('BABY_ROI', '0,0,1,1').split(','))

# Movements are bursts of motion after at least STILL_GAP seconds of stillness.
FPS = 4
MOTION_PIXEL = 18                 # grey-level change that counts as motion
MOTION_FRACTION = float(os.environ.get('MOTION_FRACTION', '0.002'))  # of the crib area
STILL_GAP = 2.0
DARK = 12                         # mean grey level below which video can't be judged
SETTLE_MPM = 4                    # 3-minute average movements/min at or below: settling
SLEEP_MPM = 1                     # movements in the last minute at or below ...
SLEEP_ACTIVITY = 0.03             # ... and moving this little of the time ...
SLEEP_AFTER = 8 * 60              # ... for this long: asleep since the quiet began
WAKE_MPM = 8                      # 2-minute average at or above wakes them
WAKE_CRY = 15                     # seconds of crying in a minute that wake them
ABSENT_AFTER = 10 * 60            # unseen and still this long: out of the crib
LONG_PAUSE = 30 * 60              # paused longer than this ends the session
SLEEPS_KEPT = 20                  # completed sleeps listed for logging to BabySteps
DETECT_EVERY = 5
PERSON_SCORE = 0.4
WINDOW, HOP = 15600, 8000         # YAMNet: 0.975 s windows at 16 kHz, every 0.5 s
CRY_SCORE = 0.35
FUSS_SCORE = 0.2
EPISODE_GAP = 8                   # sounds this close together are one episode
EPISODE_MIN = 1.5
CRY_IDS = (19, 20)                # Crying, sobbing; Baby cry, infant cry (yamnet_class_map.csv)
FUSS_IDS = (21, 22)               # Whimper; Wail, moan


def iso(t):
    return None if t is None else datetime.datetime.fromtimestamp(t, datetime.timezone.utc).isoformat(timespec='seconds')


def roi_slices(height, width):
    left, top, right, bottom = ROI
    rows = slice(int(top * height), max(int(bottom * height), int(top * height) + 1))
    cols = slice(int(left * width), max(int(right * width), int(left * width) + 1))
    return rows, cols


def in_roi(box):
    """SSD boxes are [ymin, xmin, ymax, xmax], normalized; the centre must be in the crib."""
    y, x = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    left, top, right, bottom = ROI
    return left <= x <= right and top <= y <= bottom


def blur(image):
    padded = np.pad(image, 1, mode='edge')
    height, width = image.shape
    return sum(padded[i:i + height, j:j + width] for i in range(3) for j in range(3)) // 9


class MotionDetector:
    """Frame differencing on blurred grey frames, ignoring exposure shifts."""

    def __init__(self):
        self.previous = None

    def __call__(self, gray):
        image = blur(gray[roi_slices(*gray.shape)].astype(np.int16))
        bright = float(image.mean())
        previous, self.previous = self.previous, image
        if previous is None:
            return False, bright
        change = image - previous - int(round(bright - float(previous.mean())))
        return float((np.abs(change) > MOTION_PIXEL).mean()) >= MOTION_FRACTION, bright


class Tracker:
    """Presence, movement, sound and sleep state. Every method takes the time,
    so tests can replay a night in milliseconds."""

    def __init__(self):
        self.lock = threading.RLock()
        self.state = 'absent'
        self.in_frame_at = self.awake_since = self.settling_at = self.asleep_at = self.quiet_since = None
        self.last_seen = self.last_motion = self.last_woke_at = self.last_frame = None
        self.last_sleep = self.last_cry = self.last_fuss = None
        self.cry = self.fuss = None
        self.movements = collections.deque()
        self.frames = collections.deque()
        self.cry_samples = collections.deque()
        self.minutes = collections.OrderedDict()
        self.events = collections.deque(maxlen=40)
        self.sleeps = []                # completed sleeps, oldest first; BabySteps logging marks them
        self.video = 'none'
        self.paused_at = None
        self.pause_reason = None
        self.monitoring = True

    def event(self, kind, t, **extra):
        self.events.append({'type': kind, 'at': iso(t), **extra})

    def bucket(self, t):
        minute = int(t // 60) * 60
        if minute not in self.minutes:
            self.minutes[minute] = {'movements': 0, 'cry': 0.0}
            while len(self.minutes) > 60:
                self.minutes.popitem(last=False)
        return self.minutes[minute]

    def frame(self, t, moving, bright):
        with self.lock:
            self.last_frame = t
            if bright < DARK:
                self.video = 'dark'
                return
            self.video = 'ok'
            self.frames.append((t, moving))
            if moving:
                if self.last_motion is None or t - self.last_motion >= STILL_GAP:
                    self.movements.append(t)
                    self.bucket(t)['movements'] += 1
                self.last_motion = t

    def detection(self, t, found):
        with self.lock:
            if not found:
                return
            self.last_seen = t
            if self.state == 'absent':
                self.state = 'awake'
                self.in_frame_at = self.awake_since = t
                self.event('in_frame', t)

    def episode(self, current, active, t, kind):
        if active:
            if current and t - current['end'] <= EPISODE_GAP:
                current['end'] = t
                return current
            if current:
                self.close(kind, current)
            return {'start': t, 'end': t}
        if current and t - current['end'] > EPISODE_GAP:
            self.close(kind, current)
            return None
        return current

    def close(self, kind, episode):
        if episode['end'] - episode['start'] < EPISODE_MIN:
            return
        record = {'start': episode['start'], 'end': episode['end']}
        setattr(self, f'last_{kind}', record)
        self.event(kind, episode['start'], seconds=round(episode['end'] - episode['start']))

    def audio(self, t, cry, fuss):
        with self.lock:
            crying = cry >= CRY_SCORE
            fussing = not crying and max(cry, fuss) >= FUSS_SCORE
            if crying:
                self.cry_samples.append(t)
                self.bucket(t)['cry'] += HOP / 16000
            self.cry = self.episode(self.cry, crying, t, 'cry')
            self.fuss = self.episode(self.fuss, fussing, t, 'fuss')

    def ongoing(self, episode, t):
        return bool(episode) and t - episode['end'] <= 3 and episode['end'] - episode['start'] >= EPISODE_MIN

    def rates(self, t):
        for queue, keep in ((self.movements, 180), (self.cry_samples, 60)):
            while queue and queue[0] < t - keep:
                queue.popleft()
        while self.frames and self.frames[0][0] < t - 60:
            self.frames.popleft()
        per_minute = lambda span: sum(1 for m in self.movements if m >= t - span) / (span / 60)
        activity = sum(moving for _, moving in self.frames) / len(self.frames) if self.frames else 0.0
        return per_minute(60), per_minute(120), per_minute(180), activity, len(self.cry_samples) * HOP / 16000

    def wake(self, t, why):
        self.last_sleep = {'start': self.asleep_at, 'end': t,
                           'fell_asleep_seconds': round(self.asleep_at - self.awake_since) if self.awake_since else None}
        self.sleeps = [*self.sleeps, {'id': str(int(self.asleep_at)), **self.last_sleep, 'logged': False}][-SLEEPS_KEPT:]
        self.event('woke', t, why=why, slept_seconds=round(t - self.asleep_at))
        self.state, self.asleep_at, self.settling_at, self.quiet_since = 'awake', None, None, None
        self.last_woke_at = self.awake_since = t

    def tick(self, t):
        with self.lock:
            if self.paused_at is not None:
                return
            mpm1, mpm2, mpm3, activity, cry_seconds = self.rates(t)
            video_ok = self.video == 'ok' and self.last_frame is not None and t - self.last_frame < 10
            crying = self.ongoing(self.cry, t)
            if video_ok:
                quiet = mpm1 <= SLEEP_MPM and activity <= SLEEP_ACTIVITY and not crying and not self.ongoing(self.fuss, t)
                if quiet and self.quiet_since is None:
                    # The one-minute measure lags; the quiet began about a minute ago.
                    self.quiet_since = max(t - 60, self.awake_since or t)
                elif not quiet:
                    self.quiet_since = None
            elif crying:
                self.quiet_since = None
            if self.state == 'asleep':
                if cry_seconds >= WAKE_CRY:
                    self.wake(t, 'crying')
                elif video_ok and mpm2 >= WAKE_MPM:
                    self.wake(t, 'moving')
                return
            if self.state == 'absent':
                return
            unseen = self.last_seen is None or t - self.last_seen >= ABSENT_AFTER
            still = self.last_motion is None or t - self.last_motion >= ABSENT_AFTER
            if unseen and still:
                self.event('left', t)
                self.state, self.in_frame_at, self.awake_since, self.settling_at, self.quiet_since = 'absent', None, None, None, None
                return
            if self.quiet_since is not None and t - self.quiet_since >= SLEEP_AFTER:
                self.state, self.asleep_at = 'asleep', self.quiet_since
                self.event('asleep', self.asleep_at, fell_asleep_seconds=round(self.asleep_at - self.awake_since))
            elif self.state == 'awake' and video_ok and t - self.awake_since >= 180 and mpm3 <= SETTLE_MPM and cry_seconds == 0:
                self.state, self.settling_at = 'settling', max(t - 180, self.awake_since)
                self.event('settling', self.settling_at)
            elif self.state == 'settling' and (crying or (video_ok and mpm3 > SETTLE_MPM * 1.5)):
                self.state, self.settling_at = 'awake', None

    def pause(self, t, reason):
        with self.lock:
            self.pause_reason = reason
            if self.paused_at is None:
                self.paused_at = t
                self.video = 'none'

    def resume(self, t):
        with self.lock:
            if self.paused_at is None:
                return
            if t - self.paused_at > LONG_PAUSE and self.state != 'absent':
                # Nobody knows what happened meanwhile: end the session when the pause began.
                if self.state == 'asleep':
                    self.wake(self.paused_at, 'monitor paused')
                self.event('left', self.paused_at, why='monitor paused')
                self.state, self.in_frame_at, self.awake_since, self.settling_at, self.quiet_since = 'absent', None, None, None, None
            self.paused_at = self.pause_reason = None
            self.frames.clear()

    def snapshot(self, t):
        with self.lock:
            self.tick(t)
            mpm1, _, mpm3, activity, cry_seconds = self.rates(t)
            # An episode still going counts as the latest once it is long enough.
            latest = lambda live, done: live if live and live['end'] - live['start'] >= EPISODE_MIN else done
            cry, fuss = latest(self.cry, self.last_cry), latest(self.fuss, self.last_fuss)
            minute = int(t // 60) * 60
            history = [self.minutes.get(minute - 60 * i, {'movements': 0, 'cry': 0.0}) for i in range(59, -1, -1)]
            return {
                'state': 'paused' if self.paused_at is not None else self.state,
                'paused_reason': self.pause_reason,
                'session_state': self.state,
                'video': self.video,
                'monitoring': self.monitoring,
                'in_frame_at': iso(self.in_frame_at),
                'awake_since': iso(self.awake_since),
                'settling_at': iso(self.settling_at),
                'asleep_at': iso(self.asleep_at),
                'fell_asleep_seconds': round(self.asleep_at - self.awake_since) if self.asleep_at and self.awake_since else None,
                'last_sleep': {k: iso(v) if k in ('start', 'end') else v for k, v in self.last_sleep.items()} if self.last_sleep else None,
                'last_woke_at': iso(self.last_woke_at),
                'last_seen_at': iso(self.last_seen),
                'crying': self.ongoing(self.cry, t),
                'fussing': self.ongoing(self.fuss, t),
                'last_cry': {'start': iso(cry['start']), 'end': iso(cry['end']), 'seconds': round(cry['end'] - cry['start'])} if cry else None,
                'last_fuss': {'start': iso(fuss['start']), 'end': iso(fuss['end']), 'seconds': round(fuss['end'] - fuss['start'])} if fuss else None,
                'cry_seconds_last_minute': round(cry_seconds),
                'movements_per_minute': round(mpm1),
                'movements_per_minute_3m': round(mpm3, 1),
                'activity': round(activity, 3),
                'moving': self.last_motion is not None and t - self.last_motion < 2,
                'minutes': [[h['movements'], round(h['cry'])] for h in history],
                'events': list(self.events)[-12:],
                'sleeps': [{'id': s['id'], 'start': iso(s['start']), 'end': iso(s['end']), 'seconds': round(s['end'] - s['start']),
                            'fell_asleep_seconds': s['fell_asleep_seconds'], 'logged': s['logged']} for s in reversed(self.sleeps)],
            }

    # Persisted so a restart keeps the last sleep, cry and the current session.
    KEEP = ('state', 'in_frame_at', 'awake_since', 'settling_at', 'asleep_at', 'last_seen', 'last_woke_at', 'sleeps',
            'last_sleep', 'last_cry', 'last_fuss', 'monitoring')

    def mark_logged(self, sleep_id):
        with self.lock:
            for sleep in self.sleeps:
                if sleep['id'] == sleep_id:
                    sleep['logged'] = True
                    return True
            return False

    def save(self, path, t):
        with self.lock:
            data = {key: getattr(self, key) for key in self.KEEP}
            data.update(saved_at=t, events=list(self.events))
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data))
        tmp.replace(path)

    def load(self, path, t):
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            return
        with self.lock:
            for key in self.KEEP:
                if key in data:
                    setattr(self, key, data[key])
            self.events.extend(data.get('events', []))
            if self.state != 'absent':
                # Treat the downtime as a pause; a long one ends the session.
                self.paused_at = data.get('saved_at', t)
                self.pause_reason = 'restarted'


class PersonDetector:
    """SSD-MobileNet v1 (COCO); class 1 is a person, which includes babies."""

    def __init__(self, path):
        import onnxruntime
        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = 2
        options.add_session_config_entry('session.intra_op.allow_spinning', '0')  # idle between runs
        self.session = onnxruntime.InferenceSession(str(path), options, providers=['CPUExecutionProvider'])

    def __call__(self, rgb):
        boxes, classes, scores, count = self.session.run(None, {'inputs': rgb[None]})
        return any(int(c) == 1 and s >= PERSON_SCORE and in_roi(b)
                   for b, c, s in zip(boxes[0][:int(count[0])], classes[0], scores[0]))


class SoundClassifier:
    """YAMNet: crying and fussing scores for one 0.975 s window."""

    def __init__(self, path):
        from ai_edge_litert.interpreter import Interpreter
        self.interpreter = Interpreter(str(path), num_threads=1)
        self.interpreter.allocate_tensors()
        self.input = self.interpreter.get_input_details()[0]['index']
        self.output = self.interpreter.get_output_details()[0]['index']

    def __call__(self, wave):
        self.interpreter.set_tensor(self.input, wave.astype(np.float32))
        self.interpreter.invoke()
        scores = self.interpreter.get_tensor(self.output)[0]
        return float(max(scores[i] for i in CRY_IDS)), float(max(scores[i] for i in FUSS_IDS))


def blocked(tracker):
    if not tracker.monitoring:
        return 'monitoring off'
    try:
        return None if 'open' in LID.read_text() else 'lid closed'
    except OSError:
        return None


def watch(tracker):
    import av
    motion = MotionDetector()
    detect = PersonDetector(MODELS / 'ssd_mobilenet_v1_12.onnx')
    classify = SoundClassifier(MODELS / 'yamnet.tflite')
    while True:
        reason = blocked(tracker)
        if reason:
            tracker.pause(time.time(), reason)
            time.sleep(5)
            continue
        try:
            with av.open(STREAM, options={'rtsp_transport': 'tcp'}, timeout=15) as container:
                tracker.resume(time.time())
                video, sound = container.streams.video[0], container.streams.audio[0]
                video.thread_count = 2  # PyAV otherwise starts a decoder thread per core
                resampler = av.AudioResampler(format='flt', layout='mono', rate=16000)
                samples = np.zeros(0, np.float32)
                next_frame = next_detect = next_check = 0.0
                motion.previous = None
                for packet in container.demux(video, sound):
                    for frame in packet.decode():
                        now = time.time()
                        if packet.stream is video:
                            if now >= next_frame:
                                next_frame = now + 1 / FPS
                                tracker.frame(now, *motion(frame.to_ndarray(format='gray', width=320, height=180)))
                            if now >= next_detect:
                                next_detect = now + DETECT_EVERY
                                tracker.detection(now, detect(frame.to_ndarray(format='rgb24', width=480, height=270)))
                        else:
                            for chunk in resampler.resample(frame):
                                samples = np.concatenate([samples, chunk.to_ndarray().reshape(-1)])
                            while len(samples) >= WINDOW:
                                tracker.audio(now, *classify(samples[:WINDOW]))
                                samples = samples[HOP:]
                    if time.time() >= next_check:
                        next_check = time.time() + 5
                        tracker.tick(time.time())
                        if blocked(tracker):
                            break
        except Exception as error:  # noqa: BLE001 - keep watching through stream drops
            print(f'stream: {error!r}', flush=True)
            tracker.pause(time.time(), 'no signal')
            time.sleep(5)


def serve(tracker, path):
    class Handler(BaseHTTPRequestHandler):
        def reply(self, body, status=200):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == '/state':
                self.reply(tracker.snapshot(time.time()))
            elif self.path == '/monitoring':
                self.reply({'on': tracker.monitoring})
            else:
                self.reply({'error': 'not found'}, 404)

        def do_POST(self):
            # POST /sleeps/<id>/logged, once HA has saved that sleep in BabySteps.
            parts = self.path.strip('/').split('/')
            if len(parts) == 3 and parts[0] == 'sleeps' and parts[2] == 'logged':
                if not tracker.mark_logged(parts[1]):
                    return self.reply({'error': 'no such sleep'}, 404)
                tracker.save(path, time.time())
                return self.reply({'id': parts[1], 'logged': True})
            if self.path != '/monitoring':
                return self.reply({'error': 'not found'}, 404)
            try:
                on = bool(json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}')['on'])
            except (ValueError, KeyError):
                return self.reply({'error': 'expected {"on": true|false}'}, 400)
            tracker.monitoring = on
            tracker.save(path, time.time())
            self.reply({'on': on})

        def log_message(self, *args):
            pass

    ThreadingHTTPServer(('127.0.0.1', PORT), Handler).serve_forever()


def main():
    path = DATA / 'state.json'
    tracker = Tracker()
    tracker.load(path, time.time())
    threading.Thread(target=serve, args=(tracker, path), daemon=True).start()
    threading.Thread(target=watch, args=(tracker,), daemon=True).start()
    while True:
        time.sleep(30)
        tracker.save(path, time.time())


if __name__ == '__main__':
    main()
