#!/usr/bin/env python
import os
import signal
import sys
from dotenv import load_dotenv
from handler.adb import ADBHandler, STATE_POWER_ON
from handler.hyperhdr import HyperHDRHandler


def signal_handler(signal_number, stack_frame):
    if signal_number == signal.SIGINT:
        print("Interrupted", file=sys.stderr)
        sys.exit(130)
    elif signal_number == signal.SIGQUIT:
        print("Received SIGQUIT. Exiting.", file=sys.stderr)
        sys.exit(0)
    elif signal_number == signal.SIGTERM:
        print("Received SIGTERM. Exiting.", file=sys.stderr)
        sys.exit(0)


def main():
    load_dotenv()
    shield_ip_addr = os.environ["SHIELD_IP_ADDRESS"]
    shield_adb_port = int(os.environ["SHIELD_ADB_PORT"])
    hyperhdr_ip_addr = os.environ["HYPERHDR_IP_ADDRESS"]
    hyperhdr_port = int(os.environ["HYPERHDR_PORT"])

    hyph = HyperHDRHandler(hyperhdr_ip_addr, hyperhdr_port)

    adbh = ADBHandler(
        shield_ip_addr,
        shield_adb_port,
        hdr_init_state=hyph.hdr_mode,
        power_init_state=int(hyph.led_state) + 1,
    )

    def hdr_mode_callback(new_state, old_state):
        print(f"HDR state changed from {old_state} to {new_state}")
        hyph.hdr_mode = new_state

    def power_mode_callback(new_state, old_state):
        print(f"Power state changed from {old_state} to {new_state}")
        # If we're turning the system on or off, HDR should be turned off.
        hyph.hdr_mode = False
        hyph.grabber_state = True if new_state == STATE_POWER_ON else False
        hyph.led_state = True if new_state == STATE_POWER_ON else False

    adbh.set_hdr_callback(hdr_mode_callback)
    adbh.set_power_callback(power_mode_callback)

    while True:
        adbh.loop()


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGQUIT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    main()
