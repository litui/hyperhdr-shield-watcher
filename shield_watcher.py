#!/usr/bin/env python
import os
import sys
from dotenv import load_dotenv
from handler.adb import ADBHandler, STATE_POWER_ON
from handler.hyperhdr import HyperHDRHandler


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
        hyph.led_state = True if new_state == STATE_POWER_ON else False

    adbh.set_hdr_callback(hdr_mode_callback)
    adbh.set_power_callback(power_mode_callback)

    while True:
        adbh.loop()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        try:
            sys.exit(130)
        except SystemExit:
            os._exit(130)
