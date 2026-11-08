# Cameras

Two cameras on the HA laptop (`HA_HOST`), installed with `bash install.sh`
from the Mac. It copies everything here to `~/go2rtc`, starts both go2rtc
containers, enables the systemd timers and installs the HA packages.

- **Office window**: the HEAD USB action cam in PC-camera mode, looking out
  the office window, due west (aimed 2026-10-28 for sunsets). Over USB it
  only offers 1280x720 MJPEG, at about 7 fps. Shown on the Overview under
  Current Conditions.
- **Baby monitor**: the laptop's built-in webcam and microphone. Shown on
  the BabySteps dashboard, and only while the lid is open
  (`binary_sensor.laptop_lid`). The analyzer (below) estimates sleep from it.

## go2rtc: two instances

- `go2rtc-capture` (`capture.yaml`, loopback API :1985, RTSP :8556) owns the
  devices and opens them only while someone pulls a stream. It encodes the baby
  monitor (H.264 + Opus) in one ffmpeg, using H.264 on the Intel GPU (VAAPI).
  Both containers use the `-hardware` go2rtc image for that.
- `go2rtc` (`go2rtc.yaml`, API :1984, RTSP :8554, WebRTC :8555) is the one HA
  talks to. It re-streams from the capture instance over RTSP and transcodes the
  office camera to H.264.

They are split because an active v4l2 (or exec / `ffmpeg:device`) producer has
no `url` in `/api/streams`, and HA's go2rtc client (0.4.0, HA 2026.10)
rejects the whole list. When one instance did both, live view failed whenever
a camera was already in use.

HA's `configuration.yaml` points its go2rtc integration at the container
instead of starting its own copy, and lists the media folders:

```yaml
homeassistant:
  media_dirs:
    local: /config/media         # office camera snapshots + timelapses
    pictures: /media/pictures    # ~/Pictures, mounted read-only
    music: /media/music          # ~/Music, mounted read-only
go2rtc:
  url: http://127.0.0.1:1984
stream:
```

`setup-homeassistant.sh` adds the read-only Pictures and Music mounts.

## Snapshots and timelapse

- `office-camera-snapshot.timer` runs `snapshot.sh` each minute. It writes
  `/config/media/office-camera/latest.jpg`, which the Overview card paints
  before live video connects, plus `~/office-camera/frames/<date>/HHMM.jpg`.
  Junk first frames and frames cut short (no JPEG start or end marker) are
  dropped.
- `office-camera-timelapse.timer` runs `timelapse.sh` at 00:10. It turns
  yesterday's frames into `/config/media/office-camera/timelapse/<date>.mp4`
  (about 24 s: 60 frames a second, played at 30 fps with 3-frame blending),
  using the go2rtc image's ffmpeg because the host has none. Night frames
  (average brightness under 85) get their noise floor dropped to black and
  most colour removed, which keeps a day's video near 8 MB instead of 70+.
  Every frame is decoded first and any that fail are left out, since one
  damaged JPEG shows as a grey, green or purple smear (about 3 minutes a day).
  It keeps 2 days of frames (about 190 MB a day) and 14 days of videos.

The cards load media through signed `media_source` URLs, not `/local`, which
anyone can reach through Funnel without logging in.

## What the office camera sees

From landmarks (bearings from home): Fireworks Hill (269°, 1.5 km) is at
the centre, Tarantula Hill (297°, 2.4 km) at x≈1035, and the northern Santa
Monica Mountains fill the left. Between the two hills is the Conejo Valley
Botanic Garden ridge (287.5°), and Vandenberg's SLC-4E (287.1°, 168 km) is
directly behind it. That is about 17 px a degree: the frame spans roughly
233°–305° and from the ridge (about 3°) to 21° up. These are
`CAMERA_*` in `starlink.py`; re-measure them if the camera moves.

For a typical Falcon 9 ascent, the rocket should clear the ridge at about
T+1:10 just right of centre, climb up and left, and leave the frame between
T+2:20 (out the top) and T+3:20 (top left). A twilight plume spreads much
wider than that.

## Launch and Starlink recordings (`launch_recorder.py`, `starlink.py`)

`office-camera-launches.service` records the office window around every
Vandenberg launch with a firm time and every visible Starlink train pass,
then publishes three files to
`/config/media/office-camera/{launches,starlink}/<local date_time>_<name>/`
(Media → My media → office-camera):

- `replay.mp4`: real time, with a T-mm:ss / T+mm:ss clock in the corner.
- `timelapse.mp4`: 8x, frames blended; at night it is black and white and
  `lagfun` leaves a fading streak behind the plume.
- `trail.jpg` (night only, black and white): every frame from liftoff,
  averaged in groups of 8 and then stacked by brightest pixel, so the whole arc
  is in one picture. Stacking colour picks up the chroma noise and turns the
  picture purple.

Launch times come from the HA Vandenberg sensor's cache
(`/config/.vandenberg-launches.json`). From 30 minutes before NET it also
asks Launch Library 2 for that launch every 5 minutes, which follows holds
(a slip of more than 10 minutes during recording discards it and waits). It
records the camera's own MJPEG from the capture instance
(`rtsp://127.0.0.1:8556/office_window`) with `-c copy` and wall-clock
timestamps: the camera delivers 7–10 fps although the stream says more, so
without them the video runs fast.

