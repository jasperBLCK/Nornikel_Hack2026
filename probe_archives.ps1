$root = 'C:\Users\cynricga\Desktop\HydraX\INFO_DATA\Хранилище информации'
$zips = Get-ChildItem -Path $root -Recurse -Include *.zip,*.rar -ErrorAction SilentlyContinue

if ($zips.Count -eq 0) {
    Write-Host "No archives found" -ForegroundColor Yellow
    exit 0
}

Write-Host ('Found {0} archives. Sampling first 3:' -f $zips.Count) -ForegroundColor Cyan
Write-Host ''

$zips | Select-Object -First 3 | ForEach-Object {
    $z = $_
    Write-Host ('--- {0} ({1:N1} MB) ---' -f $z.Name, ($z.Length / 1MB)) -ForegroundColor Yellow
    # Try listing contents via 7zip if available
    if (Get-Command 7z -ErrorAction SilentlyContinue) {
        & 7z l -slt $z.FullName 2>$null | Select-String -Pattern "Path = " | Select-Object -First 10 | ForEach-Object { Write-Host ('  ' + ($_ -replace '^.*Path = ', '')) }
    } elseif (Get-Command Expand-Archive -ErrorAction SilentlyContinue) {
        try {
            $tmp = Join-Path $env:TEMP ('probe_' + [guid]::NewGuid().ToString('N'))
            $null = New-Item -ItemType Directory -Path $tmp
            Expand-Archive -Path $z.FullName -DestinationPath $tmp -Force
            Get-ChildItem $tmp -Recurse -File | Select-Object -First 10 | ForEach-Object { Write-Host ('  ' + $_.FullName.Substring($tmp.Length + 1)) }
            Remove-Item -Recurse -Force $tmp
        } catch {
            Write-Host ('  [cannot read: {0}]' -f $_.Exception.Message) -ForegroundColor Red
        }
    } else {
        Write-Host "  (install 7zip to inspect: choco install 7zip)" -ForegroundColor DarkGray
    }
    Write-Host ''
}
