#!/usr/bin/env python3
"""Extract / repack the embedded web UI of the Netgear GS108Tv1 firmware (3.0.4.10).

Firmware layout (little-endian MIPS eCos ELF, vaddr 0x80001000 at file offset 0x1000):

  file table   @0x802ba098   N x 16 bytes {char *name, cgi_fn, record *desc, u32 flags}
                             sorted by name, first entry "" (= default page), ends at name==0
  web pool     one contiguous block in .data holding every file's text + record list
  record       12 bytes {u8 kind, u8 span, u16 len_or_id, u32 arg, u32 ptr}
                 kind 0x00          text chunk   (len, ptr)
                 kind 0x02/12/22    dynamic var  (id, arg, ptr = C handler printing it)
                 kind 0x01          block begin (ptr = iterator fn) / end (ptr = 0),
                                    span = record distance begin->end
                 kind |= 0x80       last record of the file (static file = one 0x80 text record)
  pool layout  per file: text chunks in record order, each 4-aligned, then the records (4-aligned);
               next file starts right after; rest of the pool is zero.

Upload image (.hex) = gzip of the ELF with
  FNAME   "_GS108Tv1h1_bcm.robo_"
  FCOMMENT "%08X%04X" % (len(payload), sum(payload) & 0xffff)   payload = bytes after the header
  (checked by cgi_fupgrade_app / FUN_800a8fd0 / FUN_800a9214; no signature). Max upload 0x180000.

Source tree written by `extract`:
  manifest.json   table entries (name -> content, cgi, flags) + pool layout order
  files/<id>      static files verbatim; templates with placeholders:
                    {{var fn=0x800820b0 id=1}}              optional: arg=N kind=0x12
                    {{block fn=0x80080440 id=0}} ... {{/block}}   optional: id=N on /block
"""
import argparse, gzip, hashlib, io, json, os, re, struct, sys, tempfile, zlib

TABLE = 0x802ba098
FNAME = b"_GS108Tv1h1_bcm.robo_"
GZ_MTIME = 0x4BBED77B          # mtime of the vendor 3.0.4.10 image, keeps builds reproducible
MAX_UPLOAD = 0x180000
TAG = re.compile(rb"\{\{(var|block|/block)((?:\s+[a-z]+=[0-9a-fA-Fx]+)*)\s*\}\}")


class Image:
    def __init__(self, data):
        self.d = bytearray(data)
        if self.d[:4] != b"\x7fELF" or self.d[5] != 1:
            sys.exit("not a little-endian ELF")
        phoff, = struct.unpack_from("<I", self.d, 0x1c)
        _, off, vaddr, _, filesz, _, _, _ = struct.unpack_from("<8I", self.d, phoff)
        self.delta, self.lo, self.hi = vaddr - off, vaddr, vaddr + filesz

    def o(self, a):
        if not self.lo <= a < self.hi:
            raise ValueError("address %#x outside loaded image" % a)
        return a - self.delta

    def u32(self, a):
        return struct.unpack_from("<I", self.d, self.o(a))[0]

    def put(self, a, b):
        self.d[self.o(a):self.o(a) + len(b)] = b

    def cstr(self, a):
        o = self.o(a)
        return bytes(self.d[o:self.d.index(0, o)]).decode("latin1")

    def table(self):
        rows, a = [], TABLE
        while self.u32(a):
            n, cgi, desc, fl = struct.unpack_from("<4I", self.d, self.o(a))
            rows.append(dict(addr=a, name=self.cstr(n), cgi=cgi, desc=desc, flags=fl))
            a += 16
        if rows[0]["name"] != "" or rows[1]["name"] != "1xconfig.html":
            sys.exit("file table not found at %#x - different firmware version?" % TABLE)
        return rows

    def records(self, desc):
        recs, a = [], desc
        while True:
            w, arg, ptr = struct.unpack_from("<3I", self.d, self.o(a))
            recs.append(dict(kind=w & 0xff, span=(w >> 8) & 0xff, val=w >> 16, arg=arg, ptr=ptr))
            a += 12
            if w & 0x80:
                return recs, a


