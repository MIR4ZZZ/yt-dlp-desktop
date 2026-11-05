#ifndef SourceDir
  #error SourceDir must be supplied by the build script
#endif
#ifndef OutputDir
  #define OutputDir "."
#endif
#ifndef AppVersion
  #define AppVersion "1.2.0-preview.1"
#endif

[Setup]
AppId={{8B80502D-D2C0-4D84-B634-96A11572B59C}
AppName=Unofficial yt-dlp Desktop
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\yt-dlp-ui
DefaultGroupName=Unofficial yt-dlp Desktop
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=yt-dlp-desktop-{#AppVersion}-setup
SetupIconFile={#SourceDir}\assets\logo.ico
UninstallDisplayIcon={app}\yt-dlp-ui.exe
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
LicenseFile={#SourceDir}\licenses\yt-dlp-LICENSE.txt

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Unofficial yt-dlp Desktop"; Filename: "{app}\yt-dlp-ui.exe"
Name: "{autodesktop}\Unofficial yt-dlp Desktop"; Filename: "{app}\yt-dlp-ui.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\yt-dlp-ui.exe"; Description: "Launch Unofficial yt-dlp Desktop"; Flags: nowait postinstall skipifsilent
