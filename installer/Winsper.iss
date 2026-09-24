#define MyAppName "Winsper"
#ifndef MyAppVersion
#define MyAppVersion "1.1.1"
#endif
#ifndef MyAppPublisher
#define MyAppPublisher "Winsper"
#endif
#ifndef MyAppReleaseSuffix
#define MyAppReleaseSuffix ""
#endif
#define MyAppExeName "Winsper.exe"

[Setup]
AppId={{13D45A8C-61C1-4C74-A09E-8863EBF61391}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL=https://winsper.app/
AppSupportURL=https://winsper.app/
AppUpdatesURL=https://winsper.app/download/
DefaultDirName={autopf}\Winsper
DefaultGroupName=Winsper
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
OutputBaseFilename=WinsperSetup-{#MyAppVersion}{#MyAppReleaseSuffix}
SetupIconFile=..\build\winsper.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription=Winsper for Windows installer
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}
VersionInfoVersion={#MyAppVersion}
CloseApplications=yes
RestartApplications=no

[Files]
Source: "..\dist\Winsper\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Winsper"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\Winsper"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch Winsper"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{userstartup}\Winsper.vbs"

[Code]
function HasUninstallParameter(Name: String): Boolean;
var
  Index: Integer;
begin
  Result := False;
  for Index := 1 to ParamCount do
  begin
    if CompareText(ParamStr(Index), Name) = 0 then
    begin
      Result := True;
      exit;
    end;
  end;
end;

function ShouldRemoveUserData(): Boolean;
begin
  if HasUninstallParameter('/PURGEUSERDATA') then
  begin
    Result := True;
    exit;
  end;
  if UninstallSilent then
  begin
    Result := False;
    exit;
  end;
  Result := MsgBox(
    'Remove Winsper settings, history, downloaded models, and diagnostics from this Windows account?' + #13#10 + #13#10 +
    'Choose No to keep your data for a later reinstall.',
    mbConfirmation,
    MB_YESNO
  ) = IDYES;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  RoamingDataPath: String;
  LocalDataPath: String;
  RoamingRemoved: Boolean;
  LocalRemoved: Boolean;
  MessageText: String;
begin
  if (CurUninstallStep <> usUninstall) or not ShouldRemoveUserData() then
    exit;

  RoamingDataPath := ExpandConstant('{userappdata}\Winsper');
  LocalDataPath := ExpandConstant('{localappdata}\Winsper');
  RoamingRemoved := DelTree(RoamingDataPath, True, True, True);
  LocalRemoved := DelTree(LocalDataPath, True, True, True);
  MessageText := '';
  if not RoamingRemoved then
    MessageText := 'Winsper could not remove roaming user data at:' + #13#10 + RoamingDataPath + #13#10 + #13#10;
  if not LocalRemoved then
    MessageText := MessageText + 'Winsper could not remove local user data at:' + #13#10 + LocalDataPath;
  if MessageText <> '' then
  begin
    Log(MessageText);
    if not UninstallSilent then
      MsgBox(MessageText, mbInformation, MB_OK);
  end;
end;
