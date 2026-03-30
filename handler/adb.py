import copy
import os
import re
import sys
import subprocess
import time
from queue import Queue, Empty
from threading import Thread
import typing

# Valid HDR states
STATE_HDR_OFF = False
STATE_HDR_ON = True

# Valid Power states
STATE_POWER_OFF = 0
STATE_POWER_SLEEP = 1
STATE_POWER_ON = 2

# Valid activity App states
STATE_APP_STOPPED = 0
STATE_APP_STARTED = 1

# Enum of state types
STATE_TYPE_HDR = 0
STATE_TYPE_POWER = 1
STATE_TYPE_ACTIVITY = 2


REGEX_MAPPING = {
    "hwcomposer": [
        {
            #   Flip new ...        == HDR is on
            #   Clear cached...     == HDR is off
            "state_type": STATE_TYPE_HDR,
            "regex": re.compile(
                r"^HDR: (?P<smpte_type>Clear cached|Flip new) SMPTE 2086 metadata.*$"
            ),
            "groups": {
                "smpte_type": {"Flip new": STATE_HDR_ON, "Clear cached": STATE_HDR_OFF},
            },
        },
    ],
    "com.limelight.LimeLog": [
        {
            # Moonlight uses a little bit of a different mechanism to trigger HDR.
            # This should enable it, while the above hwcomposer regex should disable it still.
            "state_type": STATE_TYPE_HDR,
            "regex": re.compile(r"^Display HDR mode: (?P<status>\w*)$"),
            "groups": {"status": {"enabled": STATE_HDR_ON}},
        }
    ],
    "PowerManagerService": [
        {
            "state_type": STATE_TYPE_POWER,
            "regex": re.compile(r"^(?P<sleep_msg>Sleeping|Waking up).*$"),
            "groups": {
                "sleep_msg": {
                    "Sleeping": STATE_POWER_SLEEP,
                    "Waking up": STATE_POWER_ON,
                }
            },
        }
    ],
    # Watch activities so we can kill on sight when the goddamn netflix button is
    # accidentally pressed for the 35934857492th time.
    "ActivityManager": [
        {
            "state_type": STATE_TYPE_ACTIVITY,
            "regex": re.compile(r"^(?P<activity_state>Force stopping|Start proc) (?:[0-9]+[:])?(?P<activity_app>com\.netflix\.ninja+).*$"),
            "groups": {
                "activity_state": {
                    "Force stopping": STATE_APP_STOPPED,
                    "Start proc": STATE_APP_STARTED
                }
            }
        }
    ],
    # Double-tap
    "ActivityTaskManager": [
        {
            "state_type": STATE_TYPE_ACTIVITY,
            "regex": re.compile(r"^(?P<activity_state>START) [A-Za-z0-9]+ \{.*cmp=(?P<activity_app>com\.netflix\.ninja+)/(?P<in_app_action>[A-Za-z0-9-_.]+).*$"),
            "groups": {
                "activity_state": {
                    "None": STATE_APP_STOPPED,
                    "START": STATE_APP_STARTED
                }
            }
        }
    ],
    # We're going all out on Netflix. Pernicious little piece of crap. Gets the smack down every time it tries to reach out on the network =p
    "ConnectivityService": [
        {
            "state_type": STATE_TYPE_ACTIVITY,
            "regex": re.compile(r"^.*(?P<activity_state>RequestorPackageName): (?P<activity_app>com\.netflix\.ninja+).*$"),
            "groups": {
                "activity_state": {
                    "None": STATE_APP_STOPPED,
                    "RequestorPackageName": STATE_APP_STARTED
                }
            }
        }
    ]
}


