<#
    platform-disk-facts.ps1 - the host's disk as only Windows sees it, for the office to read (DGO-1393).

    ASCII ONLY, DELIBERATELY - same reason as platform-keepalive.ps1: PowerShell 5.1 reads a file without a BOM as
    ANSI, and a non-ASCII character shifts bytes and breaks quote pairing.

    WHY THIS EXISTS
    ---------------
    On 2026-11-05 C: was at 100% (3.2 GB of 476 GB free) and every build of the office stopped, while the engine inside
    the VM read its ext4 as 865 GB free: the ext4 lives in the distro's .vhdx ON C:, and the VM can see neither that
    file nor anything else on the drive (DGO-625). What fills C: is only visible from here. So the health check
    (platform-keepalive.ps1 -HealthCheck, every 5 minutes) asks this file and appends its answer to
    <checkout>\data\power\host.json, beside the memory figures:
      c_free, c_total         C: in bytes
      vhdx_path, vhdx_size    the distro's virtual disk, from WSL's own record of it (HKCU\...\Lxss), and its length
      vhdx_sparse             whether it is a sparse file (it was on the HP: WSL 2.1's sparse VHD, and its ext4 is
                              mounted with discard - so what is deleted inside does come back to C:)
      vhdx_on_disk            what it really occupies on C: - for a sparse file far less than its length; measured
                              at most once an hour (it compiles a call into Windows), kept in disk-facts.cache

    THE SURVEY. Where the rest of C: goes needs a walk of the drive, which is minutes, not a tick: when the office
    asks for one (<checkout>\data\power\disk-survey.request exists), the tick removes the request and starts this file
    with -Survey on its own, hidden and at idle priority; it writes data\power\disk-survey.json - every folder of C:\,
    of the profile, of AppData and of the Desktop two levels down, with its bytes, and the page, hibernation and
    swap files - and exits. `robocopy /L` only LISTS: nothing is copied, timestamped or deleted.

    THE MEMORY SURVEY. With C: freed, the C: mount still failed git with "Input/output error" while Windows had 0.3-0.8
    GB of 16.8 GB free and the VM sat at its 10 GB cap (2026-11-05): ~6 GB were held outside the VM by processes no tick
    listed. On data\power\proc-survey.request the tick writes data\power\proc-survey.json at once (it is quick): the
    machine's memory and commit totals, the 40 largest processes and the 25 largest names summed (forty browser tabs
    are one name). Read-only, like everything here.

    OUTPUT (without -Survey): one line, ',"key":value' pairs, or nothing. Every part is optional: a part that fails is
    left out, never guessed, and nothing here writes, starts or stops anything but the survey it was asked for.
#>
[CmdletBinding()]
param([string]$Distro = 'Ubuntu', [switch]$Survey)

$ErrorActionPreference = 'Stop'
$Repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$Power = Join-Path $Repo 'data\power'

function Get-TreeBytes {
    # the bytes of a folder's files: robocopy /L counts them natively (fast), /XJ keeps it out of junction loops; -1
    # when it cannot be read
    param([string]$Path)
    try {
        $o = & robocopy.exe $Path 'NULL' /L /E /XJ /R:0 /W:0 /NFL /NDL /NJH /BYTES /NP 2>$null
        foreach ($l in @($o)) { if ($l -match '^\s*Bytes\s*:\s*(\d+)') { return [int64]$Matches[1] } }
    } catch { }
    return [int64]-1
}

