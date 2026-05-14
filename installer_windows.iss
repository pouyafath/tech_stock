; installer_windows.iss — Inno Setup script for tech_stock Windows installer
; Builds a signed single-file installer: dist\tech_stock_setup.exe
; Requires Inno Setup 6+: https://jrsoftware.org/isinfo.php

[Setup]
AppName=tech_stock
AppVersion=1.0.0
AppPublisher=tech_stock
AppPublisherURL=https://github.com/your-org/tech_stock
DefaultDirName={autopf}\tech_stock
DefaultGroupName=tech_stock
OutputDir=dist
OutputBaseFilename=tech_stock_setup
SetupIconFile=assets\icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64
UninstallDisplayIcon={app}\tech_stock.exe
LicenseFile=LICENSE
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
Source: "dist\tech_stock\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\tech_stock";         Filename: "{app}\tech_stock.exe"
Name: "{group}\Uninstall tech_stock"; Filename: "{uninstallexe}"
Name: "{commondesktop}\tech_stock"; Filename: "{app}\tech_stock.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\tech_stock.exe"; Description: "Launch tech_stock"; Flags: nowait postinstall skipifsilent
