# Desktop only while the lid is open

`lid-desktop.service` on the HA laptop watches `/proc/acpi/button/lid/*/state`
every 5 seconds:

- **Lid closed for 2 minutes:** stops `gdm`. The desktop session and every app
  in it (browsers, Files, desktop terminals) are closed; unsaved work is lost.
  Frees roughly 5 GB with the usual apps open.
- **Lid open:** starts `gdm`, which auto-logs in as the HA user (no password).

It leaves the desktop alone while an external display is connected. Home
Assistant, the cameras, voice, Ollama and the timers don't use the desktop.
logind already ignores the lid, so closing it never suspends the laptop.
Run long jobs over SSH (or in tmux started over SSH), not in a desktop terminal.

```sh
bash scripts/lid-desktop/install.sh          # install + enable, don't start
bash scripts/lid-desktop/install.sh --start  # also (re)start the watcher now
journalctl -u lid-desktop -f                 # on the laptop
```

Auto-login was added to `/etc/gdm3/custom.conf` (original kept as
`custom.conf.before-autologin`). Anyone who opens the lid gets the desktop.
To undo: `sudo systemctl disable --now lid-desktop`, restore that file.
