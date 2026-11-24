<#
.SYNOPSIS
    home-shortcut.ps1 - the office's folder on the Desktop after `bbox home move` (DGO-2019).

.DESCRIPTION
    The move puts the DGO folder on WSL's own disk, which Windows reaches as \\wsl.localhost\<distro>\home\...
    This puts a shortcut with the folder's name on the user's Desktop, pointing there, so the owner opens his office
    folder - and its data\ - where he always did, in Explorer. The move calls it through WSL's interop once the office
    runs well from the new folder. Idempotent; never fails the caller.
#>
param(
    [Parameter(Mandatory = $true)][string]$Target,
    [Parameter(Mandatory = $true)][string]$Name
)

$ErrorActionPreference = 'Stop'
try {
    $lnk = Join-Path ([Environment]::GetFolderPath('Desktop')) ($Name + '.lnk')
    $shell = New-Object -ComObject WScript.Shell
    $s = $shell.CreateShortcut($lnk)
    $s.TargetPath = $Target
    $s.Description = 'The digital office - its folder on WSL''s own disk (DGO-2019)'
    $s.Save()
    Write-Host "[bbox] the office's folder is on the Desktop: $lnk -> $Target"
} catch {
    Write-Host "[bbox] note: the Desktop shortcut was not made ($($_.Exception.Message)); the folder is $Target"
}
exit 0
