# PowerShell script to associate .3col files with 3ColRef
$extension = ".3col"
$progId = "3ColRef.Scene"
$description = "3ColRef Scene"
$appRoot = $PSScriptRoot.Trim()
$iconPath = "$appRoot\threecolref\assets\logo.ico"

# Try to use venv python first
$venvPython = "$appRoot\venv\Scripts\python.exe"
$venvPythonw = "$appRoot\venv\Scripts\pythonw.exe"

if (Test-Path $venvPythonw) {
    $pythonwExe = $venvPythonw
} else {
    $pythonwExe = (Get-Command python -ErrorAction SilentlyContinue).Source
    if ($pythonwExe) {
        $pythonwExe = $pythonwExe.Replace("python.exe", "pythonw.exe").Trim()
    }
}

if (!$pythonwExe) {
    Write-Error "Could not find pythonw.exe"
    exit 1
}

# Construct the Python code to run
$pythonCode = "import sys; sys.path.insert(0, r'$appRoot'); from threecolref.__main__ import main; main()"

# Construct the final command line
$command = "`"$pythonwExe`" -c `"$pythonCode`" `"%1`""

Write-Host "Registering Command: $command"

# 1. Create the ProgID
$registryPath = "HKCU:\Software\Classes\$progId"
if (!(Test-Path $registryPath)) { New-Item -Path $registryPath -Force | Out-Null }
Set-ItemProperty -Path $registryPath -Name "(Default)" -Value $description -Force

# 2. Set the Icon
$iconRegPath = "$registryPath\DefaultIcon"
if (!(Test-Path $iconRegPath)) { New-Item -Path $iconRegPath -Force | Out-Null }
Set-ItemProperty -Path $iconRegPath -Name "(Default)" -Value $iconPath -Force

# 3. Set the Open Command
$shellRegPath = "$registryPath\shell\open\command"
if (!(Test-Path $shellRegPath)) { New-Item -Path $shellRegPath -Force | Out-Null }
Set-ItemProperty -Path $shellRegPath -Name "(Default)" -Value $command -Force

# 4. Associate extension with ProgID
$extensionRegPath = "HKCU:\Software\Classes\$extension"
if (!(Test-Path $extensionRegPath)) { New-Item -Path $extensionRegPath -Force | Out-Null }
Set-ItemProperty -Path $extensionRegPath -Name "(Default)" -Value $progId -Force

# Force Windows to refresh the icon cache (simple way: send a notify signal)
# This isn't always perfect but helps.
Write-Host "Updating registry... Done."
Write-Host "Please restart Explorer or sign out/in if icons don't update immediately."