def is_text(r):
    return r["kind"] & 0x7f == 0


def align4(x):
    return (x + 3) & ~3


# ---------------------------------------------------------------- decode / encode templates

def render(img, recs):
    """records -> (bytes, is_template)"""
    if len(recs) == 1 and recs[0]["kind"] == 0x80 and not recs[0]["arg"]:
        r = recs[0]
        return bytes(img.d[img.o(r["ptr"]):img.o(r["ptr"]) + r["val"]]), False
    out, opened = [], []
    for i, r in enumerate(recs):
        k = r["kind"] & 0x7f
        if k == 0:
            out.append(bytes(img.d[img.o(r["ptr"]):img.o(r["ptr"]) + r["val"]]) if r["val"] else b"")
            continue
        attrs = ""
        if k & 2:
            attrs = " fn=%#x id=%d" % (r["ptr"], r["val"])
            if r["arg"]:
                attrs += " arg=%d" % r["arg"]
            if k != 2:
                attrs += " kind=%#x" % k
            out.append(b"{{var%s}}" % attrs.encode())
        elif k & 1 and r["ptr"]:
            opened.append((i, r))
            attrs = " fn=%#x id=%d" % (r["ptr"], r["val"])
            if k != 1 or r["arg"]:
                attrs += " kind=%#x arg=%d" % (k, r["arg"])
            out.append(b"{{block%s}}" % attrs.encode())
        elif k & 1:
            j, b = opened.pop()
            if r["span"] != i - j or b["span"] != i - j:
                raise ValueError("block span mismatch")
            attrs = " id=%d" % r["val"] if r["val"] != b["val"] else ""
            out.append(b"{{/block%s}}" % attrs.encode())
        else:
            raise ValueError("unknown record kind %#x" % r["kind"])
    return b"".join(out), True


def parse(blob):
    """template bytes -> list of records (ptr of text records = bytes)"""
    recs, stack, pos = [], [], 0

    def text(t):
        for i in range(0, len(t), 0xffff):
            recs.append(dict(kind=0, span=0, val=len(t[i:i + 0xffff]), arg=0, ptr=t[i:i + 0xffff]))

    for m in TAG.finditer(blob):
        text(blob[pos:m.start()])
        pos = m.end()
        a = {k.decode(): int(v, 0) for k, v in re.findall(rb"([a-z]+)=([0-9a-fA-Fx]+)", m.group(2))}
        tag = m.group(1)
        if tag == b"var":
            recs.append(dict(kind=a.get("kind", 2), span=0, val=a["id"], arg=a.get("arg", 0), ptr=a["fn"]))
        elif tag == b"block":
            stack.append(len(recs))
            recs.append(dict(kind=a.get("kind", 1), span=0, val=a["id"], arg=a.get("arg", 0), ptr=a["fn"]))
        else:
            if not stack:
                raise ValueError("{{/block}} without {{block}} at byte %d" % m.start())
            j = stack.pop()
            span = len(recs) - j
            if span > 0xff:
                raise ValueError("block too long (%d records)" % span)
            recs[j]["span"] = span
            recs.append(dict(kind=1, span=span, val=a.get("id", recs[j]["val"]), arg=0, ptr=0))
    if stack:
        raise ValueError("unclosed {{block}}")
    tail = blob[pos:]
    if tail or not recs:
        text(tail)
    recs[-1]["kind"] |= 0x80
    return recs


# ---------------------------------------------------------------- extract

