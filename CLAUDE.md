# GS108Tv1 web UI rewrite

Goal: replace the IE-era web UI of a Netgear GS108Tv1 (firmware 3.0.4.10) with a modern one that
renders in current browsers, then flash it. Switch on the LAN: http://192.168.0.239.

## Status
- 2026-10-10: build/GS108T-V3.0.4.10-newui-min.hex flashed to the switch (192.168.0.239); new UI confirmed running.
  Stock recovery image: tftp_root/gs108t-firmware.bin (byte-identical to Netgear's .hex).
- 2026-10-11: build 7afa4438 (inline GIFs, ?v= cache busting, no favicon) flashed with tools/flash.py; confirmed.

## Files
- `GS108T-V3.0.4.10.bin` – stock firmware: little-endian MIPS eCos ELF, file offset = vaddr - 0x80000000.
- `GS108Tv1 Firmware Version 3.0.4.10.zip` – vendor zip; its `.hex` is the upload image (gzip of the .bin).
- `web/` – editable UI source: `manifest.json` + `files/`, assembled by `tools/web_sync.py` (see "No Netgear files
  in git"). `web_extracted/` – old one-off dump, untracked, superseded.
- `tools/gs108t_web.py` – extract / pack / verify / checkhex / unhex.
- `tools/devserver.py` – Flask dev server proxying the real switch (venv in `.venv`).
- Ghidra project `gs108t.gpr`, reachable via the ghidra MCP server.

## Commands
```
./build.sh                                          # stock round trip, pack (minified + plain), checks -> build/*.hex
python3 tools/web_sync.py [--check]                  # (re)build web/ from stock + web/edits; build.sh runs it
.venv/bin/python tools/devserver.py                 # http://127.0.0.1:8088 (8080 = GhidraMCP), proxies the switch
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
- File **names cannot be added or renamed**; repoint names instead (web_sync.py points every *.gif at _blank.gif;
  manifest.json is generated, so add such rules there).
- Templates (listed in `manifest.json` "templates") contain `{{var fn=… id=…}}` and `{{block …}} … {{/block}}`.
  These are calls into C code: keep every one (they may be moved/reordered; the devserver can't preview new ones).
- Keep form field names and form `action` targets (`*.cgi`) unchanged – the C handlers parse them.
- Login: POST exactly `password` + `rtime` to `login.cgi`; session cookie `Broadcom-WebSuperSmart` (path=/) +
  client IP. `WSSHID` (path=/login.cgi) = login token, see Sessions.
- Budget: everything must fit the pool; upload image ≤ 0x180000 bytes. `pack` enforces both.

## New UI conventions
- `@@UI_VERSION@@` (System Information > Versions > Web interface) is replaced by `pack --ui-version`; build.sh
  passes `<git short SHA>[-dirty] · <date>` (dirty = uncommitted changes in web/, tools/, build.sh). Commit before a
  release build so the switch shows a clean SHA. The devserver shows "dev server".
- Theme: colour tokens at the start of the new part of default.css (:root light, html[data-theme=dark]); use var(--...)
  never hex. gsTheme() at the top of rollover.js sets data-theme from localStorage "gs108t-theme" (auto/light/dark);
  shell button cycles it. login/passwordwrong inline the same snippet; help pages load rollover.js.
- Converted pages use `<body class="ui">`; their shared styles are appended to `default.css` under `.ui` (old pages unaffected).
- rollover.js (2026-10-11): unreachable functions removed (59.7 -> 29.5 KB) and IE-only code replaced: no
  navigator.appName/window.event/srcElement/returnValue; `document.frames("maincontent")` -> `mainFrame()`
  (top.frames.maincontent, else the page's own window). Pages still use document.frames in 3 fallbacks, so the
  polyfill in index.html stays. Before deleting a function, check every page that loads rollover.js for calls,
  including inline handlers and button strings ('parent.maincontent.apply()').
- Shell `index.html` provides `#ButtonsDiv` (pages paint Cancel/Apply there via rollover.js), iframes `maincontent`/`iw1`,
  a `document.frames()` polyfill, and nav links named `lvl1`.
- Stock `default.css` had a quoted `url('` split across a line break, which made modern browsers drop the rest of the
  sheet; fixed. Watch for other IE-tolerated syntax like this.
- Unconverted pages get the new look from the "legacy skin" at the end of `default.css` (`body:not(.ui)` overrides of
  the old classes) plus `tbhdr*()` in rollover.js emitting `.lhdr` headers. Table-editor pages (row checkboxes,
  `editRow`, rows[]/cells[] scripting) stay on the skin; only simple form pages get hand-rewritten.
- Hand-converted so far: index, login, passwordwrong, sysinfo, managementip, time, jumboframeconfiguration, lacp,
  stpconfiguration, advancedstpconfiguration, igmpsnooping, qosconfiguration, 8021pqueuemap, changepassword,
  auth_type (fixed js/rollover.js path + value=3" typo), devicereboot, factorydefault, fileupload,
  filedownload (validates .hex in-browser like the firmware; boot code is hidden until the list is opened with Shift held, then needs typed confirmation), support, userguide.
- Help pop-ups (79 *_help.html, help1.html with #anchors, help.html): generated by `tools/convert_help.py` from the
  stock firmware into a shared `pop_styles.css` layout; text verified identical to stock. web_sync.py regenerates them on every run: edit convert_help.py, not the pages.
- counter.cgi (port statistics) is blocked by ad blockers; allowlist the switch/devserver.
- Flash directly against the switch, not through the devserver (it serialises requests, so upload progress polling stalls). Inline `go_on.gif` buttons are restyled by CSS.
- `.venv/bin/python tools/preview.py page.html ...` checks placeholders vs stock and screenshots with headless Edge
  (sample values, no switch needed). Run it for every page you touch.

## No Netgear files in git (2026-10-11)
Netgear's firmware and pages must not be redistributed; history was rewritten to drop them (also the Ghidra project,
.mcp.json, ghidra/). `tools/web_sync.py` builds web/ from the stock firmware (makes the .bin from the .hex or the
vendor zip if needed):
- own files: `web/files/.gitignore` is `*` plus `!name` per own file (30 rewritten pages + _blank.gif); tracked.
- edited stock (rollover.js, default.css, stormcontrol.html, communityconfigurationbasic.html):
  `web/edits/<name>.edits`, RCS-style script on units (split after \n ; { } >): `d`elete / `a`dd our text /
  `c`opy stock units by position, with base+result sha256. Contains no stock text: keep it that way (a changed
  line ending re-adds the line; stormcontrol had lost its CRLFs once).
- generated: help pop-ups + pop_styles.css (convert_help.help_pages), manifest.json (stock + gif rule). Untracked.
- state in web/.sync.json: file edited -> script re-recorded; script changed (pull) -> file rebuilt; both -> stop.
- Own-or-patch rule of thumb: a page that is mostly our text becomes own; mostly-stock pages stay edit scripts.

## Upload image (.hex)
gzip, flags exactly FNAME|FCOMMENT, FNAME `_GS108Tv1h1_bcm.robo_`, FCOMMENT `%08X%04X` =
payload length after header + 16-bit byte sum of that payload. No signature. Two flash banks (seq marker `AC xx xx 47`).

## GIFs
- All 166 *.gif names point at files/_blank.gif (1x1 transparent). The names must stay: scripts swap _on/_off and
  grey_b/x/t/u in img src, and CSS hides those imgs. Verified pixel-identical on 12 pages before/after.
- Post-action pages (fdload/fuload/cdload/cuload/restore/dispdwnstat/cfeupgrade .cgi, errormsg.htm) are rewritten.
- devserver always proxies names that have a firmware handler (manifest "cgi" != 0), e.g. dlrestart.cgi.

## Build-time rewrites (`rewrite_web` in gs108t_web.py; pack and devserver both apply them)
The switch loses ~5% of its outgoing packets and recovers only via a 1-2 s TCP retransmission timeout
(measured with tcpdump, same over Wi-Fi), so every request and every KB per page view costs. Sources stay as-is:
- `src="x.gif"` (also `../../App_themes/.../x.gif`, and rollover.js's `'<img src='+name+'_on.gif`) becomes
  `src="data:image/gif;base64,<_blank.gif>#x.gif"`: no request, and scripts still see the name at the end of
  img.src (they only use suffixes: substring(len-5), Parse_imgSrc = last 10 chars, /on\.gif$/). CSS
  `url(x.gif)` becomes `none`. Never write code that parses img.src from the front or by "/".
- `href="default.css"` / `src="rollover.js"` get `?v=<sha256 of the file, 8 hex>`: the switch caches .css/.js
  for 30 days with a fixed Last-Modified, and ignores query strings, so this busts stale caches after a flash.
- `verify` packs with rewrite=False (stock round trip stays byte-identical).
- Top-level pages (index, login, passwordwrong, help pop-ups) have `<link rel="icon" href="data:,">`; the switch
  has no favicon and every request costs.
- Each headless-browser login takes one of the switch's 4 session slots until the idle timeout (no logout
  frees it); after a few test runs the switch answers "Maximal number of logined user reached!". Unless it
  logs in with a fixed `rtime` (or sends its old `WSSHID`): then it replaces its previous session (see Sessions).

## Flashing (findings from Ghidra)
- Dual-bank flash (when flash >= 4 MB): banks at 0x80000 and 0x240000, 0x1c0000 each; boot code below 0x80000.
  fw_access_open @0x800a9618 (0=running bank, 1=other bank, 2=boot). fupgrade writes the *other* bank, verifies
  the sum16, and only then appends marker `AC seq_lo seq_hi 47` with seq = running+1. Running bank = higher seq
  (fw_banks_probe @0x800a93bc, fw_bank_get_seq @0x800a9330; wrap: 1 beats 0x7fff).
  So a rejected/interrupted upload leaves the running image intact. CFE's own choice logic is not in this ELF (unverified).
- Time (cgi_time @0x8008951c): the system clock holds LOCAL time. tz_set_offset_shift_clock shifts the clock by
  (new - old offset); manual mode sets the zone, then clock_set_local_time overwrites the clock with the entered
  time, so the zone never alters a manually entered time (but changing only the zone later shifts the clock).
  SNTP time (UTC) gets the zone offset added. time.cgi never reads inp3.
- Sessions (cgi_login @0x8007c1a0): cookie `Broadcom-WebSuperSmart` = 8-hex prefix (checksum of user name +
  password, session_init_prefix) + `%08X%08X` (session id from system time, last use); valid if a slot has that
  id AND the client IP, and not idle too long (session_validate_cookie). 4 slots. Login token = `WSSHID` cookie
  (hex) if sent, else the `rtime` field (decimal, page sends ms/500); a new login whose token equals an active
  session's token preempts that session and reuses its slot (session_create_or_cookie). New tokens get
  `Set-Cookie: WSSHID=<hex>; path=/login.cgi`. tools/flash.py uses a fixed rtime for this.
- `tools/tftp_server.py` (sudo, port 69): receives switch uploads (File Upload > TFTP). The switch sends DATA to
  port 69, not to the server's new transfer port (RFC 1350), so the server runs each transfer on port 69, one at a
  time. Writes <name>.part, renames after the last block, ACKs that block only then; keeps existing files unless
  --overwrite (tftp_root/ holds the stock recovery image). Upload only: read requests get ERROR 4.
- Switch TFTP client = tftp_client_put @0x801e2934 (get @0x801e2428): 5 s select per ACK, gives up silently
  (error 8, no TFTP ERROR packet) after 50 timeouts in the whole transfer (counter never reset); an ACK for another
  block makes it resend at once without counting. With ~5% loss a 2400-block backup died after 700-1100 blocks (also
  with the original tool). Fix in tftp_server.py: re-ACK the previous block after 1 s ("kick"), never answer
  duplicate blocks (Sorcerer's Apprentice). Simulated 5% and 10% loss: complete, 0 switch timeouts. It sends no
  empty final block when the size is a multiple of 512 (server then cannot detect the end).
- `tools/flash.py IMAGE.hex [--upload]`: validates, logs in, posts to fupgrade.cgi (UI-independent recovery path).
  The switch writes flash while receiving and can stall >10 s mid-upload; requests keeps the *connect* timeout on
  the socket while sending the body, so flash.py uses timeout=(300, 900). A failed upload leaves the running bank alone.
- Build: `python3 tools/gs108t_web.py pack GS108T-V3.0.4.10.bin web -o build/X.bin --hex build/X.hex`; the diff vs
  stock must be table+pool only (no .text bytes). Running switch = vendor 3.0.4.10 image (verified via backup prefix).

## Safety
- Never flash via `cfeupgrade.cgi` (bootloader). Use the normal firmware upgrade page only.
- Unknown whether CFE falls back to the other bank on a bad image – have a serial-console recovery path before flashing.
- Don't flash without `checkhex` passing and the UI tested through the devserver.
