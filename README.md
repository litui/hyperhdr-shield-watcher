# Nvidia Shield TV Pro Watcher for HyperHDR

This tool is for monitoring the ADB logs on the Nvidia SHIELD TV Pro in order to enable/disable LEDs and HDR mode on HyperHDR-based TV backlighting. It relies on the Android Debugger and python packages within the `requirements.txt` file.

Current functionality is to enable LEDs when the SHIELD turns on and to disable LEDs when it goes into standby. When HDR content is displayed, it will switch the LEDs to HDR mode and revert them back to SDR mode afterward. It will also revert to SDR mode when power is turned off or on.

## HDR-capable apps tested & known to work

I've set up this program on the assumption of HDR10. I'm not sure if it'll react the same for Dolby Vision. Please test and let me know!

### HDR10
* Netflix
* Disney+
* Prime Video
* Moonlight

## Preparation

1. You probably need to be using an SHIELD TV Pro as your video source. *This code can surely be adapted to work with any Android TV device but the stock messages I've set up this program to look for might not be the same for your device. You're welcome to fork and customize what's here.*

2. You need a TV capable of displaying HDR content that currently works in HDR mode with the SHIELD TV Pro.

3. You should have a fully set up Raspberry Pi or other Linux-based system (I'll assume Debian-based here) running HyperHDR with working video capture and LEDs.

4. Your LUT within HyperHDR should be calibrated or one-click downloaded to support HDR mapping on your video grabber device.

5. Your SHIELD TV Pro needs to have Developer Mode unlocked. *Go to Settings -> Device Preferences -> About, scroll down to "Build" and tap the select button on it a bunch of times until it tells you Developer Mode is unlocked. Simply unlocking it will not harm your devices.*

6. You need to enable network debugging on your SHIELD TV Pro. *Go into Settings -> Device Preferences -> Developer options. Scroll down to "Network debugging" and enable it. Make a note of the IP address (only the IPv4 address will be needed).*

7. In the HyperHDR web interface, in the Advanced -> Network Services section, make sure "Local API Authentication" is unchecked. *The current version of this tool doesn't know how to authenticate to HyperHDR. It also only uses HTTP (not HTTPS).*

## Installation

On the Raspberry Pi or other Debian-based Linux device, ssh in as a sudo-capable user and run the following:

`sudo apt-get install git adb python3-pip python3-virtualenv`

Agree to the prompts to install the necessary packages.

In your home directory or another suitable location, run each of the following commands:

```bash
git clone https://github.com/litui/hyperhdr-shield-watcher
cd hyperhdr-shield-watcher
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Use your commandline editor of choice to edit the .env file and enter the IP address of your SHIELD TV Pro. The other parameters will only need changing if you're running HyperHDR on a different system.

**Make sure your SHIELD TV Pro and TV are on for the next step. You'll need to approve adb access and make sure to tick the checkbox so you don't have to approve it again.**

Run this program for the first time. It may exit with an error but that's fine as long as you get the ADB approval popup on your SHIELD TV:

```bash
.venv/bin/python shield_watcher.py
```

If it exits the first time, run it again once you've approved the ADB connection and, assuming the IPs, ports, and prerequisites are in place, it'll run fine.

An example systemd unit file can be found in the `systemd` folder for running this tool as a background service.

## TODO:

* See what other cool things can be triggered based on the ADB logs
* Potentially add support for checking my LG TV power status so the initial state of the LEDs/grabber can match it.