def extract(bin_path, out):
    img = Image(open(bin_path, "rb").read())
    rows = img.table()
    by_desc = {}
    for r in rows:
        by_desc.setdefault(r["desc"], []).append(r["name"])
    ids = {}
    for desc, names in by_desc.items():
        pick = [n for n in names if n and not n.endswith(".cgi")] or [n for n in names if n] or ["_default"]
        ids[desc] = pick[0]
    os.makedirs(os.path.join(out, "files"), exist_ok=True)
    for desc, cid in ids.items():
        recs, _ = img.records(desc)
        blob, _ = render(img, recs)
        with open(os.path.join(out, "files", cid), "wb") as f:
            f.write(blob)
    man = dict(
        format=1,
        source=dict(file=os.path.basename(bin_path), sha256=hashlib.sha256(img.d).hexdigest()),
        templates=sorted(cid for desc, cid in ids.items() if render(img, img.records(desc)[0])[1]),
        entries=[dict(name=r["name"], content=ids[r["desc"]], cgi="%#x" % r["cgi"], flags="%#x" % r["flags"])
                 for r in rows],
        layout=[ids[d] for d in sorted(ids)],
    )
    with open(os.path.join(out, "manifest.json"), "w") as f:
        json.dump(man, f, indent=1)
    print("extracted %d table entries, %d files -> %s" % (len(rows), len(ids), out))


# ---------------------------------------------------------------- pack

def pool_range(img):
    lo, hi = None, 0
    for r in img.table():
        recs, end = img.records(r["desc"])
        starts = [x["ptr"] for x in recs if is_text(x) and x["val"]] + [r["desc"]]
        lo = min(starts + ([lo] if lo else []))
        hi = max(hi, end)
    return lo, hi


def pack(bin_path, src, out_bin):
    img = Image(open(bin_path, "rb").read())
    rows = img.table()
    man = json.load(open(os.path.join(src, "manifest.json")))
    if [e["name"] for e in man["entries"]] != [r["name"] for r in rows]:
        sys.exit("manifest entry names differ from the firmware table (names cannot be added/renamed)")
    lo, hi = pool_range(img)
    templates = set(man["templates"])
    used = [e["content"] for e in man["entries"]]
    order = [c for c in man["layout"] if c in used]
    order += [c for c in dict.fromkeys(used) if c not in order]

    pool = bytearray()
    desc_of = {}
    for cid in order:
        blob = open(os.path.join(src, "files", cid), "rb").read()
        if cid in templates:
            recs = parse(blob)
        else:
            if len(blob) > 0xffff:
                sys.exit("%s: static file larger than 65535 bytes" % cid)
            recs = [dict(kind=0x80, span=0, val=len(blob), arg=0, ptr=blob)]
        for r in recs:
            if is_text(r) and isinstance(r["ptr"], bytes):
                if r["val"]:
                    t, r["ptr"] = r["ptr"], lo + len(pool)
                    pool += t
                    pool += bytes(align4(len(pool)) - len(pool))
                else:
                    r["ptr"] = 0
        desc_of[cid] = lo + len(pool)
        for r in recs:
            pool += struct.pack("<3I", r["kind"] | r["span"] << 8 | r["val"] << 16, r["arg"], r["ptr"])
    if lo + len(pool) > hi:
        sys.exit("web content too large: %d bytes over the %d byte pool" % (lo + len(pool) - hi, hi - lo))
    img.put(lo, bytes(pool) + bytes(hi - lo - len(pool)))
    for r, e in zip(rows, man["entries"]):
        img.put(r["addr"] + 4, struct.pack("<3I", int(e["cgi"], 0), desc_of[e["content"]], int(e["flags"], 0)))
    with open(out_bin, "wb") as f:
        f.write(img.d)
    print("packed %d files into %s: pool %d/%d bytes used (%d free)"
          % (len(order), out_bin, len(pool), hi - lo, hi - lo - len(pool)))
    return bytes(img.d)


# ---------------------------------------------------------------- upload image (.hex)

def make_hex(elf, out_hex):
    c = zlib.compressobj(9, zlib.DEFLATED, -15, 8)
    payload = c.compress(elf) + c.flush() + struct.pack("<II", zlib.crc32(elf), len(elf) & 0xffffffff)
    comment = b"%08X%04X" % (len(payload), sum(payload) & 0xffff)
    hdr = b"\x1f\x8b\x08\x18" + struct.pack("<I", GZ_MTIME) + b"\x02\x03" + FNAME + b"\0" + comment + b"\0"
    data = hdr + payload
    if len(data) > MAX_UPLOAD:
        sys.exit("upload image %d bytes exceeds the %d byte limit" % (len(data), MAX_UPLOAD))
    with open(out_hex, "wb") as f:
        f.write(data)
    print("wrote %s (%d bytes, comment %s)" % (out_hex, len(data), comment.decode()))


