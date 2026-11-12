# Creates a single synthetic DICOM series with 3 instances through Orthanc's
# documented /tools/create-dicom endpoint. No Pydicom/NumPy dependency required.
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $projectRoot ".env"
$password = "pacs_dev_password_change_me"

if (Test-Path $envFile) {
    $passwordLine = Get-Content $envFile | Where-Object { $_ -match '^ORTHANC_PASSWORD=' } | Select-Object -First 1
    if ($passwordLine) { $password = $passwordLine -replace '^ORTHANC_PASSWORD=', '' }
}

$credential = "pacs_user:$password"
$encoded = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($credential))
$headers = @{ Authorization = "Basic $encoded" }
$imageDir = Join-Path $projectRoot "data\synthetic_png"
$images = @(Get-ChildItem -Path $imageDir -Filter "*.png" | Sort-Object Name)

if ($images.Count -eq 0) {
    throw "No PNG images found. Run: python tools/generate_sample_png.py"
}

$content = @(
    foreach ($image in $images) {
        $bytes = [System.IO.File]::ReadAllBytes($image.FullName)
        $base64 = [Convert]::ToBase64String($bytes)
        "data:image/png;base64,$base64"
    }
)

$bodyObject = @{
    Content = $content
    Tags = @{
        PatientName = "SYNTHETIC^TESTPATIENT"
        PatientID = "PACS-PT-7001"
        IssuerOfPatientID = "EXL-MOCK-PACS"
        PatientBirthDate = "19950510"
        PatientSex = "M"
        AccessionNumber = "PACS-ACC-7001"
        StudyDescription = "Synthetic CT Test Study"
        SeriesDescription = "Artificial Pixel Pattern"
        Modality = "CT"
    }
}

$body = $bodyObject | ConvertTo-Json -Depth 10
Write-Host "Uploading $($images.Count) artificial images to Orthanc..."
$response = Invoke-RestMethod `
    -Method Post `
    -Uri "http://localhost:8042/tools/create-dicom" `
    -Headers $headers `
    -ContentType "application/json" `
    -Body $body

$response | ConvertTo-Json -Depth 10
Write-Host "Orthanc create-dicom request completed."
