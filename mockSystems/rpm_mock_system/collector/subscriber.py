import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt

MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "exl/rpm/+/vitals")
DB_PATH = os.getenv("DB_PATH", "data/rpm_vitals.db")
REQUIRED = {"device_id", "patient_id", "timestamp", "heart_rate_bpm", "spo2_percent", "temperature_c"}

def db_connect():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS vital_readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            received_at TEXT NOT NULL,
            topic TEXT NOT NULL,
            device_id TEXT NOT NULL,
            patient_id TEXT NOT NULL,
            reading_timestamp TEXT NOT NULL,
            heart_rate_bpm REAL NOT NULL,
            spo2_percent REAL NOT NULL,
            temperature_c REAL NOT NULL,
            systolic_bp_mmhg REAL,
            diastolic_bp_mmhg REAL,
            battery_percent REAL,
            raw_payload TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn

def validate(payload, topic):
    missing = REQUIRED - payload.keys()
    if missing:
        raise ValueError(f"Missing fields: {sorted(missing)}")
    if not topic.startswith("exl/rpm/") or not topic.endswith("/vitals"):
        raise ValueError("Unexpected topic")
    for field in ("heart_rate_bpm", "spo2_percent", "temperature_c"):
        if not isinstance(payload[field], (int, float)):
            raise ValueError(f"{field} must be numeric")
    if not 0 <= payload["spo2_percent"] <= 100:
        raise ValueError("spo2_percent must be between 0 and 100")

def on_connect(client, userdata, flags, reason_code, properties):
    print(f"Connected to MQTT broker: reason_code={reason_code}", flush=True)
    if reason_code == 0:
        client.subscribe(MQTT_TOPIC, qos=1)
        print(f"Subscribed to {MQTT_TOPIC}", flush=True)

def on_message(client, userdata, msg):
    raw = msg.payload.decode("utf-8", errors="replace")
    try:
        payload = json.loads(raw)
        validate(payload, msg.topic)
        with db_connect() as conn:
            conn.execute(
                """INSERT INTO vital_readings
                (received_at, topic, device_id, patient_id, reading_timestamp,
                 heart_rate_bpm, spo2_percent, temperature_c,
                 systolic_bp_mmhg, diastolic_bp_mmhg, battery_percent, raw_payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    datetime.now(timezone.utc).isoformat(), msg.topic,
                    str(payload["device_id"]), str(payload["patient_id"]),
                    str(payload["timestamp"]), float(payload["heart_rate_bpm"]),
                    float(payload["spo2_percent"]), float(payload["temperature_c"]),
                    payload.get("systolic_bp_mmhg"), payload.get("diastolic_bp_mmhg"),
                    payload.get("battery_percent"), raw,
                ),
            )
        print(f"Stored device={payload['device_id']} patient={payload['patient_id']} "
              f"HR={payload['heart_rate_bpm']} SpO2={payload['spo2_percent']}", flush=True)
    except Exception as exc:
        print(f"Rejected MQTT message on {msg.topic}: {exc}; payload={raw}", flush=True)

def main():
    db_connect().close()
    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                         client_id="exl-rpm-collector", protocol=mqtt.MQTTv311)
    client.on_connect = on_connect
    client.on_message = on_message
    while True:
        try:
            print(f"Connecting to MQTT broker {MQTT_HOST}:{MQTT_PORT}...", flush=True)
            client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
            client.loop_forever()
        except Exception as exc:
            print(f"MQTT connection failed: {exc}; retrying in 5 seconds", flush=True)
            time.sleep(5)

if __name__ == "__main__":
    main()
