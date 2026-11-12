# RPM Mock System — MQTT / Time-Series Vitals

Standalone synthetic Remote Patient Monitoring mock for the EXL UCD healthcare integration hackathon (system 5 of 5).

> Synthetic demonstration data only. Not clinical measurements or medical advice.

## Architecture
- Broker: Eclipse Mosquitto 2
- Transport: MQTT 3.1.1 over TCP, host port 1883
- Topic: `exl/rpm/{device_id}/vitals`
- Collector: Python + Paho MQTT 2.1.0
- Persistence: SQLite time-series-style table

## Start
Run from this folder:

```powershell
docker compose up -d --build
docker compose ps
docker logs rpm-mock-mosquitto
docker logs rpm-mock-collector
```

Expected containers: `rpm-mock-mosquitto` and `rpm-mock-collector`.

## Install publisher dependency

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Publish sample readings

```powershell
.\.venv\Scripts\python.exe .\tools\publish_vitals.py --file .\samples\vitals.jsonl
```

## Inspect SQLite

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\inspect_db.ps1
```

Expected: three readings from two synthetic devices/patients.

## Payload
Required JSON fields: `device_id`, `patient_id`, `timestamp`, `heart_rate_bpm`, `spo2_percent`, `temperature_c`. Optional: systolic/diastolic blood pressure and battery percentage.

Example topic: `exl/rpm/RPM-WATCH-1001/vitals`.

## Identity separation
RPM patient IDs (`RPM-P-88001`, `RPM-P-88002`) are intentionally different from identifiers in EHR, LIS, PACS and HIS. The future integration layer must reconcile identity using multiple attributes and provenance, never patient name alone.

## Security and limitations
Anonymous MQTT access is enabled only for isolated local development. Do not expose this broker publicly or send real patient data. This is a hackathon mock, not a production RPM platform.
