#!/usr/bin/env python3
"""Rebuild web/ from the stock firmware plus what this repository tracks (Netgear's files are not in git).

    python3 tools/web_sync.py           # create/update web/ (build.sh runs this)
    python3 tools/web_sync.py --check   # only report what would change; exit 1 if anything would

web/ is the working tree that the dev server, preview.py and pack use. It is made of:
  own files        web/files/<name> listed as "!<name>" in web/files/.gitignore: our work, tracked in git,
                   never written by this tool
  edited stock     web/edits/<name>.edits: an edit script against the stock file (positions plus the
                   text we added; stock text is only referenced, never copied). The edited file lives in web/files.
  generated        help pop-ups and pop_styles.css (tools/convert_help.py), web/manifest.json
  stock            every other file, extracted unchanged from the firmware

Edits to a stock file in web/files are recorded as (or update) its edit script. When an edit script
changes in git (pull, checkout) and the file was not edited since the last sync, the file is rebuilt
from it. If both changed, the tool stops and changes nothing. web/.sync.json remembers the last state.

The stock firmware is GS108T-V3.0.4.10.bin; if it is missing, it is made from GS108T-V3.0.4.10.hex or
from Netgear's zip "GS108Tv1 Firmware Version 3.0.4.10.zip" in the project root (see README).
"""
import argparse, glob, hashlib, io, json, os, re, sys, tempfile, zipfile
from difflib import SequenceMatcher

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gs108t_web as fw
import convert_help

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "GS108T-V3.0.4.10.bin")
HEX = os.path.join(ROOT, "GS108T-V3.0.4.10.hex")
ZIP_GLOB = os.path.join(ROOT, "GS108Tv1*3.0.4.10*.zip")
STOCK_SHA256 = "bb1dd3e062891a923599f9575096904420e9fde3156c3426d54c2f2b6b5f8951"
WEB = os.path.join(ROOT, "web")
FILES = os.path.join(WEB, "files")
EDITS = os.path.join(WEB, "edits")
STATE = os.path.join(WEB, ".sync.json")
OWN_LIST = os.path.join(FILES, ".gitignore")

sha = lambda b: hashlib.sha256(b).hexdigest()


def read(path):
    try:
        return open(path, "rb").read()
    except FileNotFoundError:
        return None


# ---------------------------------------------------------------- stock firmware

def stock_bin():
    """Path of the verified stock .bin, made from the .hex or the vendor zip if needed."""
    if not os.path.exists(BIN):
        src = HEX if os.path.exists(HEX) else None
        if not src:
            for z in sorted(glob.glob(ZIP_GLOB)):
                with zipfile.ZipFile(z) as zf:
                    hexes = [n for n in zf.namelist() if n.endswith("GS108T-V3.0.4.10.hex")]
                    if hexes:
                        with tempfile.NamedTemporaryFile(suffix=".hex", delete=False) as t:
                            t.write(zf.read(hexes[0]))
                        src = t.name
                        break
        if not src:
            sys.exit("missing the stock firmware: put GS108T-V3.0.4.10.bin, GS108T-V3.0.4.10.hex or Netgear's\n"
                     "\"GS108Tv1 Firmware Version 3.0.4.10.zip\" in %s (README: Getting the stock firmware)" % ROOT)
        elf = fw.check_hex(src, quiet=True)
        if src != HEX:
            os.unlink(src)
        if sha(elf) != STOCK_SHA256:
            sys.exit("%s is not the stock GS108T v1 3.0.4.10 firmware (SHA-256 mismatch)" % src)
        open(BIN, "wb").write(elf)
        print("made %s from the upload image" % os.path.basename(BIN))
    if sha(open(BIN, "rb").read()) != STOCK_SHA256:
        sys.exit("%s is not the stock GS108T v1 3.0.4.10 firmware (SHA-256 mismatch)" % BIN)
    return BIN


