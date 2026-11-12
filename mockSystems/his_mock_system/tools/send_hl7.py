"""Send a sample HL7 v2 message to the mock HIS over MLLP."""
import argparse
import socket
from pathlib import Path

VT = b"\x0b"
FS_CR = b"\x1c\x0d"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2575)
    parser.add_argument("--file", default="samples/adt_a01.hl7")
    args = parser.parse_args()

    message = Path(args.file).read_text(encoding="utf-8").strip("\r\n")
    payload = VT + message.replace("\n", "\r").encode("utf-8") + FS_CR

    with socket.create_connection((args.host, args.port), timeout=10) as sock:
        sock.sendall(payload)
        response = bytearray()
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response.extend(chunk)
            if FS_CR in response:
                break

    if not response.startswith(VT) or FS_CR not in response:
        raise RuntimeError(f"Invalid MLLP response: {response!r}")

    ack = bytes(response[1:response.index(FS_CR)]).decode("utf-8", errors="replace")
    print("HIS ACK received:")
    print(ack.replace("\r", "\n"))

if __name__ == "__main__":
    main()
