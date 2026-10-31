# Office music playback

Deployed to `~/music-assistant` on the HA laptop (`HA_HOST`); initial server version 2.10.8.

- UI: `http://HA_IP:8095` on the home network.
- Audio stream server: port 8097. Host networking supports player discovery.
- YouTube Music PO helper: `http://127.0.0.1:4416`, deployed version 1.2.1.
- Music Assistant data and account credentials persist in `./data` on the host.
  Do not commit that directory or copy authentication cookies into this repo.

Office's EchoMuse Sendspin section is enabled with pairing required
(`sendspinEnabled=true`, `sendspinUnpaired=false`). Other config sections still
follow the existing fleet settings. Music Assistant discovered Office as
`up51691b34`. Pairing and YouTube Music authentication are complete.

For future re-pairing, use **Show pairing token** under
EchoMuse → Office → Config → Sendspin. The token belongs only in the pairing
form. The YouTube Music source uses the paid account's login cookie and
the helper URL above; use the current provider instructions for obtaining
the cookie.

Home Assistant's native Music Assistant integration is connected. Its
`media_player.office` is in the Office area and exposed to Assist. A text
Assist test started the Lofi Loft playlist on Office at 25% volume on
2026-10-25; audible and microphone confirmation is a separate user check.

`office_music.yaml` is installed as `/config/packages/office_music.yaml`.
It routes play requests directly to Music Assistant before the tool-enabled
Ollama agent can send them to web search. Office is the default destination
for these commands. Examples:

- "Hey Jarvis, play the playlist Lofi Loft on Office."
- "Hey Jarvis, play the song Here Comes the Sun."
- "Hey Jarvis, play the album Abbey Road."

"Stop the music", "pause the music", and "pause Office" explicitly pause
`media_player.office` before the AI agent runs. Resume, next track, and volume
use the built-in Assist commands. The base-int8 speech recognizer has misheard
"pause Office" as "puzzle office"; "stop the music" is an alternative phrase.
After editing the package, run HA's configuration check and reload automations.

Spotify can be added separately with the wife's Premium account when she is
available to sign in. Spotify Connect is a separate Music Assistant plugin
for exposing Office in the Spotify app's device picker.

```sh
cd ~/music-assistant
docker compose ps
docker compose logs --tail 50
```

References:
- https://www.music-assistant.io/installation/
- https://www.music-assistant.io/music-providers/youtube-music/
- https://www.music-assistant.io/music-providers/spotify/
