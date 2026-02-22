# PowerShell script to associate .3col files with 3ColRef
$extension = ".3col"
$progId = "3ColRef.Scene"
$description = "3ColRef Scene"
$appRoot = "f:\Luohino\resources\beeref"
$iconPath = "$appRoot\threecolref\assets\logo.ico"

$pythonExe = (Get-Command python).Source
$pythonwExe = $pythonExe.Replace("python.exe", "pythonw.exe")
if (!(Test-Path $pythonwExe)) { $pythonwExe = $pythonExe }

# Construct the Python code to run
$pythonCode = "import sys; sys.path.insert(0, r'$appRoot'); from threecolref.__main__ import main; main()"

# Construct the final command line
$command = "`"$pythonwExe`" -c `"$pythonCode`" `"%1`""

Write-Host "Registering Command: $command"

# 1. Create the ProgID
$registryPath = "HKCU:\Software\Classes\$progId"
if (!(Test-Path $registryPath)) { New-Item -Path $registryPath -Force }
Set-ItemProperty -Path $registryPath -Name "(Default)" -Value $description

# 2. Set the Icon
$iconRegPath = "$registryPath\DefaultIcon"
if (!(Test-Path $iconRegPath)) { New-Item -Path $iconRegPath -Force }
Set-ItemProperty -Path $iconRegPath -Name "(Default)" -Value $iconPath

# 3. Set the Open Command
$shellRegPath = "$registryPath\shell\open\command"
if (!(Test-Path $shellRegPath)) { New-Item -Path $shellRegPath -Force }
Set-ItemProperty -Path $shellRegPath -Name "(Default)" -Value $command

# 4. Associate extension with ProgID
$extensionRegPath = "HKCU:\Software\Classes\$extension"
if (!(Test-Path $extensionRegPath)) { New-Item -Path $extensionRegPath -Force }
Set-ItemProperty -Path $extensionRegPath -Name "(Default)" -Value $progId

Write-Host "Done."
