; Inno Setup script - builds release\OpenUninstaller-<version>-Setup.exe from dist\OpenUninstaller
; Build:  packaging\build.bat   (or: ISCC.exe packaging\installer.iss)

#define AppName "OpenUninstaller"
#define AppVersion "1.0.0"
#define AppPublisher "Vighnesh Kunjir"
#define AppURL "https://github.com/VighneshKunjir/OpenUninstaller"
#define AppExe "OpenUninstaller.exe"

[Setup]
; Never change AppId - Windows uses it to recognise upgrades of the same app
AppId={{A0A28923-8034-4A06-B70E-35D4C110798C}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir=..\release
OutputBaseFilename={#AppName}-{#AppVersion}-Setup
SetupIconFile=OpenUninstaller.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
; Installs for all users by default; the dialog lets people choose a per-user install instead
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
CloseApplications=yes
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#AppName} Setup
VersionInfoProductName={#AppName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "contextmenu"; Description: "Add 'Uninstall with OpenUninstaller' to the Explorer right-click menu"; GroupDescription: "Integration:"; Flags: unchecked

[Files]
Source: "..\dist\OpenUninstaller\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; Explorer integration (same keys the in-app Options checkbox writes)
Root: HKCU; Subkey: "Software\Classes\Directory\shell\OpenUninstaller"; ValueType: string; ValueName: ""; ValueData: "Uninstall with OpenUninstaller"; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\shell\OpenUninstaller"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe}"; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\Directory\shell\OpenUninstaller\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --forced ""%1"""; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\lnkfile\shell\OpenUninstaller"; ValueType: string; ValueName: ""; ValueData: "Uninstall with OpenUninstaller"; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\lnkfile\shell\OpenUninstaller"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe}"; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\lnkfile\shell\OpenUninstaller\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --forced ""%1"""; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\exefile\shell\OpenUninstaller"; ValueType: string; ValueName: ""; ValueData: "Uninstall with OpenUninstaller"; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\exefile\shell\OpenUninstaller"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe}"; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\exefile\shell\OpenUninstaller\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --forced ""%1"""; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\exefile\shell\OpenUninstallerTrace"; ValueType: string; ValueName: ""; ValueData: "Install with OpenUninstaller (trace)"; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\exefile\shell\OpenUninstallerTrace"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#AppExe}"; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\exefile\shell\OpenUninstallerTrace\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" --trace ""%1"""; Tasks: contextmenu
; Always remove these on uninstall, also when they were enabled later from the app's Options
Root: HKCU; Subkey: "Software\Classes\Directory\shell\OpenUninstaller"; Flags: uninsdeletekey dontcreatekey
Root: HKCU; Subkey: "Software\Classes\lnkfile\shell\OpenUninstaller"; Flags: uninsdeletekey dontcreatekey
Root: HKCU; Subkey: "Software\Classes\exefile\shell\OpenUninstaller"; Flags: uninsdeletekey dontcreatekey
Root: HKCU; Subkey: "Software\Classes\exefile\shell\OpenUninstallerTrace"; Flags: uninsdeletekey dontcreatekey

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
// Settings, backups, history and trace logs live in %LOCALAPPDATA%\OpenUninstaller.
// Ask before removing them, because backups may be needed to restore something later.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{localappdata}\OpenUninstaller');
    if DirExists(DataDir) and not UninstallSilent then
      if MsgBox('Also delete your OpenUninstaller settings, registry backups, uninstall history and trace logs?' + #13#10 + #13#10 +
                'Keep them if you may want to restore something removed with OpenUninstaller.',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);
  end;
end;