def check_hex(path, quiet=False):
    """Validate an upload image the way the firmware does; returns the decompressed ELF."""
    h = open(path, "rb").read()
    fail = lambda m: sys.exit("%s: %s" % (path, m))
    if h[:3] != b"\x1f\x8b\x08" or h[3] != 0x18:
        fail("bad gzip magic/flags (need 1f8b08, flags FNAME|FCOMMENT only)")
    o = 10
    e = h.index(b"\0", o)
    fname = h[o:e]
    o = e + 1
    e = h.index(b"\0", o)
    comment = h[o:e]
    o = e + 1
    if fname != FNAME:
        fail("FNAME %r is not %r" % (fname, FNAME))
    if len(comment) != 12:
        fail("comment must be 12 hex chars, got %r" % comment)
    plen, psum = int(comment[:8], 16), int(comment[8:], 16)
    payload = h[o:]
    if plen != len(payload):
        fail("length in comment %#x != payload %#x" % (plen, len(payload)))
    if sum(payload) & 0xffff != psum:
        fail("checksum in comment %#x != %#x" % (psum, sum(payload) & 0xffff))
    if len(h) > MAX_UPLOAD:
        fail("larger than upload limit %#x" % MAX_UPLOAD)
    elf = gzip.decompress(h)  # also verifies CRC32 / ISIZE
    if elf[:4] != b"\x7fELF":
        fail("payload is not an ELF")
    if not quiet:
        print("%s: OK  (%d bytes, ELF %d bytes, sha256 %s)" % (path, len(h), len(elf), hashlib.sha256(elf).hexdigest()[:16]))
    return elf


# ---------------------------------------------------------------- verify

def verify(bin_path):
    orig = open(bin_path, "rb").read()
    with tempfile.TemporaryDirectory() as t:
        extract(bin_path, os.path.join(t, "src"))
        new = pack(bin_path, os.path.join(t, "src"), os.path.join(t, "out.bin"))
        if new != orig:
            diff = [i for i in range(len(orig)) if orig[i] != new[i]]
            sys.exit("round trip FAILED: %d bytes differ, first at file offset %#x" % (len(diff), diff[0]))
        print("round trip OK: repacked ELF is byte-identical to %s" % bin_path)
        make_hex(new, os.path.join(t, "out.hex"))
        if check_hex(os.path.join(t, "out.hex")) != orig:
            sys.exit("upload image does not decompress to the original ELF")
        print("upload image OK: decompresses to the identical ELF")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    s = p.add_subparsers(dest="cmd", required=True)
    a = s.add_parser("extract", help="firmware .bin -> editable source tree")
    a.add_argument("bin"); a.add_argument("out")
    a = s.add_parser("pack", help="source tree + stock .bin -> new .bin (and .hex)")
    a.add_argument("bin"); a.add_argument("src"); a.add_argument("-o", "--out", required=True)
    a.add_argument("--hex", help="also write the gzip upload image")
    a = s.add_parser("verify", help="prove extract+pack reproduces the stock image")
    a.add_argument("bin")
    a = s.add_parser("checkhex", help="validate an upload image like the firmware does")
    a.add_argument("hex", nargs="+")
    a = s.add_parser("unhex", help="upload image -> .bin")
    a.add_argument("hex"); a.add_argument("out")
    args = p.parse_args()
    if args.cmd == "extract":
        extract(args.bin, args.out)
    elif args.cmd == "pack":
        elf = pack(args.bin, args.src, args.out)
        if args.hex:
            make_hex(elf, args.hex)
            check_hex(args.hex)
    elif args.cmd == "verify":
        verify(args.bin)
    elif args.cmd == "checkhex":
        for h in args.hex:
            check_hex(h)
    elif args.cmd == "unhex":
        open(args.out, "wb").write(check_hex(args.hex))


if __name__ == "__main__":
    main()
