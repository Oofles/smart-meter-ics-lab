#!/usr/bin/env python3
"""USB 4-key macropad -> facilitator RF trigger on the central node (Kit 00).

A physical shortcut for the dashboard's "send" button. Each key on the pad fires the
SAME code path as clicking send in fleet.html: an HTTP POST to the collector's
/api/send endpoint, which broadcasts the payload over LoRa to every in-range kit AND
applies it to Kit 00's own Opta. Because it goes through the collector we do NOT touch
the SX1262 serial port ourselves — the collector owns the radio (RX beacons + TX),
so there's zero contention for /dev/ttyAMA0.

  [pad key] --evdev--> keypad.py --HTTP POST /api/send--> collector --LoRa--> mesh

Two modes:
  sudo python3 central/keypad.py --learn     # one-time: press each key to bind it
  python3 central/keypad.py                  # run: grab the pad, POST on each keypress

--learn auto-discovers BOTH the device and the keycode: it watches every input device
at once, so you just press the key you want for each action and it records which device
+ code fired. The mapping is saved to /etc/smartmeter-keypad.json (override --config).

Runtime grabs the pad exclusively (evdev grab) so keystrokes don't also spill into a
console/TTY on Kit 00. Needs read access to /dev/input/* — run as root, or add the
service user to the `input` group (the installer does this). Needs python3-evdev:
  sudo apt install python3-evdev
"""
import argparse
import glob
import json
import os
import selectors
import sys
import time
import urllib.request

try:
    from evdev import InputDevice, categorize, ecodes, list_devices
except ImportError:
    sys.stderr.write(
        "error: python3-evdev not installed. Run: sudo apt install python3-evdev\n")
    sys.exit(1)

DEFAULT_CONFIG = "/etc/smartmeter-keypad.json"
DEFAULT_URL = "http://127.0.0.1:8090/api/send"

# The actions --learn walks through, in order. Each value is a collector SEND_TYPES key
# (see central/collector.py). Pressing Enter (on your SSH session) skips/unbinds one.
ACTIONS = [
    ("malicious",      "TEST trip     — red, voltage/usage->0; operator RESET clears it"),
    ("malicious_lock", "EXERCISE LOCK — red; operator RESET disabled (facilitator recovers)"),
    ("reset",          "RECOVERY      — FW_MODE:=0 everywhere (clears TEST and LOCK)"),
    ("benign",         "HEARTBEAT     — benign version beacon (safe no-op)"),
]


# ---------------------------------------------------------------- device helpers

def byid_path(dev_path):
    """Resolve /dev/input/eventN -> a stable /dev/input/by-id/*-kbd symlink if one points
    at it, so a saved binding survives reboots/replug (eventN can renumber). Falls back to
    the raw path when there's no by-id link."""
    real = os.path.realpath(dev_path)
    for link in sorted(glob.glob("/dev/input/by-id/*")):
        try:
            if os.path.realpath(link) == real:
                return link
        except OSError:
            continue
    return dev_path


def open_all_devices():
    """Open every readable input device (for --learn, where we don't yet know the pad)."""
    devs = []
    for path in list_devices():
        try:
            devs.append(InputDevice(path))
        except (OSError, PermissionError):
            pass  # no read access (not in `input` group?) — skip, others may still work
    return devs


# ---------------------------------------------------------------- learn mode

def learn(config_path):
    if os.geteuid() != 0 and not os.access(os.path.dirname(config_path) or "/", os.W_OK):
        print("note: may need sudo to write %s" % config_path)
    devs = open_all_devices()
    if not devs:
        sys.exit("no readable input devices — run with sudo, or join the `input` group")
    print("Watching %d input device(s). For each action below, press the pad key you want"
          % len(devs))
    print("(or press Enter here to leave that action unbound).\n")

    sel = selectors.DefaultSelector()
    for d in devs:
        sel.register(d.fileno(), selectors.EVENT_READ, d)
    # stdin lets you SKIP an action by pressing Enter on your SSH session.
    stdin_ok = sys.stdin and sys.stdin.isatty()
    if stdin_ok:
        sel.register(sys.stdin.fileno(), selectors.EVENT_READ, "stdin")

    bindings = []
    used = set()
    for action, desc in ACTIONS:
        print("  [%s]  %s" % (action.upper(), desc))
        print("      press a key (or Enter to skip) ... ", end="", flush=True)
        cap = _capture_one(sel, devs, stdin_ok)
        if cap is None:
            print("skipped")
            continue
        dev, code = cap
        keyname = ecodes.KEY.get(code, "code %d" % code)
        if isinstance(keyname, list):
            keyname = keyname[0]
        stable = byid_path(dev.path)
        if (stable, code) in used:
            print("already bound to another action — skipped (pick a different key)")
            continue
        used.add((stable, code))
        bindings.append({"action": action, "device": stable,
                         "code": int(code), "keyname": keyname})
        print("bound %s  (%s on %s)" % (keyname, "code %d" % code, os.path.basename(stable)))

    if not bindings:
        sys.exit("\nno keys bound — nothing saved.")

    cfg = {"url": DEFAULT_URL, "bindings": bindings}
    with open(config_path, "w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")
    print("\nsaved %d binding(s) -> %s" % (len(bindings), config_path))
    print("start the daemon with:  sudo systemctl start smartmeter-keypad")


