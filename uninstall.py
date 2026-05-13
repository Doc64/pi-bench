#!/usr/bin/env python3
"""
uninstall.py — Pi Bench complete uninstaller.

Removes ONLY the artifacts that Pi Bench itself created or downloaded.
Nothing else on the system is touched.

What IS removed (all inside this folder or under our specific app paths):
  • venv/                  — Python venv created by install.py (system-Python mode)
  • python/                — Embedded Python 3.12 downloaded by setup.bat
  • pi_bench_models/       — LLM model file downloaded by the app (~2.2 GB)
  • pi_bench_runs/         — Benchmark run history saved by the app (JSON files)
  • run.bat / run.sh etc.  — Launcher scripts written by install.py
  • %LOCALAPPDATA%\pi_bench\LibreHardwareMonitor\
                           — LHM portable copy downloaded by the app.
                             Only this specific subdirectory is removed.
                             Any pre-existing system-wide LHM installation
                             (e.g. in Program Files) is not touched.
  • OS keyring entry       — The SFTP password stored under service "pi_bench"
                             (only our specific entry, nothing else in keyring)

What is NOT removed:
  • Any system Python installation
  • Any packages installed into system / user Python (we never touch those)
  • Any other application data or registry keys
  • LHM installed system-wide by the user independently
  • setup.bat / setup.sh / install.py / uninstall.py themselves
    (the caller can delete the whole folder afterward)

Usage:
    python uninstall.py            # interactive — shows list and asks [y/N]
    python uninstall.py --yes      # non-interactive (scripted / CI)
"""

import argparse, os, platform, shutil, subprocess, sys

# Force UTF-8 output so symbols display correctly in any terminal / SSH session.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
KEYRING_SVC  = "pi_bench"
KEYRING_USER = "pi_bench"   # matches DEFAULT_SFTP_USER in pi_bench.py

# Only our specific managed-LHM subdirectory — NOT the whole pi_bench folder.
# pi_bench.py downloads LHM to: %LOCALAPPDATA%\pi_bench\LibreHardwareMonitor\
_LHM_MANAGED = os.path.join(
    os.environ.get("LOCALAPPDATA") or
    os.path.join(os.path.expanduser("~"), ".local", "share"),
    "pi_bench", "LibreHardwareMonitor"
)

# Directories inside SCRIPT_DIR that we created/downloaded.
_OUR_DIRS = [
    ("venv",            "Python venv (system-Python install mode)"),
    ("python",          "Embedded Python 3.12 (setup.bat install mode, ~80 MB)"),
    ("pi_bench_models", "Downloaded LLM model (Phi-3.5 Mini, ~2.2 GB)"),
    ("pi_bench_runs",   "Benchmark run history (JSON files)"),
]

# Launcher scripts that install.py writes — only the ones we generate.
_OUR_LAUNCHERS = [
    "run.bat", "run_dev.bat", "run_llm.bat", "uninstall.bat",
    "run.sh",  "run_dev.sh",  "run_llm.sh",  "uninstall.sh",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _dir_size_mb(path: str) -> float:
    total = 0
    for dp, _, fnames in os.walk(path):
        for fn in fnames:
            try:
                total += os.path.getsize(os.path.join(dp, fn))
            except OSError:
                pass
    return total / 1_048_576


def _lhm_is_running() -> bool:
    """Return True if LibreHardwareMonitor.exe is currently running."""
    if platform.system() != "Windows":
        return False
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", "IMAGENAME eq LibreHardwareMonitor.exe",
             "/NH", "/FO", "CSV"],
            stderr=subprocess.DEVNULL, timeout=5)
        return b"LibreHardwareMonitor.exe" in out
    except Exception:
        return False


def _remove_dir(path: str) -> bool:
    try:
        shutil.rmtree(path, ignore_errors=False)
        return True
    except Exception as exc:
        print(f"    FAILED: {exc}")
        return False


def _remove_file(path: str) -> bool:
    try:
        os.unlink(path)
        return True
    except Exception as exc:
        print(f"    FAILED: {exc}")
        return False


