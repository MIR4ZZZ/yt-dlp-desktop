#ifndef PayloadUrl
  #error PayloadUrl is required
#endif
#ifndef PayloadHash
  #error PayloadHash is required
#endif
#ifndef PayloadBytes
  #error PayloadBytes is required
#endif
#ifndef PayloadExpandedBytes
  #error PayloadExpandedBytes is required
#endif

#define AppVersion "1.3.0-preview.1"

[Setup]
AppId={{B6E97B35-287D-49A4-A7AE-3E98760DA210}
AppName=Unofficial yt-dlp Desktop
AppVersion={#AppVersion}
AppPublisher=MIR4ZZZ
AppPublisherURL=https://github.com/MIR4ZZZ/yt-dlp-desktop
DefaultDirName={localappdata}\Programs\Unofficial yt-dlp Desktop
DefaultGroupName=Unofficial yt-dlp Desktop
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\dist\tauri-preview
OutputBaseFilename=yt-dlp-desktop-{#AppVersion}-online-setup
Compression=lzma2
SolidCompression=yes
ArchiveExtraction=full
WizardStyle=modern
SetupIconFile=..\src-tauri\icons\icon.ico
InfoBeforeFile=download-notice.txt
UninstallDisplayIcon={app}\yt-dlp-desktop.exe

[Files]
Source: "{#PayloadUrl}"; DestDir: "{app}"; DestName: "yt-dlp-desktop-payload.zip"; ExternalSize: {#PayloadExpandedBytes}; Hash: "{#PayloadHash}"; Flags: external download extractarchive ignoreversion recursesubdirs createallsubdirs
Source: "..\..\build\MicrosoftEdgeWebview2Setup.exe"; Flags: dontcopy

[Icons]
Name: "{autoprograms}\Unofficial yt-dlp Desktop"; Filename: "{app}\yt-dlp-desktop.exe"
Name: "{autodesktop}\Unofficial yt-dlp Desktop"; Filename: "{app}\yt-dlp-desktop.exe"; Tasks: desktopicon

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; Flags: unchecked

[Run]
Filename: "{app}\yt-dlp-desktop.exe"; Description: "Launch Unofficial yt-dlp Desktop"; Flags: nowait postinstall skipifsilent

[Code]
function HasWebView2: Boolean;
var
  Version: String;
  Key: String;
begin
  Key := 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  Result := (RegQueryStringValue(HKCU, Key, 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0')) or
    (RegQueryStringValue(HKLM64, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0'));
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ExitCode: Integer;
begin
  Result := '';
  if HasWebView2 then Exit;
  ExtractTemporaryFile('MicrosoftEdgeWebview2Setup.exe');
  if not Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe'), '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, ExitCode) or (ExitCode <> 0) or not HasWebView2 then
    Result := 'WebView2 could not be installed. Setup has stopped before downloading the app.';
end;
