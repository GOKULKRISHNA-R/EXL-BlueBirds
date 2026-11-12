# PACS Mock System — Orthanc DICOM Server (Updated)

Standalone synthetic Picture Archiving and Communication System for the EXL UCD healthcare integration hackathon.

> **Synthetic data only.** The generated images are artificial pixel patterns, not anatomical or diagnostic images. This is a hackathon mock, not a validated clinical PACS.

## 1. What is included

- Orthanc DICOM server in Docker Compose.
- DICOM network endpoint on TCP `4242`, AE Title `EXLPACS`.
- Orthanc REST API for studies, series, instances and metadata.
- DICOMweb plugin enabled (QIDO-RS, WADO-RS, STOW-RS).
- Persistent storage in a Docker volume.
- Standard-library PNG generator (no Python packages needed).
- PowerShell uploader using Orthanc's documented `POST /tools/create-dicom` endpoint.
- PowerShell verification script.

**Important update:** The previous `generate_sample_dicom.py` / Pydicom workflow has been removed. Do not use the earlier hand-crafted raw DICOM files. This version asks Orthanc to create valid DICOM objects from PNG data URIs, avoiding the Windows NumPy/Pydicom issue and malformed DICOM uploads.

## 2. Requirements

- Docker Desktop with Docker Compose.
- Windows PowerShell 5.1 or PowerShell 7.
- Python 3.9+ only for generating PNGs (standard library only).

No virtual environment or `pip install` is required.

## 3. Start Orthanc

Run these commands from this project folder:

```powershell
Copy-Item .env.example .env
docker compose up -d
docker compose ps
docker logs pacs-mock-orthanc
```

If `.env` already exists, do not overwrite it; retain your configured password.

Endpoints:
- Orthanc Explorer 2: http://localhost:8042/ui/app/
- REST API base: http://localhost:8042
- DICOMweb root: http://localhost:8042/dicom-web/
- DICOM host/port: `localhost:4242`
- DICOM AE Title: `EXLPACS`

Default login:
- Username: `pacs_user`
- Password: `pacs_dev_password_change_me` (unless changed in `.env`)

## 4. Check Orthanc connectivity

```powershell
$password = "pacs_dev_password_change_me"
$credential = "pacs_user:$password"
$encoded = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($credential))
$headers = @{ Authorization = "Basic $encoded" }

Invoke-RestMethod -Uri "http://localhost:8042/system" -Headers $headers
Invoke-RestMethod -Uri "http://localhost:8042/plugins" -Headers $headers
```

If you changed the password in `.env`, use that value instead.

## 5. Generate artificial image files

From the project folder:

```powershell
python .\tools\generate_sample_png.py
```

This creates three 128×128 synthetic grayscale PNGs under `data\synthetic_png`. No `pip install`, NumPy, or Pydicom is involved.

## 6. Create and upload one DICOM series

Ensure Orthanc is running, then run:

```powershell
.\tools\create_dicom_series.ps1
```

The script reads the password from `.env` if present and sends the three PNGs to Orthanc's `POST /tools/create-dicom` endpoint. The `Content` array is intended to create one series containing one instance per image. Orthanc generates the DICOM objects and identifiers.

Expected: a successful REST response containing Orthanc resource identifiers. The exact response structure can vary by Orthanc version.

If PowerShell blocks running the `.ps1` file due to execution policy, run the script with a process-scoped bypass:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\create_dicom_series.ps1
```

This does not change the machine-wide execution policy.

## 7. Verify the uploaded study, series and instances

```powershell
.\tools\verify_orthanc.ps1
```

Or manually:

```powershell
$studies = Invoke-RestMethod -Uri "http://localhost:8042/studies" -Headers $headers
$studies

$studyId = $studies[0]
Invoke-RestMethod -Uri "http://localhost:8042/studies/$studyId" -Headers $headers |
    ConvertTo-Json -Depth 10

$seriesIds = Invoke-RestMethod -Uri "http://localhost:8042/studies/$studyId/series" -Headers $headers
$seriesIds
```

For the single-series upload, expect one study, one series and three instances. If the server already contains previous uploads, it may show additional studies.

## 8. Synthetic identifiers and integration

The synthetic PACS patient uses:
- `PatientID`: `PACS-PT-7001`
- `IssuerOfPatientID`: `EXL-MOCK-PACS`
- `AccessionNumber`: `PACS-ACC-7001`

This is deliberately different from the EHR and LIS identifiers. Do not assume PatientID is globally unique. The later integration layer should reconcile identity using multiple attributes and preserve source provenance; never match by patient name alone.

Important DICOM attributes:
- PatientID `(0010,0020)`
- IssuerOfPatientID `(0010,0021)`
- PatientName `(0010,0010)`
- PatientBirthDate `(0010,0030)`
- AccessionNumber `(0008,0050)`
- StudyInstanceUID `(0020,000D)`
- SeriesInstanceUID `(0020,000E)`
- SOPInstanceUID `(0008,0018)`
- Modality `(0008,0060)`

## 9. Persistence and reset

Stop Orthanc without deleting stored studies:

```powershell
docker compose down
```

Reset and permanently delete stored synthetic DICOM data:

```powershell
docker compose down -v
docker compose up -d
```

## 10. Scope and limitations

This is a local hackathon mock. It does not implement enterprise storage tiering, clinical audit workflows, modality worklists, disaster recovery, production-grade authorization, or clinical validation. Keep it local and use synthetic data only.

## 11. Validation Results

The PACS mock system was successfully tested locally using Docker Desktop and Windows PowerShell.

**Environment**
- Orthanc version: 1.13.0
- Orthanc API version: 31
- DICOM AE Title: `EXLPACS`
- HTTP port: `8042`
- DICOM port: `4242`

**Synthetic DICOM test data**

| Resource | Verified count |
|---|---:|
| Patients | 1 |
| Studies | 1 |
| Series | 1 |
| DICOM instances | 3 |

**Synthetic patient identifiers**
- Patient ID: `PACS-PT-7001`
- Issuer: `EXL-MOCK-PACS`
- Accession Number: `PACS-ACC-7001`
- Modality: `CT`

**Validation performed**
- Orthanc container starts successfully.
- REST API authentication works.
- Synthetic PNG images are generated using Python's standard library.
- Orthanc successfully converts the images into DICOM instances through `POST /tools/create-dicom`.
- Study, series and instance retrieval through the Orthanc REST API works.
- Three DICOM instances were confirmed in the same series.

These results validate the local synthetic PACS workflow. They do not establish clinical or production readiness.