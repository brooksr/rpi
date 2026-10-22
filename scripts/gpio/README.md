# GPIO playground

First steps with the CanaKit components on the Pi 3B's 40-pin header.
Modern Raspberry Pi OS (Trixie) uses **gpiozero + lgpio** and the **`pinctrl`**
CLI. The old `RPi.GPIO` library and `/sys/class/gpio` sysfs are deprecated — the
scripts here use the current stack (already installed on the Pi).

> ⚠️ **GPIO safety:** pins are **3.3V**, ~16mA max each. Always put a resistor in
> series with an LED. Never feed 5V into a GPIO pin, and never wire a pin
> straight to GND while it's driven high. Double-check wiring before powering on.

## Pin map cheat-sheet (the ones you'll use most)

```
         3V3  (1) (2)  5V
       GPIO2  (3) (4)  5V
       GPIO3  (5) (6)  GND
       GPIO4  (7) (8)  GPIO14
         GND  (9) (10) GPIO15
      GPIO17 (11) (12) GPIO18      <- 17 = our LED, 18 = IR later
      GPIO27 (13) (14) GND
      GPIO22 (15) (16) GPIO23
         ...
```
Full map any time: run `pinctrl` on the Pi, or see pinout.xyz.

---

## Project 1 — Blink an LED (start here)

**Parts:** 1 LED, 1 resistor (~330Ω; 220Ω is fine too), 2 jumper wires, breadboard.

**Wire it (Pi powered OFF):**
1. LED straddles the breadboard center gap. Note the legs: **long = + (anode)**,
   **short = − (cathode)** (flat side of the rim is the cathode).
2. Resistor from **GPIO17 (physical pin 11)** → LED **long leg**.
3. Jumper from LED **short leg** → **GND (pin 6 or 9)**.

**Run it (on the Pi):**
```bash
# copy the script over from the Mac (run on the Mac):
scp scripts/gpio/blink.py pi@raspberrypi.local:~/

# then on the Pi:
ssh pi@raspberrypi.local
python3 ~/blink.py                 # default: GPIO17, 0.5s on/off
python3 ~/blink.py --pin 17 --on 0.1 --off 0.1   # fast blink
```
Ctrl-C to stop. If it errors about a pin factory, prefix with
`GPIOZERO_PIN_FACTORY=lgpio python3 ~/blink.py`.

**No LED handy? Test a pin from the CLI** (watch the state flip):
```bash
pinctrl set 17 op dh   # output, drive high
pinctrl get 17         # should read 'hi'
pinctrl set 17 dl      # drive low
```

---

## Project 2 — Dim / fade the LED (PWM)

Same wiring as Project 1. PWM pulses the pin thousands of times a second; the
on-fraction ("duty cycle") sets brightness.
```bash
python3 ~/dim.py                       # breathe: fade in/out forever
python3 ~/dim.py --level 0.3           # steady 30% brightness
python3 ~/dim.py --fade 3 --level 1.0  # ramp 0 -> 100% over 3s, then hold
```
Ctrl-C to stop. (`--pin` works here too.)

## Next ideas (when you want them)
- **Button input** — read a pushbutton with `gpiozero.Button` (event-driven).
- **Traffic light** — 3 LEDs, a tiny state machine.
- **Combine** — button press cycles brightness levels on the LED.

## IR capabilities (for later — needs a module)
The base CanaKit usually has **no IR parts**. To do IR you'd add:
- **Receiver** (decode remotes): a TSOP-style 38kHz IR receiver (e.g. VS1838B).
- **Transmitter** (blast IR, control a TV): an IR LED + driver (e.g. KY-005).

Software path on current Pi OS: enable the kernel IR GPIO overlays in
`/boot/firmware/config.txt`, then use the `ir-keytable` / `lirc` tools:
```
dtoverlay=gpio-ir,gpio_pin=18       # receiver on GPIO18
dtoverlay=gpio-ir-tx,gpio_pin=17    # transmitter on GPIO17
```
Ping me when you've got a module and I'll wire up the overlay + a test.
