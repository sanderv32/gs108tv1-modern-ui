#!/usr/bin/env python3
"""Check and screenshot converted pages without the switch.

    .venv/bin/python tools/preview.py sysinfo.html managementip.html [--out DIR] [--loops N]

For each page: compares its {{var}}/{{block}} placeholders with the stock template
(missing ones are an error: the firmware would no longer output that value), renders it
with sample values, and screenshots it with headless Edge into DIR (default: preview/).
"""
import argparse, os, shutil, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import devserver as ds

ROOT = ds.ROOT
EDGE = "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"


def keys(items, acc):
    for it in items:
        if isinstance(it, tuple):
            acc.add(it[1])
            if it[0] == "block":
                keys(it[2], acc)
    return acc


def sample(items, loops, n=[0]):
    sc = {}
    for it in items:
        if isinstance(it, tuple) and it[0] == "var":
            n[0] += 1
            sc[it[1]] = b"value%d" % n[0]
        elif isinstance(it, tuple):
            sc[it[1]] = [sample(it[2], loops) for _ in range(loops)]
    return sc


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("pages", nargs="+")
    p.add_argument("--out", default=os.path.join(ROOT, "preview"))
    p.add_argument("--loops", type=int, default=3, help="iterations per {{block}}")
    p.add_argument("--size", default="1000,900")
    a = p.parse_args()
    site = ds.Site(os.path.join(ROOT, "GS108T-V3.0.4.10.bin"), os.path.join(ROOT, "web"))
    os.makedirs(a.out, exist_ok=True)
    for f in ("default.css", "rollover.js", "usecookies.js"):
        shutil.copy(os.path.join(ROOT, "web", "files", f), a.out)
    ok = True
    for page in a.pages:
        name = page.lower()
        blob, is_tpl = site.local(name)
        if blob is None:
            print("%s: not in manifest" % page); ok = False; continue
        tree = ds.load(blob) if is_tpl else [blob]
        if name in site.stock:
            missing = keys(site.stock[name], set()) - keys(tree, set())
            extra = keys(tree, set()) - keys(site.stock[name], set())
            if missing:
                ok = False
                print("%s: MISSING placeholders %s" % (page, sorted(missing)))
            if extra:
                print("%s: new placeholders (devserver can't fill them) %s" % (page, sorted(extra)))
        html = ds.fill(tree, [sample(tree, a.loops)], set())
        path = os.path.join(a.out, name)
        open(path, "wb").write(html)
        png = os.path.splitext(path)[0] + ".png"
        try:  # virtual time budget: pages with refresh timers would otherwise never settle
            subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--virtual-time-budget=3000",
                            "--screenshot=" + png, "--window-size=" + a.size, "file://" + path],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
        except subprocess.TimeoutExpired:
            print("%s: screenshot timed out (page keeps running scripts)" % page)
        print("%s: %d bytes, placeholders OK%s -> %s" % (page, len(blob), "" if name in site.stock else " (static)", png))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
