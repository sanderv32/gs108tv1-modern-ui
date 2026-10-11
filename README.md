# GS108T v1 — modern web interface

A replacement web UI for the **Netgear GS108T v1** smart switch (firmware **3.0.4.10**, the last release
Netgear published for it). The stock interface was built for Internet Explorer and no longer works properly
in current browsers. This project rewrites it, packs it back into the firmware and produces an image that
the switch accepts through its normal firmware upgrade.

Only the web content inside the firmware is replaced. **The switch software itself is unchanged**: the
build checks that not a single byte of program code differs from Netgear's image.

## What changed for the user

- Modern shell: top tabs, a sidebar per section, and a button bar for Apply / Cancel.
- Light, dark and auto (follows the OS) theme, switchable from the top bar.
- Simple settings pages rewritten from scratch (System, IP, time, RSTP, LACP, jumbo frames, IGMP snooping,
  QoS, password, authentication, reboot, factory default, file up/download, support).
- Table-editor pages (VLANs, LAGs, ports, ACLs, statistics, logs, …) keep Netgear's original logic and get a
  new look through a stylesheet "skin", so their behaviour is exactly the original.
- 79 help pop-ups converted to the new layout (text unchanged).
- Fixes for bugs in the stock pages, among others:
  - BootP sent an empty management VLAN.
  - Authentication Type loaded its script from a non-existent path.
  - `default.css` contained a line break inside a string, so modern browsers dropped most of the stylesheet.
  - Selected table rows were not highlighted.
- Firmware upload validates the image in the browser exactly as the switch does before anything is sent.
  Boot-code (bootloader) uploads need a typed confirmation.
- Web content in the firmware went from 1,228,376 to 692,224 bytes (minified build); all images are replaced by CSS.

## Requirements

