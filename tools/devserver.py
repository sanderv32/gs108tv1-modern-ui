#!/usr/bin/env python3
"""Development server for a new GS108T web UI, backed by the real switch.

    python tools/devserver.py [--switch http://192.168.0.239] [--port 8088]

Every request goes to the switch, then:
  * static files that exist in web/files (css/js/images/...) are served locally instead;
  * template pages / .cgi responses: the switch's rendered HTML is matched against the
    *stock* template (from the firmware .bin) to recover each {{var}} / {{block}} value,
    and those values are rendered into your *edited* template from web/files;
  * anything that doesn't match (C-generated pages, unknown files) passes through untouched.
So you can rework the markup with live data and never flash anything.
"""
import argparse, mimetypes, os, re, sys, threading

import requests
from flask import Flask, Response, request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gs108t_web as fw
import minify

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.setrecursionlimit(20000)  # match() recurses once per template item


# ---------------------------------------------------------------- template trees

def tree(recs):
    """flat records (from fw.parse) -> nested items: bytes | ('var', key) | ('block', key, [items])"""
    root, stack = [], []
    cur = root
    for r in recs:
        k = r["kind"] & 0x7f
        if k == 0:
            if r["val"]:
                cur.append(r["ptr"])
        elif k & 2:
            cur.append(("var", (r["ptr"], r["val"], r["arg"])))
        elif k & 1 and r["ptr"]:
            node = ("block", (r["ptr"], r["val"]), [])
            cur.append(node)
            stack.append(cur)
            cur = node[2]
        else:
            cur = stack.pop()
    return root


def load(blob):
    return tree(fw.parse(blob))


def match(items, s, pos=0):
    """Yield (end, scope) for every way `items` can match s[pos:]. scope: key -> value | [scopes]."""
    if not items:
        yield pos, {}
        return
    _BUDGET[0] -= 1
    if _BUDGET[0] < 0:
        raise TooAmbiguous()
    head, rest = items[0], items[1:]
    if isinstance(head, bytes):
        if s.startswith(head, pos):
            yield from match(rest, s, pos + len(head))
    elif head[0] == "var":
        nxt = rest[0] if rest and isinstance(rest[0], bytes) else None
        if nxt is None:  # var at end / before var or block: try every split, shortest first
            ends = range(pos, len(s) + 1)
        else:
            ends, i = [], s.find(nxt, pos)
            while i != -1:
                ends.append(i)
                i = s.find(nxt, i + 1)
        for e in ends:
            for end, sc in match(rest, s, e):
                yield end, {head[1]: s[pos:e], **sc}
    else:  # block: try 0..n iterations, each iteration must consume input
        def reps(p, done):
            for end, sc in match(rest, s, p):
                yield end, {head[1]: done, **sc}
            for e, it in match(head[2], s, p):
                if e > p:
                    yield from reps(e, done + [it])
        yield from reps(pos, [])


class TooAmbiguous(Exception):
    pass


_BUDGET = [0]


def extract_values(stock, page, budget=200000):
    """None if the page doesn't match (or matching would take too long, e.g. a template
    without any literal text such as gs108t.cfg)."""
    _BUDGET[0] = budget
    try:
        for end, scope in match(stock, page):
            if end == len(page):
                return scope
    except (TooAmbiguous, RecursionError):
        pass
    return None


def fill(items, scopes, missing):
    out = []
    for it in items:
        if isinstance(it, bytes):
            out.append(it)
        elif it[0] == "var":
            v = next((sc[it[1]] for sc in reversed(scopes) if it[1] in sc), None)
            if v is None:
                missing.add(it[1])
            out.append(v or b"")
        else:
            iters = next((sc[it[1]] for sc in reversed(scopes) if it[1] in sc), None)
            if iters is None:
                missing.add(it[1])
            for sc in iters or []:
                out.append(fill(it[2], scopes + [sc], missing))
    return b"".join(out)


# ---------------------------------------------------------------- site model

