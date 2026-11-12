$ErrorActionPreference = "Stop"
docker exec rpm-mock-collector python -c "import sqlite3; c=sqlite3.connect('/app/data/rpm_vitals.db'); print('Stored readings:'); print(*c.execute('SELECT id,device_id,patient_id,reading_timestamp,heart_rate_bpm,spo2_percent,temperature_c FROM vital_readings ORDER BY id'), sep='\n')"
