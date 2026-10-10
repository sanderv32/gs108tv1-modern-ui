import os
import socket

TFTP_DIRECTORY = "./tftp_root"

OP_RRQ = 1
OP_WRQ = 2
OP_DATA = 3
OP_ACK = 4
OP_ERROR = 5
OP_OACK = 6

BLOCK_SIZE = 512


def handle_wrq(sock, client_address, filename):
  """Handles upload entirely on port 69, optimized for Netgear bootloaders."""
  filepath = os.path.join(TFTP_DIRECTORY, os.path.basename(filename))
  print(f"\n[{client_address[0]}] Starting upload stream for: {filename}")

  # Send initial ACK 0 to accept the write request
  ack_packet = OP_ACK.to_bytes(2, "big") + (0).to_bytes(2, "big")
  sock.sendto(ack_packet, client_address)
  print(f"[{client_address[0]}] Sent ACK 0. Waiting for data blocks...")

  block_num = 1
  total_bytes = 0
  max_retries = 15
  retries = 0

  try:
    with open(filepath, "wb") as f:
      while True:
        sock.settimeout(10.0)
        try:
          data, addr = sock.recvfrom(BLOCK_SIZE + 516)

          if addr[0] != client_address[0]:
            continue

          if len(data) < 4:
            continue

          opcode = int.from_bytes(data[:2], byteorder="big")
          rcvd_block = int.from_bytes(data[2:4], byteorder="big")

          if opcode == OP_DATA:
            retries = 0
            chunk = data[4:]

            if rcvd_block == block_num:
              f.write(chunk)
              total_bytes += len(chunk)

              ack_packet = (
                  OP_ACK.to_bytes(2, "big") + block_num.to_bytes(2, "big")
              )
              sock.sendto(ack_packet, client_address)

              if block_num % 50 == 0 or len(chunk) < BLOCK_SIZE:
                print(
                    f"[{client_address[0]}] Progress: Block {block_num} | Total:"
                    f" {total_bytes} bytes"
                )

              if len(chunk) < BLOCK_SIZE:
                print(
                    f"\n[+] SUCCESS! File {filename} fully received."
                    f" Total size: {total_bytes} bytes."
                )
                break

              block_num += 1

            elif rcvd_block == block_num - 1:
              ack_packet = (
                  OP_ACK.to_bytes(2, "big") + (block_num - 1).to_bytes(2, "big")
              )
              sock.sendto(ack_packet, client_address)

        except socket.timeout:
          retries += 1
          print(
              f"[!] Timeout waiting for block {block_num}"
              f" ({retries}/{max_retries}). Reminding switch..."
          )
          if retries >= max_retries:
            print(f"[X] Transfer failed: Too many timeouts from switch.")
            break

          last_ack = block_num - 1 if block_num > 1 else 0
          ack_packet = OP_ACK.to_bytes(2, "big") + last_ack.to_bytes(2, "big")
          sock.sendto(ack_packet, client_address)
  finally:
    # Always reset socket timeout back to blocking/infinite for the main listener
    sock.settimeout(None)


def main():
  if not os.path.exists(TFTP_DIRECTORY):
    os.makedirs(TFTP_DIRECTORY)
    print(f"Created root directory at: {TFTP_DIRECTORY}")

  sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
  sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

  HOST, PORT = "0.0.0.0", 69
  try:
    sock.bind((HOST, PORT))
  except PermissionError:
    print(
        "Error: Port 69 is privileged. Please run with sudo (macOS/Linux) or"
        " Administrator (Windows)."
    )
    return

  print(f"[*] Netgear-Optimized TFTP Server listening on {HOST}:{PORT}...")
  print("[*] Ready for firmware upload. Press Ctrl+C to stop.\n")

  try:
    sock.settimeout(None)  # Ensure main socket is blocking
    while True:
      data, client_address = sock.recvfrom(1500)
      if len(data) < 2:
        continue

      opcode = int.from_bytes(data[:2], byteorder="big")

      if opcode == OP_WRQ:
        parts = data[2:].split(b"\x00")
        filename = parts[0].decode("utf-8", errors="ignore")
        handle_wrq(sock, client_address, filename)

  except KeyboardInterrupt:
    print("\nServer stopped.")
  finally:
    sock.close()


if __name__ == "__main__":
  main()
