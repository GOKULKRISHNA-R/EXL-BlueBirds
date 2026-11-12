# DICOM / Orthanc quick reference

## DICOM hierarchy
Patient → Study → Series → Instance.

- Patient: demographics and PatientID.
- Study: imaging examination, identified by StudyInstanceUID.
- Series: acquisition grouping, identified by SeriesInstanceUID.
- Instance: an individual DICOM object, identified by SOPInstanceUID.

Orthanc internal IDs are not DICOM UIDs.

## Useful Orthanc REST endpoints
- `GET /system`
- `GET /plugins`
- `GET /studies`
- `GET /studies/{orthanc-study-id}`
- `GET /studies/{orthanc-study-id}/series`
- `GET /series/{orthanc-series-id}/instances`
- `GET /instances/{orthanc-instance-id}/tags`
- `POST /instances` — upload an already valid DICOM object
- `POST /tools/create-dicom` — create DICOM from JSON (including image data URIs)

## DICOMweb
Default root: `/dicom-web/`.
- QIDO-RS: query studies, series and instances.
- WADO-RS: retrieve DICOM objects, metadata and frames.
- STOW-RS: store DICOM instances.

## Synthetic data
The included PNGs are artificial grayscale patterns. Orthanc converts them to DICOM through its REST API. They are not genuine CT images, anatomical images, or suitable for clinical use.

### Synthetic data creation

Use Orthanc's documented endpoint:

`POST /tools/create-dicom`

The request accepts image data URIs and DICOM tags. Passing multiple images in the `Content` array creates a series containing multiple instances.

The included PowerShell script `tools/create_dicom_series.ps1` performs this operation.

Verify the hierarchy using:

- `GET /studies`
- `GET /studies/{study-id}/series`
- `GET /series/{series-id}/instances`

The `/series/{series-id}/instances` endpoint returns an array of Orthanc instance IDs.