function Invoke-Survey {
    try { (Get-Process -Id $PID).PriorityClass = 'Idle' } catch { }
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $rows = New-Object System.Collections.ArrayList
    $dirs = New-Object System.Collections.ArrayList
    foreach ($base in @('C:\', $env:USERPROFILE, $env:LOCALAPPDATA, $env:APPDATA, (Join-Path $env:USERPROFILE 'Desktop'))) {
        foreach ($d in @(Get-ChildItem -LiteralPath $base -Force -Directory -ErrorAction SilentlyContinue)) {
            if (-not ($d.Attributes -band [IO.FileAttributes]::ReparsePoint)) { [void]$dirs.Add($d.FullName) }
            if ($base -eq (Join-Path $env:USERPROFILE 'Desktop')) {
                foreach ($e in @(Get-ChildItem -LiteralPath $d.FullName -Force -Directory -ErrorAction SilentlyContinue)) {
                    if (-not ($e.Attributes -band [IO.FileAttributes]::ReparsePoint)) { [void]$dirs.Add($e.FullName) }
                }
            }
        }
    }
    foreach ($p in ($dirs | Select-Object -Unique)) {
        [void]$rows.Add([pscustomobject]@{ path = $p; bytes = (Get-TreeBytes $p) })
    }
    foreach ($f in @('C:\pagefile.sys', 'C:\hiberfil.sys', 'C:\swapfile.sys')) {
        try { [void]$rows.Add([pscustomobject]@{ path = $f; bytes = [int64](Get-Item -LiteralPath $f -Force).Length }) } catch { }
    }
    try {
        $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
        [void]$rows.Add([pscustomobject]@{ path = ('C:\$Recycle.Bin\' + $sid); bytes = (Get-TreeBytes ('C:\$Recycle.Bin\' + $sid)) })
    } catch { }
    $doc = [pscustomobject]@{ updated_at = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds(); seconds = [int]$sw.Elapsed.TotalSeconds
                              items = @($rows | Sort-Object -Property bytes -Descending) }
    $tmp = Join-Path $Power 'disk-survey.json.tmp'
    [System.IO.File]::WriteAllText($tmp, (ConvertTo-Json -Depth 4 -InputObject $doc), (New-Object System.Text.UTF8Encoding($false)))
    Move-Item -LiteralPath $tmp -Destination (Join-Path $Power 'disk-survey.json') -Force
}

function Invoke-ProcSurvey {
    $os = Get-CimInstance Win32_OperatingSystem
    $ps = @(Get-Process -ErrorAction SilentlyContinue)
    $top = @($ps | Sort-Object -Property WorkingSet64 -Descending | Select-Object -First 40 |
             ForEach-Object { [pscustomobject]@{ name = $_.ProcessName; id = $_.Id; ws = [int64]$_.WorkingSet64; private = [int64]$_.PrivateMemorySize64 } })
    $names = @($ps | Group-Object -Property ProcessName | ForEach-Object {
                 [pscustomobject]@{ name = $_.Name; count = $_.Count
                                    ws = [int64](($_.Group | Measure-Object -Property WorkingSet64 -Sum).Sum)
                                    private = [int64](($_.Group | Measure-Object -Property PrivateMemorySize64 -Sum).Sum) } } |
               Sort-Object -Property ws -Descending | Select-Object -First 25)
    $doc = [pscustomobject]@{ updated_at = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
                              mem_total = [int64]$os.TotalVisibleMemorySize * 1024; mem_free = [int64]$os.FreePhysicalMemory * 1024
                              commit_limit = [int64]$os.TotalVirtualMemorySize * 1024; commit_free = [int64]$os.FreeVirtualMemory * 1024
                              processes = $ps.Count; top = $top; by_name = $names }
    $tmp = Join-Path $Power 'proc-survey.json.tmp'
    [System.IO.File]::WriteAllText($tmp, (ConvertTo-Json -Depth 4 -InputObject $doc), (New-Object System.Text.UTF8Encoding($false)))
    Move-Item -LiteralPath $tmp -Destination (Join-Path $Power 'proc-survey.json') -Force
}

if ($Survey) { Invoke-Survey; return }

# where Windows' memory went, when the office asks: quick, so it runs here, the request taken away first
try {
    $preq = Join-Path $Power 'proc-survey.request'
    if (Test-Path -LiteralPath $preq) { Remove-Item -LiteralPath $preq -Force; Invoke-ProcSurvey }
} catch { }

# a survey the office asked for: started once, on its own, and the request taken away first so no tick starts two
try {
    $req = Join-Path $Power 'disk-survey.request'
    if (Test-Path -LiteralPath $req) {
        Remove-Item -LiteralPath $req -Force
        # the path quoted: PowerShell 5.1 joins these with spaces and quotes nothing
        Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden -ArgumentList @(
            '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', ('"' + $PSCommandPath + '"'), '-Survey', '-Distro', $Distro) | Out-Null
    }
} catch { }

$out = ''
try {
    $c = Get-PSDrive -Name C
    $out += ',"c_free":' + [int64]$c.Free + ',"c_total":' + ([int64]$c.Free + [int64]$c.Used)
} catch { }
try {
    foreach ($k in @(Get-ChildItem 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss')) {
        $p = Get-ItemProperty -LiteralPath $k.PSPath -ErrorAction SilentlyContinue
        if ($p -and $p.DistributionName -eq $Distro -and $p.BasePath) {
            $base = ([string]$p.BasePath) -replace '^\\\\\?\\', ''
            $name = if ($p.VhdFileName) { [string]$p.VhdFileName } else { 'ext4.vhdx' }
            $vhd = Join-Path $base $name
            if (Test-Path -LiteralPath $vhd) {
                $f = Get-Item -LiteralPath $vhd
                $sparse = if ($f.Attributes -band [IO.FileAttributes]::SparseFile) { 'true' } else { 'false' }
                $out += ',"vhdx_path":' + (ConvertTo-Json -Compress -InputObject ([string]$vhd)) +
                        ',"vhdx_size":' + [int64]$f.Length + ',"vhdx_sparse":' + $sparse
                # A sparse file's length is not what it holds on C: (measured 2026-11-05: 207 GB long, sparse): the
                # clusters it really occupies are what GetCompressedFileSize answers, for sparse and compressed files.
                # Asking it compiles a call into Windows, so it is asked at most once an hour and the answer kept.
                $onDisk = $null
                $cache = Join-Path $Power 'disk-facts.cache'
                try {
                    $k0 = Get-Content -LiteralPath $cache -Raw | ConvertFrom-Json
                    if ($k0.path -eq [string]$vhd -and ([DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - [int64]$k0.at) -lt 3600) { $onDisk = [int64]$k0.on_disk }
                } catch { }
                if ($null -eq $onDisk) {
                    try {
                        if (-not ('DgoDiskFacts.Native' -as [type])) {
                            Add-Type -Namespace DgoDiskFacts -Name Native -MemberDefinition @'
[DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
public static extern uint GetCompressedFileSizeW(string lpFileName, out uint lpFileSizeHigh);
'@
                        }
                        $hi = [uint32]0
                        $lo = [DgoDiskFacts.Native]::GetCompressedFileSizeW([string]$vhd, [ref]$hi)
                        if ($lo -ne [uint32]::MaxValue -or [Runtime.InteropServices.Marshal]::GetLastWin32Error() -eq 0) {
                            $onDisk = ([int64]$hi * 4294967296) + [int64]$lo
                            $k1 = '{"at":' + [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() + ',"path":' +
                                  (ConvertTo-Json -Compress -InputObject ([string]$vhd)) + ',"on_disk":' + $onDisk + '}'
                            [System.IO.File]::WriteAllText($cache, $k1, (New-Object System.Text.UTF8Encoding($false)))
                        }
                    } catch { }
                }
                if ($null -ne $onDisk) { $out += ',"vhdx_on_disk":' + $onDisk }
            }
            break
        }
    }
} catch { }
$out
