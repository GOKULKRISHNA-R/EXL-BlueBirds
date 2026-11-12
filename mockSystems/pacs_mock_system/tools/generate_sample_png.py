"""Create tiny synthetic PNG pixel patterns using only Python's standard library."""
from pathlib import Path
import struct
import zlib

OUT = Path(__file__).resolve().parents[1] / "data" / "synthetic_png"
OUT.mkdir(parents=True, exist_ok=True)

def _chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )

def create_png(path: Path, index: int) -> None:
    width = height = 128
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # PNG filter: None
        for x in range(width):
            # Artificial grayscale pattern; not a scan or anatomical image.
            value = (x * 3 + y * 2 + index * 35 + ((x // 16) % 2) * 20) % 256
            raw.append(value)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(bytes(raw)))
        + _chunk(b"IEND", b"")
    )
    path.write_bytes(png)
    print(f"Created {path}")

if __name__ == "__main__":
    for number in range(1, 4):
        create_png(OUT / f"synthetic_image_{number:03d}.png", number)
    print("Generated 3 synthetic PNG images.")
