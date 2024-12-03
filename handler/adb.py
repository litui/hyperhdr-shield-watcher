import copy
import os
import re
import sys
import subprocess
import time
from queue import Queue, Empty
from threading import Thread

# Valid HDR states
STATE_HDR_OFF = False
STATE_HDR_ON = True

# Valid Power states
STATE_POWER_OFF = 0
STATE_POWER_SLEEP = 1
STATE_POWER_ON = 2

# Enum of state types
STATE_TYPE_HDR = 0
STATE_TYPE_POWER = 1

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
}


class ADBHandler:
    def __init__(
        self,
        hostname: str,
        port: int = 5555,
        hdr_init_state=STATE_HDR_OFF,
        power_init_state=STATE_POWER_OFF,
    ):
        self._hostname = hostname
        self._port = port
        self._connected = False
        self._current_state = {
            STATE_TYPE_HDR: hdr_init_state,
            STATE_TYPE_POWER: power_init_state,
        }
        self._callbacks = {STATE_TYPE_HDR: None, STATE_TYPE_POWER: None}

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

                matches = REGEX_MAPPING.get(process, [])

                for m in matches:
                    state_type = m["state_type"]
                    state = self._current_state[state_type]
                    matched_msg = m["regex"].match(message)
                    if matched_msg:
                        for name, values in m["groups"].items():
                            g = matched_msg.group(name)
                            if g and g in values.keys():
                                state = values[g]
                                # print(
                                #     f"Process log: {process} logged state {state} via regex match group {name}"
                                # )

                        queue.put(
                            {
                                "process": process,
                                "state_type": state_type,
                                "state": state,
                            }
                        )

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

        while True:
            try:
                qitem = self._queue.get_nowait()
                new_state[qitem["state_type"]] = qitem["state"]
            except Empty:
                # Nothing to update
                break

        for stype, sval in self._current_state.items():
            if new_state[stype] != sval:
                try:
                    # print(f"Process {qitem['process']} triggered {stype} callback...")
                    self._callbacks[stype](new_state[stype], sval)
                except:
                    pass
                self._current_state[stype] = qitem["state"]

    def set_hdr_callback(self, callback):
        self._callbacks[STATE_TYPE_HDR] = callback

    def set_power_callback(self, callback):
        self._callbacks[STATE_TYPE_POWER] = callback

    def loop(self):
        self._check_adb_state()
        self._update_states_from_queue()
