#!/usr/bin/env python3
"""
install.py — Pi Bench package installer.

Called by setup.bat / setup.sh after Python is ready.
Can also be called directly if Python 3.10+ is already on PATH.

Two modes are detected automatically:
  embedded  — python/python.exe exists next to this script
              (created by setup.bat from the embeddable zip).
              Packages are installed directly into that Python.
              No venv needed — the embedded Python is already isolated.

  venv      — fallback for system Python on Linux / macOS or when
              no embedded Python is present.
              Creates venv/ and installs there.
"""

import argparse, os, platform, subprocess, sys

# Force UTF-8 output so symbols display correctly in any terminal / SSH session.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
EMBEDDED_PY = os.path.join(SCRIPT_DIR, "python")   # managed embedded Python dir
VENV_DIR    = os.path.join(SCRIPT_DIR, "venv")

# Core packages — always installed
CORE_PKGS = ["PyQt6", "pyqtgraph", "keyring", "paramiko"]

# LLM package — gpt4all ships its own compiled DLL in the PyPI wheel so it
# installs as a real binary on Windows/Linux/macOS with no compiler needed.
# PyPI wheel: gpt4all-X.X.X-py3-none-win_amd64.whl  (~114 MB, any Python 3)
# It uses the same llama.cpp engine internally as llama-cpp-python but
# bundles the native library, so no prebuilt-wheel hunt is required.
LLM_PKG = "gpt4all"

# Launcher scripts to write
LAUNCHERS_WIN = [
    ("run.bat",       "pi_bench_gui.py",         "Production build"),
    ("run_dev.bat",   "pi_bench_gui_dev.py",     "Dev build (no LLM)"),
    ("run_llm.bat",   "pi_bench_gui_dev_llm.py", "Dev build + AI analysis"),
    ("uninstall.bat", "uninstall.py",             "Uninstaller"),
    ("setup.bat",     None,                       None),   # written by setup.bat, keep it
]
LAUNCHERS_UNIX = [
    ("run.sh",        "pi_bench_gui.py",         "Production build"),
    ("run_dev.sh",    "pi_bench_gui_dev.py",     "Dev build (no LLM)"),
    ("run_llm.sh",    "pi_bench_gui_dev_llm.py", "Dev build + AI analysis"),
    ("uninstall.sh",  "uninstall.py",             "Uninstaller"),
]


# ── Mode detection ────────────────────────────────────────────────────────────

def _detect_mode():
    """Return ('embedded', exe_path) or ('venv', None)."""
    if platform.system() == "Windows":
        exe = os.path.join(EMBEDDED_PY, "python.exe")
        if os.path.exists(exe):
            return "embedded", exe
    return "venv", None


def _target_python(mode: str, embedded_exe: str | None) -> str:
    """Return the Python executable that will run the app after install."""
    if mode == "embedded":
        return embedded_exe  # type: ignore[return-value]
    if platform.system() == "Windows":
        return os.path.join(VENV_DIR, "Scripts", "python.exe")
    return os.path.join(VENV_DIR, "bin", "python")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(*cmd, **kw):
    print("  $", " ".join(str(c) for c in cmd))
    subprocess.run(list(cmd), check=True, **kw)


def _ensure_pip(py_exe: str):
    """Bootstrap pip into the target Python if it is missing.

    Embedded Python ships without pip — setup.bat normally installs it via
    get-pip.py, but if that step was skipped or failed we catch it here.

    Uses PowerShell on Windows for the download because urllib in a freshly
    extracted embedded Python may not have SSL available yet.
    """
    result = subprocess.run([py_exe, "-m", "pip", "--version"],
                            capture_output=True)
    if result.returncode == 0:
        return   # pip is already present
    print("      pip not found — bootstrapping pip …")
    import tempfile
    url = "https://bootstrap.pypa.io/get-pip.py"
    tmp = os.path.join(tempfile.gettempdir(), "_get_pip.py")
    try:
        if platform.system() == "Windows":
            # PowerShell has full TLS support regardless of Python's ssl state.
            ps_cmd = (
                "[Net.ServicePointManager]::SecurityProtocol="
                "[Net.SecurityProtocolType]::Tls12; "
                f"(New-Object Net.WebClient).DownloadFile('{url}','{tmp}')"
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-Command", ps_cmd],
                check=True
            )
        else:
            import urllib.request
            req = urllib.request.Request(url, headers={"User-Agent": "pi-bench/1.0"})
            with urllib.request.urlopen(req, timeout=60) as resp, \
                 open(tmp, "wb") as f:
                f.write(resp.read())
        subprocess.run([py_exe, tmp, "--quiet"], check=True)
        print("      ✓ pip bootstrapped")
    except Exception as exc:
        raise RuntimeError(f"Could not bootstrap pip: {exc}") from exc
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass


def _vcredist_present() -> bool:
    """Return True if MSVC 2015-2022 runtime is already installed."""
    # msvcp140.dll in System32 is the reliable indicator
    sys32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
    return os.path.exists(os.path.join(sys32, "msvcp140.dll"))


def _ensure_vcredist():
    """Download and silently install the VC++ 2022 x64 redistributable if absent.

    gpt4all's llmodel.dll is compiled with MSVC and needs msvcp140.dll.
    The VC++ redistributable is tiny (~26 MB) and installs system-wide.
    The installer will prompt for UAC elevation — that is normal and expected.
    """
    if platform.system() != "Windows":
        return
    if _vcredist_present():
        print("      ✓ MSVC runtime already installed")
        return

    import urllib.request, tempfile
    url = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
    tmp = os.path.join(tempfile.gettempdir(), "vc_redist.x64.exe")
    print(f"      Downloading VC++ 2022 runtime (~26 MB) …")
    print(f"      (needed by gpt4all's native library — admin prompt will appear)")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "pi-bench/1.0"})
        with urllib.request.urlopen(req, timeout=120) as resp, open(tmp, "wb") as f:
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
        print(f"      Running installer (accept the UAC prompt if asked) …")
        result = subprocess.run([tmp, "/quiet", "/norestart"], timeout=120)
        if result.returncode in (0, 3010):   # 0 = ok, 3010 = reboot recommended
            print(f"      ✓ VC++ 2022 runtime installed")
        else:
            print(f"      ⚠  VC++ installer returned {result.returncode} — "
                  f"gpt4all may not work.  Run vc_redist.x64.exe manually if needed.")
    except Exception as exc:
        print(f"      ⚠  Could not install VC++ runtime: {exc}")
        print(f"         Download manually: {url}")
        print(f"         gpt4all will not work until this is installed.")
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Pi Bench installer")
    ap.add_argument("--no-llm", action="store_true",
                    help="Skip gpt4all (AI tab won't work)")
    ap.add_argument("--no-launchers", action="store_true",
                    help="Skip writing .bat/.sh launcher scripts "
                         "(used when called from an Inno Setup installer — "
                         "shortcuts are managed by the installer instead)")
    args = ap.parse_args()

    # Auto-detect Inno Setup managed install: if unins000.exe is present next to
    # us, Inno Setup owns the shortcuts and uninstall — don't write launchers.
    if not args.no_launchers:
        if os.path.exists(os.path.join(SCRIPT_DIR, "unins000.exe")):
            args.no_launchers = True
    mode, embedded_exe = _detect_mode()
    app_py = _target_python(mode, embedded_exe)

    print("=" * 60)
    print("  Pi Bench Installer")
    print("=" * 60)
    print(f"  Script directory  : {SCRIPT_DIR}")
    print(f"  Python mode       : {mode}  ({'embedded Python 3.12' if mode == 'embedded' else 'system Python + venv'})")
    print(f"  App Python        : {app_py}")
    print(f"  Installer Python  : {sys.version.split()[0]}")
    print(f"  Platform          : {platform.system()} {platform.machine()}")
    print()

    # ── Step 1: Prepare Python environment ───────────────────────────────
    print("[1/4] Preparing Python environment …")
    if mode == "embedded":
        # Embedded Python is already isolated.
        # Ensure pip is present (setup.bat bootstraps it, but guard anyway).
        _ensure_pip(app_py)
        _run(app_py, "-m", "pip", "install", "--upgrade", "pip", "--quiet")
        print(f"      ✓ embedded Python ready  ({app_py})")
    else:
        # System Python: create / reuse a venv.
        if os.path.exists(VENV_DIR):
            print(f"      venv already exists — reusing  ({VENV_DIR})")
        else:
            import venv as _venv
            print(f"      Creating venv …")
            _venv.create(VENV_DIR, with_pip=True, clear=False)
        _ensure_pip(app_py)
        _run(app_py, "-m", "pip", "install", "--upgrade", "pip", "--quiet")
        print(f"      ✓ venv ready  ({VENV_DIR})")

    # ── Step 2: VC++ 2022 runtime (Windows, needed by gpt4all) ──────────
    if not args.no_llm and platform.system() == "Windows":
        print("\n[2/4] Checking MSVC runtime …")
        _ensure_vcredist()

    # ── Step 3: Install packages ─────────────────────────────────────────
    print("\n[3/4] Installing packages …")
    _run(app_py, "-m", "pip", "install", *CORE_PKGS, "--quiet")
    print(f"      ✓ {', '.join(CORE_PKGS)}")

    if not args.no_llm:
        print(f"      Installing gpt4all  (LLM inference, prebuilt binary ~114 MB) …")
        try:
            _run(app_py, "-m", "pip", "install", LLM_PKG, "--quiet")
            print(f"      ✓ gpt4all  (prebuilt binary — includes compiled native library)")
        except subprocess.CalledProcessError:
            print(f"      ⚠  gpt4all install failed.")
            print(f"         AI analysis tab will be disabled.")
            print(f"         Tip: run  python install.py --no-llm  to skip it.")
    else:
        print("      Skipping gpt4all  (--no-llm)")

    # ── Step 4: Write launcher scripts ───────────────────────────────────
    if args.no_launchers:
        print("\n[4/4] Skipping launcher scripts  (managed by installer).")
    else:
        print("\n[4/4] Writing launcher scripts …")
        launchers = LAUNCHERS_WIN if platform.system() == "Windows" else LAUNCHERS_UNIX

        for entry in launchers:
            fname, script, desc = entry
            if script is None:
                continue   # setup.bat/setup.sh — already exists, don't touch it
            path = os.path.join(SCRIPT_DIR, fname)
            if platform.system() == "Windows":
                if fname == "uninstall.bat":
                    # uninstall.bat runs python.exe which locks python\python.exe,
                    # preventing uninstall.py from deleting the python\ dir itself.
                    # After python.exe exits the lock is gone, so we rmdir here.
                    content = (
                        f"@echo off\n"
                        f"REM {desc}\n"
                        f'"{app_py}" "%~dp0{script}" %*\n'
                        f"REM python.exe has exited — now safe to remove the embedded Python dir\n"
                        f'if exist "%~dp0python\\" rmdir /s /q "%~dp0python" 2>nul\n'
                    )
                else:
                    content = (
                        f"@echo off\n"
                        f"REM {desc}\n"
                        f'"{app_py}" "%~dp0{script}" %*\n'
                    )
            else:
                content = (
                    f"#!/bin/bash\n"
                    f"# {desc}\n"
                    f'cd "$(dirname "$0")"\n'
                    f'"{app_py}" "{script}" "$@"\n'
                )
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(content)
            if platform.system() != "Windows":
                os.chmod(path, 0o755)
            print(f"      ✓ {fname}")

    # ── Done ─────────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("  Install complete!")
    print("=" * 60)
    if args.no_launchers:
        print("  App installed — launch from Start Menu or Desktop shortcut.")
    elif platform.system() == "Windows":
        print("  run.bat         — production GUI")
        print("  run_dev.bat     — dev build  (no LLM)")
        print("  run_llm.bat     — dev build + AI analysis")
        print("  uninstall.bat   — remove everything")
    else:
        print("  ./run.sh         — production GUI")
        print("  ./run_dev.sh     — dev build  (no LLM)")
        print("  ./run_llm.sh     — dev build + AI analysis")
        print("  ./uninstall.sh   — remove everything")
    if not args.no_llm:
        print()
        print("  The LLM model (~2.2 GB) downloads automatically on first")
        print("  launch of run_llm — this takes a few minutes.")
    print()


if __name__ == "__main__":
    main()