def _capture_one(sel, devs, stdin_ok):
    """Block until one pad key goes down (return (device, code)) or Enter is pressed on
    stdin (return None = skip). Ignores autorepeat/release; debounces the release after."""
    while True:
        for key, _ in sel.select():
            if key.data == "stdin":
                sys.stdin.readline()
                return None
            dev = key.data
            try:
                events = list(dev.read())
            except OSError:
                continue
            for ev in events:
                if ev.type == ecodes.EV_KEY and ev.value == 1:  # key DOWN only
                    _drain(devs)                                 # eat the matching release
                    return dev, ev.code


def _drain(devs, settle=0.4):
    """Swallow queued events for a moment so one physical press isn't read twice."""
    end = time.monotonic() + settle
    while time.monotonic() < end:
        for d in devs:
            try:
                while d.read_one() is not None:
                    pass
            except OSError:
                pass
        time.sleep(0.02)


# ---------------------------------------------------------------- run mode

def post(url, kind, ttl):
    """POST {"type": kind, "ttl": ttl} to the collector's /api/send. Never raises —
    a down collector (or dropped RF) must not kill the daemon; it just logs and waits
    for the next keypress."""
    body = json.dumps({"type": kind, "ttl": ttl}).encode()
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            resp = json.loads(r.read() or b"{}")
        msg = "msg_id=0x%04X" % resp["msg_id"] if resp.get("msg_id") is not None else resp
        print("  SENT %-14s ttl=%d  -> %s" % (kind, ttl, msg))
    except Exception as e:
        print("  SEND FAILED %-14s -> %s (is the collector up on %s?)" % (kind, e, url))


def run(config_path, url_override, ttl, cooldown):
    with open(config_path) as f:
        cfg = json.load(f)
    url = url_override or cfg.get("url") or DEFAULT_URL
    bindings = cfg.get("bindings", [])
    if not bindings:
        sys.exit("no bindings in %s — run --learn first" % config_path)

    # Group bindings by device so we open+grab each pad device once. lookup[(path,code)]=action
    lookup, want_paths = {}, []
    for b in bindings:
        path = b["device"]
        if path not in want_paths:
            want_paths.append(path)
        lookup[(path, b["code"])] = b["action"]

    devices, sel = [], selectors.DefaultSelector()
    for path in want_paths:
        try:
            d = InputDevice(path)
            d.grab()                       # exclusive: keystrokes won't leak to a TTY
            devices.append(d)
            sel.register(d.fileno(), selectors.EVENT_READ, path)
        except (OSError, PermissionError) as e:
            print("warning: cannot open/grab %s: %s" % (path, e))
    if not devices:
        sys.exit("no pad devices could be opened — is it plugged in? are you in `input`?")

    print("keypad armed -> %s   (ttl=%d, cooldown=%.1fs)" % (url, ttl, cooldown))
    for b in bindings:
        print("  %-8s %-14s -> type=%s" % (b["keyname"], "(" + b["action"] + ")", b["action"]))

    last = {}  # per-action cooldown so a bounce/double-tap can't double-fire the payload
    try:
        while True:
            for key, _ in sel.select():
                dev_path = key.data
                dev = next(d for d in devices if d.path == dev_path)
                try:
                    events = list(dev.read())
                except OSError:
                    continue
                for ev in events:
                    if ev.type != ecodes.EV_KEY or ev.value != 1:  # key DOWN only
                        continue
                    action = lookup.get((dev_path, ev.code))
                    if not action:
                        continue
                    now = time.monotonic()
                    if now - last.get(action, 0) < cooldown:
                        continue
                    last[action] = now
                    post(url, action, ttl)
    except KeyboardInterrupt:
        pass
    finally:
        for d in devices:
            try:
                d.ungrab()
            except OSError:
                pass


# ---------------------------------------------------------------- cli

def main():
    ap = argparse.ArgumentParser(description="4-key macropad -> facilitator RF trigger (Kit 00)")
    ap.add_argument("--learn", action="store_true",
                    help="one-time: press each pad key to bind it, then save the mapping")
    ap.add_argument("--config", default=DEFAULT_CONFIG, help="mapping file (default %s)" % DEFAULT_CONFIG)
    ap.add_argument("--url", default=None, help="collector /api/send URL (default from config / %s)" % DEFAULT_URL)
    ap.add_argument("--ttl", type=int, default=3, help="RF hop limit for each send (default 3)")
    ap.add_argument("--cooldown", type=float, default=1.5,
                    help="min seconds between repeats of the same action (anti-double-fire)")
    ap.add_argument("--list", action="store_true", help="list input devices and exit")
    args = ap.parse_args()

    if args.list:
        for p in list_devices():
            try:
                d = InputDevice(p)
                print("%-20s %-30s %s" % (p, d.name, byid_path(p)))
            except (OSError, PermissionError):
                print("%-20s (no read access)" % p)
        return
    if args.learn:
        learn(args.config)
    else:
        run(args.config, args.url, args.ttl, args.cooldown)


if __name__ == "__main__":
    main()
