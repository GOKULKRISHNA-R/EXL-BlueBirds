CREATE TABLE patients (
  patient_id VARCHAR(32) PRIMARY KEY,
  medical_record_no VARCHAR(32) NOT NULL UNIQUE,
  given_name VARCHAR(80) NOT NULL,
  family_name VARCHAR(80) NOT NULL,
  date_of_birth DATE NOT NULL,
  sex VARCHAR(16) NOT NULL CHECK (sex IN ('female','male','other','unknown')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE lab_orders (
  order_id VARCHAR(32) PRIMARY KEY,
  patient_id VARCHAR(32) NOT NULL REFERENCES patients(patient_id),
  accession_no VARCHAR(40) NOT NULL UNIQUE,
  ordering_location VARCHAR(100) NOT NULL,
  ordering_provider VARCHAR(120) NOT NULL,
  order_status VARCHAR(20) NOT NULL CHECK (order_status IN ('placed','in_progress','completed','cancelled')),
  priority VARCHAR(16) NOT NULL DEFAULT 'routine' CHECK (priority IN ('routine','urgent','stat')),
  ordered_at TIMESTAMPTZ NOT NULL,
  collected_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (collected_at IS NULL OR collected_at >= ordered_at)
);

CREATE TABLE specimens (
  specimen_id VARCHAR(32) PRIMARY KEY,
  order_id VARCHAR(32) NOT NULL REFERENCES lab_orders(order_id) ON DELETE CASCADE,
  specimen_type VARCHAR(40) NOT NULL,
  container_type VARCHAR(40) NOT NULL,
  specimen_status VARCHAR(20) NOT NULL CHECK (specimen_status IN ('collected','received','processing','rejected','completed')),
  collected_at TIMESTAMPTZ,
  received_at TIMESTAMPTZ,
  rejection_reason TEXT,
  CHECK (received_at IS NULL OR collected_at IS NULL OR received_at >= collected_at),
  CHECK (specimen_status <> 'rejected' OR rejection_reason IS NOT NULL)
);

CREATE TABLE lab_tests (
  test_code VARCHAR(24) PRIMARY KEY,
  test_name VARCHAR(120) NOT NULL,
  loinc_code VARCHAR(24),
  specimen_type VARCHAR(40) NOT NULL,
  unit VARCHAR(32),
  description TEXT
);

CREATE TABLE lab_order_tests (
  order_id VARCHAR(32) NOT NULL REFERENCES lab_orders(order_id) ON DELETE CASCADE,
  test_code VARCHAR(24) NOT NULL REFERENCES lab_tests(test_code),
  test_status VARCHAR(20) NOT NULL CHECK (test_status IN ('ordered','in_progress','completed','cancelled')),
  PRIMARY KEY (order_id, test_code)
);

CREATE TABLE lab_results (
  result_id VARCHAR(32) PRIMARY KEY,
  order_id VARCHAR(32) NOT NULL,
  test_code VARCHAR(24) NOT NULL,
  result_value NUMERIC(12,3),
  result_text TEXT,
  unit VARCHAR(32),
  reference_low NUMERIC(12,3),
  reference_high NUMERIC(12,3),
  abnormal_flag VARCHAR(12) NOT NULL DEFAULT 'normal' CHECK (abnormal_flag IN ('normal','low','high','critical','abnormal','unknown')),
  result_status VARCHAR(20) NOT NULL CHECK (result_status IN ('preliminary','final','corrected','cancelled')),
  observed_at TIMESTAMPTZ NOT NULL,
  verified_at TIMESTAMPTZ,
  verified_by VARCHAR(120),
  FOREIGN KEY (order_id, test_code) REFERENCES lab_order_tests(order_id, test_code) ON DELETE CASCADE,
  CHECK (reference_low IS NULL OR reference_high IS NULL OR reference_low <= reference_high),
  CHECK (verified_at IS NULL OR verified_at >= observed_at)
);

CREATE INDEX idx_lab_orders_patient ON lab_orders(patient_id);
CREATE INDEX idx_lab_orders_status ON lab_orders(order_status);
CREATE INDEX idx_lab_orders_ordered_at ON lab_orders(ordered_at DESC);
CREATE INDEX idx_specimens_order ON specimens(order_id);
CREATE INDEX idx_results_order ON lab_results(order_id);
CREATE INDEX idx_results_observed_at ON lab_results(observed_at DESC);
CREATE INDEX idx_patients_name_dob ON patients(family_name, given_name, date_of_birth);

CREATE VIEW v_lab_results_detail AS
SELECT p.patient_id, p.medical_record_no, p.given_name, p.family_name, p.date_of_birth,
       o.order_id, o.accession_no, o.order_status, o.priority, o.ordered_at,
       s.specimen_id, s.specimen_type, s.specimen_status,
       t.test_code, t.test_name, t.loinc_code,
       r.result_id, r.result_value, r.result_text, COALESCE(r.unit,t.unit) AS unit,
       r.reference_low, r.reference_high, r.abnormal_flag, r.result_status,
       r.observed_at, r.verified_at
FROM patients p
JOIN lab_orders o ON o.patient_id=p.patient_id
JOIN lab_order_tests ot ON ot.order_id=o.order_id
JOIN lab_tests t ON t.test_code=ot.test_code
LEFT JOIN specimens s ON s.order_id=o.order_id AND s.specimen_type=t.specimen_type
LEFT JOIN lab_results r ON r.order_id=ot.order_id AND r.test_code=ot.test_code;
