$pythonPath = "f:\Luohino\resources\beeref\venv\Scripts\python.exe"
$argsList = "-m threecolref"

Write-Host "Started auto-runner for threecolref" -ForegroundColor Cyan
Write-Host "Commands:"
Write-Host "  r - restart the application"
Write-Host "  q - quit the auto-runner"
Write-Host "-----------------------------------"

while ($true) {
    Write-Host "Starting application..." -ForegroundColor Green
    $process = Start-Process -FilePath $pythonPath -ArgumentList $argsList -PassThru -NoNewWindow
    
    $restart = $false
    $quit = $false
    
    while ($true) {
        if ([console]::KeyAvailable) {
            $key = [console]::ReadKey($true)
            if ($key.KeyChar -eq 'r' -or $key.KeyChar -eq 'R') {
                $restart = $true
                break
            }
            elseif ($key.KeyChar -eq 'q' -or $key.KeyChar -eq 'Q') {
                $quit = $true
                break
            }
        }
        
        if ($process.HasExited) {
            Write-Host "`nApplication exited. Press 'r' to restart or 'q' to quit." -ForegroundColor Yellow
            while ($true) {
                $waitkey = [console]::ReadKey($true)
                if ($waitkey.KeyChar -eq 'r' -or $waitkey.KeyChar -eq 'R') {
                    $restart = $true
                    break
                }
                elseif ($waitkey.KeyChar -eq 'q' -or $waitkey.KeyChar -eq 'Q') {
                    $quit = $true
                    break
                }
            }
            break
        }
        
        Start-Sleep -Milliseconds 50
    }
    
    if ($restart) {
        if (-not $process.HasExited) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        }
        Write-Host "Restarting..." -ForegroundColor Cyan
        continue
    }
    
    if ($quit) {
        if (-not $process.HasExited) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        }
        Write-Host "Quitting..." -ForegroundColor Cyan
        break
    }
}