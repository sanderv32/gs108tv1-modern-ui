#!/usr/bin/env python3
"""Minimal TFTP server that receives uploads from the GS108T (Maintenance > File Upload > TFTP).

    sudo python3 tools/tftp_server.py                  # listen on port 69, save into tftp_root/
    sudo python3 tools/tftp_server.py --verbose        # also hex-dump every packet
    sudo python3 tools/tftp_server.py --bind 192.168.0.10 --overwrite

Written for this switch: it sends every DATA packet to port 69 instead of to the server's new
transfer port that RFC 1350 prescribes, so a standard server (which answers from an ephemeral
port) never sees the data. This server therefore runs each transfer on port 69 itself, one at a time.

The switch's TFTP client (tftp_client_put @0x801e2934, eCos style) waits 5 s for each ACK and gives up
silently, without an ERROR packet, after 50 such timeouts in the WHOLE transfer (the counter is never
reset). It loses ~5% of its outgoing packets, so a 1.2 MB backup (2400 blocks) used to die after 700-1100 blocks. An ACK for
the previous block makes it resend at once without counting a timeout, so the server re-sends that ACK
("kick") whenever the next block is 1 s late. Duplicate blocks are not answered: a late kick makes the
switch send one, and answering it would start the Sorcerer's Apprentice loop (every block sent twice);
the next kick covers a lost ACK anyway.
The switch sends no empty final block when a file is an exact multiple of 512 bytes, so such a transfer
cannot be recognised as complete; it ends with a timeout and is discarded (the firmware image is not affected).

Only uploads (write requests, mode octet) are supported. A file is written as <name>.part and only
renamed when the last block has arrived, so an aborted transfer never leaves a truncated file behind
and never touches an existing one. Existing files are not replaced unless --overwrite is given
(tftp_root/ holds the stock recovery image).
"""
import argparse, os, socket, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

OP_RRQ, OP_WRQ, OP_DATA, OP_ACK, OP_ERROR = 1, 2, 3, 4, 5
ERR_UNDEFINED, ERR_NOT_FOUND, ERR_ACCESS, ERR_DISK_FULL, ERR_ILLEGAL_OP, ERR_UNKNOWN_TID, ERR_EXISTS = 0, 1, 2, 3, 4, 5, 6
BLOCK_SIZE = 512          # options (blksize, ...) are ignored without an OACK, so the client uses 512
KICK = 1.0                # re-ACK the last block when the next one is this late (the switch waits 5 s)
GIVE_UP = 150.0           # no new block for this long: the switch has given up
DALLY = 12.0              # after the last ACK, re-ACK a repeated last block (the switch retries after 5 s)


def ack(block):
    return OP_ACK.to_bytes(2, "big") + (block & 0xffff).to_bytes(2, "big")


def error(code, msg):
    return OP_ERROR.to_bytes(2, "big") + code.to_bytes(2, "big") + msg.encode("ascii", "replace") + b"\0"


