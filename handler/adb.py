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
            # hwcomposer always seems to clear its HDR cache after reverting to SDR.
            # Therefore:
            #   All hwcomposer HDR messages except the cache clear == HDR is on
            #   hwcomposer HDR messages with "Clear cached..."     == HDR is off
            "state_type": STATE_TYPE_HDR,
            "regex": re.compile(r"^(?P<label>HDR): (?P<clear_msg>Clear cached)?.*$"),
            "groups": {
                "label": {"HDR": STATE_HDR_ON},
                "clear_msg": {"Clear cached": STATE_HDR_OFF},
            },
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

        # Check for existence of ADB on the path
        try:
            self._adb_path = subprocess.check_output(
                ("/usr/bin/which", "adb"), stderr=subprocess.DEVNULL
            ).strip()
        except subprocess.CalledProcessError:
            print("Error: adb util not found on path!", file=sys.stderr)
            sys.exit(1)

        # Connect ADB to the SHIELD TV
        try:
            subprocess.check_output(
                (self._adb_path, "connect", f"{hostname}:{port}"),
                stderr=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError:
            print(
                "Unable to connect to adb port on SHIELD TV device "
                f"at {hostname}:{port}.",
                file=sys.stderr,
            )
            sys.exit(2)
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

        # Prepare common log parsing regex
        self.regex_log_parse = re.compile(
            r"^(?P<month>\d{2})-(?P<date>\d{2})\s+"
            r"(?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2})\.(?P<millisecond>\d{3})\s+"
            r"\d+\s+\d+\s+\w\s+(?P<process>\S+)\s*:\s+(?P<message>.+)$"
        )

        # Start processing logs
        self._ps = subprocess.Popen((self._adb_path, "logcat"), stdout=subprocess.PIPE)

        self._queue = Queue()
        t = Thread(target=self._process_log, args=(self._ps.stdout, self._queue))
        t.daemon = True
        t.start()

    def _process_log(self, output, queue: Queue):
        for line in iter(output.readline, b""):
            matched_line = self.regex_log_parse.match(line.decode("utf-8"))

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

                    queue.put({"state_type": state_type, "state": state})

        output.close()

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
                    self._callbacks[stype](new_state[stype], sval)
                except:
                    pass
                self._current_state[stype] = qitem["state"]

    def set_hdr_callback(self, callback):
        self._callbacks[STATE_TYPE_HDR] = callback

    def set_power_callback(self, callback):
        self._callbacks[STATE_TYPE_POWER] = callback

    def loop(self):
        self._update_states_from_queue()
