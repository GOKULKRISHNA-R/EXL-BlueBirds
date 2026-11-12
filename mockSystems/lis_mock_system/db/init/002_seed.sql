INSERT INTO patients VALUES
('LIS-P-1001','LAB-MRN-78120','John','Smith','1995-05-10','male',NOW()),
('LIS-P-2044','LAB-MRN-66531','Aisha','Khan','1988-11-22','female',NOW()),
('LIS-P-3098','LAB-MRN-99207','Sofia','Murphy','1992-03-14','female',NOW());

INSERT INTO lab_tests VALUES
('CBC','Complete blood count','58410-2','whole_blood',NULL,'Haematology panel'),
('HBA1C','Haemoglobin A1c','4548-4','whole_blood','%','Glycated haemoglobin'),
('GLU','Glucose','2345-7','serum','mg/dL','Serum glucose'),
('CREAT','Creatinine','2160-0','serum','mg/dL','Serum creatinine'),
('LIPID','Lipid panel','24331-1','serum',NULL,'Lipid profile');

INSERT INTO lab_orders VALUES
('LIS-ORD-5001','LIS-P-1001','ACC-2026-81001','Outpatient Clinic A','Dr Emily Carter','completed','routine','2026-10-12T08:30:00Z','2026-10-12T08:45:00Z',NOW()),
('LIS-ORD-5002','LIS-P-2044','ACC-2026-81002','Medical Ward 2','Dr Liam O''Connor','completed','urgent','2026-11-11T13:30:00Z','2026-11-11T13:42:00Z',NOW()),
('LIS-ORD-5003','LIS-P-3098','ACC-2026-81003','Outpatient Clinic B','Dr Niamh Kelly','in_progress','routine','2026-11-12T08:00:00Z','2026-11-12T08:15:00Z',NOW());

INSERT INTO specimens VALUES
('LIS-SP-7001','LIS-ORD-5001','whole_blood','EDTA tube','completed','2026-10-12T08:45:00Z','2026-10-12T09:00:00Z',NULL),
('LIS-SP-7002','LIS-ORD-5001','serum','Serum separator tube','completed','2026-10-12T08:45:00Z','2026-10-12T09:00:00Z',NULL),
('LIS-SP-7003','LIS-ORD-5002','serum','Serum separator tube','completed','2026-11-11T13:42:00Z','2026-11-11T13:55:00Z',NULL),
('LIS-SP-7004','LIS-ORD-5003','whole_blood','EDTA tube','processing','2026-11-12T08:15:00Z','2026-11-12T08:30:00Z',NULL);

INSERT INTO lab_order_tests VALUES
('LIS-ORD-5001','HBA1C','completed'),
('LIS-ORD-5001','GLU','completed'),
('LIS-ORD-5001','CREAT','completed'),
('LIS-ORD-5002','CBC','completed'),
('LIS-ORD-5002','CREAT','completed'),
('LIS-ORD-5003','CBC','in_progress');

INSERT INTO lab_results VALUES
('LIS-RES-9001','LIS-ORD-5001','HBA1C',7.2,NULL,'% ',4.0,5.6,'high','final','2026-10-12T10:00:00Z','2026-10-12T10:25:00Z','Lab Scientist A'),
('LIS-RES-9002','LIS-ORD-5001','GLU',132,NULL,'mg/dL',70,99,'high','final','2026-10-12T10:02:00Z','2026-10-12T10:27:00Z','Lab Scientist A'),
('LIS-RES-9003','LIS-ORD-5001','CREAT',0.9,NULL,'mg/dL',0.6,1.3,'normal','final','2026-10-12T10:04:00Z','2026-10-12T10:29:00Z','Lab Scientist A'),
('LIS-RES-9004','LIS-ORD-5002','CBC',NULL,'Illustrative panel summary',NULL,NULL,NULL,'unknown','final','2026-11-11T15:00:00Z','2026-11-11T15:30:00Z','Lab Scientist B'),
('LIS-RES-9005','LIS-ORD-5002','CREAT',1.1,NULL,'mg/dL',0.6,1.3,'normal','final','2026-11-11T15:05:00Z','2026-11-11T15:35:00Z','Lab Scientist B');