class Site:
    def __init__(self, bin_path, src, minify=False):
        self.minify = minify
        img = fw.Image(open(bin_path, "rb").read())
        self.src = src
        man = fw.json.load(open(os.path.join(src, "manifest.json")))
        self.templates = set(man["templates"])
        self.entry = {e["name"]: e["content"] for e in man["entries"]}
        # names with a firmware handler (.cgi, gs108t.cfg, firmware.bin): always ask the switch
        self.handled = {e["name"] for e in man["entries"] if int(e["cgi"], 0)}
        self.stock = {}  # name -> stock tree, for every template entry in the stock firmware
        self.stock_blob = {}  # name -> stock template source (to skip re-rendering unchanged pages)
        self.static_blob = {}  # name -> stock content of non-template entries (pages without values)
        cache, blobs = {}, {}
        for r in img.table():
            if r["desc"] not in cache:
                blob, is_tpl = fw.render(img, img.records(r["desc"])[0])
                cache[r["desc"]] = load(blob) if is_tpl else None
                blobs[r["desc"]] = blob
            if cache[r["desc"]] is not None:
                self.stock[r["name"]] = cache[r["desc"]]
                self.stock_blob[r["name"]] = blobs[r["desc"]]
            else:
                self.static_blob[r["name"]] = blobs[r["desc"]]

    def local(self, name):
        cid = self.entry.get(name)
        if cid is None:
            return None, False
        path = os.path.join(self.src, "files", cid)
        blob = open(path, "rb").read().replace(b"@@UI_VERSION@@", b"dev server")
        if self.minify:
            blob = minify.minify(cid, blob)
        return blob, cid in self.templates


# ---------------------------------------------------------------- flask app

DUMP = os.path.join(ROOT, "devserver-dumps")
SWITCH_LOCK = threading.Lock()
DUMP_ALL = False


def dump(name, body):
    """Save a switch response we couldn't render, for debugging."""
    os.makedirs(DUMP, exist_ok=True)
    with open(os.path.join(DUMP, name or "_default"), "wb") as f:
        f.write(body)


HOP = {"connection", "keep-alive", "transfer-encoding", "content-encoding", "content-length", "host"}


