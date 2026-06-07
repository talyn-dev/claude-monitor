$python = (Get-Command python -ErrorAction Stop).Source
$ws = New-Object -ComObject WScript.Shell
$shortcut = $ws.CreateShortcut("$env:USERPROFILE\Desktop\Claude Monitor.lnk")
$shortcut.TargetPath = $python
$shortcut.Arguments = "`"$PSScriptRoot\main.py`""
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.WindowStyle = 7
$shortcut.Description = "Claude Usage Monitor"
$shortcut.Save()
Write-Host "Shortcut created on desktop."
