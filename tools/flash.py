#!/usr/bin/env python3
"""Upload a firmware image to the GS108T without using its web UI (also the recovery path).

    .venv/bin/python tools/flash.py IMAGE.hex                 # dry run: validate image, log in, check session
    .venv/bin/python tools/flash.py IMAGE.hex --upload        # really flash it

Talks to the same CGIs the stock page uses, so it works even if a flashed UI is broken:
  login.cgi   POST password=..&rtime=..   -> session cookie (bound to this machine's IP, 4 slots max)
  fupgrade.cgi POST multipart, single part "http_dl_fname" = the .hex
  upgstatus.html  "var current = N; var total = M;" progress while flashing

The switch writes the image to its *inactive* flash bank and only marks it bootable after the
whole image checked out, so an interrupted or rejected upload leaves the running firmware alone.
Never use cfeupgrade.cgi (bootloader).
"""
import argparse, getpass, os, re, sys, threading, time

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gs108t_web as fw


def login(s, base, password):
    r = s.post(base + "/login.cgi", data={"password": password, "rtime": str(time.time() * 1000 / 500)},
               allow_redirects=True, timeout=20)
    if "maximal number" in r.text.lower():
        sys.exit("login refused: all 4 session slots are in use. Sessions are only freed by the idle timeout\n"
                 "(System Information > Idle timeout, 3-30 min); 'Log out' does not free one. Wait and retry.")
    page = s.get(base + "/sysInfo.html", timeout=20)
    if "inputBox_SystemName" not in page.text and "System Information" not in page.text:
        sys.exit("login failed: wrong password?")
    return page.text


def upgrade_status(s, base):
    """(current, total) from upgstatus.html; current < 0 = error, total 0 = no upgrade running."""
    t = s.get(base + "/upgstatus.html", timeout=20).text
    cur = re.search(r"var current = (-?\d+)", t)
    tot = re.search(r"var total = (\d+)", t)
    return (int(cur.group(1)), int(tot.group(1))) if cur and tot else (None, None)


def progress(s, base, stop):
    last = None
    while not stop.is_set():
        try:
            t = s.get(base + "/upgstatus.html", timeout=10).text
            cur = re.search(r"var current = (-?\d+)", t)
            tot = re.search(r"var total = (\d+)", t)
            if cur and tot and int(tot.group(1)):
                c, n = int(cur.group(1)), int(tot.group(1))
                msg = "  flashing: %d / %d bytes (%d%%)" % (c, n, c * 100 // n) if c >= 0 else "  switch reports an ERROR"
                if msg != last:
                    print(msg, flush=True)
                    last = msg
        except requests.RequestException:
            pass
        stop.wait(2)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("image")
    p.add_argument("--switch", default="http://192.168.0.239")
    p.add_argument("--upload", action="store_true", help="actually flash (default: dry run)")
    a = p.parse_args()
    base = a.switch.rstrip("/")

    fw.check_hex(a.image)  # same checks as the switch: gzip header, FNAME, length+sum16 comment, size
    data = open(a.image, "rb").read()
    o = 10                 # backups saved from the switch end with one extra "\n": send only the image
    o = data.index(b"\0", o) + 1
    c = data.index(b"\0", o)
    if len(data) - (c + 1) == int(data[o:o + 8], 16) + 1 and data.endswith(b"\n"):
        data = data[:-1]

    s = requests.Session()
    s.headers["Connection"] = "close"
    password = os.environ.get("GS108T_PASSWORD") or getpass.getpass("Switch password: ")
    login(s, base, password)
    print("logged in to %s, session OK" % base)

    if not a.upload:
        print("dry run: image and login are fine. Re-run with --upload to flash.")
        return
    cur, tot = upgrade_status(s, base)
    if tot and cur is not None and 0 <= cur < tot:
        sys.exit("the switch reports an upgrade in progress (%d / %d bytes); wait for it or reboot first" % (cur, tot))
    if input("Flash %s (%d bytes) to %s? Type 'flash' to continue: " % (os.path.basename(a.image), len(data), base)) != "flash":
        sys.exit("aborted")

    stop = threading.Event()
    poller = requests.Session()
    poller.cookies = s.cookies  # same login session, separate connection (like the stock page's iframe)
    poller.headers["Connection"] = "close"
    threading.Thread(target=progress, args=(poller, base, stop), daemon=True).start()
    print("uploading... do not power off the switch")
    t0 = time.time()
    try:
        # urllib3 keeps the *connect* timeout on the socket while it sends the body; the read timeout
        # only starts once the switch answers. The switch writes flash while receiving and can stall
        # well over 10 s (erase, plus 1-2 s TCP retransmits per lost packet), so both must be long.
        r = s.post(base + "/fupgrade.cgi",
                   files={"http_dl_fname": (os.path.basename(a.image), data, "application/octet-stream")},
                   timeout=(300, 900))
    except requests.RequestException as e:
        stop.set()
        print("upload failed after %.0f s: %s" % (time.time() - t0, e.__class__.__name__))
        try:
            print("  switch upgrade status now: current %s / total %s" % upgrade_status(poller, base))
        except requests.RequestException:
            print("  switch does not answer right now")
        sys.exit("The running firmware is untouched (the new bank is only marked bootable after a complete,\n"
                 "verified image). Wait until the status above is no longer counting, then run this again.")
    finally:
        stop.set()
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r.text))
    print("switch answered HTTP %d after %.0f s" % (r.status_code, time.time() - t0))
    for msg in ("Invalid firmware", "Failed to", "already started", "Internal server error", "Firmware Upgrade"):
        if msg.lower() in text.lower():
            print("  message:", text[:300])
            break
    print("If the switch reported success, reboot it (Maintenance > Device Reboot) to start the new firmware.")


if __name__ == "__main__":
    main()
