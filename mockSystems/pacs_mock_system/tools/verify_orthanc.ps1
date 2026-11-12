
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$password = "pacs_dev_password_change_me"

$envFile = Join-Path $projectRoot ".env"
if (Test-Path $envFile) {
    $passwordLine = Get-Content $envFile |
        Where-Object { $_ -match '^ORTHANC_PASSWORD=' } |
        Select-Object -First 1

    if ($passwordLine) {
        $password = $passwordLine -replace '^ORTHANC_PASSWORD=', ''
    }
}

$encoded = [Convert]::ToBase64String(
    [Text.Encoding]::ASCII.GetBytes("pacs_user:$password")
)
$headers = @{ Authorization = "Basic $encoded" }

Write-Host "`n=== ORTHANC SYSTEM ==="
$system = Invoke-RestMethod `
    -Uri "http://localhost:8042/system" `
    -Headers $headers

$system | ConvertTo-Json -Depth 5

Write-Host "`n=== STUDIES ==="
$studyIds = @(Invoke-RestMethod `
    -Uri "http://localhost:8042/studies" `
    -Headers $headers)

Write-Host "Total studies: $($studyIds.Count)"

foreach ($studyId in $studyIds) {

    $study = Invoke-RestMethod `
        -Uri "http://localhost:8042/studies/$studyId" `
        -Headers $headers

    Write-Host "`nStudy ID: $studyId"
    Write-Host "Patient ID: $($study.PatientMainDicomTags.PatientID)"

    $seriesList = @(Invoke-RestMethod `
        -Uri "http://localhost:8042/studies/$studyId/series" `
        -Headers $headers)

    Write-Host "Total series: $($seriesList.Count)"

    foreach ($series in $seriesList) {

        $seriesId = $series.ID

        $instances = @($series.Instances)

        Write-Host "`nSeries ID: $seriesId"
        Write-Host "Modality: $($series.MainDicomTags.Modality)"
        Write-Host "Instances: $($instances.Count)"

        foreach ($instance in $instances) {
            Write-Host "  Instance ID: $($instance)"
        }
    }
}

Write-Host "`n=== VERIFICATION COMPLETED ==="
