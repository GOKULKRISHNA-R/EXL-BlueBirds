# SQL quick reference

```sql
-- Patient → order → test → result
SELECT p.patient_id, p.given_name, p.family_name, o.accession_no,
       t.test_name, r.result_value, COALESCE(r.unit,t.unit) AS unit,
       r.abnormal_flag, r.result_status
FROM patients p
JOIN lab_orders o ON o.patient_id=p.patient_id
JOIN lab_order_tests ot ON ot.order_id=o.order_id
JOIN lab_tests t ON t.test_code=ot.test_code
LEFT JOIN lab_results r ON r.order_id=ot.order_id AND r.test_code=ot.test_code
WHERE p.patient_id='LIS-P-1001'
ORDER BY o.ordered_at DESC;
```