class Server:
    def __init__(self, sock, root, overwrite, verbose):
        self.sock, self.root, self.overwrite, self.verbose = sock, root, overwrite, verbose

    def log(self, msg):
        print(msg, flush=True)

    def dump(self, direction, data, addr):
        if not self.verbose:
            return
        self.log("  %s %s:%d  %d bytes" % (direction, addr[0], addr[1], len(data)))
        head = data[:64]
        self.log("      HEX: " + " ".join("%02x" % b for b in head) + (" ..." if len(data) > 64 else ""))
        self.log("      ASC: " + "".join(chr(b) if 32 <= b <= 126 else "." for b in head))

    def send(self, data, addr):
        self.dump("->", data, addr)
        self.sock.sendto(data, addr)

    def recv(self, timeout):
        self.sock.settimeout(timeout)
        data, addr = self.sock.recvfrom(65536)
        self.dump("<-", data, addr)
        return data, addr

    def serve(self):
        while True:
            try:
                data, addr = self.recv(None)
                if len(data) < 2:
                    continue
                op = int.from_bytes(data[:2], "big")
                if op == OP_WRQ:
                    self.write_request(data, addr)
                elif op == OP_RRQ:
                    self.log("[%s] read request refused: this server only receives uploads" % addr[0])
                    self.send(error(ERR_ILLEGAL_OP, "read not supported, upload only"), addr)
                elif op in (OP_DATA, OP_ACK):
                    self.send(error(ERR_UNKNOWN_TID, "no transfer in progress"), addr)
            except OSError as e:          # e.g. network unreachable: report and keep serving
                self.log("[!] %s" % e)

    def write_request(self, data, addr):
        parts = data[2:].split(b"\0")
        if len(parts) < 3:
            return self.send(error(ERR_ILLEGAL_OP, "malformed request"), addr)
        raw, mode = parts[0].decode("latin-1"), parts[1].decode("latin-1").lower()
        opts = [p.decode("latin-1") for p in parts[2:-1]]
        if opts and self.verbose:
            self.log("  options (ignored, client falls back to 512-byte blocks): " + " ".join(opts))
        name = os.path.basename(raw.replace("\\", "/"))
        if not name or name.startswith("."):
            self.log("[%s] refused file name %r" % (addr[0], raw))
            return self.send(error(ERR_ACCESS, "invalid file name"), addr)
        if mode != "octet":
            self.log("[%s] refused %s: mode %r (only octet)" % (addr[0], name, mode))
            return self.send(error(ERR_ILLEGAL_OP, "only octet mode"), addr)
        path = os.path.join(self.root, name)
        if os.path.exists(path) and not self.overwrite:
            self.log("[%s] refused %s: file exists (use --overwrite)" % (addr[0], name))
            return self.send(error(ERR_EXISTS, "file exists"), addr)
        part = path + ".part"
        try:
            f = open(part, "wb")
        except OSError as e:
            self.log("[%s] cannot write %s: %s" % (addr[0], part, e))
            return self.send(error(ERR_ACCESS, "cannot create file"), addr)
        self.log("[%s] receiving %s" % (addr[0], name))
        last = None
        try:
            last = self.receive(f, addr, name)
            f.close()
            if last is not None:
                os.replace(part, path)
        except OSError as e:
            self.log("[X] %s: %s" % (name, e))
            self.send(error(ERR_DISK_FULL if e.errno == 28 else ERR_UNDEFINED, "write failed"), addr)
            last = None
        finally:
            f.close()
            if last is None and os.path.exists(part):
                os.unlink(part)
        if last is not None:              # acknowledge the last block only once the file is in place
            self.send(ack(last), addr)
            self.log("[+] saved %s (%d bytes)" % (path, os.path.getsize(path)))
            self.dally(addr)

    def receive(self, f, client, name):
        """DATA/ACK loop on port 69; returns the number of the last block (not yet acknowledged) once all
        data is written and synced, or None if the transfer failed."""
        self.send(ack(0), client)
        block, total, kicks, dups = 1, 0, 0, 0
        last_new = time.monotonic()
        next_kick = last_new + KICK
        while True:
            now = time.monotonic()
            if now - last_new > GIVE_UP:
                self.log("[X] %s: no new block for %g s, giving up (switch aborted?)" % (name, GIVE_UP))
                self.send(error(ERR_UNDEFINED, "timeout"), client)
                return None
            if now >= next_kick:
                kicks += 1
                if now - last_new >= 10 and kicks % 10 == 0:
                    self.log("[!] %s: waiting %d s for block %d, re-sending ACK %d" % (
                        name, now - last_new, block, block - 1))
                self.send(ack(block - 1), client)
                next_kick = now + KICK
            try:
                data, addr = self.recv(max(0.01, next_kick - time.monotonic()))
            except socket.timeout:
                continue
            if len(data) < 4:
                continue
            op = int.from_bytes(data[:2], "big")
            if addr[0] != client[0]:
                # Match on the IP only, as the original tool did: answering the switch with an ERROR for
                # an unexpected source port made it abort a transfer (suspected; the "[?]" log line below
                # shows whether the port really changes).
                if op == OP_WRQ:          # another transfer while this one runs (single socket, port 69)
                    self.send(error(ERR_UNDEFINED, "busy, try again later"), addr)
                else:
                    self.log("[?] %s: ignored opcode %d from %s:%d" % (name, op, addr[0], addr[1]))
                continue
            if addr != client:
                self.log("[?] %s: opcode %d block %d from port %d (transfer started from %d)" % (
                    name, op, int.from_bytes(data[2:4], "big"), addr[1], client[1]))
            if op == OP_ERROR:
                code = int.from_bytes(data[2:4], "big")
                self.log("[X] %s: client aborted with error %d: %s" % (
                    name, code, data[4:].split(b"\0")[0].decode("latin-1")))
                return None
            if op == OP_WRQ and block == 1:   # our ACK 0 got lost: the client repeats its request
                self.send(ack(0), client)
                continue
            if op != OP_DATA:
                self.log("[?] %s: ignored opcode %d" % (name, op))
                continue
            n = int.from_bytes(data[2:4], "big")
            chunk = data[4:]
            if n == block & 0xffff:       # block numbers wrap after 65535
                f.write(chunk)
                total += len(chunk)
                last_new = time.monotonic()
                next_kick = last_new + KICK
                if len(chunk) < BLOCK_SIZE:
                    f.flush()
                    os.fsync(f.fileno())
                    self.log("    %s: %d bytes, %d kicks, %d duplicate blocks ignored" % (name, total, kicks, dups))
                    return block
                self.send(ack(block), client)
                if block % 200 == 0:
                    self.log("    %s: %d bytes (%d kicks so far)" % (name, total, kicks))
                block += 1
            elif n == (block - 1) & 0xffff:   # not answered (see module docstring); the next kick re-ACKs it
                dups += 1
            else:
                self.log("[?] %s: ignored block %d (expecting %d)" % (name, n, block & 0xffff))

    def dally(self, client):
        """The last ACK may get lost; answer a repeated last block instead of leaving the client hanging."""
        last = None
        try:
            while True:
                data, addr = self.recv(DALLY)
                if addr[0] == client[0] and data[:2] == OP_DATA.to_bytes(2, "big"):
                    last = data[2:4]
                    self.send(OP_ACK.to_bytes(2, "big") + last, client)
                elif data[:2] == OP_WRQ.to_bytes(2, "big"):
                    self.send(error(ERR_UNDEFINED, "busy, try again later"), addr)
        except socket.timeout:
            pass


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=os.path.join(ROOT, "tftp_root"), help="directory for received files")
    p.add_argument("--bind", default="0.0.0.0", help="address to listen on (default: all interfaces)")
    p.add_argument("--port", type=int, default=69, help="UDP port (the switch always uses 69)")
    p.add_argument("--overwrite", action="store_true", help="replace existing files")
    p.add_argument("-v", "--verbose", action="store_true", help="hex-dump every packet")
    a = p.parse_args()
    os.makedirs(a.root, exist_ok=True)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((a.bind, a.port))
    except PermissionError:
        sys.exit("port %d is privileged: run with sudo" % a.port)
    except OSError as e:
        sys.exit("cannot listen on %s:%d: %s (another TFTP server running?)" % (a.bind, a.port, e))
    print("TFTP server on %s:%d, saving uploads to %s%s" % (
        a.bind, a.port, a.root, "" if a.overwrite else " (existing files are kept)"), flush=True)
    try:
        Server(sock, a.root, a.overwrite, a.verbose).serve()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        sock.close()


if __name__ == "__main__":
    main()
