#!/usr/bin/env python3
"""blink.py — the GPIO 'hello world': blink an LED on the Pi.

RUN THIS ON THE PI (gpiozero talks to the Pi's own hardware), not the Mac:
    ssh pi@raspberrypi.local
    python3 ~/blink.py              # after copying it over (see gpio/README.md)

Wiring (BCM GPIO17 = physical pin 11):
    GPIO17 (pin 11) --[ 330Ω resistor ]--> LED long leg (+ anode)
    LED short leg (- cathode) ------------> GND (pin 6 or pin 9)

Stop with Ctrl-C.
"""
import argparse
from signal import pause
from gpiozero import LED

def main():
    ap = argparse.ArgumentParser(description="Blink an LED on a GPIO pin.")
    ap.add_argument("--pin", type=int, default=17, help="BCM GPIO number (default 17)")
    ap.add_argument("--on",  type=float, default=0.5, help="seconds on (default 0.5)")
    ap.add_argument("--off", type=float, default=0.5, help="seconds off (default 0.5)")
    args = ap.parse_args()

    led = LED(args.pin)
    print(f"Blinking LED on GPIO{args.pin}  ({args.on}s on / {args.off}s off). Ctrl-C to stop.")
    # gpiozero runs the blink in a background thread; pause() keeps us alive.
    led.blink(on_time=args.on, off_time=args.off)
    try:
        pause()
    except KeyboardInterrupt:
        led.off()
        print("\nStopped, LED off.")

if __name__ == "__main__":
    main()
