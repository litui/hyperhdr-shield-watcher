import json
import requests
import sys


class HyperHDRHandler:
    def __init__(self, host: str, port: int = 8090):
        self._url = f"http://{host}:{port}/json-rpc"

    @property
    def hdr_mode(self):
        return self._serverinfo["info"]["components"][1]["enabled"]

    @hdr_mode.setter
    def hdr_mode(self, value: bool):
        content = {
            "command": "componentstate",
            "componentstate": {"component": "HDR", "state": value},
        }

        try:
            requests.post(self._url, json=content)
        except:
            print("Could not call to HyperHDR API =(", file=sys.stderr)

    @property
    def led_state(self):
        return self._serverinfo["info"]["components"][7]["enabled"]

    @led_state.setter
    def led_state(self, value: bool):
        content = {
            "command": "componentstate",
            "componentstate": {"component": "LEDDEVICE", "state": value},
        }

        try:
            requests.post(self._url, json=content)
        except:
            print("Could not call to HyperHDR API =(", file=sys.stderr)

    @property
    def _serverinfo(self):
        content = {"command": "serverinfo"}

        try:
            result = requests.post(self._url, json=content)
        except:
            print("Could not call to HyperHDR API =(", file=sys.stderr)
            return {}

        return result.json()
