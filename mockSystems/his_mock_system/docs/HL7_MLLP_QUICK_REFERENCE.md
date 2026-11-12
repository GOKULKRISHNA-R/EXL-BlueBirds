# HL7 v2 / MLLP Quick Reference

## MLLP framing

Each message is framed as:

`<VT>HL7 message<FS><CR>`

Byte values:
- VT = `0x0B` (start block)
- FS = `0x1C` (end block)
- CR = `0x0D` (carriage return)

MLLP is a transport framing protocol commonly used to send HL7 v2 messages over TCP. It is not the HL7 message format itself.

## Common segments in this mock

| Segment | Purpose |
|---|---|
| MSH | Message header and routing metadata |
| EVN | Event metadata |
| PID | Patient identity and demographics |
| PV1 | Patient visit / encounter |
| ORC | Common order information |
| OBR | Observation request / order detail |
| OBX | Observation or result |
| MSA | Acknowledgement status |

## Message types accepted

- `ADT^A01`: admit/visit notification
- `ORM^O01`: order message
- `ORU^R01`: unsolicited observation/result message

## ACK codes

- `AA`: application accept
- `AE`: application error
- `AR`: application reject

The ACK's `MSA-2` echoes the inbound `MSH-10` message control ID.

## Patient identity

PID-3 is the patient identifier field and can include an assigning authority. The mock uses `HIS-P-55001^^^EXL-HIS^MR`. Do not treat this local identifier as globally unique.

## Sample sender

```powershell
python .\\tools\\send_hl7.py --file .\\samples\\adt_a01.hl7
```

The sender uses Python's standard library and transmits one MLLP-framed message over TCP.