# ---------------------------------------------------------------- edit scripts
# Format (bytes):  "gs108t-edits 1 <name>\n" "base <sha256>\n" "result <sha256>\n", then commands on units
# of the stock file (1-based), RCS style:
#   d<u> <n>        delete n stock units starting at unit u
#   a<u> <n>        after stock unit u, add the n units that follow in the script (our text)
#   c<u> <from> <n> after stock unit u, insert a copy of stock units from..from+n-1 (moved stock text)
# A unit ends after "\n", ";", "{", "}" or ">", so a small change inside one of the long stock lines (default.css
# has 10 KB lines) does not re-add the whole line. Units contain no newline, so every unit and command is
# split the same way when the script is read back.

def lines(b):
    return re.findall(rb"[^\n;{}>]*[\n;{}>]|[^\n;{}>]+$", b)


def _inserts(at, new, src, where):
    """Commands adding units `new` after stock unit `at`: copies of stock runs, literal text otherwise."""
    out, lit, i = [], [], 0
    def flush():
        if lit:
            out.append(b"a%d %d\n" % (at, len(lit)))
            out.extend(lit)
            del lit[:]
    while i < len(new):
        best = (0, 0)
        if len(new[i]) >= 12:                      # short units ("}\n", "\t\t") are not worth a reference
            for p in where.get(new[i], ()):
                r = 0
                while i + r < len(new) and p + r < len(src) and new[i + r] == src[p + r]:
                    r += 1
                best = max(best, (r, -p))
        if best[0]:
            flush()
            out.append(b"c%d %d %d\n" % (at, -best[1] + 1, best[0]))
            i += best[0]
        else:
            lit.append(new[i])
            i += 1
    flush()
    return out


def make_edits(name, base, new):
    a, b = lines(base), lines(new)
    out = [b"gs108t-edits 1 %s\nbase %s\nresult %s\n" % (name.encode(), sha(base).encode(), sha(new).encode())]
    where = {}
    for p, u in enumerate(a):
        where.setdefault(u, []).append(p)
    for op, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op in ("replace", "delete"):
            out.append(b"d%d %d\n" % (i1 + 1, i2 - i1))
        if op in ("replace", "insert"):
            out.extend(_inserts(i2, b[j1:j2], a, where))
    return b"".join(out)


def apply_edits(name, base, script):
    ls = lines(script)
    head = re.match(rb"gs108t-edits 1 (\S+)\nbase ([0-9a-f]{64})\nresult ([0-9a-f]{64})\n$", b"".join(ls[:3]))
    if not head or head.group(1).decode() != name:
        sys.exit("web/edits/%s.edits: bad header" % name)
    if head.group(2).decode() != sha(base):
        sys.exit("web/edits/%s.edits: made for a different stock file" % name)
    src, out, pos, k = lines(base), [], 0, 3      # pos = stock lines consumed
    while k < len(ls):
        m = re.match(rb"([adc])(\d+) (\d+)(?: (\d+))?\n$", ls[k])
        if not m or (m.group(1) == b"c") != (m.group(4) is not None):
            sys.exit("web/edits/%s.edits: bad command %r" % (name, ls[k][:40]))
        line, count = int(m.group(2)), int(m.group(4) or m.group(3))
        k += 1
        if m.group(1) == b"d":
            out.extend(src[pos:line - 1])
            pos = line - 1 + count
            continue
        out.extend(src[pos:line])
        pos = max(pos, line)
        if m.group(1) == b"a":
            out.extend(ls[k:k + count])
            k += count
        else:
            first = int(m.group(3)) - 1
            out.extend(src[first:first + count])
    out.extend(src[pos:])
    new = b"".join(out)
    if sha(new) != head.group(3).decode():
        sys.exit("web/edits/%s.edits: result does not match its checksum" % name)
    return new


# ---------------------------------------------------------------- sync

def own_files():
    names = []
    for l in open(OWN_LIST, encoding="utf-8").read().splitlines():
        if l.startswith("!") and l[1:] != ".gitignore":
            names.append(l[1:])
    return names