The window runs from T-1 to T+10 min (`BEFORE`, `AFTER`). On the first
recording (Starlink 15-18, Oct 30 2026) the minute snapshots caught the rocket
just over the ridge at T+1:26, as predicted below, but the video showed it at
T+12:00 to T+13:50. It was recorded from `office_window_h264`, go2rtc's
transcode, which the dashboard's live view had kept running all evening and
which had fallen about 11 minutes behind; a fresh one is in sync. Don't
record from the transcode. Raw MJPEG recordings (about 30 MB a minute in
daylight) are kept 30 days in `~/office-camera/launches` on /data
so they can be reprocessed while tuning:
`python3 ~/go2rtc/launch_recorder.py process ~/office-camera/launches/<dir>`.
Published files are kept 90 days. Processing a 20-minute window takes about
10 minutes. Logs: `journalctl -u office-camera-launches`. Tests:
`python3 -m unittest test_launch_recorder test_starlink` (needs `sgp4`).

### Starlink trains

For a week or two after launch, a Starlink batch flies low (about 270–370
km) in a tight line that is easy to see by eye. Every 10 minutes the service
reads CelesTrak's recent-launch orbits (`GROUP=last-30-days`, downloaded at
most every 6 hours into `~/office-camera/starlink-orbits.json`). It treats a
batch as a train when its median altitude is under 400 km and at least 10
satellites are chained with neighbours under 1500 km (about 3 minutes)
apart; a batch that has spread out is skipped. SGP4 (`python3-sgp4`, matched
against Skyfield to 0.002°) then finds the next 36 hours of passes that are
15° or more up, in sunlight, with the sun 6° or more below the horizon here.
These only happen in the hour or two after sunset or before sunrise, and
many fresh trains have none for days.

The passes go to `/config/.starlink-trains.json`, read by
`sensor.starlink_trains` (`starlink_trains.yaml`), and
`automation.starlink_train_announcement` speaks on the tablet 5 minutes
before the next one (05:00–21:00, like the launch announcement). Each pass
that crosses the camera's view is recorded (passes seen only low in
that view are recorded but not announced), from a minute before it starts to
a minute after it ends; the
clock's T0 is its highest point. Home coordinates reach the service through
`~/go2rtc/home.env`, written by `install.sh` from `.env`. The thresholds
are guesses until we see a few trains.

## Sleep tracking (`analyzer/`)

`baby-monitor-analyzer` reads the baby monitor stream from the capture
instance while the lid is open and `switch.baby_monitoring` is on. It serves
`GET /state` on 127.0.0.1:8791, which HA polls every 5 s into
`sensor.baby_monitor_analysis` (details; excluded from the recorder) and
`sensor.baby_sleep` (state history). Running continuously keeps the webcam
light on. It uses about 20% of a core, and the GPU encode about 18%.

- **Baby in frame**: SSD-MobileNet v1 (COCO person) every 5 s. It can't tell a
  baby from an adult; set `BABY_ROI` in `compose.yaml` to the crib's area
  (left, top, right, bottom as fractions) to ignore the rest of the room.
- **Movement**: frame differencing at 4 fps on 320x180 grey frames. A
  movement is a burst after 2 s of stillness.
- **Crying and fussing**: YAMNet on 0.975 s windows every 0.5 s. A cry is
  classes 19/20 (Crying, sobbing; Baby cry, infant cry) at 0.35 or above.
  Fussing is Whimper/Wail at 0.2 or above, or a weak cry score. Sounds within
  8 s of each other are one episode; episodes under 1.5 s are ignored. On
  ESC-50 crying-baby clips, 3 of 4 scored 0.74 to 0.99, and one read as speech.
- **Sleep**: awake → settling (3-minute average of 4 or fewer movements a
  minute, no crying) → asleep after 8 minutes of 1 or fewer movements a
  minute. Sleep start is backdated to when that quiet began. They wake on
  15 s of crying in a minute, or 8 or more movements a minute over 2
  minutes, so brief stirs don't count. "Took to fall asleep" runs from being
  put down, or from the last waking.
- **Logging to BabySteps**: the analyzer keeps the last 20 completed sleeps
  (`sleeps` in `/state`). The Sleep card has **Log** on each sleep and **Log
  all sleeps**, which goes oldest first and stops at the first refusal. Both
  call `script.baby_monitor_log_sleep`, which sends a `sleep` entry
  (`startedAt`/`endedAt`) through `shell_command.babysteps_log`. Only a sleep
  BabySteps accepts is marked logged (`POST /sleeps/<id>/logged`); a refusal's
  reason shows under the sleep.
- With the picture too dark (mean grey under 12, since the webcam has no
  night vision), movement can't be judged. The current estimate holds and
  crying is still detected. A dim night light makes it work at night.
- Thresholds are constants at the top of `analyzer.py`, untuned against a
  real baby. Tests: `python3 -m unittest test_analyzer` in `analyzer/`.

## Notes

- The cards live in `scripts/local-map/overview-widgets.js`
  (`office-camera-card`, `baby-monitor-card`). They use HA's
  `ha-camera-stream`, which only works inside the HA element tree (Lit
  context).
- HA's WebRTC player receives the baby monitor's audio track but never
  attaches it, so the card plays it through its own `<audio>` element after
  you tap Listen.
- The built-in webcam has no night vision; in a dark room the picture is
  black.
