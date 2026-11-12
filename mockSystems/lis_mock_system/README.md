# LIS Mock System — PostgreSQL

Standalone synthetic Laboratory Information System for the EXL healthcare integration hackathon. Unlike the EHR, this system exposes a relational PostgreSQL database rather than a FHIR REST API.

> Synthetic hackathon data only. Not for real patient data or clinical use. Values and reference ranges are illustrative, not clinical guidance.

## Architecture
- PostgreSQL 16 and Docker Compose
- Normalized relational tables: `patients`, `lab_orders`, `specimens`, `lab_tests`, `lab_order_tests`, `lab_results`
- Foreign keys, check constraints, indexes and a reporting view `v_lab_results_detail`
- Independent LIS patient IDs and MRNs

## Start
```powershell

docker compose up -d
docker compose ps
```
PostgreSQL is exposed at `localhost:5433` to avoid conflict with a local database on port 5432. Schema and seed scripts run on first volume initialization.

## Connect
```powershell
docker exec -it lis-mock-db psql -U lis_app -d lis
```
Host client settings: host `localhost`, port `5433`, database `lis`, user `lis_app`, password from `.env`.

## Validate
```sql
\dt
SELECT COUNT(*) FROM patients;
SELECT COUNT(*) FROM lab_orders;
SELECT COUNT(*) FROM specimens;
SELECT COUNT(*) FROM lab_tests;
SELECT COUNT(*) FROM lab_results;
```
Expected counts: 3 patients, 3 orders, 4 specimens, 5 tests, 5 results.

All joined result data:
```sql
SELECT * FROM v_lab_results_detail ORDER BY ordered_at DESC, test_code;
```

One patient's lab history:
```sql
SELECT * FROM v_lab_results_detail
WHERE patient_id='LIS-P-1001'
ORDER BY observed_at DESC;
```

Abnormal results:
```sql
SELECT patient_id, given_name, family_name, test_name, result_value,
       unit, reference_low, reference_high, abnormal_flag
FROM v_lab_results_detail
WHERE abnormal_flag IN ('low','high','critical','abnormal');
```

## Cross-system identity
| Synthetic person | EHR ID | LIS ID |
|---|---|---|
| John Smith | `ehr-pat-001` | `LIS-P-1001` |
| Aisha Khan | `ehr-pat-002` | `LIS-P-2044` |
| Sofia Murphy | `ehr-pat-003` | `LIS-P-3098` |

This mapping is documentation only; it is not stored in the LIS database. The integration platform must resolve identities using multiple attributes and provenance, not name alone.

## Reset
Warning: deletes the local database volume and all its data.
```powershell
docker compose down -v
docker compose up -d
```

This is a hackathon mock, not a vendor-certified LIS. It does not implement analyzer interfaces, HL7 messaging, full terminology validation or production-grade clinical access controls.