def _remove_keyring() -> bool:
    """Delete our specific SFTP password entry from the OS keyring."""
    try:
        import keyring
        keyring.delete_password(KEYRING_SVC, KEYRING_USER)
        return True
    except Exception:
        return False   # not installed or entry doesn't exist — fine


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Pi Bench uninstaller")
    ap.add_argument("--yes", "-y", action="store_true",
                    help="Skip confirmation prompt")
    args = ap.parse_args()

    print("=" * 60)
    print("  Pi Bench Uninstaller")
    print("=" * 60)
    print(f"  App folder : {SCRIPT_DIR}")
    print()

    # ── Build inventory of what we will delete ────────────────────────────
    # kind values: "dir", "file", "lhm_dir", "keyring", "bat_handled"
    items: list[tuple[str, str, str]] = []

    # Detect whether we are running from the embedded Python directory.
    # If so, python.exe is locked and we cannot delete python/ ourselves —
    # uninstall.bat does the rmdir AFTER this process exits.
    _this_exe = os.path.abspath(sys.executable)
    _embedded_py_dir = os.path.join(SCRIPT_DIR, "python")

    for subdir, desc in _OUR_DIRS:
        path = os.path.join(SCRIPT_DIR, subdir)
        if not os.path.exists(path):
            continue
        mb = _dir_size_mb(path)
        if subdir == "python" and _this_exe.startswith(_embedded_py_dir + os.sep):
            # Can't self-delete — uninstall.bat handles this after we exit.
            items.append(("bat_handled", path,
                          f"{desc}  ({mb:.0f} MB)  "
                          f"[removed by uninstall.bat after this script exits]"))
        else:
            items.append(("dir", path, f"{desc}  ({mb:.0f} MB)"))

    for fname in _OUR_LAUNCHERS:
        path = os.path.join(SCRIPT_DIR, fname)
        if os.path.exists(path):
            items.append(("file", path, "Launcher script created by install.py"))

    if os.path.exists(_LHM_MANAGED):
        mb = _dir_size_mb(_LHM_MANAGED)
        lhm_running = _lhm_is_running()
        note = f"Pi Bench managed LHM download  ({mb:.0f} MB)"
        if lhm_running:
            note += "  [WARNING: LHM is currently running — close it first]"
        items.append(("lhm_dir", _LHM_MANAGED, note))

    # Keyring entry is always listed (we can't easily check if it exists)
    items.append(("keyring", "",
                  f"SFTP password in OS keyring  "
                  f"[service={KEYRING_SVC!r}, user={KEYRING_USER!r}]"))

    if len(items) == 1:   # only the keyring entry
        print("  Nothing significant to remove.")
        print("  (No app directories, launchers, or LHM download found.)")
        print()

    # ── Display inventory ─────────────────────────────────────────────────
    print("  Will permanently delete:")
    print()
    for kind, path, note in items:
        if kind == "keyring":
            label = "(OS keyring)"
        elif path.startswith(SCRIPT_DIR):
            label = os.path.relpath(path, SCRIPT_DIR)
        else:
            label = path
        print(f"    {label}")
        print(f"      {note}")
    print()
    print("  Will NOT touch:")
    print("    - Any system Python installation or system-wide packages")
    print("    - Any LHM installed independently (only our managed download)")
    print("    - Any Windows registry entries")
    print("    - Any other application data")
    print("    - setup.bat / setup.sh / install.py / uninstall.py")
    print()

    # ── Confirm ───────────────────────────────────────────────────────────
    if not args.yes:
        try:
            answer = input("  Proceed? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n  Cancelled.")
            return
        if answer != "y":
            print("  Cancelled.")
            return

    print()
    print("  Removing ...")

    ok = total = 0
    for kind, path, _ in items:
        total += 1

        if kind == "bat_handled":
            label = (os.path.relpath(path, SCRIPT_DIR)
                     if path.startswith(SCRIPT_DIR) else path)
            print(f"    {label}/  ...  (uninstall.bat will remove this after we exit)")
            ok += 1   # counts as handled

        elif kind in ("dir", "lhm_dir"):
            if kind == "lhm_dir" and _lhm_is_running():
                print(f"    SKIPPED: LibreHardwareMonitor is still running.")
                print(f"             Close LHM first, then re-run uninstall.py")
                continue
            label = (os.path.relpath(path, SCRIPT_DIR)
                     if path.startswith(SCRIPT_DIR) else path)
            print(f"    {label}/  ...", end="", flush=True)
            if _remove_dir(path):
                print("  done")
                ok += 1
                # If it was our LHM dir, try to remove the parent pi_bench
                # folder too — but only if it is now empty.
                if kind == "lhm_dir":
                    parent = os.path.dirname(path)
                    try:
                        if os.path.isdir(parent) and not os.listdir(parent):
                            os.rmdir(parent)
                    except Exception:
                        pass   # non-empty or permission issue — leave it alone

        elif kind == "file":
            label = os.path.relpath(path, SCRIPT_DIR)
            print(f"    {label}  ...", end="", flush=True)
            if _remove_file(path):
                print("  done")
                ok += 1

        elif kind == "keyring":
            print(f"    keyring entry  ...", end="", flush=True)
            if _remove_keyring():
                print("  done")
            else:
                print("  (not found or keyring unavailable — skipped)")
            ok += 1   # keyring is best-effort, never counts as a failure

    print()
    print("=" * 60)
    if ok >= total:
        print("  Uninstall complete.")
    else:
        print("  Uninstall finished with warnings (see above).")
    print("=" * 60)
    print()
    print("  You can now delete this folder to fully remove Pi Bench.")
    print("  Nothing was written outside this folder (except the keyring")
    print("  entry and managed LHM download, both cleaned up above).")
    print()


if __name__ == "__main__":
    main()
