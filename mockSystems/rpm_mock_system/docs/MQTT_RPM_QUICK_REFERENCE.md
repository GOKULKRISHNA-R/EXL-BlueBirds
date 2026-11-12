# MQTT / RPM Quick Reference

- Broker: Mosquitto.
- Publisher: sends JSON readings.
- Subscriber: receives messages matching topic filters.
- Topic: `exl/rpm/{device_id}/vitals`.
- Collector subscribes to `exl/rpm/+/vitals`.
- QoS 1 means at-least-once delivery; duplicates are possible, so production consumers need idempotency/deduplication.
- The collector retains parsed values and the raw JSON payload in SQLite.
- Anonymous access is for isolated local development only; use authentication, TLS and ACLs outside local demos.