- macOS or Linux with Python 3.10+.
- The stock firmware `GS108T-V3.0.4.10.bin`; see "Getting the stock firmware" below.
- For the dev server: a virtualenv with Flask and requests.
- Optional: Microsoft Edge or Chrome for headless previews (`tools/preview.py`); Ghidra plus the
  [GhidraMCP](https://github.com/LaurieWired/GhidraMCP) bridge for reverse engineering (see below).

```
python3 -m venv .venv
.venv/bin/pip install flask requests
```

## Quick start

```
# 1. develop against the real switch (no flashing needed)
.venv/bin/python tools/devserver.py                 # http://localhost:8088
.venv/bin/python tools/devserver.py --minify        # serve exactly what will be flashed

# 2. build the firmware image
./build.sh                                          # -> build/GS108T-V3.0.4.10-newui-min.hex

# 3. flash (dry run first, then --upload)
.venv/bin/python tools/flash.py build/GS108T-V3.0.4.10-newui-min.hex
.venv/bin/python tools/flash.py build/GS108T-V3.0.4.10-newui-min.hex --upload
```

The switch address defaults to `http://192.168.0.239`; pass `--switch http://<ip>` to change it.

## Project layout

| Path | What |
|---|---|
| `web/files/` | The web UI: every file the switch serves. Edit here. |
| `web/manifest.json` | Firmware file table: name → content file, CGI handler, flags; plus pool order. |
| `tools/gs108t_web.py` | `extract`, `pack`, `verify`, `checkhex`, `unhex`: firmware ⇄ `web/`. |
| `tools/devserver.py` | Flask dev server that serves `web/` and proxies the real switch. |
| `tools/preview.py` | Placeholder check plus headless screenshot of pages, with sample data, without a switch. |
| `tools/minify.py` | Conservative HTML/CSS/JS minifier used by `pack --minify` and `devserver --minify`. |
| `tools/convert_help.py` | Regenerates the help pop-ups from the stock firmware. |
| `tools/flash.py` | Logs in and uploads an image to `fupgrade.cgi`, independent of the web UI. |
| `build.sh` | Full build plus checks. |
| `CLAUDE.md` | Detailed technical notes (firmware format, conventions, findings). |

## The dev server

`tools/devserver.py` lets you redesign pages against live data:

- **Static files** (CSS, JS, images, static HTML) come from `web/files/`.
- **Template pages** are fetched from the switch. The values are pulled out by matching the response against
  the stock template, then filled into your edited template.
- **Everything else** (all POSTs, CGIs) is passed straight to the switch.

The `X-Devserver` response header tells you what happened: `rendered`, `passthrough`, `no-match` or
`switch-error`. `--dump` saves every raw switch response to `devserver-dumps/`; `--selftest` checks the
matcher offline.

Port **8088** is the default because the GhidraMCP bridge uses 8080.

## Editing rules

The firmware serves a fixed set of 387 file names, and many pages are templates whose values are filled in
by C code. So:

1. **File names cannot be added or renamed.** To drop a file, point its entry in `manifest.json` at another
   content file (for example `_blank.gif`).
2. **Keep every placeholder.** `{{var fn=… id=…}}` and `{{block …}} … {{/block}}` are calls into the firmware.
   They may move or repeat, but must not disappear. `tools/preview.py page.html` checks this.
3. **Keep form field names and `.cgi` targets.** The C handlers parse them, sometimes by position (for
   example `dot1pqos.cgi` reads its 8 values in order).
4. **Respect the limits.** All content must fit the 1,228,376-byte pool, each static file must stay under
   64 KB, and the upload image must stay under 1.5 MB. `pack` enforces all three.

Converted pages use `<body class="ui">` and the styles at the end of `default.css`. Colours are theme
variables (`var(--surface)`, `var(--text)`, …), never hex values.

`pack` (and the dev server) rewrite two things on the way out, so the sources stay readable:

- **Images:** `src="x.gif"` becomes an inline blank image with the name kept after a `#`, so no
  request reaches the switch, while the old scripts that switch `x_on.gif`/`x_off.gif` keep working. Those
  scripts only look at the end of `img.src`; new code must do the same.
- **Cache busting:** `default.css`, `rollover.js` and the other stylesheets and scripts are referenced as
  `default.css?v=<hash of the file>`. The switch tells browsers to cache them for 30 days, so without this a
  browser would keep using the old files after a flash.

The switch's network stack is slow to recover from lost packets (each loss costs 1–2 seconds), so fewer
requests and smaller pages make the UI noticeably faster.

## Getting the stock firmware

The build needs Netgear's firmware **3.0.4.10** as `GS108T-V3.0.4.10.bin` in the project root. It must be
exactly this version: the pack tool works with addresses inside this specific image, and `build.sh` refuses
any other file. There are two ways to get it:

1. **From Netgear.** Download `GS108Tv1 Firmware Version 3.0.4.10.zip` from the
   [GS108Tv1 support page](https://support.netgear.com/support/product/gs108tv1) and unzip the `.hex`.
2. **From your own switch**, if it already runs 3.0.4.10 (System → System Information shows the software
   version), via Maintenance → File Upload → Firmware:
   - **TFTP (recommended):** run a TFTP server on your computer and enter its address and a file name. The
     switch writes the exact image, byte-identical to Netgear's `.hex`.
   - **HTTP ("Download to this computer"):** be patient, the switch sends it very slowly (about 10 minutes for
     1.2 MB). It also appends one extra line break after the image; `checkhex`, `unhex` and `flash.py`
     recognise and ignore that byte.

Then convert and verify it:

```
python3 tools/gs108t_web.py checkhex GS108T-V3.0.4.10.hex          # must say OK
python3 tools/gs108t_web.py unhex GS108T-V3.0.4.10.hex GS108T-V3.0.4.10.bin
shasum -a 256 GS108T-V3.0.4.10.bin
# bb1dd3e062891a923599f9575096904420e9fde3156c3426d54c2f2b6b5f8951
```

## Firmware files

- `GS108T-V3.0.4.10.bin`: the stock firmware, a little-endian MIPS eCos ELF. File offset = address − `0x80000000`.
- `GS108T-V3.0.4.10.hex`: the upload image inside Netgear's zip. It's gzip with
  `FNAME=_GS108Tv1h1_bcm.robo_` and a 12-character comment: payload length (8 hex) and the 16-bit byte sum
  (4 hex). There is no signature.
  `tools/gs108t_web.py unhex GS108T-V3.0.4.10.hex GS108T-V3.0.4.10.bin` converts it.
- Web content lives in one contiguous block in `.data`, described by a 16-byte-per-entry file table at
  `0x802ba098`. See `CLAUDE.md` for the record format.

## Flashing and recovery

- An upgrade is written to the switch's **inactive** flash bank. Only after the whole image has been checked
  is it marked active with a higher sequence number. A rejected or interrupted upload leaves the running
  firmware untouched. This is how the firmware selects banks; the bootloader's own logic is not in this
  image and has not been verified.
- Flash **directly** against the switch (`tools/flash.py` or the stock upgrade page), not through the dev
  server.
- **To go back to stock**, flash Netgear's original `.hex` with `tools/flash.py --upload`. This uses the
  firmware's upgrade handler directly, so it works even if a web UI were broken.
- **Never** use the boot-code upload (`cfeupgrade.cgi`) unless you have a bootloader image for this exact
  hardware: a bad bootloader cannot be fixed by a firmware upload.

## Known quirks (stock firmware behaviour)

- **Ad blockers** block `counter.cgi` (Port Statistics). Allow the switch's address.
- **Storm control** mode and threshold only take effect on ports whose status is *Enable*. The page now says
  so and warns.
- **Port mirroring** always opens showing "Disable": the firmware does not report the current setting.
- **Firmware backup** ("File Upload → Firmware") is very slow (about 10 minutes) and ends with one extra
  line break. The new page waits for it, strips the extra byte and verifies the image before saving it.
- **Sessions** are bound to the client IP and limited to 4. The idle timeout logs you out.

## Reverse engineering

The firmware was analysed in [Ghidra](https://ghidra-sre.org/) (project `gs108t.gpr`) through
[GhidraMCP](https://github.com/LaurieWired/GhidraMCP) by LaurieWired. GhidraMCP is a Ghidra plugin plus an MCP
server, so an AI assistant (Claude Code here) can decompile functions, follow cross-references and rename symbols
in the open project. It was used to work out:

- the web file table and the 12-byte template records, which made `extract`/`pack` possible;
- what individual CGI handlers do with their form fields (for example Time: `time.cgi` never reads `inp3`);
- the upgrade path: dual flash banks, the sum16 check and the boot marker, and that an interrupted upload leaves
  the running image alone;
- sessions (cookie, IP binding, 4 slots) and how the clock and time zone are stored.

The findings are written up in `CLAUDE.md`. The bridge listens on port 8080 by default.

## Disclaimer

This is an unofficial project, not affiliated with or endorsed by Netgear. Flashing modified firmware is at
your own risk. The stock firmware and the original web content are Netgear's; don't redistribute them.

**Use at your own risk.** This software is provided "as is", without warranty of any kind. Flashing firmware can
brick your switch, and I am not responsible for any damage to your hardware, loss of data or configuration, network
outages, or any other consequences of using this project or its tools.
