"""Inspect received HL7 messages from the SQLite audit store (host-side helper)."""
import os
import sqlite3
from pathlib import Path

db = Path(os.getenv("DB_PATH", "data/his_messages.db"))
if not db.exists():
    raise SystemExit(f"Database not found: {db}. Use docker exec to inspect container DB.")
with sqlite3.connect(db) as conn:
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT id, received_at, message_control_id, message_type,
               patient_id, patient_name, ack_code
        FROM inbound_messages ORDER BY id
    """).fetchall()
    for row in rows:
        print(dict(row))
    print(f"Total messages: {len(rows)}")
