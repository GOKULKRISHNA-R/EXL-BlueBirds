import argparse
import json
import time
from pathlib import Path
import paho.mqtt.client as mqtt

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--file", default="samples/vitals.jsonl")
    parser.add_argument("--interval", type=float, default=0.5)
    args = parser.parse_args()
    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                         client_id="exl-rpm-sample-publisher", protocol=mqtt.MQTTv311)
    client.connect(args.host, args.port, keepalive=60)
    client.loop_start()
    try:
        rows = [line for line in Path(args.file).read_text(encoding="utf-8").splitlines() if line.strip()]
        for line in rows:
            payload = json.loads(line)
            topic = f"exl/rpm/{payload['device_id']}/vitals"
            info = client.publish(topic, json.dumps(payload), qos=1)
            info.wait_for_publish(timeout=10)
            print(f"Published to {topic}: {payload}")
            time.sleep(args.interval)
    finally:
        client.loop_stop()
        client.disconnect()

if __name__ == "__main__":
    main()
