#!/usr/bin/env bash
# Builds a day's office window timelapse (a frame a minute at 60 fps, about 24 s)
# into HA's media folder, then prunes.
set -euo pipefail
day="${1:-$(date -d yesterday +%F)}"
frames="${HOME}/office-camera/frames/${day}"
out="${HOME}/homeassistant/media/office-camera/timelapse"
mkdir -p "${out}"
# The camera's auto-gain turns the night sky into coloured noise, which made a
# day's video 70+ MB. Blending 3 frames and denoising (chroma hardest) calms it;
# then frames whose average brightness is under 85 (night sits at 60-70, day at
# 130-165) drop the noise floor to black and lose most colour, fading back to
# the untouched picture by 115.
mask='clip((115-lum(0\,0))*255/30\,0\,255)'
filter="format=yuv444p,tmix=frames=3,fps=30,hqdn3d=4:12:8:20,split=3[day][raw][m];\
[raw]lutyuv=y=max(0\,val-60)*255/195:u=128+(val-128)*0.3:v=128+(val-128)*0.3[night];\
[m]scale=1:1:flags=area,geq=lum=${mask}:cb=${mask}:cr=${mask},scale=1280:720:flags=neighbor[mask];\
[day][night][mask]maskedmerge,format=yuv420p"
if compgen -G "${frames}/*.jpg" >/dev/null; then
  # The host has no ffmpeg; the go2rtc image does.
  docker run --rm --user "$(id -u):$(id -g)" --cpu-shares 256 --entrypoint ffmpeg \
    -v "${frames}:/frames:ro" -v "${out}:/out" alexxit/go2rtc:1.9.14-hardware \
    -hide_banner -loglevel error -y -framerate 60 -pattern_type glob -i '/frames/*.jpg' \
    -filter_complex "${filter}" \
    -c:v libx264 -preset veryfast -crf 28 -movflags +faststart "/out/.${day}.mp4"
  mv "${out}/.${day}.mp4" "${out}/${day}.mp4"
fi
find "${HOME}/office-camera/frames" -mindepth 1 -maxdepth 1 -type d -mtime +2 -exec rm -rf {} +
find "${out}" -name '*.mp4' -mtime +14 -delete