def make_app(site, switch):
    app = Flask(__name__)
    sw_host = re.sub(r"^https?://", "", switch).rstrip("/")

    @app.route("/", defaults={"path": ""}, methods=["GET", "POST"])
    @app.route("/<path:path>", methods=["GET", "POST"])
    def any_path(path):
        name = path.split("/")[-1].lower() if path else ""
        blob, is_tpl = site.local(name)
        if blob is not None and not is_tpl and request.method == "GET" and name not in site.stock \
                and name not in site.handled:
            mt = mimetypes.guess_type(name or site.entry[name])[0] or "application/octet-stream"
            return Response(blob, mimetype=mt, headers={"Cache-Control": "no-store"})

        headers = {k: v for k, v in request.headers if k.lower() not in HOP}
        headers["Host"] = sw_host
        for h in ("Referer", "Origin"):
            if h in headers:
                headers[h] = headers[h].replace(request.host, sw_host)
        # Forward the raw query string: forms repeat names (e.g. 8x m8021p) and CGIs read
        # parameters by position, so a dict of args would silently drop values.
        url = "%s/%s" % (switch.rstrip("/"), path)
        if request.query_string:
            url += "?" + request.query_string.decode("latin1")
        # The switch's embedded server copes badly with keep-alive and concurrent requests
        # (responses stall until timeout), so ask it to close and send one request at a time.
        headers["Connection"] = "close"
        try:
            with SWITCH_LOCK:
                r = requests.request(request.method, url, data=request.get_data(), headers=headers,
                                     allow_redirects=False,
                                     timeout=(5, 900 if name == "firmware.bin" else 120))  # backup: ~10 min
                body = r.content
        except requests.RequestException as e:
            app.logger.warning("%s /%s -> switch error: %s", request.method, path, e)
            return Response("<h1>502 Switch did not respond</h1><p>%s</p><p>Reload the page to try again.</p>"
                            % type(e).__name__, status=502, mimetype="text/html",
                            headers={"X-Devserver": "switch-error", "Cache-Control": "no-store"})
        status = "passthrough"
        if r.status_code == 200 and name in site.stock and blob is not None and blob != site.stock_blob.get(name):
            try:
                values = extract_values(site.stock[name], body)
                if values is None:
                    status = "no-match"
                    dump(name, body)
                else:
                    missing = set()
                    body = fill(load(blob), [values], missing)
                    status = "rendered" + (" missing=%d" % len(missing) if missing else "")
            except Exception:
                app.logger.exception("rendering %s failed, passing the switch's page through", name)
                dump(name, body)
                status = "error"
        elif r.status_code == 200 and blob is not None and name in site.static_blob \
                and body == site.static_blob[name] and blob != body:
            # handler ran on the switch and answered with the stock page (no values in it):
            # send our version, exactly as the flashed firmware will
            body = blob
            status = "local"
        if r.status_code == 200 and status in ("passthrough", "no-match") and name in site.handled \
                and name != "errormsg.htm" and "errormsg.htm" in site.stock:
            # handlers report failures with the firmware's message template (errormsg.htm)
            values = extract_values(site.stock["errormsg.htm"], body)
            if values is not None:
                err_blob, _ = site.local("errormsg.htm")
                body = fill(load(err_blob), [values], set())
                status = "rendered errormsg.htm"
        if DUMP_ALL and r.status_code == 200 and name:
            dump(name, r.content)  # raw switch output, before any re-rendering
        body = body.replace(sw_host.encode(), request.host.encode())
        out = Response(body, status=r.status_code)
        for k, v in r.raw.headers.items():
            if k.lower() not in HOP:
                out.headers.add(k, v.replace(sw_host, request.host) if k.lower() == "location" else v)
        out.headers["Cache-Control"] = "no-store"
        out.headers["X-Devserver"] = status
        app.logger.info("%s /%s -> %d %s", request.method, path, r.status_code, status)
        return out

    return app


def selftest(site):
    """Render every stock template with synthetic values and check extract+fill reproduces it."""
    import random
    rnd = random.Random(1)
    bad = 0
    for name, t in sorted(site.stock.items()):
        def gen(items, depth=0):
            sc = {}
            for it in items:
                if isinstance(it, tuple) and it[0] == "var":
                    sc[it[1]] = b"v%d" % rnd.randrange(1000)
                elif isinstance(it, tuple):
                    sc[it[1]] = [gen(it[2], depth + 1) for _ in range(rnd.randrange(0, 4))]
            return sc
        vals = gen(t)
        page = fill(t, [vals], set())
        got = extract_values(t, page)
        if got is None or fill(t, [got], set()) != page:
            bad += 1
            print("FAIL", name)
    print("selftest: %d templates, %d failures" % (len(site.stock), bad))
    return bad == 0


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--switch", default="http://192.168.0.239")
    p.add_argument("--bin", default=os.path.join(ROOT, "GS108T-V3.0.4.10.bin"), help="stock firmware")
    p.add_argument("--src", default=os.path.join(ROOT, "web"), help="edited source tree")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8088)  # 8080 is the GhidraMCP bridge
    p.add_argument("--selftest", action="store_true")
    p.add_argument("--minify", action="store_true", help="serve pages minified, exactly as `pack --minify` builds them")
    p.add_argument("--dump", action="store_true", help="save every raw switch page to devserver-dumps/")
    a = p.parse_args()
    global DUMP_ALL
    DUMP_ALL = a.dump
    site = Site(a.bin, a.src, a.minify)
    if a.selftest:
        sys.exit(0 if selftest(site) else 1)
    import logging
    logging.basicConfig(level=logging.INFO)
    # firmware.bin is served with a bare "Content-Length" line; urllib3 warns but reads the body fine
    logging.getLogger("urllib3.connection").setLevel(logging.ERROR)
    make_app(site, a.switch).run(host=a.host, port=a.port, debug=False)


if __name__ == "__main__":
    main()
