; ─────────────────────────────────────────────────────────────────────────────
;  Pi Bench — Inno Setup 6 installer script
;
;  Build:   iscc pi_bench_setup.iss
;  Output:  dist\PiBenchSetup.exe
;
;  Requirements (build machine only):
;    Inno Setup 6.x  — https://jrsoftware.org/isdl.php
;
;  The installer:
;    • Downloads Python 3.12.8 embeddable runtime (~26 MB) during install
;    • Downloads and installs Python packages (PyQt6, gpt4all, ~200 MB)
;    • Installs VC++ 2022 runtime if missing (needed by gpt4all)
;    • Installs to  %LOCALAPPDATA%\Programs\Pi Bench\  (no admin required)
;    • Registers with Windows Add/Remove Programs
;    • Creates Start Menu shortcuts and optional Desktop shortcut
;    • LLM model (~2.2 GB) downloads automatically on first AI-tab launch
; ─────────────────────────────────────────────────────────────────────────────

#define AppName    "Pi Bench"
; AppVersion is injected by build_installer.bat via /DAppVersion=x.y.z
; Fall back to "1.0.0" only if built directly without the build script.
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppId      "PiBench"
#define SrcDir     "."

; ── App metadata ──────────────────────────────────────────────────────────────
[Setup]
AppId={{B7E4A2F1-3D8C-4E9B-A1F2-5C7D9E0B3A4E}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Pi Bench
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
AllowNoIcons=yes
OutputDir=dist
OutputBaseFilename=PiBenchSetup-{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern

; User-level install — no admin UAC prompt.
; (The VC++ 2022 runtime install inside install.py will prompt for UAC
;  if it is not already present, which is normal and expected.)
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DisableProgramGroupPage=yes

; Add/Remove Programs display
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\python\pythonw.exe

; ── Languages ─────────────────────────────────────────────────────────────────
[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

; ── Optional tasks shown in the wizard ────────────────────────────────────────
[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

; ── Files to install ──────────────────────────────────────────────────────────
[Files]
; Core app
Source: "{#SrcDir}\pi_bench.py";              DestDir: "{app}"; Flags: ignoreversion
Source: "{#SrcDir}\pi_bench_dev.py";          DestDir: "{app}"; Flags: ignoreversion
Source: "{#SrcDir}\pi_bench_gui.py";          DestDir: "{app}"; Flags: ignoreversion
Source: "{#SrcDir}\pi_bench_gui_dev.py";      DestDir: "{app}"; Flags: ignoreversion
Source: "{#SrcDir}\pi_bench_gui_aero.py";     DestDir: "{app}"; Flags: ignoreversion
Source: "{#SrcDir}\pi_bench_gui_dev_llm.py";  DestDir: "{app}"; Flags: ignoreversion

; Maintenance scripts
Source: "{#SrcDir}\install.py";               DestDir: "{app}"; Flags: ignoreversion
Source: "{#SrcDir}\uninstall.py";             DestDir: "{app}"; Flags: ignoreversion

; Bootstrap helper — runs during install, then auto-deleted
Source: "{#SrcDir}\_setup_python.bat";        DestDir: "{app}"; Flags: ignoreversion deleteafterinstall

; ── Shortcuts ─────────────────────────────────────────────────────────────────
; PiBench.exe is a pythonw.exe wrapper — no console window on launch.
[Icons]
; Start Menu — classic theme
Name: "{group}\{#AppName}";                Filename: "{app}\python\PiBench.exe"; Parameters: """{app}\pi_bench_gui_dev.py""";      WorkingDir: "{app}"; Comment: "Pi Bench CPU Benchmark"
; Start Menu — Frutiger Aero theme
Name: "{group}\{#AppName} Aero";           Filename: "{app}\python\PiBench.exe"; Parameters: """{app}\pi_bench_gui_aero.py""";     WorkingDir: "{app}"; Comment: "Pi Bench CPU Benchmark — Frutiger Aero theme"
; Start Menu — uninstall
Name: "{group}\Uninstall {#AppName}";      Filename: "{uninstallexe}";                                                             Comment: "Uninstall Pi Bench"
; Desktop shortcuts (shown only if task is checked)
Name: "{autodesktop}\{#AppName}";          Filename: "{app}\python\PiBench.exe"; Parameters: """{app}\pi_bench_gui_dev.py""";      WorkingDir: "{app}"; Comment: "Pi Bench CPU Benchmark"; Tasks: desktopicon
Name: "{autodesktop}\{#AppName} Aero";     Filename: "{app}\python\PiBench.exe"; Parameters: """{app}\pi_bench_gui_aero.py""";     WorkingDir: "{app}"; Comment: "Pi Bench CPU Benchmark — Frutiger Aero theme"; Tasks: desktopicon

; ── Post-install steps ────────────────────────────────────────────────────────
[Run]
; Step 1: Download Python runtime + bootstrap pip
Filename: "cmd.exe"; \
    Parameters: "/c _setup_python.bat"; \
    WorkingDir: "{app}"; \
    StatusMsg: "Downloading Python runtime (~26 MB)..."; \
    Flags: waituntilterminated

; Step 2: Install Python packages (PyQt6, gpt4all, VC++ runtime, etc.)
; --no-launchers: skip .bat files — Inno Setup creates shortcuts itself
Filename: "{app}\python\python.exe"; \
    Parameters: """{app}\install.py"" --no-launchers"; \
    WorkingDir: "{app}"; \
    StatusMsg: "Installing packages (PyQt6, gpt4all ~200 MB — may take several minutes)..."; \
    Flags: waituntilterminated

; Optional: offer to launch the app at the end of installation
Filename: "{app}\python\PiBench.exe"; \
    Parameters: """{app}\pi_bench_gui_dev.py"""; \
    WorkingDir: "{app}"; \
    Description: "Launch {#AppName} now"; \
    Flags: nowait postinstall skipifsilent

; ── Uninstall steps ───────────────────────────────────────────────────────────
; Step 1: Run uninstall.py to remove runtime artifacts (keyring, LHM, model, runs).
; Step 2: After python.exe exits, forcibly delete the entire app folder.
;         A 2-second pause lets Windows release any DLL file locks before rmdir.
[UninstallRun]
Filename: "{app}\python\python.exe"; \
    Parameters: """{app}\uninstall.py"" --yes"; \
    WorkingDir: "{app}"; \
    RunOnceId: "CleanArtifacts"; \
    Flags: waituntilterminated

Filename: "cmd.exe"; \
    Parameters: "/c timeout /t 2 /nobreak >nul & rmdir /s /q ""{app}"""; \
    RunOnceId: "RemoveAppDir"; \
    Flags: waituntilterminated runhidden

; ── Uninstall cleanup ─────────────────────────────────────────────────────────
; Remove user-data dirs that uninstall.py may not have reached (e.g., if it
; was skipped), and ensure the whole install directory is gone.
[UninstallDelete]
Type: filesandordirs; Name: "{app}\pi_bench_models"
Type: filesandordirs; Name: "{app}\pi_bench_runs"
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}"
