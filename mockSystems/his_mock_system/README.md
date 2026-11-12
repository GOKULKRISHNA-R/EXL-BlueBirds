# HIS Mock System — HL7 v2 over MLLP

Standalone synthetic Hospital Information System interface for the EXL UCD healthcare integration hackathon.

## 1. Role in the architecture

This is system 4 of 5. It deliberately differs from the EHR (FHIR-style HTTP API), LIS (PostgreSQL), and PACS (DICOM/Orthanc).

- Protocol: HL7 v2.x
- Transport: MLLP over TCP
- Default host port: `2575`
- Message types accepted: `ADT^A01`, `ORM^O01`, `ORU^R01`
- Persistence: SQLite audit store inside the container

The mock contains no AI agent or identity-resolution logic. Its job is only to receive, minimally validate, acknowledge, and store HL7 messages.

## 2. Requirements

- Docker Desktop with Docker Compose
- Python 3.9+ to run the sample sender (standard library only)

## 3. Start the HIS interface

From this project folder:

```powershell

docker compose up -d --build
docker compose ps
docker logs his-mock-mllp
```

If `.env` already exists, do not overwrite your configured values.

The MLLP listener is available at `localhost:2575`.

## 4. Send an ADT admission message

```powershell
python .\tools\send_hl7.py --file .\samples\adt_a01.hl7
```

Expected ACK includes:

```text
MSA|AA|ADT-0001
```

`AA` means application accept acknowledgement. The server returns `AR` for unsupported message types and `AE` when it cannot parse a message.

## 5. Send ORM and ORU messages

```powershell
python .\tools\send_hl7.py --file .\samples\orm_o01.hl7
python .\tools\send_hl7.py --file .\samples\oru_r01.hl7
```

Expected control IDs: `ORM-0001` and `ORU-0001`, each with an `AA` acknowledgement.

## 6. Inspect stored messages

Messages are stored in SQLite at `/app/data/his_messages.db` inside the container.

```powershell
docker exec -it his-mock-mllp python -c "import sqlite3; c=sqlite3.connect('/app/data/his_messages.db'); print(*c.execute('SELECT id,message_control_id,message_type,patient_id,ack_code FROM inbound_messages'), sep='\\n')"
```

Inspect the full message payload:

```powershell
docker exec -it his-mock-mllp python -c "import sqlite3; c=sqlite3.connect('/app/data/his_messages.db'); print(*c.execute('SELECT raw_message FROM inbound_messages'), sep='\\n---\\n')"
```

## 7. HL7 / MLLP concepts

- HL7 v2 is a pipe-delimited, segment-based healthcare messaging format.
- `MSH` identifies the sender, receiver, timestamp, message type, control ID and version.
- `PID` carries patient identity and demographics.
- `PV1` carries visit information.
- `ORC` and `OBR` describe orders.
- `OBX` carries an observation/result.
- MLLP frames a message as `VT + HL7 payload + FS + CR`.
- `MSA` in the ACK carries the acknowledgement code and original message control ID.

## 8. Deliberately different patient identifiers

The sample HIS patient is `HIS-P-55001` with assigning authority `EXL-HIS`. This is intentionally different from:
- EHR: `ehr-pat-001`
- LIS: `LIS-P-1001`
- PACS: `PACS-PT-7001`

These identifiers are not interchangeable. The later integration layer must reconcile identities using multiple attributes and preserve source provenance. Never match by patient name alone.

## 9. Validation checklist

- [ ] Container starts and listens on TCP 2575.
- [ ] ADT^A01 returns `MSA|AA|ADT-0001`.
- [ ] ORM^O01 returns `MSA|AA|ORM-0001`.
- [ ] ORU^R01 returns `MSA|AA|ORU-0001`.
- [ ] Three messages appear in the SQLite audit table.

## 10. Scope and limitations

This is a minimal hackathon mock, not a complete HL7 engine or production HIS. It supports a small set of message types and basic MSH/PID parsing, with no TLS, advanced HL7 conformance profiles, message de-duplication, ACK retry queue, or clinical workflow logic. Use synthetic data only.
