#!/usr/bin/env python3
"""Conservative minifier for the GS108T web files (used by `gs108t_web.py pack --minify`
and `devserver.py --minify`).

Safe by construction for the old Netgear code:
  * JavaScript keeps every line break (the stock scripts rely on automatic semicolon insertion);
    only indentation, trailing spaces, blank lines and whole-line // or /* */ comments go.
  * HTML: comments outside <script>/<style> removed, whitespace between tags collapsed;
    <script>/<style>/<pre>/<textarea> bodies handled by their own rules / left alone.
  * {{var ...}} / {{block ...}} placeholders are never touched (they contain no whitespace runs
    that matter and are matched as opaque text).
Works on bytes (latin-1) so non-ASCII content round-trips unchanged.
"""
import re

RAW = re.compile(rb"(<(script|style|pre|textarea)\b[^>]*>)(.*?)(</\2\s*>)", re.I | re.S)


def minify_js(b):
    out, in_block = [], False
    for line in b.split(b"\n"):
        s = line.strip()
        if in_block:                      # inside a /* ... */ that started on its own line
            if b"*/" in s:
                in_block = False
                rest = s[s.index(b"*/") + 2:].strip()
                if rest:
                    out.append(rest)
            continue
        if not s or s.startswith(b"//"):
            continue
        if s.startswith(b"/*") and b"*/" not in s:
            in_block = True
            continue
        if s.startswith(b"/*") and s.endswith(b"*/") and s.count(b"*/") == 1:
            continue
        out.append(s)
    return b"\n".join(out)


def minify_css(b):
    b = re.sub(rb"/\*.*?\*/", b"", b, flags=re.S)
    b = re.sub(rb"\s+", b" ", b)
    b = re.sub(rb"\s*([{};:,>])\s*", rb"\1", b)
    return b.replace(b";}", b"}").strip()


def _html_text(b):
    b = re.sub(rb"<!--(?!\[if).*?-->", b"", b, flags=re.S)        # comments (keep IE conditionals)
    b = re.sub(rb"[ \t\r\f\v]*\n[\s]*", b"\n", b)                  # indentation / blank lines
    b = re.sub(rb"[ \t\r\f\v]{2,}", b" ", b)                       # runs of spaces
    return b


def minify_html(b):
    out, pos = [], 0
    for m in RAW.finditer(b):
        out.append(_html_text(b[pos:m.start()]))
        tag, body = m.group(2).lower(), m.group(3)
        if tag == b"script":
            body = minify_js(body)
            # old pages hide scripts in <!-- ... //--> ; that is JS syntax here, keep it
        elif tag == b"style":
            body = minify_css(body)
        out.append(m.group(1) + body + m.group(4))
        pos = m.end()
    out.append(_html_text(b[pos:]))
    return b"".join(out).strip() + b"\n"


def minify(name, b):
    n = name.lower()
    if n.endswith((".html", ".htm", ".cgi")):
        return minify_html(b)
    if n.endswith(".js"):
        return minify_js(b) + b"\n"
    if n.endswith(".css"):
        return minify_css(b) + b"\n"
    return b
