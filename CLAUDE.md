# GS108Tv1 web UI rewrite

Goal: replace the IE-era web UI of a Netgear GS108Tv1 (firmware 3.0.4.10) with a modern one that
renders in current browsers, then flash it. Switch on the LAN: http://192.168.0.239.

## Files
- `GS108T-V3.0.4.10.bin` – stock firmware: little-endian MIPS eCos ELF, file offset = vaddr - 0x80000000.
- `GS108Tv1 Firmware Version 3.0.4.10.zip` – vendor zip; its `.hex` is the upload image (gzip of the .bin).
- `web/` – editable UI source (from `tools/gs108t_web.py extract`): `manifest.json` + `files/`.
- `web_extracted/` – old one-off dump, superseded by `web/`, not repackable.
- `tools/gs108t_web.py` – extract / pack / verify / checkhex / unhex.
- `tools/devserver.py` – Flask dev server proxying the real switch (venv in `.venv`).
- Ghidra project `gs108t.gpr`, reachable via the ghidra MCP server.

## Commands
```
.venv/bin/python tools/devserver.py                 # http://127.0.0.1:8080, proxies the switch
.venv/bin/python tools/devserver.py --selftest      # offline template-matching test
python3 tools/gs108t_web.py verify GS108T-V3.0.4.10.bin   # stock round trip must stay byte-identical
python3 tools/gs108t_web.py pack GS108T-V3.0.4.10.bin web -o out.bin --hex out.hex
python3 tools/gs108t_web.py checkhex out.hex
```
Run `--selftest` and `verify` after changing either tool.

## Firmware web storage
- File table @0x802ba098: 387 entries `{name, cgi_fn, desc, flags}` sorted by name, entry 0 = "" (default page → login.html).
- All web content is one contiguous pool in .data (0x802bb9e8, 1,228,376 bytes); pack rewrites only table + pool.
- Each file = 12-byte records `{u8 kind, u8 span, u16 len/id, u32 arg, u32 ptr}`: 0x00 text, 0x02/0x12/0x22 var,
  0x01 block begin/end, |0x80 = last record. Static files are a single 0x80 record (max 65535 bytes).
- C code generates no HTML referencing images/CSS (only `logview.htm` links and simple message pages).

## Rules for editing `web/files`
- File **names cannot be added or renamed**; repoint names in `manifest.json` instead (e.g. all unused GIFs → one tiny file).
- Templates (listed in `manifest.json` "templates") contain `{{var fn=… id=…}}` and `{{block …}} … {{/block}}`.
  These are calls into C code: keep every one (they may be moved/reordered; the devserver can't preview new ones).
- Keep form field names and form `action` targets (`*.cgi`) unchanged – the C handlers parse them.
- Login: POST `password` (+ `rtime`) to `login.cgi`; session cookie `WSSHID` (path=/login.cgi) + client IP.
- Budget: everything must fit the pool; upload image ≤ 0x180000 bytes. `pack` enforces both.

## Upload image (.hex)
gzip, flags exactly FNAME|FCOMMENT, FNAME `_GS108Tv1h1_bcm.robo_`, FCOMMENT `%08X%04X` =
payload length after header + 16-bit byte sum of that payload. No signature. Two flash banks (seq marker `AC xx xx 47`).

## Safety
- Never flash via `cfeupgrade.cgi` (bootloader). Use the normal firmware upgrade page only.
- Unknown whether CFE falls back to the other bank on a bad image – have a serial-console recovery path before flashing.
- Don't flash without `checkhex` passing and the UI tested through the devserver.
