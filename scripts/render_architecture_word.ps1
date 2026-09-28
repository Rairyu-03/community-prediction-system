$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$inputDoc = Join-Path $taskRoot '完整社区预测系统项目架构设计说明.docx'
$previewPdf = Join-Path $taskRoot 'runtime\architecture-document\preview.pdf'
$wordApp = New-Object -ComObject Word.Application
$wordApp.Visible = $false
$wordApp.DisplayAlerts = 0
try {
    $wordDoc = $wordApp.Documents.Open($inputDoc, $false, $true)
    $wordDoc.Repaginate()
    $wordDoc.ExportAsFixedFormat($previewPdf, 17)
    Write-Output ('Pages: ' + $wordDoc.ComputeStatistics(2))
    $wordDoc.Close(0)
} finally {
    $wordApp.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($wordApp) | Out-Null
}
