#!/usr/bin/env python
import os
import signal
import sys
import time
from dotenv import load_dotenv
from handler.adb import ADBHandler, STATE_POWER_ON, STATE_APP_STARTED
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
    power_on_apps_to_stop = os.environ.get("POWER_ON_STOP_APPS", "").split(',')
    always_stop_apps = os.environ.get("ALWAYS_STOP_APPS", "").split(',')

    hyph = HyperHDRHandler(hyperhdr_ip_addr, hyperhdr_port)

    adbh = ADBHandler(
        shield_ip_addr,
        shield_adb_port,
        hdr_init_state=hyph.hdr_mode,
        power_init_state=int(hyph.led_state) + 1,
    )

    def hdr_mode_callback(new_state, match_groups, old_state):
        print(f"HDR state changed from {old_state} to {new_state}")
        hyph.hdr_mode = new_state

    def power_mode_callback(new_state, match_groups, old_state):
        print(f"Power state changed from {old_state} to {new_state}")
        # If we're turning the system on or off, HDR should be turned off.
        hyph.hdr_mode = False
        hyph.grabber_state = True if new_state == STATE_POWER_ON else False
        hyph.led_state = True if new_state == STATE_POWER_ON else False

        if new_state == STATE_POWER_ON:
            for app in power_on_apps_to_stop:
                if app != "" and app is not None:
                    # Leave out the `adb` at the start
                    adbh.send_adb_shell_command(["shell", "am", "force-stop", app.strip()])

    def app_activity_callback(new_state, match_groups, old_state):
        print(f"AppActivityCallback state changed from {old_state} to {new_state} [groups:{match_groups}]")

        # print(f"Kill list: {always_stop_apps}")

        print(f"Match Groups? {match_groups}")
        app = match_groups.get("activity_app")
        if new_state == 1 and app in always_stop_apps:
            # Wait a couple seconds for it to get off the ground
            # Murder the apps on the kill list \o/
            adbh.send_adb_shell_command(["shell", "am", "force-stop", app])

        # We want to be overzealous in setting the new state value to 0 every time so nothing is missed.
        return 0


    adbh.set_app_activity_callback(app_activity_callback)
    adbh.set_hdr_callback(hdr_mode_callback)
    adbh.set_power_callback(power_mode_callback)


    while True:
        adbh.loop()
        time.sleep(1)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGQUIT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    main()