def plan():
    """List of (description, action) where action() performs one write; exits on conflicts."""
    stock, man = fw.stock_tree(stock_bin())
    for e in man["entries"]:                       # every image is the one blank GIF (see CLAUDE.md)
        if e["name"].lower().endswith(".gif"):
            e["content"] = "_blank.gif"
    generated = convert_help.help_pages(stock)
    own = own_files()
    state = json.loads(read(STATE) or b"{}")
    new_state = {}
    todo, conflicts = [], []

    def write(path, blob, why):
        todo.append(("%-8s %s" % (why, os.path.relpath(path, ROOT)), lambda: open(path, "wb").write(blob)))

    def remove(path, why):
        todo.append(("%-8s %s" % (why, os.path.relpath(path, ROOT)), lambda: os.unlink(path)))

    for n in own:
        if n in generated or not os.path.exists(os.path.join(FILES, n)):
            conflicts.append("%s is listed as our own file in web/files/.gitignore but %s" % (
                n, "is generated" if n in generated else "does not exist"))
        if os.path.exists(os.path.join(EDITS, n + ".edits")):
            conflicts.append("%s is our own file but also has web/edits/%s.edits (delete one)" % (n, n))

    m = (json.dumps(man, indent=1)).encode()
    if read(os.path.join(WEB, "manifest.json")) != m:
        write(os.path.join(WEB, "manifest.json"), m, "manifest")
    for n, blob in sorted(generated.items()):
        if read(os.path.join(FILES, n)) != blob:
            write(os.path.join(FILES, n), blob, "help")

    for n, base in sorted(stock.items()):
        if n in own or n in generated:
            continue
        path, epath = os.path.join(FILES, n), os.path.join(EDITS, n + ".edits")
        cur, script, st = read(path), read(epath), state.get(n)
        file_changed = cur is not None and (st is None or st["file"] != sha(cur))
        script_changed = (st or {}).get("edits") != (sha(script) if script else None)
        if script is None and st is None:          # plain stock file, or one just edited for the first time
            if cur is None:
                write(path, base, "stock")
            elif cur != base:
                s = make_edits(n, base, cur)
                write(epath, s, "recorded")
                new_state[n] = {"edits": sha(s), "file": sha(cur)}
            continue
        if script is None:                         # edit script deleted: back to stock unless edited since
            if file_changed and cur != base:
                conflicts.append("web/edits/%s.edits was removed, but web/files/%s was edited since the "
                                 "last sync" % (n, n))
            elif cur != base:
                write(path, base, "stock")
            continue
        result = apply_edits(n, base, script)
        if cur == result:
            new_state[n] = {"edits": sha(script), "file": sha(cur)}
        elif cur is None or not file_changed:     # missing, or only the script changed (git pull)
            write(path, result, "applied")
            new_state[n] = {"edits": sha(script), "file": sha(result)}
        elif not script_changed:                   # edited in web/files: record it
            if cur == base:
                remove(epath, "dropped")
            else:
                s = make_edits(n, base, cur)
                write(epath, s, "recorded")
                new_state[n] = {"edits": sha(s), "file": sha(cur)}
        else:
            conflicts.append("web/files/%s was edited and web/edits/%s.edits changed too: keep one (delete "
                             "the file to take the script, or restore the script with git)" % (n, n))
    if conflicts:
        sys.exit("web_sync: nothing changed, fix first:\n  " + "\n  ".join(conflicts))
    return todo, new_state


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--check", action="store_true", help="report only; exit 1 if web/ is not in sync")
    a = p.parse_args()
    if not os.path.exists(OWN_LIST):
        sys.exit("missing %s" % OWN_LIST)
    todo, new_state = plan()
    for why, _ in todo:
        print("  " + why)
    if a.check:
        print("web/ is in sync" if not todo else "web/ is not in sync (%d)" % len(todo))
        sys.exit(1 if todo else 0)
    os.makedirs(EDITS, exist_ok=True)
    for _, act in todo:
        act()
    blob = json.dumps(new_state, indent=1, sort_keys=True).encode()
    if read(STATE) != blob:
        open(STATE, "wb").write(blob)
    print("web/ in sync (%d %s)" % (len(todo), "change" if len(todo) == 1 else "changes"))


if __name__ == "__main__":
    main()
