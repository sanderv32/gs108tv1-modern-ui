import os
import socket

TFTP_DIRECTORY = "./tftp_root"

OP_RRQ = 1
OP_WRQ = 2
OP_DATA = 3
OP_ACK = 4
OP_ERROR = 5
OP_OACK = 6


def print_hex_dump(data):
  """Prints a clean hex and ASCII representation of the packet."""
  hex_view = " ".join(f"{b:02x}" for b in data)
  ascii_view = "".join(chr(b) if 32 <= b <= 126 else "." for b in data)
  print(f"      HEX: {hex_view}")
  print(f"      ASC: {ascii_view}")


def main():
  if not os.path.exists(TFTP_DIRECTORY):
    os.makedirs(TFTP_DIRECTORY)

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

  print(f"[*] Diagnostic TFTP Server listening on {HOST}:{PORT}...")
  print("[*] Waiting for traffic from your device. Press Ctrl+C to stop.\n")

  active_client = None
  file_obj = None
  block_num = 1
  total_bytes = 0
  block_size = 512

  try:
    while True:
      sock.settimeout(None) if not active_client else sock.settimeout(10.0)
      try:
        data, client_address = sock.recvfrom(1500)
      except socket.timeout:
        print(f"\n[!] Timeout waiting for data from {active_client}")
        if file_obj:
          file_obj.close()
          file_obj = None
        active_client = None
        continue

      if len(data) < 2:
        continue

      opcode = int.from_bytes(data[:2], byteorder="big")

      # If this is from a new client or new transfer request
      if opcode in (OP_RRQ, OP_WRQ):
        if file_obj:
          file_obj.close()
        active_client = client_address
        block_num = 1
        total_bytes = 0

        op_name = "RRQ (Read)" if opcode == OP_RRQ else "WRQ (Write)"
        print(
            f"\n--- NEW {op_name} from {client_address[0]}:{client_address[1]} ---"
        )
        print_hex_dump(data)

        parts = data[2:].split(b"\x00")
        filename = parts[0].decode("utf-8", errors="ignore")
        print(f"    -> Target Filename: {filename}")

        # Print out any options sent by the client
        if len(parts) > 2:
          print("    -> Parsed Options:")
          i = 2
          while i < len(parts) - 1:
            k = parts[i].decode("utf-8", errors="ignore")
            v = parts[i + 1].decode("utf-8", errors="ignore")
            if k:
              print(f"       * {k} = {v}")
              if k.lower() == "blksize":
                block_size = int(v)
            i += 2

        filepath = os.path.join(TFTP_DIRECTORY, os.path.basename(filename))
        if opcode == OP_WRQ:
          file_obj = open(filepath, "wb")
          # Acknowledge the WRQ with ACK block 0
          ack_packet = OP_ACK.to_bytes(2, "big") + (0).to_bytes(2, "big")
          sock.sendto(ack_packet, client_address)
          print("    <- Sent ACK 0")

      elif active_client and client_address[0] == active_client[0]:
        # Handle ongoing upload packets from the active client
        if opcode == OP_DATA:
          if len(data) < 4:
            continue
          rcvd_block = int.from_bytes(data[2:4], byteorder="big")
          chunk = data[4:]
          total_bytes += len(chunk)

          print(
              f"[DATA] Block {rcvd_block} received | Size: {len(chunk)} bytes |"
              f" Cumulative Total: {total_bytes}"
          )

          if rcvd_block == block_num:
            if file_obj:
              file_obj.write(chunk)

            # Send ACK
            ack_packet = (
                OP_ACK.to_bytes(2, "big") + block_num.to_bytes(2, "big")
            )
            sock.sendto(ack_packet, client_address)
            block_num += 1

            if len(chunk) < block_size:
              print(f"[+] Transfer complete! Total file size: {total_bytes}")
              if file_obj:
                file_obj.close()
                file_obj = None
              active_client = None
          else:
            print(
                f"[!] Expected block {block_num}, but got {rcvd_block}."
                " Re-acknowledging previous block."
            )
            ack_packet = (
                OP_ACK.to_bytes(2, "big") + (block_num - 1).to_bytes(2, "big")
            )
            sock.sendto(ack_packet, client_address)

        else:
          print(f"[?] Received unknown opcode {opcode} from client:")
          print_hex_dump(data)

  except KeyboardInterrupt:
    print("\nDiagnostic server stopped.")
  finally:
    if file_obj:
      file_obj.close()
    sock.close()


if __name__ == "__main__":
  main()

