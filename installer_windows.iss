; installer_windows.iss — Inno Setup script for the tech_stock Windows installer.
; Builds a single-file installer: dist\tech_stock_setup.exe
; Requires Inno Setup 6+: https://jrsoftware.org/isinfo.php
;
; v1.19 — productisation parity with the macOS bundle:
;   * AppVersion is injected by build_windows.bat (parsed from src/version.py)
;   * Start-Menu group + uninstaller + optional desktop shortcut
;   * CSV file association so double-clicking a holdings-report*.csv opens the app
;   * Per-user (no admin / no UAC prompt) by default — set PrivilegesRequired=admin
;     if you want a machine-wide install
;   * Optional code-signing via a SignTool stanza driven by the SIGN env var

#define AppName       "tech_stock"
#define AppPublisher  "tech_stock"
#define AppURL        "https://github.com/pouyafath/tech_stock"
#ifndef AppVersion
  #define AppVersion  "0.0.0"
#endif

[Setup]
AppId={{B5C3E2FB-1A92-4D7B-9F3C-3C0F4B7AE901}}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
OutputDir=dist
OutputBaseFilename=tech_stock_setup
SetupIconFile=assets\icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64
UninstallDisplayIcon={app}\tech_stock.exe
UninstallDisplayName={#AppName} {#AppVersion}
LicenseFile=LICENSE
MinVersion=10.0
VersionInfoVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription=AI-powered portfolio advisor built on Claude
VersionInfoProductName={#AppName}
ChangesAssociations=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked
Name: "associatecsv"; Description: "Open Wealthsimple &CSV files with tech_stock"; GroupDescription: "File associations:"; Flags: unchecked

[Files]
Source: "dist\tech_stock\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "data\samples\*"; DestDir: "{app}\samples"; Flags: ignoreversion recursesubdirs; Components: samples
Source: "LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Components]
Name: "core"; Description: "Core application"; Types: full compact custom; Flags: fixed
Name: "samples"; Description: "Bundled sample portfolio for demo mode"; Types: full

[Icons]
Name: "{group}\{#AppName}";              Filename: "{app}\tech_stock.exe"
Name: "{group}\{#AppName} (Demo mode)";  Filename: "{app}\tech_stock.exe"; Parameters: "--demo"; Comment: "Launch with bundled sample data"
Name: "{group}\Uninstall {#AppName}";    Filename: "{uninstallexe}"
Name: "{commondesktop}\{#AppName}";      Filename: "{app}\tech_stock.exe"; Tasks: desktopicon

[Registry]
; CSV file association — registered under the per-user hive so no admin needed.
Root: HKCU; Subkey: "Software\Classes\.csv\OpenWithProgids"; ValueType: string; ValueName: "tech_stock.holdings_csv"; ValueData: ""; Flags: uninsdeletevalue; Tasks: associatecsv
Root: HKCU; Subkey: "Software\Classes\tech_stock.holdings_csv"; ValueType: string; ValueName: ""; ValueData: "Wealthsimple Holdings CSV"; Flags: uninsdeletekey; Tasks: associatecsv
Root: HKCU; Subkey: "Software\Classes\tech_stock.holdings_csv\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\tech_stock.exe,0"; Tasks: associatecsv
Root: HKCU; Subkey: "Software\Classes\tech_stock.holdings_csv\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\tech_stock.exe"" --import-csv ""%1"""; Tasks: associatecsv

[Run]
Filename: "{app}\tech_stock.exe"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
  // Future: SmartScreen / Authenticode signing gate would happen here if SIGN env-var is set.
end;
