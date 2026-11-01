; BinaOS.iss — Inno Setup script for BinaOS-Setup.exe
;
;   ISCC.exe /DVersion=2026.08.0 /DPayloadDir=..\..\dist packaging\windows\BinaOS.iss
;
; WHY INNO AND NOT NSIS/MSI/SFX
;   NSIS caps installers at 2 GB — disqualifying for a ~3 GB payload.
;   MSI's transactional file-copy buys nothing here, and %WINDIR%\Installer caching risks doubling
;     peak disk.
;   A 7-Zip SFX stages to %TEMP%, which is exactly the failure being avoided — this repo's own dev
;     machine was filled to zero bytes free by a large temp write.
;   Inno needs disk spanning only above ~4.2 GB, so a 3-3.5 GB single .exe is fine.
;
; THE DISK RULE
;   Compression=none and `nocompression` on the payload: it is already gzip/zstd, so recompressing
;   costs build time and gains nothing. The payload is extracted to {app}, NEVER to {tmp}, and the
;   rootfs is then STREAMED into `wsl --import` from stdin so it never exists twice.
;
; THE SIGNING RULE
;   Appending to an already-signed exe voids the signature — verified empirically: copying a signed
;   notepad.exe and appending 1 MB flips Get-AuthenticodeSignature from Valid to NotSigned. So:
;   build fully, THEN sign, then never touch the bytes. SignTool below runs at the end of the build.

#ifndef Version
  #define Version "0.0.0-dev"
#endif
#ifndef PayloadDir
  #define PayloadDir "..\..\dist"
#endif

[Setup]
AppId={{7C4E1A62-2C1E-4B8E-9E3A-BINAOS000001}
AppName=BinaOS
AppVersion={#Version}
AppPublisher=Bina Solutions
DefaultDirName={localappdata}\BinaOS
DefaultGroupName=BinaOS
OutputDir={#PayloadDir}
OutputBaseFilename=BinaOS-Setup-{#Version}
; Non-elevated by default. The ONLY thing needing admin is enabling VirtualMachinePlatform and
; writing the hosts block, and both are done by one explicitly-elevated child process — see
; packaging/windows.md. Running the whole installer elevated would be wrong: `wsl --import` from an
; elevated context can register the distro under a different profile when Windows Admin Protection
; is on.
PrivilegesRequired=lowest
Compression=none
SolidCompression=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; WSL2 needs build 19041+. Gate on the build number, never on ProductName — it reads
; "Windows 10 Pro" on Windows 11 build 26200.
MinVersion=10.0.19041
WizardStyle=modern
DisableProgramGroupPage=yes
UninstallDisplayName=BinaOS {#Version}

[Files]
; nocompression: the payload is already gzip/zstd, and recompressing 2 GB buys nothing but hours.
;
; NOT `external`. That flag means the file is NOT stored inside Setup.exe - it is read from the
; source path at INSTALL time, so the customer would need the .tar.gz and .tar.zst sitting next to
; the installer. That is the opposite of the single-file brief. It was useful only for syntax-
; checking the script without a 2 GB payload present; define SKIPPAYLOAD for that instead:
;   ISCC.exe /DSKIPPAYLOAD packaging\windows\BinaOS.iss
#ifndef SKIPPAYLOAD
; The WSL2 kernel. 17 MB, and without it a clean Windows 10 machine cannot start the distro at all -
; enabling the WSL and VirtualMachinePlatform features is necessary but NOT sufficient, and
; `wsl --import --version 2` fails with "WSL 2 requires an update to its kernel component".
; Bundled rather than downloaded at install time, so one file stays enough.
Source: "{#PayloadDir}\wsl_update_x64.msi";  DestDir: "{app}"; Flags: skipifsourcedoesntexist
Source: "{#PayloadDir}\binaos-rootfs.tar.gz"; DestDir: "{app}"; Flags: nocompression
Source: "{#PayloadDir}\images.tar.zst";       DestDir: "{app}"; Flags: nocompression
Source: "{#PayloadDir}\manifest.json";        DestDir: "{app}"; Flags: skipifsourcedoesntexist
Source: "{#PayloadDir}\manifest.sigstore.json"; DestDir: "{app}"; Flags: skipifsourcedoesntexist
#endif
Source: "install.ps1";                        DestDir: "{app}"; Flags: ignoreversion
Source: "uninstall.ps1";                      DestDir: "{app}"; Flags: ignoreversion

[Run]
Filename: "powershell.exe"; \
  Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\install.ps1"" -AppDir ""{app}"" -Version ""{#Version}"""; \
  StatusMsg: "Importing the BinaOS distribution and loading images (this takes several minutes)..."; \
  Flags: runhidden waituntilterminated

[UninstallRun]
; runascurrentuser: `wsl --unregister` must run as the installing user, since the distro is
; registered under HKCU.
Filename: "powershell.exe"; \
  Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\uninstall.ps1"" -AppDir ""{app}"""; \
  Flags: runhidden waituntilterminated runascurrentuser;   RunOnceId: "BinaOSRemoveDistro"

[Code]
function VmpEnabled(): Boolean;
var
  ResultCode: Integer;
begin
  { Win32_OptionalFeature via WMI is readable WITHOUT elevation; Get-WindowsOptionalFeature (the
    DISM module) is not. InstallState 1 = Enabled. }
  Result := Exec('powershell.exe',
    '-NoProfile -ExecutionPolicy Bypass -Command "exit [int]!((Get-CimInstance Win32_OptionalFeature ' +
    '-Filter ''Name=''''VirtualMachinePlatform'''''').InstallState -eq 1)"',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
begin
  Result := True;
  if not VmpEnabled() then
  begin
    if MsgBox('Windows needs one system feature enabled before BinaOS can run:' #13#10 #13#10
            + '    Virtual Machine Platform' #13#10 #13#10
            + 'This requires administrator approval and a restart. It is a one-time step —'
            + ' everything afterwards runs without administrator rights.' #13#10 #13#10
            + 'Enable it now?', mbConfirmation, MB_YESNO) = IDYES then
    begin
      { Deliberately a separate elevated child rather than elevating the whole installer. }
      Exec('powershell.exe',
        '-NoProfile -ExecutionPolicy Bypass -Command "Start-Process wsl.exe ' +
        '-ArgumentList ''--install'',''--no-distribution'' -Verb RunAs -Wait"',
        '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
      MsgBox('Restart Windows, then run this installer again to finish.', mbInformation, MB_OK);
    end;
    Result := False;
  end;
end;