class ADBHandler:
    def __init__(
        self,
        hostname: str,
        port: int = 5555,
        hdr_init_state=STATE_HDR_OFF,
        power_init_state=STATE_POWER_OFF,
        activity_init_state=STATE_APP_STOPPED
    ):
        self._hostname = hostname
        self._port = port
        self._connected = False
        self._current_state = {
            STATE_TYPE_HDR: hdr_init_state,
            STATE_TYPE_POWER: power_init_state,
            STATE_TYPE_ACTIVITY: activity_init_state
        }
        self._callbacks = {STATE_TYPE_HDR: None, STATE_TYPE_POWER: None, STATE_TYPE_ACTIVITY: None}

        self._ps = None
        self._pl_thread = None

        self._queue = Queue()

        # Prepare common log parsing regex
        self._regex_log_parse = re.compile(
            r"^(?P<month>\d{2})-(?P<date>\d{2})\s+"
            r"(?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2})\.(?P<millisecond>\d{3})\s+"
            r"\d+\s+\d+\s+\w\s+(?P<process>\S+)\s*:\s+(?P<message>.+)$"
        )
        self._regex_logcat_fails = [
            re.compile("logcat: Unexpected EOF!")
        ]

        self._adb_start()

    def _process_log(self, output, err, queue: Queue):
        for line in iter(output.readline, b""):
            matched_line = self._regex_log_parse.match(line.decode("utf-8"))

            if matched_line:
                process = matched_line.group("process")
                message = matched_line.group("message")

                match_spec = REGEX_MAPPING.get(process, [])
                match_results = [process["regex"].match(message) for process in match_spec]

                for i in range(len(match_spec)):
                    if match_results[i] is not None:
                        state_type = match_spec[i]["state_type"]
                        state = self._current_state[state_type]  # fallback to prior value
                        all_groups = {
                            g: match_spec[i].get("groups", {}).get(g, {v: v}).get(v, v)
                            for g, v in match_results[i].groupdict().items()
                        }
                        print(f"All groups: {all_groups}")
                        if len(all_groups.values()) > 0:
                            state = [v for k, v in all_groups.items()][0]
                        print(f"Process: {process}, State: {state}")
                        queue.put({
                            "process": process,
                            "state_type": state_type,
                            "state": state,
                            "match_groups": all_groups
                        })

        for line in iter(err.readline, b""):
            for fail in self._regex_logcat_fails:
                matched_line = fail.match(line.decode("utf-8"))

                if matched_line:
                    # Terminate now, cleanup later
                    self._ps.terminate()

        output.close()

    def _adb_start(self):
        # Check for existence of ADB on the path
        try:
            self._adb_path = subprocess.check_output(
                ("/usr/bin/which", "adb"), stderr=subprocess.DEVNULL
            ).strip()
        except subprocess.CalledProcessError:
            print("Error: adb util not found on path!", file=sys.stderr)
            sys.exit(1)

        # Connect ADB to the SHIELD TV
        while not self._connected:
            try:
                subprocess.check_output(
                    (self._adb_path, "connect", f"{self._hostname}:{self._port}"),
                    stderr=subprocess.DEVNULL,
                )
            except subprocess.CalledProcessError:
                print(
                    "Unable to connect to adb port on SHIELD TV device "
                    f"at {self._hostname}:{self._port}.",
                    file=sys.stderr,
                )
                time.sleep(5)
            finally:
                self._connected = True

        # Flush the adb logs
        try:
            subprocess.check_output(
                (self._adb_path, "logcat", "-c"),
                stderr=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError:
            print("Unable to flush adb logs", file=sys.stderr)
            sys.exit(3)

        # Start processing logs
        self._ps = subprocess.Popen(
            (self._adb_path, "logcat"), stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )

        self._pl_thread = Thread(target=self._process_log, args=(self._ps.stdout, self._ps.stderr, self._queue))
        self._pl_thread.daemon = True
        self._pl_thread.start()

    def _check_adb_state(self):
        if self._ps.poll() is not None:
            self._connected = False
            print("ADB process has died. Restarting...")
            self._adb_start()

    def _update_states_from_queue(self):
        new_state = copy.deepcopy(self._current_state)
        # print(f"Deepcopy new state: {new_state}")

        while True:
            try:
                qitem = self._queue.get_nowait()
                new_state[qitem["state_type"]] = qitem["state"]
            except Empty:
                # Nothing to update
                break

        # print(f"New state after queue loop: {new_state}")

        for stype, sval in self._current_state.items():
            if new_state[stype] != sval:
                try:
                    # print(f"New state just before callback: {new_state}")
                    # print(f"Process {qitem['process']} triggered {stype} callback...")
                    updated_state = self._callbacks[stype](new_state[stype], qitem["match_groups"], sval)

                    if updated_state is not None:
                        self._current_state[stype] = updated_state
                    else:
                        self._current_state[stype] = qitem["state"]
                except:
                    pass

    def set_hdr_callback(self, callback):
        self._callbacks[STATE_TYPE_HDR] = callback

    def set_power_callback(self, callback):
        self._callbacks[STATE_TYPE_POWER] = callback

    def set_app_activity_callback(self, callback):
        self._callbacks[STATE_TYPE_ACTIVITY] = callback

    def send_adb_shell_command(self, command: list[str]) -> bool:
        # Send shell command via ADB as a one-off
        # - my own use case is ["am", "force-stop", "PACKAGE_NAME"] for the stubborn apps that stop accepting
        #   chromecast connections after the device wakes from standby.
        # - careful what you run as this is potentially a blocking command

        try:
            final_cmd = [self._adb_path]
            final_cmd.extend(command)
            print(f"Command being sent: {final_cmd}")

            subprocess.check_output(
                final_cmd,
                stderr=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError:
            print(
                f"Unable to run adb command '{command}' on SHIELD TV device "
                f"at {self._hostname}:{self._port}.",
                file=sys.stderr,
            )
            return False

        return True

    def loop(self):
        self._check_adb_state()
        self._update_states_from_queue()
