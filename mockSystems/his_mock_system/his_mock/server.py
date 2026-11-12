"""Minimal HL7 v2.x MLLP receiver for the EXL healthcare integration hackathon.

This is a synthetic, local-only mock HIS interface, not a production HL7 engine.
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

VT = b"\x0b"
FS = b"\x1c"
CR = b"\x0d"
HOST = os.getenv("MLLP_HOST", "0.0.0.0")
PORT = int(os.getenv("MLLP_PORT", "2575"))
DB_PATH = os.getenv("DB_PATH", "/app/data/his_messages.db")
SYSTEM_NAME = os.getenv("HIS_SYSTEM_NAME", "EXL-MOCK-HIS")
SUPPORTED = {"ADT^A01", "ORM^O01", "ORU^R01"}


def db_connect() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS inbound_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            received_at TEXT NOT NULL,
            message_control_id TEXT,
            message_type TEXT,
            sending_application TEXT,
            sending_facility TEXT,
            patient_id TEXT,
            patient_name TEXT,
            raw_message TEXT NOT NULL,
            ack_code TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def parse_message(raw: str) -> dict:
    segments = [line for line in raw.replace("\n", "\r").split("\r") if line]
    if not segments or not segments[0].startswith("MSH"):
        raise ValueError("Message must begin with an MSH segment")

    msh = segments[0]
    # MSH-1 is the field separator itself; subsequent fields begin after it.
    fields = msh.split("|")
    if len(fields) < 12:
        raise ValueError("MSH segment has too few fields")

    message_type = fields[8]
    control_id = fields[9]
    sending_app = fields[2]
    sending_facility = fields[3]

    pid = next((s for s in segments if s.startswith("PID|")), "")
    pid_fields = pid.split("|") if pid else []
    patient_id = pid_fields[3] if len(pid_fields) > 3 else ""
    patient_name = pid_fields[5] if len(pid_fields) > 5 else ""

    return {
        "segments": segments,
        "message_type": message_type,
        "control_id": control_id,
        "sending_application": sending_app,
        "sending_facility": sending_facility,
        "patient_id": patient_id,
        "patient_name": patient_name,
    }


def build_ack(parsed: dict, code: str = "AA", error: str = "") -> bytes:
    now = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    control_id = parsed.get("control_id") or "UNKNOWN"
    message_type = parsed.get("message_type", "")
    trigger = message_type.split("^")[1] if "^" in message_type else "ACK"
    ack_type = f"ACK^{trigger}"
    msh = (
        f"MSH|^~\\&|{SYSTEM_NAME}|EXL-HOSPITAL|"
        f"{parsed.get('sending_application', 'UNKNOWN')}|"
        f"{parsed.get('sending_facility', 'UNKNOWN')}|{now}||{ack_type}|"
        f"ACK-{control_id}|P|2.5"
    )
    msa = f"MSA|{code}|{control_id}"
    if error:
        # HL7 ERR segment; keep the text simple and safely delimited.
        safe_error = error.replace("|", "/").replace("\r", " ").replace("\n", " ")
        err = f"ERR|||207^Application internal error^HL70357|E|||{safe_error}"
        payload = f"{msh}\r{msa}\r{err}\r"
    else:
        payload = f"{msh}\r{msa}\r"
    return VT + payload.encode("utf-8") + FS + CR


def persist(parsed: dict, raw: str, ack_code: str) -> None:
    with db_connect() as conn:
        conn.execute(
            """INSERT INTO inbound_messages
            (received_at, message_control_id, message_type, sending_application,
             sending_facility, patient_id, patient_name, raw_message, ack_code)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                datetime.now(timezone.utc).isoformat(),
                parsed.get("control_id"),
                parsed.get("message_type"),
                parsed.get("sending_application"),
                parsed.get("sending_facility"),
                parsed.get("patient_id"),
                parsed.get("patient_name"),
                raw,
                ack_code,
            ),
        )


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    peer = writer.get_extra_info("peername")
    print(f"Connection from {peer}", flush=True)
    buffer = bytearray()
    try:
        while True:
            chunk = await reader.read(4096)
            if not chunk:
                break
            buffer.extend(chunk)

            while True:
                start = buffer.find(VT)
                if start < 0:
                    buffer.clear()
                    break
                end = buffer.find(FS + CR, start + 1)
                if end < 0:
                    if start > 0:
                        del buffer[:start]
                    break

                raw_bytes = bytes(buffer[start + 1:end])
                del buffer[:end + 2]
                raw = raw_bytes.decode("utf-8", errors="replace").strip("\r\n")
                try:
                    parsed = parse_message(raw)
                    if parsed["message_type"] not in SUPPORTED:
                        ack = build_ack(parsed, "AR", f"Unsupported message type: {parsed['message_type']}")
                        persist(parsed, raw, "AR")
                    else:
                        persist(parsed, raw, "AA")
                        ack = build_ack(parsed, "AA")
                    writer.write(ack)
                    await writer.drain()
                    print(
                        f"Received {parsed['message_type']} control_id={parsed['control_id']} "
                        f"patient_id={parsed['patient_id']} -> ACK",
                        flush=True,
                    )
                except Exception as exc:
                    fallback = {
                        "control_id": "UNKNOWN",
                        "message_type": "ACK",
                        "sending_application": "UNKNOWN",
                        "sending_facility": "UNKNOWN",
                    }
                    writer.write(build_ack(fallback, "AE", str(exc)))
                    await writer.drain()
                    print(f"Rejected message from {peer}: {exc}", flush=True)
    except (asyncio.IncompleteReadError, ConnectionResetError):
        pass
    finally:
        writer.close()
        await writer.wait_closed()
        print(f"Disconnected {peer}", flush=True)


async def main():
    # Ensure DB exists before accepting traffic.
    db_connect().close()
    server = await asyncio.start_server(handle_client, HOST, PORT)
    print(f"{SYSTEM_NAME} listening on {HOST}:{PORT} (HL7 v2 MLLP)", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
