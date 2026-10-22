#!/usr/bin/env python3
"""dim.py — control LED brightness with PWM (pulse-width modulation).

Same wiring as blink.py (GPIO17 -> 330Ω -> LED long leg; short leg -> GND).
PWM flips the pin on/off thousands of times a second; the fraction of time it's
on ("duty cycle", 0.0-1.0) sets the apparent brightness.

RUN ON THE PI:
    python3 ~/dim.py                 # breathe: fade in and out forever
    python3 ~/dim.py --level 0.3     # hold a steady 30% brightness
    python3 ~/dim.py --fade 3 --level 1.0   # ramp 0 -> 100% over 3s, then hold

Ctrl-C to stop (LED turns off).
"""
import argparse
from signal import pause
from time import sleep
from gpiozero import PWMLED

def main():
    ap = argparse.ArgumentParser(description="Dim/fade an LED with PWM.")
    ap.add_argument("--pin",   type=int,   default=17,   help="BCM GPIO number (default 17)")
    ap.add_argument("--level", type=float, default=None, help="target brightness 0.0-1.0")
    ap.add_argument("--pulse", action="store_true",      help="breathe: fade in/out continuously")
    ap.add_argument("--fade",  type=float, default=0.0,  help="seconds to ramp 0->level before holding")
    args = ap.parse_args()

    # Default action (no brightness args) is to breathe.
    breathe = args.pulse or (args.level is None and args.fade == 0)
    level = max(0.0, min(1.0, args.level if args.level is not None else 1.0))  # clamp
    led = PWMLED(args.pin)

    try:
        if breathe:
            print(f"Breathing on GPIO{args.pin}. Ctrl-C to stop.")
            led.pulse()          # continuous fade in/out in a background thread
            pause()
        else:
            if args.fade > 0:
                print(f"Fading GPIO{args.pin} 0 -> {level:.0%} over {args.fade}s...")
                steps = 50
                for i in range(steps + 1):
                    led.value = level * i / steps
                    sleep(args.fade / steps)
            else:
                led.value = level
            print(f"Holding GPIO{args.pin} at {level:.0%}. Ctrl-C to stop.")
            pause()
    except KeyboardInterrupt:
        led.off()
        print("\nStopped, LED off.")

if __name__ == "__main__":
    main()
