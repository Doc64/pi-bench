#!/usr/bin/env python3
"""
pi_bench.py / pi_bench_dev.py -- Cross-platform CPU stress benchmark via Pi.

Computes Pi using the Chudnovsky algorithm with binary splitting -- the same
approach used by y-cruncher and every modern Pi world-record run. Pure-Python
bigint multiplication keeps a CPU pinned and is a meaningful sustained load
for stress / thermal testing.

Self-verifying:
  * First 1000 digits checked against an embedded reference.
  * In multi mode, all worker outputs are SHA-256 hashed and compared.
  * A mismatch implies silent CPU/RAM error -- same kind of correctness
    check y-cruncher's stress mode is designed to catch.

Cross-platform: pure Python stdlib. Requires Python 3.8+.

Archive mode -- captures sensor data during the benchmark, parses it into
a human-readable per-machine report, and uploads the report to a NAS share.
Sensor source depends on the platform:

  Linux:   turbostat (kernel-tools) for CPU package + per-core data, plus
           /sys/class/hwmon and /sys/devices/platform/applesmc fans for fan
           RPMs where exposed.

  Windows: LibreHardwareMonitor (LHM) running with its remote-web-server
           feature enabled, polled at http://localhost:8085/data.json.
           If LHM isn't already running, the script can:
             1. Detect existing reachable web server (lhm_check_reachable)
             2. Download the latest LHM portable zip from GitHub and
                extract it to %LOCALAPPDATA%\\pi_bench\\LibreHardwareMonitor
                (lhm_download_and_extract)
             3. Pre-write LibreHardwareMonitor.config so the web server starts
                on launch (lhm_write_config)
             4. Launch LHM elevated via UAC ShellExecute "runas"
                (lhm_launch) -- admin is required for PawnIO kernel-mode
                sensor access
             5. Poll the JSON endpoint for sample data (lhm_fetch_sample)
           First-time-on-a-machine setup may also pop a one-shot PawnIO
           kernel-driver install dialog that the user must approve.

Examples:
    python pi_bench.py --digits 1000000
    python pi_bench.py --digits 5000000 --mode multi
    SMB_PASSWORD=xxxx python3 pi_bench.py --digits 5000000 --mode multi --archive
"""

import argparse
import datetime
import getpass
import glob
import hashlib
import io
import json
import math
import multiprocessing as mp
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

# ── Version & auto-update ─────────────────────────────────────────────────────
APP_VERSION = "2.0.0"

# Set to "owner/repo" of the GitHub project that hosts releases.
# The update checker looks for the latest release asset named *.exe.
# Leave empty to disable update checks.
_UPDATE_GITHUB_REPO = ""


def check_for_update() -> "tuple[str, str] | tuple[None, None]":
    """Check GitHub releases for a newer version.

    Returns (version_str, download_url) if an update is available, or
    (None, None) if already up-to-date, no repo configured, or any error.
    Safe to call from a background thread.
    """
    if not _UPDATE_GITHUB_REPO:
        return None, None
    try:
        import urllib.request as _req
        url = f"https://api.github.com/repos/{_UPDATE_GITHUB_REPO}/releases/latest"
        rq  = _req.Request(url, headers={
            "User-Agent": f"pi-bench/{APP_VERSION}",
            "Accept": "application/vnd.github+json",
        })
        with _req.urlopen(rq, timeout=8) as resp:
            data = json.loads(resp.read())
        tag = data.get("tag_name", "").lstrip("v")
        if not tag or not _version_gt(tag, APP_VERSION):
            return None, None
        for asset in data.get("assets", []):
            if asset.get("name", "").lower().endswith(".exe"):
                return tag, asset["browser_download_url"]
        return None, None
    except Exception:
        return None, None


def _version_gt(a: str, b: str) -> bool:
    """Return True if semver string *a* is strictly greater than *b*."""
    def _parts(v):
        try:    return tuple(int(x) for x in v.split("."))
        except: return (0,)
    return _parts(a) > _parts(b)


def _raise_int_str_limit(digits):
    if hasattr(sys, "set_int_max_str_digits"):
        sys.set_int_max_str_digits(max(640, digits * 2 + 1024))


def _live(msg):
    """Print transient progress to the terminal only (bypasses the archive capture buffer)."""
    try:
        sys.__stdout__.write(msg + "\n")
        sys.__stdout__.flush()
    except Exception:
        pass


def _add_fan_from_path(fans_list, drv_name, inp_path):
    base = inp_path[:-len("_input")]
    max_path = base + "_max"
    label_path = base + "_label"
    label = None
    try:
        if os.path.exists(label_path):
            with open(label_path) as f:
                label = f.read().strip()
    except Exception:
        pass
    name = "{}/{}".format(drv_name, os.path.basename(base))
    fans_list.append({
        "input": inp_path,
        "max_path": max_path if os.path.exists(max_path) else None,
        "name": name,
        "label": label or name,
    })


def discover_fans():
    """Find fan-RPM inputs exposed by the kernel.

    Scans:
      1. /sys/class/hwmon/hwmon*/fan*_input  (standard path for most drivers)
      2. /sys/devices/platform/applesmc.*/fan*_input  (Apple SMC -- not always
         linked into hwmon on every kernel/device combination)

    Returns a list of dicts: {name, label, input, max_path or None}."""
    fans = []
    seen = set()

    # 1. Standard hwmon path
    for hw in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
        try:
            with open(os.path.join(hw, "name")) as f:
                drv = f.read().strip()
        except Exception:
            drv = "?"
        for inp in sorted(glob.glob(os.path.join(hw, "fan*_input"))):
            real = os.path.realpath(inp)
            if real in seen:
                continue
            seen.add(real)
            _add_fan_from_path(fans, drv, inp)

    # 2. applesmc direct path (Mac mini / MacBook Pro / iMac on Linux)
    for inp in sorted(glob.glob("/sys/devices/platform/applesmc.*/fan*_input")):
        real = os.path.realpath(inp)
        if real in seen:
            continue
        seen.add(real)
        _add_fan_from_path(fans, "applesmc", inp)

    return fans


def read_fan_speeds(fans):
    """Read current RPM per fan. Returns dict of name -> rpm (or None on error)."""
    out = {}
    for f in fans:
        try:
            with open(f["input"]) as fh:
                out[f["name"]] = int(fh.read().strip())
        except Exception:
            out[f["name"]] = None
    return out


def read_fan_max(fan):
    if not fan.get("max_path"):
        return None
    try:
        with open(fan["max_path"]) as f:
            return int(f.read().strip())
    except Exception:
        return None


def _tail_turbostat_aggregate(path):
    """Return a short live readout from the latest turbostat aggregate row, or None.
    Also reports the file's mtime age so we can flag stale buffered data."""
    if not path or not os.path.exists(path):
        return None
    try:
        st = os.stat(path)
        age = time.time() - st.st_mtime
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 16384))
            data = f.read().decode("utf-8", errors="replace")
    except Exception:
        return None
    headers = None
    last_agg = None
    for line in data.splitlines():
        ls = line.strip()
        if not ls:
            continue
        if ls.startswith("Core") and "CPU" in ls:
            headers = ls.split()
            continue
        if headers is None:
            continue
        parts = ls.split()
        if len(parts) < 4:
            continue
        if parts[0] == "-":
            last_agg = (headers, parts)
    if not last_agg:
        return None
    headers, parts = last_agg
    row = dict(zip(headers, parts))
    busy = row.get("Busy%", "?")
    mhz = row.get("Bzy_MHz", "?")
    pkg_t = row.get("PkgTmp", "?")
    pkg_w = row.get("PkgWatt", "?")
    # Heuristic: flag implausibly low package power when CPU is clearly busy.
    # Some CPUs (e.g. consumer Haswell-E i7-58XX/59XX) have broken RAPL energy
    # counters that report sub-watt values regardless of actual load.
    suspicious = False
    try:
        if float(busy) >= 80.0 and float(pkg_w) < 5.0:
            suspicious = True
    except (TypeError, ValueError):
        pass

    if suspicious:
        base = "{:>5}% busy @ {:>4} MHz, {:>3}C, RAPL unreliable on this CPU".format(
            busy, mhz, pkg_t)
    else:
        base = "{:>5}% busy @ {:>4} MHz, {:>3}C, {:>5}W".format(busy, mhz, pkg_t, pkg_w)
    if age > 4:
        base += "  (last sample {:.0f}s ago)".format(age)
    return base


class HeartbeatReporter:
    """Background thread that prints periodic progress lines to the terminal during long runs."""
    def __init__(self, label, raw_turbo_path=None, interval=2.0, fans=None,
                 fan_samples=None, lhm_sampler=None, progress_callback=None):
        self.label = label
        self.raw_path = raw_turbo_path
        self.interval = interval
        self.fans = fans or []
        self.fan_samples = fan_samples if fan_samples is not None else []
        self.lhm_sampler = lhm_sampler   # Windows path: LHMSampler instance, or None
        self.progress_callback = progress_callback  # optional: fn(elapsed, done, total, busy, mhz, temp, power)
        self._stop = threading.Event()
        self._thread = None
        self._start_time = None
        self.workers_done = 0
        self.workers_total = 0

    def set_workers(self, total):
        self.workers_total = total

    def worker_done(self):
        self.workers_done += 1

    def start(self):
        self._start_time = time.time()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    def _run(self):
        while not self._stop.wait(self.interval):
            elapsed = time.time() - self._start_time
            chunks = ["[{}] elapsed {:>5.0f}s".format(self.label, elapsed)]
            if self.workers_total > 0:
                chunks.append("workers {}/{} done".format(self.workers_done, self.workers_total))

            # Sensor live readout: prefer LHM (Windows path) if provided,
            # else fall back to turbostat tail (Linux path).
            # Also extract raw numeric values for the GUI progress callback.
            busy_pct = mhz = temp_c = power_w = 0.0
            tail = None
            if self.lhm_sampler is not None:
                sample = self.lhm_sampler.latest_sample()
                if sample is not None:
                    busy_pct = sample.get("cpu_busy") or 0.0
                    clocks = sample.get("core_clocks") or []
                    mhz = max(clocks) if clocks else 0.0
                    temp_c = sample.get("pkg_tmp") or 0.0
                    power_w = sample.get("pkg_watt") or 0.0
                    tail = _format_lhm_live(self.lhm_sampler)
            if tail is None:
                tail = _tail_turbostat_aggregate(self.raw_path)
            if tail:
                chunks.append(tail)

            if self.fans:
                speeds = read_fan_speeds(self.fans)
                self.fan_samples.append((elapsed, speeds))
                live_rpm = next((v for v in speeds.values() if v is not None), None)
                if live_rpm is not None:
                    chunks.append("fan: {:>4} RPM".format(live_rpm))

            _live("  " + " | ".join(chunks))

            # Notify GUI (or any other listener) with structured sensor data.
            if self.progress_callback is not None:
                try:
                    # Pass per-core lists when available (LHM path only).
                    core_clocks       = []
                    core_temps        = []
                    core_clock_names  = []
                    core_temp_names   = []
                    if self.lhm_sampler is not None:
                        s = self.lhm_sampler.latest_sample()
                        if s is not None:
                            core_clocks      = s.get("core_clocks")      or []
                            core_temps       = s.get("core_temps")       or []
                            core_clock_names = s.get("core_clock_names") or []
                            core_temp_names  = s.get("core_temp_names")  or []
                    self.progress_callback(elapsed, self.workers_done, self.workers_total,
                                           busy_pct, mhz, temp_c, power_w,
                                           core_clocks, core_temps,
                                           core_clock_names, core_temp_names)
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# Windows: LibreHardwareMonitor sensor source
# ---------------------------------------------------------------------------
# Design notes:
#   LHM (https://github.com/LibreHardwareMonitor/LibreHardwareMonitor) is a
#   .NET app that reads CPU/board sensors via a kernel-mode I/O driver
#   (PawnIO, signed and prompted for install on first use). Once running with
#   its built-in web server enabled, it serves the entire sensor tree as JSON
#   at a configurable URL (default port 8085).
#
#   We picked LHM over alternatives (HWiNFO, OpenHardwareMonitor, raw WMI)
#   because: MIT-licensed (so we can auto-distribute), pure-portable zip (no
#   installer / registry footprint), JSON endpoint is structurally stable
#   across CPU vendors, and it's the most-maintained option in this niche.
#
#   The pipeline below is the bootstrap chain. Each function is independently
#   testable; the eventual coordinator (TBD) chains them in order:
#
#     lhm_check_reachable()         -> already running? skip ahead
#     _lhm_install_dir()            -> path management for our managed copy
#     lhm_download_and_extract()    -> pull latest zip, unpack
#     lhm_write_config()            -> pre-bake config to enable web server
#     lhm_launch()                  -> ShellExecute "runas" (UAC prompt)
#     [poll lhm_check_reachable() with timeout] -> wait for endpoint
#     lhm_fetch_sample()            -> normalized {sensor: value} dict
#
#   On a fresh machine the first launch may show the PawnIO installer
#   dialog (kernel driver approval); that is one user click that we cannot
#   automate without redistributing PawnIO ourselves. After approval, all
#   future runs on that machine are silent.
#
#   Sensor matching in lhm_fetch_sample() is by Type + Text, not by SensorId,
#   so the same code works on Intel/AMD CPUs and across LHM versions.
LHM_DEFAULT_URL = "http://localhost:8085/data.json"


def lhm_check_reachable(url=LHM_DEFAULT_URL, timeout=2.0):
    """Return True if LibreHardwareMonitor's web server responds with valid JSON.

    Used to detect whether LHM is already running before we try to launch
    or auto-install it. False on any failure (server down, port closed,
    timeout, garbage response).
    """
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.load(resp)
    except Exception:
        return False
    # LHM JSON always has an "id" at the top level and a "Children" list.
    return isinstance(data, dict) and "id" in data and "Children" in data


def _to_float(s):
    """Pull the numeric prefix out of an LHM Value string like '33.0 °C', '34.6 W',
    '12.3 %', '2095.2 MHz'. Returns None on anything unparseable."""
    if not s:
        return None
    try:
        return float(str(s).split()[0])
    except (ValueError, IndexError, TypeError):
        return None


def lhm_fetch_sample(url=LHM_DEFAULT_URL, timeout=2.0):
    """Fetch one live sensor sample from LHM.

    Returns a normalized dict with these keys (each value is None / [] / {} if
    the corresponding sensor isn't exposed on this machine):

      pkg_watt      float   CPU package power, watts
      pkg_tmp       float   CPU package temperature, C
      core_max_tmp  float   Hottest individual core, C
      core_avg_tmp  float   Average across cores, C
      cpu_busy      float   CPU total load, %
      core_clocks   [float] Per-physical-core clocks, MHz
      core_temps    [float] Per-physical-core temps, C (excludes Distance-to-TjMax)
      core_loads    [float] Per-physical-core load, %
      fans          {str:float}  Fan name -> RPM (empty if board exposes no fans)

    Returns None if the LHM server didn't respond / returned bad data.
    Sensor matching is by Type + Text (the human-friendly label), NOT by SensorId,
    so it works the same on Intel/AMD chips and across different CPU generations.
    """
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.load(resp)
    except Exception:
        return None

    sample = {
        "pkg_watt": None, "pkg_tmp": None,
        "core_max_tmp": None, "core_avg_tmp": None,
        "cpu_busy": None,
        "core_clocks": [], "core_temps": [], "core_loads": [],
        "core_clock_names": [], "core_temp_names": [],
        "fans": {},
    }

    def walk(node):
        text = node.get("Text") or ""
        typ = node.get("Type")
        if typ:
            v = _to_float(node.get("Value"))
            if v is not None:
                if typ == "Power" and text in ("CPU Package", "Package"):
                    # Intel: "CPU Package"  |  AMD: "Package"
                    sample["pkg_watt"] = v
                elif typ == "Temperature":
                    if text in ("CPU Package", "Core (Tctl/Tdie)"):
                        # Intel: "CPU Package"  |  AMD: "Core (Tctl/Tdie)"
                        sample["pkg_tmp"] = v
                    elif text == "Core Max":
                        sample["core_max_tmp"] = v
                    elif text == "Core Average":
                        sample["core_avg_tmp"] = v
                    elif text.startswith("CPU Core #") and "Distance" not in text:
                        # Intel per-core temps
                        sample["core_temps"].append(v)
                        sample["core_temp_names"].append(text)
                    elif text in ("CCD1 (Tdie)", "CCD2 (Tdie)") and not sample["core_temps"]:
                        # AMD CCD-level temps as fallback (no per-core temps on Ryzen)
                        sample["core_temps"].append(v)
                        sample["core_temp_names"].append(text)
                elif typ == "Load":
                    if text == "CPU Total":
                        sample["cpu_busy"] = v
                    elif text.startswith("CPU Core #"):
                        sample["core_loads"].append(v)
                elif typ == "Clock":
                    if text.startswith("CPU Core #"):
                        # Intel: "CPU Core #1", "CPU Core #2", ...
                        sample["core_clocks"].append(v)
                        sample["core_clock_names"].append(text)
                    elif (text.startswith("Core #")
                          and "(Effective)" not in text
                          and "Cores" not in text):
                        # AMD: "Core #0", "Core #1", ... (excludes "Core #0 Effective" etc.)
                        sample["core_clocks"].append(v)
                        sample["core_clock_names"].append(text)
                elif typ == "Fan":
                    sample["fans"][text or "fan"] = v
        for child in node.get("Children") or []:
            walk(child)

    walk(data)
    return sample


# Stable GitHub "latest release" URL -- redirects to whichever LibreHardwareMonitor.zip
# is current. The .NET Framework 4.7.2 build that runs on stock Win10/Win11 with
# no extra runtime install. About 6 MB.
LHM_DOWNLOAD_URL = (
    "https://github.com/LibreHardwareMonitor/LibreHardwareMonitor"
    "/releases/latest/download/LibreHardwareMonitor.zip"
)


def _lhm_install_dir():
    """Returns the directory where pi_bench installs its managed copy of LHM.
    Default: %LOCALAPPDATA%\\pi_bench\\LibreHardwareMonitor on Windows,
    ~/.local/share/pi_bench/LibreHardwareMonitor on other platforms (where
    LHM doesn't run anyway, but the code stays cross-platform)."""
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        base = os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "pi_bench", "LibreHardwareMonitor")


def _lhm_install_exe_path():
    """Where our managed LibreHardwareMonitor.exe should live."""
    return os.path.join(_lhm_install_dir(), "LibreHardwareMonitor.exe")


def lhm_download_and_extract(target_dir=None, url=LHM_DOWNLOAD_URL, timeout=60):
    """Download the latest LibreHardwareMonitor portable zip and extract it.

    Returns the path to LibreHardwareMonitor.exe on success, or None on failure.
    Does not launch anything, does not modify the system outside target_dir.
    """
    import urllib.request
    import zipfile

    if target_dir is None:
        target_dir = _lhm_install_dir()

    try:
        os.makedirs(target_dir, exist_ok=True)
    except Exception as e:
        print("[lhm-install] could not create target dir {}: {}".format(target_dir, e))
        return None

    print("[lhm-install] downloading {}".format(url))
    print("[lhm-install]    -> tempfile, then extract to {}".format(target_dir))

    tmp_path = None
    try:
        # Download to a temp file; urllib follows the GitHub /latest/download redirect
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tf:
                shutil.copyfileobj(resp, tf)
                tmp_path = tf.name
        size = os.path.getsize(tmp_path)
        print("[lhm-install] downloaded {:,} bytes".format(size))

        with zipfile.ZipFile(tmp_path) as zf:
            zf.extractall(target_dir)
        print("[lhm-install] extracted")
    except Exception as e:
        print("[lhm-install] download/extract failed: {}".format(e))
        return None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    exe = _lhm_install_exe_path()
    if os.path.exists(exe):
        print("[lhm-install] OK: {}".format(exe))
        return exe
    print("[lhm-install] zip extracted but {} not found".format(exe))
    print("[lhm-install]    contents of {}:".format(target_dir))
    try:
        for name in sorted(os.listdir(target_dir))[:20]:
            print("[lhm-install]      {}".format(name))
    except Exception:
        pass
    return None


def lhm_launch(exe_path=None, elevated=True):
    """Launch LibreHardwareMonitor.exe.

    On Windows with elevated=True, uses ShellExecute with the "runas" verb to
    trigger a UAC prompt; LHM needs administrator rights to read most CPU
    sensors via the PawnIO kernel driver.

    Returns True if the launch was initiated successfully (process started or
    UAC accepted), False otherwise (exe missing, UAC declined, non-Windows
    platform, or other failure).

    Note: a True return does NOT mean LHM's web server is up yet, just that
    the process started. The web server only comes up if it's enabled in
    LibreHardwareMonitor.config -- which on a fresh install is OFF by default.
    Caller should poll lhm_check_reachable() afterward, and on a fresh install
    the web server has to be enabled either by pre-writing the config (next
    step) or by the user toggling it once via Options menu.
    """
    if exe_path is None:
        exe_path = _lhm_install_exe_path()
    if not os.path.exists(exe_path):
        print("[lhm-launch] exe not found at {}".format(exe_path))
        return False

    if platform.system() != "Windows":
        print("[lhm-launch] not running on Windows; skipping")
        return False

    work_dir = os.path.dirname(exe_path)

    if elevated:
        try:
            import ctypes
            # ShellExecuteW(hwnd, verb, file, params, working_dir, show_cmd)
            # nShowCmd=1 == SW_SHOWNORMAL. Return value > 32 means success;
            # <=32 is an error code per Win32 docs.
            ret = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", exe_path, None, work_dir, 1)
        except Exception as e:
            print("[lhm-launch] ShellExecute call failed: {}".format(e))
            return False

        if ret > 32:
            print("[lhm-launch] launched elevated: {}".format(exe_path))
            return True

        err_names = {
            0:  "out of memory or resources",
            2:  "file not found",
            3:  "path not found",
            5:  "access denied (UAC declined?)",
            8:  "out of memory",
            11: "bad executable format",
            26: "sharing violation",
            27: "association incomplete",
            28: "DDE transaction timeout",
            29: "DDE transaction failed",
            30: "DDE busy",
            31: "no application associated with file type",
            32: "required DLL not found",
        }
        reason = err_names.get(ret, "ShellExecute returned code {}".format(ret))
        print("[lhm-launch] elevated launch failed: {}".format(reason))
        return False

    # Non-elevated path: fine for testing existence of the binary, but LHM
    # without admin won't read most sensors.
    try:
        subprocess.Popen([exe_path], cwd=work_dir,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("[lhm-launch] launched WITHOUT elevation: {}".format(exe_path))
        print("[lhm-launch] note: most sensors will be missing without admin")
        return True
    except Exception as e:
        print("[lhm-launch] non-elevated launch failed: {}".format(e))
        return False


# Pre-baked LHM config: enables web server, port 8085, localhost only.
# Written next to LibreHardwareMonitor.exe so LHM picks it up on launch.
#
# Security: "localhost" (HTTP.sys strong wildcard for loopback) restricts
# the endpoint to this machine only.  "+" would bind to all interfaces and
# let any host on the LAN read sensor data unauthenticated.  The app only
# ever polls http://localhost:8085/data.json, so localhost is sufficient.
LHM_CONFIG_XML = """<?xml version=\"1.0\" encoding=\"utf-8\"?>
<configuration>
    <appSettings>
        <add key=\"runWebServerMenuItem\" value=\"true\" />
        <add key=\"listenerPort\" value=\"8085\" />
        <add key=\"listenerIP\" value=\"localhost\" />
    </appSettings>
</configuration>
"""


def lhm_write_config(install_dir=None):
    """Write LibreHardwareMonitor.config in the install dir with our preferred
    settings: web server enabled, port 8085, all interfaces.

    Returns True if written successfully, False otherwise. Safe to call when
    LHM is not running. If LHM IS running, the change won't take effect until
    LHM is closed and relaunched -- and worse, LHM's normal exit will OVERWRITE
    this file with whatever its in-memory state was. So always quit LHM,
    write the config, then launch LHM.
    """
    if install_dir is None:
        install_dir = _lhm_install_dir()
    if not os.path.isdir(install_dir):
        print("[lhm-config] install dir doesn't exist: {}".format(install_dir))
        return False
    config_path = os.path.join(install_dir, "LibreHardwareMonitor.config")
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(LHM_CONFIG_XML)
        print("[lhm-config] wrote {}".format(config_path))
        return True
    except Exception as e:
        print("[lhm-config] failed to write config: {}".format(e))
        return False


def _lhm_process_running():
    """Return True if LibreHardwareMonitor.exe is currently running on the
    local machine (any user, any path). Uses Windows' tasklist; returns False
    on non-Windows or if tasklist fails."""
    if platform.system() != "Windows":
        return False
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", "IMAGENAME eq LibreHardwareMonitor.exe",
             "/NH", "/FO", "CSV"],
            stderr=subprocess.DEVNULL, timeout=5)
        text = out.decode("utf-8", errors="replace")
    except Exception:
        return False
    return "LibreHardwareMonitor.exe" in text


def _lhm_kill_running():
    """Kill any running LibreHardwareMonitor.exe processes.

    Tries a plain taskkill first (works if our script and LHM are running as
    the same user / same elevation). If that fails with access-denied (typical
    when LHM is running elevated and we are not), falls back to ShellExecute
    with the "runas" verb so taskkill itself runs elevated -- this fires a UAC
    prompt.

    Returns True if no LHM was running OR kill succeeded; False if kill failed.
    """
    if platform.system() != "Windows":
        return True

    # Plain taskkill first
    try:
        result = subprocess.run(
            ["taskkill", "/F", "/IM", "LibreHardwareMonitor.exe"],
            capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            print("[lhm-kill] killed running LHM (plain taskkill)")
            return True
        # rc 128 == not found, that's fine
        if "not found" in (result.stdout + result.stderr).lower():
            return True
    except Exception as e:
        print("[lhm-kill] plain taskkill exception: {}".format(e))

    # Elevated taskkill via ShellExecute runas
    print("[lhm-kill] retrying with elevation (UAC prompt)...")
    try:
        import ctypes
        ret = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", "taskkill.exe",
            "/F /IM LibreHardwareMonitor.exe", None, 0)  # 0 = SW_HIDE
        if ret > 32:
            # ShellExecute is fire-and-forget; give the kill a moment to land
            time.sleep(1.0)
            print("[lhm-kill] killed running LHM (elevated taskkill)")
            return True
        print("[lhm-kill] elevated taskkill ShellExecute failed (code {})".format(ret))
        return False
    except Exception as e:
        print("[lhm-kill] elevated taskkill exception: {}".format(e))
        return False


def lhm_wait_for_endpoint(timeout=30.0, poll_interval=1.0, url=LHM_DEFAULT_URL):
    """Poll the LHM JSON endpoint until it responds or `timeout` seconds elapse.

    Used after lhm_launch() to wait for LHM to finish starting up and begin
    serving its web API. Prints occasional progress lines so the user knows
    we haven't stalled.

    Returns True on success (endpoint responded with valid JSON), False on
    timeout. Does not raise.
    """
    start = time.time()
    next_progress = start + 5.0
    while True:
        if lhm_check_reachable(url=url, timeout=poll_interval):
            elapsed = time.time() - start
            print("[lhm-wait] endpoint up after {:.1f}s".format(elapsed))
            return True
        now = time.time()
        if now - start >= timeout:
            print("[lhm-wait] timed out after {:.0f}s waiting for endpoint".format(timeout))
            return False
        if now >= next_progress:
            print("[lhm-wait] still waiting... ({:.0f}s elapsed)".format(now - start))
            next_progress = now + 5.0
        time.sleep(poll_interval)


def lhm_ensure_running(install_dir=None, download_if_missing=True):
    """Ensure LibreHardwareMonitor is running and serving its JSON endpoint.

    The full bootstrap chain:

      1. If the endpoint is already reachable -> True (nothing to do).
      2. If LHM.exe is already installed at our managed path -> launch it.
      3. Otherwise, download + extract -> launch.
      4. Pre-write LibreHardwareMonitor.config so the web server starts on launch.
      5. Launch LHM elevated (UAC prompt).
      6. Wait up to 30s for the JSON endpoint to come up.

    Returns True only if the endpoint is verified reachable at the end.
    Prints [lhm-ensure] progress lines along the way so the caller can see
    where in the chain we are. Linux/macOS: returns False immediately
    (LHM is Windows-only).
    """
    print("[lhm-ensure] checking if LHM is already running...")
    if lhm_check_reachable():
        print("[lhm-ensure] OK -- already reachable, no setup needed")
        return True

    if platform.system() != "Windows":
        print("[lhm-ensure] not Windows; LHM bootstrap not applicable here")
        return False

    # Scenario 3: LHM process is running but its web server is off (or wrong
    # port / interface). Need to terminate it before relaunching with our
    # config, otherwise PawnIO is held by the running instance and our launch
    # silently fails. Kill it; we'll relaunch our managed copy below.
    if _lhm_process_running():
        print("[lhm-ensure] LHM process is running but no JSON endpoint "
              "(web server disabled or different config)")
        print("[lhm-ensure] killing existing LHM so we can relaunch with our config...")
        if not _lhm_kill_running():
            print("[lhm-ensure] could not kill running LHM; aborting")
            return False
        # Brief pause to let PawnIO release the kernel device
        time.sleep(1.0)

    if install_dir is None:
        install_dir = _lhm_install_dir()
    exe = os.path.join(install_dir, "LibreHardwareMonitor.exe")

    if not os.path.exists(exe):
        if not download_if_missing:
            print("[lhm-ensure] LHM not installed at {} and download disabled".format(exe))
            return False
        print("[lhm-ensure] LHM not installed; downloading...")
        result = lhm_download_and_extract(target_dir=install_dir)
        if result is None:
            print("[lhm-ensure] download/extract failed")
            return False
    else:
        print("[lhm-ensure] LHM already installed at {}".format(exe))

    if not lhm_write_config(install_dir=install_dir):
        print("[lhm-ensure] failed to pre-write config; aborting")
        return False

    print("[lhm-ensure] launching LHM (UAC prompt expected)...")
    if not lhm_launch(exe_path=exe):
        print("[lhm-ensure] launch failed (declined UAC?); aborting")
        return False

    print("[lhm-ensure] waiting for web server to come up...")
    if not lhm_wait_for_endpoint(timeout=30.0):
        print("[lhm-ensure] endpoint did not respond within 30s")
        print("[lhm-ensure] possible causes:")
        print("[lhm-ensure]   - PawnIO kernel-driver install dialog still open (click through it)")
        print("[lhm-ensure]   - LHM still loading its sensor tree (try again in a moment)")
        print("[lhm-ensure]   - port 8085 conflict with another app")
        return False

    print("[lhm-ensure] success -- LHM is up and serving JSON")
    return True


class LHMSampler:
    """Background thread that polls LHM's JSON endpoint at a fixed interval
    and accumulates parsed sensor samples in memory.

    Analogous to turbostat's logging on the Linux side: it runs alongside
    the benchmark, building up a time-series of CPU package power, temps,
    clocks, load, fans. After the benchmark stops, all_samples() returns
    everything we collected for the post-run analysis pass to chew on.

    Each sample dict has the shape returned by lhm_fetch_sample() with an
    added "timestamp" key (float seconds since start() was called), so the
    samples are directly time-aligned with benchmark events.

    Thread-safe: the internal list is guarded by a Lock; latest_sample(),
    all_samples(), and sample_count() are safe to call from the main thread
    while the worker is appending.
    """
    def __init__(self, url=LHM_DEFAULT_URL, interval=1.0):
        self.url = url
        self.interval = interval
        self._samples = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._start_time = None
        self._fetch_failures = 0

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._start_time = time.time()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval + 1.0)

    def _run(self):
        # Use _stop.wait() as the sleep so stop() takes effect within one
        # interval rather than blocking on the full sleep.
        while not self._stop.wait(self.interval):
            sample = lhm_fetch_sample(url=self.url, timeout=self.interval)
            now = time.time() - self._start_time
            if sample is None:
                self._fetch_failures += 1
                continue
            sample["timestamp"] = now
            with self._lock:
                self._samples.append(sample)

    def latest_sample(self):
        """Most recent sample dict, or None if none collected yet."""
        with self._lock:
            return self._samples[-1] if self._samples else None

    def all_samples(self):
        """Return a copy of the accumulated samples list."""
        with self._lock:
            return list(self._samples)

    def sample_count(self):
        with self._lock:
            return len(self._samples)

    def fetch_failure_count(self):
        return self._fetch_failures


def _format_lhm_live(sampler):
    """Return a short live readout string from an LHMSampler, mirroring the
    format that _tail_turbostat_aggregate produces on Linux:
        '100.0% busy @ 3100 MHz, 95C, 25.3W'
    Returns None if there's no sampler or no sample yet.
    """
    if sampler is None:
        return None
    sample = sampler.latest_sample()
    if sample is None:
        return None
    busy = sample.get("cpu_busy")
    if busy is None:
        return None
    clocks = sample.get("core_clocks") or []
    mhz = max(clocks) if clocks else 0.0
    tmp = sample.get("pkg_tmp") or 0.0
    pkg_w = sample.get("pkg_watt")
    if pkg_w is None:
        # Match the turbostat-side phrasing for the no-RAPL case
        return "{:>5.1f}% busy @ {:>4.0f} MHz, {:>3.0f}C, (no power data)".format(
            busy, mhz, tmp)
    return "{:>5.1f}% busy @ {:>4.0f} MHz, {:>3.0f}C, {:>5.2f}W".format(
        busy, mhz, tmp, pkg_w)


# ---------------------------------------------------------------------------
# Chudnovsky constants
A = 13591409
B = 545140134
C = 640320
C3_OVER_24 = C ** 3 // 24

PI_REF_FRAC_1000 = (
    "1415926535897932384626433832795028841971693993751058209749445923078164"
    "0628620899862803482534211706798214808651328230664709384460955058223172"
    "5359408128481117450284102701938521105559644622948954930381964428810975"
    "6659334461284756482337867831652712019091456485669234603486104543266482"
    "1339360726024914127372458700660631558817488152092096282925409171536436"
    "7892590360011330530548820466521384146951941511609433057270365759591953"
    "0921861173819326117931051185480744623799627495673518857527248912279381"
    "8301194912983367336244065664308602139494639522473719070217986094370277"
    "0539217176293176752384674818467669405132000568127145263560827785771342"
    "7577896091736371787214684409012249534301465495853710507922796892589235"
    "4201995611212902196086403441815981362977477130996051870721134999999837"
    "2978049951059731732816096318595024459455346908302642522308253344685035"
    "2619311881710100031378387528865875332083814206171776691473035982534904"
    "2875546873115956286388235378759375195778185778053217122680661300192787"
    "66111959092164201989"
)
assert len(PI_REF_FRAC_1000) == 1000

DEFAULT_SMB_SHARE = os.environ.get("SMB_SHARE", "//192.168.200.36/Common-Room")
DEFAULT_SMB_USER = os.environ.get("SMB_USER", "tom")
DEFAULT_SMB_SUBDIR = os.environ.get("SMB_SUBDIR", "Scripts/Benchmarks")
DEFAULT_SFTP_USER = os.environ.get("SFTP_USER", "pi_bench")
DEFAULT_SFTP_PATH = os.environ.get("SFTP_PATH", "/mnt/Family-Nas/Common-Room/Scripts/Benchmarks")

# Service name used for all pi_bench credentials stored in the OS keyring.
# Windows: Windows Credential Locker (DPAPI-encrypted).
# Linux:   Secret Service API (GNOME Keyring / KWallet).
# In both cases the password is never stored as plain text.
_KEYRING_SERVICE = "pi_bench"


# ---------------------------------------------------------------------------
# Pi math
# ---------------------------------------------------------------------------
def chudnovsky_bs(a, b):
    if b - a == 1:
        if a == 0:
            P, Q = 1, 1
        else:
            P = (6 * a - 5) * (2 * a - 1) * (6 * a - 1)
            Q = a * a * a * C3_OVER_24
        T = P * (A + B * a)
        if a & 1:
            T = -T
        return P, Q, T
    m = (a + b) // 2
    P1, Q1, T1 = chudnovsky_bs(a, m)
    P2, Q2, T2 = chudnovsky_bs(m, b)
    return P1 * P2, Q1 * Q2, Q2 * T1 + P1 * T2


def compute_pi(digits):
    n_terms = digits // 14 + 2
    _, Q, T = chudnovsky_bs(0, n_terms)
    one_squared = 10 ** (2 * digits)
    sqrt_10005 = math.isqrt(10005 * one_squared)
    return (426880 * sqrt_10005 * Q) // T


def pi_to_decimal_string(pi_int, digits):
    s = str(pi_int)
    if len(s) < digits + 1:
        s = s.zfill(digits + 1)
    return s[0] + "." + s[1 : digits + 1]


def verify_against_reference(pi_str):
    frac = pi_str.split(".", 1)[1] if "." in pi_str else pi_str[1:]
    n = min(len(frac), len(PI_REF_FRAC_1000))
    for i in range(n):
        if frac[i] != PI_REF_FRAC_1000[i]:
            return False, i + 1, n
    return True, None, n


def _worker(payload):
    digits, worker_id = payload
    _raise_int_str_limit(digits)
    t0 = time.perf_counter()
    pi_int = compute_pi(digits)
    elapsed = time.perf_counter() - t0
    pi_text = str(pi_int)
    digest = hashlib.sha256(pi_text.encode("ascii")).hexdigest()
    pi_str = pi_text[0] + "." + pi_text[1 : digits + 1]
    ok, mismatch, _ = verify_against_reference(pi_str)
    return {"worker_id": worker_id, "elapsed_s": elapsed, "sha256": digest,
            "verified_first_1000": ok, "mismatch_at_digit": mismatch}


def run_single(digits, quiet=False, raw_turbo_path=None, fans=None, fan_samples=None,
               lhm_sampler=None, progress_callback=None):
    if not quiet:
        print("\n[ single-thread ] computing Pi to {:,} digits...".format(digits), flush=True)
    hb = None
    if not quiet or progress_callback is not None:
        hb = HeartbeatReporter("single-thread", raw_turbo_path, fans=fans,
                               fan_samples=fan_samples, lhm_sampler=lhm_sampler,
                               progress_callback=progress_callback)
        hb.start()
    # Run in a subprocess so the GIL is released and the GUI stays responsive.
    # _worker already computes everything we need (elapsed, sha256, verified).
    try:
        with ProcessPoolExecutor(max_workers=1) as ex:
            w = ex.submit(_worker, (digits, 0)).result()
    finally:
        if hb:
            hb.stop()
    elapsed    = w["elapsed_s"]
    digest     = w["sha256"]
    ok         = w["verified_first_1000"]
    mismatch   = w["mismatch_at_digit"]
    throughput = digits / elapsed if elapsed > 0 else 0.0
    if not quiet:
        print("  time:        {:.3f} s".format(elapsed))
        print("  throughput:  {:,.0f} digits/sec".format(throughput))
        print("  sha256:      {}...".format(digest[:16]))
        if ok:
            print("  verified:    OK")
        else:
            print("  verified:    FAIL at digit {} -- possible CPU/RAM error!".format(mismatch))
    return {"mode": "single", "digits": digits, "elapsed_s": elapsed,
            "throughput_digits_per_sec": throughput, "sha256": digest,
            "verified_reference": ok, "mismatch_at_digit": mismatch}


def run_multi(digits, workers, quiet=False, raw_turbo_path=None, fans=None, fan_samples=None,
              lhm_sampler=None, progress_callback=None):
    if not quiet:
        print("\n[ multi-thread  ] {} workers x {:,} digits each...".format(workers, digits), flush=True)
    payloads = [(digits, i) for i in range(workers)]
    hb = None
    if not quiet or progress_callback is not None:
        hb = HeartbeatReporter("multi-thread", raw_turbo_path, fans=fans,
                               fan_samples=fan_samples, lhm_sampler=lhm_sampler,
                               progress_callback=progress_callback)
        hb.set_workers(workers)
        hb.start()
    results = []
    t0 = time.perf_counter()
    try:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futures = [ex.submit(_worker, p) for p in payloads]
            for fut in as_completed(futures):
                r = fut.result()
                results.append(r)
                if hb:
                    hb.worker_done()
                if not quiet:
                    _live("  worker {:>2} finished in {:>6.1f}s ({}/{})".format(
                        r["worker_id"], r["elapsed_s"], len(results), workers))
    finally:
        if hb:
            hb.stop()
    wall = time.perf_counter() - t0
    # Sort for deterministic downstream stats
    results.sort(key=lambda r: r["worker_id"])
    total_digits = workers * digits
    aggregate_throughput = total_digits / wall if wall > 0 else 0.0
    per_worker_avg = sum(r["elapsed_s"] for r in results) / len(results)
    per_worker_max = max(r["elapsed_s"] for r in results)
    all_verified = all(r["verified_first_1000"] for r in results)
    hashes = {r["sha256"] for r in results}
    cross_check_ok = len(hashes) == 1
    if not quiet:
        print("  wall time:            {:.3f} s".format(wall))
        print("  per-worker avg:       {:.3f} s".format(per_worker_avg))
        print("  per-worker max:       {:.3f} s".format(per_worker_max))
        print("  aggregate throughput: {:,.0f} digits/sec".format(aggregate_throughput))
        if all_verified:
            print("  reference check:      OK (all {} workers match first 1000 digits)".format(workers))
        else:
            bad = [r["worker_id"] for r in results if not r["verified_first_1000"]]
            print("  reference check:      FAIL on workers {} -- possible CPU/RAM error!".format(bad))
        if cross_check_ok:
            print("  cross-worker check:   OK (all {} workers produced identical output)".format(workers))
        else:
            print("  cross-worker check:   FAIL ({} distinct outputs) -- CPU/RAM error!".format(len(hashes)))
    return {"mode": "multi", "digits": digits, "workers": workers, "wall_s": wall,
            "per_worker_avg_s": per_worker_avg, "per_worker_max_s": per_worker_max,
            "aggregate_throughput_digits_per_sec": aggregate_throughput,
            "verified_reference": all_verified, "cross_worker_consistent": cross_check_ok,
            "worker_results": results}


def system_info():
    return {"platform": platform.platform(), "machine": platform.machine(),
            "processor": platform.processor(), "python": platform.python_version(),
            "logical_cpus": os.cpu_count()}


# ---------------------------------------------------------------------------
# Tee for capturing stdout while still printing live
# ---------------------------------------------------------------------------
class _Tee:
    def __init__(self, *streams):
        self.streams = streams
    def write(self, data):
        for s in self.streams:
            try: s.write(data)
            except Exception: pass
        return len(data)
    def flush(self):
        for s in self.streams:
            try: s.flush()
            except Exception: pass
    def isatty(self):
        return False


# ---------------------------------------------------------------------------
# Archive mode: turbostat capture, parsing, SMB upload
# ---------------------------------------------------------------------------
def detect_cpu_name():
    name = None
    # Linux: prefer lscpu's "Model name:" line (gives friendly marketing name)
    try:
        out = subprocess.check_output(["lscpu"], text=True, timeout=5)
        for line in out.splitlines():
            if line.startswith("Model name:"):
                name = line.split(":", 1)[1].strip()
                break
    except Exception:
        pass
    # Windows: read ProcessorNameString from registry. Same value Task Manager,
    # HWiNFO, and LHM all show ("Intel(R) Core(TM) i5-4590S CPU @ 3.00GHz").
    if not name and platform.system() == "Windows":
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            ) as k:
                val, _ = winreg.QueryValueEx(k, "ProcessorNameString")
                name = (val or "").strip()
        except Exception:
            pass
    # Last-resort fallback: platform.processor() / platform.machine()
    if not name:
        name = platform.processor() or platform.machine() or "unknown_cpu"
    name = re.sub(r"\(R\)|\(TM\)", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    name = re.sub(r'[/\\:*?"<>|]', "_", name)
    return name


def detect_ram_spec():
    """Return a short RAM description string like '32GB DDR5-6000', or None.

    Windows: queries Win32_PhysicalMemory via PowerShell (fast, ~0.5s).
    Linux:   reads /proc/meminfo for total; tries sudo -n dmidecode for speed.

    Returns None on any failure — callers should treat the result as optional.
    SMBIOSMemoryType codes: 24=DDR3, 26=DDR4, 34=DDR5, 0=unknown.
    """
    if platform.system() == "Windows":
        try:
            out = subprocess.check_output(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-Command",
                 "Get-CimInstance Win32_PhysicalMemory | "
                 "Select-Object Capacity,Speed,SMBIOSMemoryType | "
                 "ConvertTo-Json -Compress"],
                timeout=10, stderr=subprocess.DEVNULL)
            modules = json.loads(out.decode("utf-8", errors="replace").strip())
            if isinstance(modules, dict):
                modules = [modules]
            if not modules:
                return None
            total_bytes = sum(int(m.get("Capacity") or 0) for m in modules)
            total_gb    = total_bytes // (1024 ** 3)
            if total_gb <= 0:
                return None
            speed       = max((int(m.get("Speed") or 0) for m in modules), default=0)
            type_map    = {24: "DDR3", 26: "DDR4", 34: "DDR5"}
            mem_type    = type_map.get(int(modules[0].get("SMBIOSMemoryType") or 0), "DDR")
            return "{}GB {}-{}".format(total_gb, mem_type, speed) if speed > 0 \
                   else "{}GB {}".format(total_gb, mem_type)
        except Exception:
            return None

    elif platform.system() == "Linux":
        total_gb = None
        speed    = None
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        total_gb = round(int(line.split()[1]) / 1024 / 1024)
                        break
        except Exception:
            pass
        try:
            out = subprocess.check_output(
                ["sudo", "-n", "dmidecode", "-t", "memory"],
                stderr=subprocess.DEVNULL, timeout=5)
            for line in out.decode("utf-8", errors="replace").splitlines():
                ls = line.strip()
                if ls.startswith("Speed:") and "MT/s" in ls:
                    m = re.search(r"(\d+)\s*MT/s", ls)
                    if m:
                        speed = int(m.group(1))
                        break
        except Exception:
            pass
        if total_gb:
            return "{}GB DDR-{}".format(total_gb, speed) if speed \
                   else "{}GB RAM".format(total_gb)
    return None


def start_turbostat(out_path):
    if shutil.which("turbostat") is None:
        print("[archive] turbostat not found; skipping capture", flush=True)
        return None
    if shutil.which("sudo") is None:
        print("[archive] sudo not found; skipping capture", flush=True)
        return None
    # Force line-buffered output so each sample lands on disk immediately
    # (otherwise turbostat block-buffers when stdout is a file, and the live
    # readout ends up showing stale idle-period samples).
    if shutil.which("stdbuf") is not None:
        cmd = ["sudo", "-n", "stdbuf", "-oL", "turbostat", "--interval", "1"]
    else:
        cmd = ["sudo", "-n", "turbostat", "--interval", "1"]
    try:
        f = open(out_path, "w")
        proc = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT, preexec_fn=os.setsid)
        time.sleep(0.5)
        if proc.poll() is not None:
            print("[archive] turbostat failed to start (sudo password needed?). Try `sudo -v` first.", flush=True)
            return None
        return proc
    except Exception as e:
        print("[archive] turbostat start failed: {}".format(e), flush=True)
        return None


def stop_turbostat(proc):
    if proc is None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except Exception:
        try: proc.terminate()
        except Exception: pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try: os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception: proc.kill()


def _fnum(s, default=0.0):
    try: return float(s)
    except Exception: return default


def parse_turbostat(raw_text, load_threshold=50.0):
    """Return a dict of summary statistics parsed from turbostat output."""
    lines = raw_text.splitlines()
    headers = None
    aggregate = []      # rows where Core == "-"
    per_cpu = {}        # cpu_id -> list of rows
    for line in lines:
        line_s = line.strip()
        if not line_s:
            continue
        if line_s.startswith("Core") and "CPU" in line_s:
            headers = line_s.split()
            continue
        if headers is None:
            continue
        parts = line_s.split()
        if len(parts) < 4:
            continue
        row = dict(zip(headers, parts))
        if row.get("Core") == "-":
            aggregate.append(row)
        else:
            try:
                cid = int(row.get("CPU", "-1"))
            except Exception:
                continue
            per_cpu.setdefault(cid, []).append(row)

    summary = {
        "total_samples": len(aggregate),
        "load_samples": 0,
        "idle_samples": 0,
    }
    if not aggregate:
        return summary

    load = [r for r in aggregate if _fnum(r.get("Busy%", 0)) >= load_threshold]
    summary["load_samples"] = len(load)
    summary["idle_samples"] = len(aggregate) - len(load)

    if load:
        def avg(field): return sum(_fnum(r.get(field, 0)) for r in load) / len(load)
        def peak(field): return max(_fnum(r.get(field, 0)) for r in load)
        summary["aggregate"] = {
            "avg_busy_pct":   avg("Busy%"),
            "peak_busy_pct":  peak("Busy%"),
            "avg_clock_mhz":  avg("Bzy_MHz"),
            "peak_clock_mhz": peak("Bzy_MHz"),
            "avg_pkg_tmp_c":  avg("PkgTmp"),
            "peak_pkg_tmp_c": peak("PkgTmp"),
            "avg_pkg_watt":   avg("PkgWatt"),
            "peak_pkg_watt":  peak("PkgWatt"),
            "avg_core_watt":  avg("CorWatt"),
            "peak_core_watt": peak("CorWatt"),
        }
        # Per-core peaks during load
        per_core_peaks = {}
        for cid, rows in per_cpu.items():
            load_rows = [r for r in rows if _fnum(r.get("Busy%", 0)) >= load_threshold]
            if not load_rows:
                continue
            per_core_peaks[cid] = {
                "peak_mhz": max(_fnum(r.get("Bzy_MHz", 0)) for r in load_rows),
                "avg_mhz":  sum(_fnum(r.get("Bzy_MHz", 0)) for r in load_rows) / len(load_rows),
                "peak_tmp": max(_fnum(r.get("CoreTmp", 0)) for r in load_rows),
            }
        summary["per_core_peaks"] = per_core_peaks
    return summary


def summarize_lhm_samples(samples, load_threshold=50.0):
    """Build a summary dict in the same shape as parse_turbostat() but from LHM
    samples (the list returned by LHMSampler.all_samples()).

    Output dict can be passed directly to format_turbostat_summary() so the
    Windows report section renders with the same shape as the Linux one.

    LHM exposes per-physical-core data; turbostat exposes per-logical-CPU. The
    "per_core_peaks" key here is keyed by physical core index. Core-power isn't
    exposed by LHM in a stable way across CPU vendors, so it's reported as 0
    (the formatter prints "(not exposed by this CPU)" in that case).
    """
    summary = {
        "total_samples": len(samples),
        "load_samples": 0,
        "idle_samples": 0,
    }
    if not samples:
        return summary

    load = [s for s in samples if (s.get("cpu_busy") or 0) >= load_threshold]
    summary["load_samples"] = len(load)
    summary["idle_samples"] = len(samples) - len(load)
    if not load:
        return summary

    def _sample_max_mhz(s):
        clocks = s.get("core_clocks") or []
        return max(clocks) if clocks else 0.0

    def _avg(values):
        vals = [v for v in values if v is not None]
        return sum(vals) / len(vals) if vals else 0.0

    def _peak(values):
        vals = [v for v in values if v is not None]
        return max(vals) if vals else 0.0

    summary["aggregate"] = {
        "avg_busy_pct":    _avg([s.get("cpu_busy") for s in load]),
        "peak_busy_pct":   _peak([s.get("cpu_busy") for s in load]),
        "avg_clock_mhz":   _avg([_sample_max_mhz(s) for s in load]),
        "peak_clock_mhz":  _peak([_sample_max_mhz(s) for s in load]),
        "avg_pkg_tmp_c":   _avg([s.get("pkg_tmp") for s in load]),
        "peak_pkg_tmp_c":  _peak([s.get("pkg_tmp") for s in load]),
        "avg_pkg_watt":    _avg([s.get("pkg_watt") for s in load]),
        "peak_pkg_watt":   _peak([s.get("pkg_watt") for s in load]),
        # LHM doesn't reliably expose a CPU-Cores-only power rail across
        # vendors, so we emit zeros and let the formatter print the
        # "(not exposed by this CPU)" message.
        "avg_core_watt":   0.0,
        "peak_core_watt":  0.0,
    }

    # Per-physical-core peaks during load.
    # core_clocks / core_temps are parallel lists indexed by physical core id.
    n_cores = max((len(s.get("core_clocks") or []) for s in load), default=0)
    per_core_peaks = {}
    for cid in range(n_cores):
        clocks = []
        temps = []
        for s in load:
            cc = s.get("core_clocks") or []
            ct = s.get("core_temps") or []
            if cid < len(cc) and cc[cid] is not None:
                clocks.append(cc[cid])
            if cid < len(ct) and ct[cid] is not None:
                temps.append(ct[cid])
        if not clocks:
            continue
        per_core_peaks[cid] = {
            "peak_mhz": max(clocks),
            "avg_mhz":  sum(clocks) / len(clocks),
            "peak_tmp": max(temps) if temps else 0.0,
        }
    summary["per_core_peaks"] = per_core_peaks

    # ── Clock consistency across all per-core samples during load ──────────
    # Coefficient of variation (std dev / mean × 100) tells you how much the
    # clocks bounced around.  Low CV = held boost steadily.  High CV = a lot
    # of boost-to-idle cycling (thermal or power limit throttling).
    all_clock_readings = []
    for s in load:
        for c in (s.get("core_clocks") or []):
            if c is not None and c > 0:
                all_clock_readings.append(float(c))
    # Fallback to per-sample max when no per-core data available
    if not all_clock_readings:
        all_clock_readings = [_sample_max_mhz(s) for s in load
                              if _sample_max_mhz(s) > 0]
    if len(all_clock_readings) >= 2:
        import statistics as _stats
        _c_mean = _stats.mean(all_clock_readings)
        _c_std  = _stats.stdev(all_clock_readings)
        summary["aggregate"]["clock_stddev_mhz"] = round(_c_std, 1)
        summary["aggregate"]["clock_cv_pct"]     = round(
            (_c_std / _c_mean * 100.0) if _c_mean > 0 else 0.0, 2)
    else:
        summary["aggregate"]["clock_stddev_mhz"] = 0.0
        summary["aggregate"]["clock_cv_pct"]     = 0.0

    return summary


def measure_cooldown(lhm_sampler, target_tmp, progress_callback=None,
                     max_duration=90):
    """Sample LHM after a benchmark ends until the CPU temp falls within 5 °C
    of *target_tmp* (the idle baseline), or *max_duration* seconds elapses.

    Calls *progress_callback* with the same extended signature used by
    HeartbeatReporter so the GUI chart can plot the cool-down live.

    Returns a list of LHM sample dicts (~1 per second).
    """
    cooldown_samples = []
    t0 = time.time()
    while True:
        elapsed = time.time() - t0
        if elapsed > max_duration:
            break
        s = lhm_sampler.latest_sample()
        if s is not None:
            cooldown_samples.append(dict(s))
            cur_tmp = float(s.get("pkg_tmp") or 0.0)
            # Stop once we've cooled within 5 °C of idle (after a minimum 5 s)
            if cur_tmp <= (target_tmp + 5.0) and elapsed >= 5.0:
                break
            if progress_callback is not None:
                try:
                    clocks = s.get("core_clocks") or []
                    mhz    = max(clocks) if clocks else 0.0
                    progress_callback(
                        elapsed, 0, 0,
                        float(s.get("cpu_busy") or 0.0),
                        mhz,
                        cur_tmp,
                        float(s.get("pkg_watt") or 0.0),
                        clocks,
                        s.get("core_temps")       or [],
                        s.get("core_clock_names") or [],
                        s.get("core_temp_names")  or [],
                    )
                except Exception:
                    pass
        time.sleep(1.0)
    return cooldown_samples


def summarize_cooldown(cooldown_samples):
    """Summarise a cool-down sample list returned by measure_cooldown().

    Returns a dict with:
      duration_s      — how long the cool-down phase lasted
      start_tmp_c     — temperature at cool-down start (= end of benchmark)
      end_tmp_c       — temperature when cool-down ended
      drop_c          — total degrees dropped
      rate_c_per_min  — average cooling rate (higher = faster cooler)
    """
    if not cooldown_samples or len(cooldown_samples) < 2:
        return {}
    temps      = [float(s.get("pkg_tmp") or 0.0) for s in cooldown_samples]
    duration_s = len(cooldown_samples)      # LHMSampler runs at ~1 Hz
    start_tmp  = temps[0]
    end_tmp    = temps[-1]
    drop_c     = start_tmp - end_tmp
    rate_c_per_min = (drop_c / duration_s * 60.0) if duration_s > 0 else 0.0
    return {
        "duration_s":     duration_s,
        "start_tmp_c":    round(start_tmp, 1),
        "end_tmp_c":      round(end_tmp, 1),
        "drop_c":         round(drop_c, 1),
        "rate_c_per_min": round(rate_c_per_min, 1),
    }


def format_turbostat_summary(summary):
    out = []
    out.append("Samples captured:    {} (1Hz)".format(summary["total_samples"]))
    out.append("Idle samples:        {}".format(summary["idle_samples"]))
    out.append("Load samples (>=50% busy): {}".format(summary["load_samples"]))
    agg = summary.get("aggregate")
    if not agg:
        out.append("")
        out.append("(no high-load samples captured -- workload may have been too brief")
        out.append(" or turbostat captured only idle time)")
        return "\n".join(out)

    out.append("")
    out.append("Aggregate during load:")
    out.append("  CPU usage:        {:5.1f}% avg     (peak {:5.1f}%)".format(
        agg["avg_busy_pct"], agg["peak_busy_pct"]))
    out.append("  Clock:            {:>5.0f} MHz avg   (peak {:>5.0f} MHz)".format(
        agg["avg_clock_mhz"], agg["peak_clock_mhz"]))
    cv  = agg.get("clock_cv_pct")
    std = agg.get("clock_stddev_mhz")
    if cv is not None:
        stability = "stable" if cv < 5 else ("moderate" if cv < 15 else "erratic")
        out.append("  Clock consistency:{:>6.1f}% CV   ({:.0f} MHz std dev — {})".format(
            cv, std or 0.0, stability))
    out.append("  Package temp:     {:5.1f} C avg     (peak {:5.1f} C)".format(
        agg["avg_pkg_tmp_c"], agg["peak_pkg_tmp_c"]))
    out.append("  Package power:    {:5.2f} W avg     (peak {:5.2f} W)".format(
        agg["avg_pkg_watt"], agg["peak_pkg_watt"]))
    if agg["avg_core_watt"] > 0.001:
        out.append("  Core power:       {:5.2f} W avg     (peak {:5.2f} W)".format(
            agg["avg_core_watt"], agg["peak_core_watt"]))
    else:
        out.append("  Core power:       (not exposed by this CPU)")

    pcp = summary.get("per_core_peaks", {})
    if pcp:
        out.append("")
        out.append("Per-CPU peaks during load:")
        for cid in sorted(pcp.keys()):
            p = pcp[cid]
            if p["peak_tmp"] > 0.1:
                tmp_str = "{:5.1f} C peak".format(p["peak_tmp"])
            else:
                tmp_str = "(shares temp w/ physical core)"
            out.append("  CPU{:>2}:  {:>5.0f} MHz peak ({:>5.0f} MHz avg),  {}".format(
                cid, p["peak_mhz"], p["avg_mhz"], tmp_str))
    return "\n".join(out)


def _analyze_cooling_flat(samples, load_threshold=80.0, idle_threshold=10.0):
    """Core cooling/thermal analyzer.

    Takes a flat list of dicts (one per 1Hz time-aligned sample) with keys:
      busy : float    overall CPU usage %, 0..100
      mhz  : float    representative core clock for that sample, MHz
      tmp  : float    package temperature, C
      watt : float    package power, W (0 is acceptable; rth becomes unreliable)
      thr  : float    F-state throttle counter (>0 means F-state hit this sample)

    Linux fills these from turbostat columns; Windows fills them from LHM samples.
    Returns the dict shape format_cooling_analysis() expects, or None if the
    workload was too brief / never went into load.
    """
    if len(samples) < 5:
        return None

    load_start_idx = next((i for i, s in enumerate(samples) if s["busy"] >= load_threshold), None)
    if load_start_idx is None:
        return None
    load_samples = [s for s in samples if s["busy"] >= load_threshold]
    pre_load_idle = [s for s in samples[:load_start_idx] if s["busy"] < idle_threshold]
    baseline = pre_load_idle if pre_load_idle else [s for s in samples if s["busy"] < idle_threshold]

    if baseline:
        baseline_tmp = sum(s["tmp"] for s in baseline) / len(baseline)
        baseline_watt = sum(s["watt"] for s in baseline) / len(baseline)
        baseline_n = len(baseline)
    else:
        baseline_tmp = baseline_watt = None
        baseline_n = 0

    half = len(load_samples) // 2
    steady_load = load_samples[half:] if half > 0 else load_samples
    steady_tmp = sum(s["tmp"] for s in steady_load) / len(steady_load)
    steady_watt = sum(s["watt"] for s in steady_load) / len(steady_load)
    peak_tmp = max(s["tmp"] for s in load_samples)

    # Thermal ramp rate: temp slope during first up-to-10s of load
    ramp_window = samples[load_start_idx : load_start_idx + 11]
    ramp_tmps = [s["tmp"] for s in ramp_window if s["tmp"] > 0]
    if len(ramp_tmps) >= 3:
        ramp_rate = (ramp_tmps[-1] - ramp_tmps[0]) / (len(ramp_tmps) - 1)
    else:
        ramp_rate = None

    # Time to thermal steady state: rolling 5-sample slope falls below 0.2 C/s
    time_to_steady = None
    for i in range(load_start_idx + 5, min(len(samples), load_start_idx + 600)):
        window = samples[i-5:i]
        if all(w["busy"] >= load_threshold for w in window):
            slope = (window[-1]["tmp"] - window[0]["tmp"]) / 4.0
            if abs(slope) < 0.2:
                time_to_steady = i - load_start_idx
                break

    throttled = [s for s in load_samples if s["thr"] > 0]

    # T-state (PROCHOT / duty-cycle) throttle detection.
    # Intel's thermal throttle has two flavors:
    #   F-state: drops the actual clock frequency (caught by CoreThr column above)
    #   T-state: keeps clock at boost but inserts idle cycles to reduce work.
    #            Does NOT register in CoreThr -- shows up as a sudden busy% drop
    #            while clock stays at the boost target and temps are near TjMax.
    # Heuristic: high temp + busy% < 95% + clock still near max load freq.
    if load_samples:
        boost_mhz = max(s["mhz"] for s in load_samples)
        # "Hot" = within 5 C of the peak we saw, but never below 90 C
        hot_threshold = max(90.0, peak_tmp - 5.0)
        t_state_throttled = [
            s for s in load_samples
            if s["busy"] < 95.0
            and s["tmp"] >= hot_threshold
            and s["mhz"] >= boost_mhz * 0.97
        ]
    else:
        boost_mhz = 0
        t_state_throttled = []

    # Effective thermal resistance (only with reliable power data)
    rth = None
    rth_reliable = False
    if baseline_tmp is not None and steady_watt > 5.0 and steady_watt > baseline_watt + 1.0:
        rth = (steady_tmp - baseline_tmp) / (steady_watt - baseline_watt)
        rth_reliable = True

    return {
        "baseline_tmp": baseline_tmp, "baseline_watt": baseline_watt,
        "baseline_samples": baseline_n,
        "steady_tmp": steady_tmp, "steady_watt": steady_watt,
        "steady_samples": len(steady_load), "peak_tmp": peak_tmp,
        "delta_tmp": (steady_tmp - baseline_tmp) if baseline_tmp is not None else None,
        "delta_watt": (steady_watt - baseline_watt) if baseline_watt is not None else None,
        "ramp_rate_c_per_s": ramp_rate,
        "time_to_steady_s": time_to_steady,
        "thermal_resistance_c_per_w": rth,
        "thermal_resistance_reliable": rth_reliable,
        "throttled_sample_count": len(throttled),
        "tstate_throttled_sample_count": len(t_state_throttled),
        "boost_mhz_observed": boost_mhz,
        "load_sample_count": len(load_samples),
        "tjmax_estimate_c": 100.0,
        "throttle_headroom_c": 100.0 - peak_tmp,
    }


def analyze_cooling(raw_text, load_threshold=80.0, idle_threshold=10.0):
    """Parse turbostat output for cooler / thermal-behavior metrics.
    Returns a dict, or None if there's insufficient data."""
    lines = raw_text.splitlines()
    headers = None
    samples = []
    for line in lines:
        ls = line.strip()
        if not ls:
            continue
        if ls.startswith("Core") and "CPU" in ls:
            headers = ls.split()
            continue
        if headers is None:
            continue
        parts = ls.split()
        if len(parts) < 4:
            continue
        if parts[0] == "-":
            row = dict(zip(headers, parts))
            samples.append({
                "busy": _fnum(row.get("Busy%", 0)),
                "mhz":  _fnum(row.get("Bzy_MHz", 0)),
                "tmp":  _fnum(row.get("PkgTmp", 0)),
                "watt": _fnum(row.get("PkgWatt", 0)),
                "thr":  _fnum(row.get("CoreThr", 0)),
            })
    return _analyze_cooling_flat(samples, load_threshold, idle_threshold)


def analyze_cooling_lhm(lhm_samples, load_threshold=80.0, idle_threshold=10.0):
    """Cooling/thermal analyzer for the Windows (LHM) sample shape.

    LHM doesn't expose Intel's CoreThr counter, so F-state throttling is
    detected via a fallback heuristic: a high-busy sample whose clock dropped
    >=15% below the peak boost we observed during the run is flagged.
    T-state detection is the same as Linux (high temp + busy% drop + clock
    still pinned at boost).
    """
    flat = []
    for s in lhm_samples:
        clocks = s.get("core_clocks") or []
        flat.append({
            "busy": float(s.get("cpu_busy") or 0.0),
            "mhz":  float(max(clocks) if clocks else 0.0),
            "tmp":  float(s.get("pkg_tmp") or 0.0),
            "watt": float(s.get("pkg_watt") or 0.0),
            "thr":  0.0,  # filled in below if heuristic catches an F-state event
        })
    if flat:
        load_rows = [r for r in flat if r["busy"] >= load_threshold]
        if load_rows:
            boost = max(r["mhz"] for r in load_rows)
            for r in flat:
                # F-state heuristic: sample is heavily loaded but clock dropped
                # well below the run's peak boost frequency.
                if r["busy"] >= 80.0 and boost > 0 and r["mhz"] < boost * 0.85:
                    r["thr"] = 1.0
    return _analyze_cooling_flat(flat, load_threshold, idle_threshold)


def analyze_fans_lhm(lhm_samples):
    """Aggregate fan readings from LHM samples. Returns dict in the same shape
    as analyze_fans() so format_fan_analysis() works without changes.

    LHM doesn't expose a fan's max-RPM capability, so max_rpm_capable is None.
    format_fan_analysis() prints '(max capable: not exposed)' in that case
    and skips the saturation-vs-headroom verdict for that fan.
    """
    if not lhm_samples:
        return None
    # Discover all fan names that ever appeared
    fan_names = set()
    for s in lhm_samples:
        for k in (s.get("fans") or {}):
            fan_names.add(k)
    if not fan_names:
        return None
    out = {}
    for name in sorted(fan_names):
        readings = []
        for s in lhm_samples:
            fmap = s.get("fans") or {}
            v = fmap.get(name)
            if v is not None and v > 0:
                readings.append(v)
        if not readings:
            continue
        out[name] = {
            "label": name,
            "min_rpm": int(min(readings)),
            "avg_rpm": sum(readings) / len(readings),
            "max_rpm_observed": int(max(readings)),
            "max_rpm_capable": None,  # LHM doesn't expose this
            "samples": len(readings),
        }
    return out or None


def format_cooling_analysis(c):
    if c is None:
        return "(insufficient turbostat data for cooler analysis)"
    out = []
    if c["baseline_tmp"] is not None:
        out.append("Idle baseline:           {:5.1f} C  @ {:5.2f} W   ({} samples before load)".format(
            c["baseline_tmp"], c["baseline_watt"], c["baseline_samples"]))
    else:
        out.append("Idle baseline:           (none captured before load began)")
    out.append("Steady-state under load: {:5.1f} C  @ {:5.2f} W   ({} samples, latter half of load)".format(
        c["steady_tmp"], c["steady_watt"], c["steady_samples"]))
    out.append("Peak temperature:        {:5.1f} C".format(c["peak_tmp"]))
    if c["delta_tmp"] is not None:
        out.append("")
        out.append("Temperature climb:       +{:.1f} C above idle".format(c["delta_tmp"]))
    if c["delta_watt"] is not None and c["delta_watt"] > 0:
        out.append("Power increase:          +{:.2f} W above idle".format(c["delta_watt"]))
    out.append("")
    if c["ramp_rate_c_per_s"] is not None:
        out.append("Thermal ramp rate:       {:+.2f} C/s during first 10s of load".format(c["ramp_rate_c_per_s"]))
    if c["time_to_steady_s"] is not None:
        out.append("Time to steady-state:    ~{}s after load started".format(c["time_to_steady_s"]))
    else:
        out.append("Time to steady-state:    did not stabilize during this run")
    out.append("")
    if c["thermal_resistance_reliable"]:
        rth = c["thermal_resistance_c_per_w"]
        if   rth < 0.15: verdict = "excellent (AIO / premium air-cooling territory)"
        elif rth < 0.30: verdict = "good (decent tower cooler)"
        elif rth < 0.60: verdict = "adequate (stock-class)"
        else:            verdict = "high (cooling is undersized for this thermal load)"
        out.append("Effective thermal resistance: {:.3f} C/W   ({})".format(rth, verdict))
    else:
        out.append("Effective thermal resistance: (cannot compute -- needs reliable RAPL power data)")
    out.append("")
    out.append("Throttle headroom:       ~{:.0f} C below assumed TjMax (100 C)".format(c["throttle_headroom_c"]))
    fstate_n = c.get("throttled_sample_count", 0)
    tstate_n = c.get("tstate_throttled_sample_count", 0)
    load_n = c["load_sample_count"]

    if fstate_n > 0:
        pct = 100.0 * fstate_n / load_n
        out.append("F-state throttling:      YES on {} of {} load samples ({:.1f}%)".format(
            fstate_n, load_n, pct))
        out.append("                         (clock frequency dropped -- caught via CoreThr)")
    else:
        out.append("F-state throttling:      no (CoreThr = 0 throughout load)")

    if tstate_n > 0:
        pct = 100.0 * tstate_n / load_n
        out.append("T-state throttling:      YES on {} of {} load samples ({:.1f}%)".format(
            tstate_n, load_n, pct))
        out.append("                         (PROCHOT / duty-cycle modulation -- clock stays at")
        out.append("                          boost but the chip inserts idle cycles to cool down.")
        out.append("                          Real performance hit, hidden from CoreThr counter.)")
    else:
        out.append("T-state throttling:      none detected")

    any_throttle = (fstate_n > 0) or (tstate_n > 0)

    out.append("")
    out.append("Verdict:")
    if any_throttle:
        worst_pct = 100.0 * max(fstate_n, tstate_n) / load_n
        out.append("  Cooler reached its thermal limit -- CPU was throttled "
                   "for ~{:.0f}% of the run.".format(worst_pct))
        out.append("  Better cooling would unlock noticeably more sustained throughput.")
    elif c["peak_tmp"] < 70:
        out.append("  Excellent cooling. Massive thermal headroom -- could push longer/harder workloads.")
    elif c["peak_tmp"] < 85:
        out.append("  Good cooling. Comfortable margin to throttle threshold.")
    elif c["peak_tmp"] < 95:
        out.append("  Cooling is adequate but running warm. Little margin for hotter ambient temps.")
    else:
        out.append("  Cooling is right at the limit -- chip is hovering near TjMax.")
        out.append("  Watch for T-state throttling on longer runs.")
    return "\n".join(out)


def analyze_fans(fan_samples, fans):
    """Aggregate fan readings across the run.
    Returns dict of fan_name -> stats, or None if no data."""
    if not fan_samples or not fans:
        return None
    out = {}
    for fan in fans:
        name = fan["name"]
        readings = [s.get(name) for _, s in fan_samples if s.get(name) is not None and s.get(name) > 0]
        if not readings:
            continue
        cap = read_fan_max(fan)
        out[name] = {
            "label": fan["label"],
            "min_rpm": min(readings),
            "avg_rpm": sum(readings) / len(readings),
            "max_rpm_observed": max(readings),
            "max_rpm_capable": cap,
            "samples": len(readings),
        }
    return out or None


def format_fan_analysis(fan_data):
    if not fan_data:
        return None
    out = ["Fans observed during run:"]
    any_saturated = False
    any_headroom = False
    for d in fan_data.values():
        cap = d["max_rpm_capable"]
        peak = d["max_rpm_observed"]
        avg = d["avg_rpm"]
        mn = d["min_rpm"]
        if cap and cap > 0:
            pct = 100.0 * peak / cap
            if pct >= 95:
                any_saturated = True
            else:
                any_headroom = True
            out.append("  {}: min {:>4} / avg {:>4.0f} / peak {:>4} RPM   "
                       "(max capable {} RPM, {:.0f}% utilized at peak)".format(
                d["label"], mn, avg, peak, cap, pct))
        else:
            out.append("  {}: min {:>4} / avg {:>4.0f} / peak {:>4} RPM   "
                       "(max capable: not exposed)".format(d["label"], mn, avg, peak))
    out.append("")
    if any_saturated:
        out.append("Fan capacity:  SATURATED -- one or more fans hit ~max RPM during the run.")
        out.append("               Cooler is using all available active cooling. Any further")
        out.append("               temperature reduction would require better hardware")
        out.append("               (heatsink, paste, larger fan, or AIO).")
    elif any_headroom:
        out.append("Fan capacity:  headroom remaining -- fans never reached max RPM.")
        out.append("               If temps are still high, the cooler may not be ramping the fan")
        out.append("               aggressively enough (check fan curve), or thermal interface is")
        out.append("               the bottleneck (worth a repaste on older systems).")
    else:
        out.append("Fan capacity:  unknown (no max-RPM info exposed by hwmon)")
    return "\n".join(out)


def _smb_env(password):
    env = os.environ.copy()
    if password is not None:
        env["PASSWD"] = password
    return env


def _smb_to_unc(share):
    r"""Convert a //host/share-style path to a Windows UNC path \\host\share.
    Tolerates //, \\, host:/share, and forward-slash inside the share name.
    """
    s = share.replace("\\", "/")
    if s.startswith("//"):
        s = s[2:]
    return "\\\\" + s.replace("/", "\\")


def _smb_unc_subdir(share, subdir):
    """Full UNC path for share + relative subdir, with backslashes."""
    unc = _smb_to_unc(share)
    sub = (subdir or "").replace("/", "\\").strip("\\")
    return (unc + "\\" + sub) if sub else unc


def _net_use_connect(share, user, password):
    """Establish a Windows SMB session for our process.
    Returns the subprocess result, or None if the net.exe call fails.
    If the share is already mapped (live session), reuses it immediately.
    Otherwise purges stale UNC mapping and cached credentials before connecting.
    """
    unc_root = _smb_to_unc(share)
    parts = unc_root.split("\\")
    host_part = parts[2] if len(parts) > 2 else unc_root
    pw = password or ""
    cmd = ["net", "use", unc_root, "/user:" + user, pw]
    try:
        # Reuse an already-live session without touching it
        existing = subprocess.run(["net", "use"], capture_output=True, text=True, timeout=10)
        already = unc_root.lower() in existing.stdout.lower()
        if already:
            return subprocess.CompletedProcess(cmd, 0, stdout="already connected", stderr="")
        # No live session — purge any stale state and connect fresh
        subprocess.run(["net", "use", unc_root, "/delete", "/y"],
                       capture_output=True, timeout=10)
        subprocess.run(["cmdkey", "/delete:" + host_part],
                       capture_output=True, timeout=10)
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=20, check=False)
        return r
    except Exception as e:
        print("[archive] net use connect failed: {}".format(e), flush=True)
        return None


def _net_use_disconnect(share):
    """Tear down the Windows SMB session. Best-effort, errors ignored."""
    unc_root = _smb_to_unc(share)
    cmd = ["net", "use", unc_root, "/delete", "/y"]
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=10, check=False)
    except Exception:
        return None


def _smb_list_all_windows(share, user, password, subdir):
    """List files (non-directories) in the share's subdir on Windows.
    Connects briefly via 'net use', listdir's the UNC path, disconnects.
    """
    if password is None:
        return []
    conn = _net_use_connect(share, user, password)
    if conn is None or conn.returncode != 0:
        return []
    try:
        unc_path = _smb_unc_subdir(share, subdir)
        try:
            entries = os.listdir(unc_path)
        except (FileNotFoundError, NotADirectoryError, OSError):
            return []
        files = []
        for name in entries:
            full = os.path.join(unc_path, name)
            try:
                if os.path.isfile(full):
                    files.append(name)
            except OSError:
                pass
        return files
    finally:
        _net_use_disconnect(share)


def _smb_mkdir_windows(share, user, password, path):
    """Create the subdir on the Windows SMB share. Returns a fake
    subprocess.CompletedProcess so the caller's existing return-handling works.
    """
    class _Result:
        def __init__(self, rc, stderr=""):
            self.returncode = rc
            self.stdout = ""
            self.stderr = stderr
    if password is None:
        return _Result(1, "no password")
    conn = _net_use_connect(share, user, password)
    if conn is None or conn.returncode != 0:
        return _Result(1, conn.stderr if conn else "net use failed")
    try:
        unc_path = _smb_unc_subdir(share, path)
        try:
            os.makedirs(unc_path, exist_ok=True)
            return _Result(0)
        except Exception as e:
            return _Result(1, str(e))
    finally:
        _net_use_disconnect(share)


def _smb_put_windows(share, user, password, subdir, local_path):
    """Copy local_path into share/subdir/. Returns a fake CompletedProcess."""
    class _Result:
        def __init__(self, rc, stderr=""):
            self.returncode = rc
            self.stdout = ""
            self.stderr = stderr
    if password is None:
        return _Result(1, "no password")
    conn = _net_use_connect(share, user, password)
    if conn is None or conn.returncode != 0:
        return _Result(1, conn.stderr if conn else "net use failed")
    try:
        unc_path = _smb_unc_subdir(share, subdir)
        try:
            os.makedirs(unc_path, exist_ok=True)
        except Exception:
            pass  # already exists, or will fail on copy below
        try:
            import shutil as _shutil
            dest = os.path.join(unc_path, os.path.basename(local_path))
            _shutil.copyfile(local_path, dest)
            return _Result(0)
        except Exception as e:
            return _Result(1, str(e))
    finally:
        _net_use_disconnect(share)


def smb_list_all(share, user, password, subdir):
    """List all non-directory entries inside <share>/<subdir>. Filtering happens in Python."""
    if platform.system() == "Windows":
        return _smb_list_all_windows(share, user, password, subdir)
    cmd = ["smbclient", share, "-U", user, "-c", 'cd "{}"; ls'.format(subdir)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=20,
                                env=_smb_env(password), check=False)
    except Exception as e:
        print("[archive] smbclient ls failed: {}".format(e), flush=True)
        return []
    if result.returncode != 0:
        # Likely the subdir does not exist yet -- normal on first run.
        return []
    files = []
    for line in result.stdout.splitlines():
        line_r = line.rstrip()
        if not line_r:
            continue
        ls = line_r.lstrip()
        if ls.startswith(("Domain=", "blocks of size", "Anonymous", "OS=", "Server=",
                          "Workgroup", "session setup")):
            continue
        # smbclient ls format:  "  FILENAME           A  SIZE  Day Mon NN HH:MM:SS YYYY"
        m = re.match(r"^\s+(.+?)\s+([ADHRSN]+)\s+\d+\s+\w{3}\s+\w{3}", line_r)
        if m:
            name = m.group(1).strip()
            attrs = m.group(2)
            if "D" in attrs:
                continue  # skip directories like . and ..
            files.append(name)
    return files


def smb_mkdir(share, user, password, path):
    """Create a single SMB directory. Harmless if it already exists (mkdir errors
    are ignored). Returns the CompletedProcess on success or None if smbclient
    isn't available / something went wrong (logs the error)."""
    if platform.system() == "Windows":
        return _smb_mkdir_windows(share, user, password, path)
    cmd = ["smbclient", share, "-U", user, "-c", 'mkdir "{}"'.format(path)]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=20,
                              env=_smb_env(password), check=False)
    except Exception as e:
        print("[archive] smbclient mkdir failed: {}".format(e), flush=True)
        return None


def smb_put(share, user, password, subdir, local_path):
    """Upload local_path into <share>/<subdir>. Caller is responsible for
    ensuring subdir exists. Returns the CompletedProcess, or None if smbclient
    isn't available."""
    if platform.system() == "Windows":
        return _smb_put_windows(share, user, password, subdir, local_path)
    fname = os.path.basename(local_path)
    smb_cmd = 'cd "{}"; put "{}" "{}"'.format(subdir, local_path, fname)
    cmd = ["smbclient", share, "-U", user, "-c", smb_cmd]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=120,
                              env=_smb_env(password), check=False)
    except Exception as e:
        print("[archive] smbclient put failed: {}".format(e), flush=True)
        return None


def _keyring_get(username):
    """Look up a stored credential from the OS keyring.
    Returns the password string, or None if not found / keyring unavailable.
    Credentials are encrypted by the OS (DPAPI on Windows, Secret Service on Linux).
    """
    try:
        import keyring as _kr
        return _kr.get_password(_KEYRING_SERVICE, username)
    except Exception:
        return None


def _keyring_set(username, password):
    """Save a credential to the OS keyring (encrypted at rest).
    Returns True on success, False if keyring is unavailable or the write failed.
    """
    try:
        import keyring as _kr
        # Reject plaintext fallback backends — we only accept secure storage.
        backend = _kr.get_keyring()
        backend_name = type(backend).__module__ + "." + type(backend).__name__
        if "plaintext" in backend_name.lower() or "fail" in backend_name.lower():
            return False
        _kr.set_password(_KEYRING_SERVICE, username, password)
        return True
    except Exception:
        return False


def _sftp_host_from_share(share):
    r"""Extract hostname/IP from //host/share or \\host\share."""
    s = share.replace("\\", "/").lstrip("/")
    return s.split("/")[0]


class _TOFUPolicy:
    """Trust-On-First-Use SSH host key policy for paramiko.SSHClient.

    Behaviour:
      • Known host, key matches  → accepted silently (paramiko built-in check).
      • Known host, key changed  → paramiko raises BadHostKeyException before
                                   this policy is consulted.  Caller catches it
                                   and aborts the upload with a clear message.
      • New host (not in known_hosts) → key is accepted and saved to
                                   ~/.ssh/known_hosts for verification on all
                                   future connections.
    """

    def __init__(self, known_hosts_path):
        self._path = known_hosts_path

    def missing_host_key(self, client, hostname, key):
        # First time seeing this host: persist the key so changes are caught later.
        try:
            ssh_dir = os.path.dirname(self._path)
            if ssh_dir:
                os.makedirs(ssh_dir, exist_ok=True)
            client._host_keys.add(hostname, key.get_name(), key)
            client.save_host_keys(self._path)
        except Exception:
            pass  # Can't write known_hosts — accept this session but don't persist


def _sftp_put_windows(host, user, password, remote_dir, local_path):
    """Upload local_path into remote_dir/ on host via SFTP (paramiko).

    Uses Trust-On-First-Use host key verification:
      - First connection to a host: accepts and saves the key.
      - Subsequent connections: verifies against the saved key.
      - Changed key (possible MITM): upload is aborted with a clear error.

    Creates remote_dir if it doesn't exist. Returns (ok: bool, err: str).
    """
    try:
        import paramiko
    except ImportError:
        return False, "paramiko not installed (pip install paramiko)"

    known_hosts = os.path.join(os.path.expanduser("~"), ".ssh", "known_hosts")
    try:
        ssh = paramiko.SSHClient()
        ssh.load_system_host_keys()          # /etc/ssh/ssh_known_hosts (if present)
        if os.path.exists(known_hosts):
            ssh.load_host_keys(known_hosts)  # ~/.ssh/known_hosts
        ssh.set_missing_host_key_policy(_TOFUPolicy(known_hosts))

        ssh.connect(host, port=22, username=user, password=password, timeout=15)
        sftp = ssh.open_sftp()
        try:
            # Ensure each component of remote_dir exists
            parts = remote_dir.lstrip("/").split("/")
            path = ""
            for part in parts:
                path = path + "/" + part
                try:
                    sftp.stat(path)
                except FileNotFoundError:
                    try:
                        sftp.mkdir(path)
                    except Exception:
                        pass
            remote_path = remote_dir.rstrip("/") + "/" + os.path.basename(local_path)
            sftp.put(local_path, remote_path)
        finally:
            sftp.close()
        ssh.close()
        return True, ""
    except paramiko.BadHostKeyException as exc:
        return False, (
            "SSH host key for {} has changed — upload aborted. "
            "If the NAS was reinstalled or its SSH key was rotated, remove the "
            "old entry from {} and retry.  Details: {}".format(host, known_hosts, exc)
        )
    except Exception as e:
        return False, str(e)


def next_run_number(existing_files, prefix):
    max_n = 0
    for f in existing_files:
        if not f.startswith(prefix):
            continue
        rest = f[len(prefix):].strip()
        m = re.match(r"^(\d+)\.log$", rest)
        if m:
            n = int(m.group(1))
            if n > max_n:
                max_n = n
    return max_n + 1


def archive_setup(args):
    """Returns dict of state, or {'enabled': False} if archive cannot run.

    Cross-platform: the OS-agnostic parts (CPU detection, NAS credentials,
    run-number discovery, log filename) run on both Linux and Windows. The
    sensor-source startup branches: Linux launches turbostat as a subprocess,
    Windows ensures LibreHardwareMonitor is running and starts an LHMSampler.
    """
    state = {"enabled": False}
    sysname = platform.system()
    if sysname not in ("Linux", "Windows"):
        print("[archive] not supported on {}; skipping".format(sysname), flush=True)
        return state

    # Step 1: determine CPU
    cpu = detect_cpu_name()
    print("[archive] CPU detected: {}".format(cpu), flush=True)

    # Filename + credential setup.  Windows uses SFTP + timestamp (zero NAS contact
    # before the benchmark).  Linux uses SMB + sequential run number.
    if sysname == "Windows":
        user = args.sftp_user
        # Credential priority: --sftp-password CLI → SFTP_PASSWORD env → OS keyring → prompt.
        # The keyring backend is always encrypted (DPAPI on Windows, Secret Service on Linux).
        # Plain-text fallback backends are rejected; password never hits disk unencrypted.
        pw_source = "none"
        if args.sftp_password:
            password = args.sftp_password
            pw_source = "cli"
        elif os.environ.get("SFTP_PASSWORD"):
            password = os.environ["SFTP_PASSWORD"]
            pw_source = "env"
        else:
            password = _keyring_get(user)
            if password is not None:
                print("[archive] SFTP credentials loaded from system keyring", flush=True)
                pw_source = "keyring"
            elif sys.stdin.isatty():
                try:
                    password = getpass.getpass(
                        "SFTP password for {}@{}: ".format(
                            user, _sftp_host_from_share(args.smb_share)))
                    pw_source = "prompt"
                except Exception:
                    print("[archive] no SFTP password available; skipping upload", flush=True)
                    password = None
            else:
                print("[archive] no SFTP password (non-interactive session); "
                      "pass --sftp-password or seed the keyring interactively", flush=True)
                password = None
        ts = datetime.datetime.now().strftime("%m-%d-%Y %H-%M-%S")
        tag = getattr(args, "run_tag", "") or ""
        tag_safe = re.sub(r'[/\\:*?"<>|]', "_", tag).strip()[:40]
        if tag_safe:
            log_filename = "{} [{}] {}.log".format(cpu, tag_safe, ts)
        else:
            log_filename = "{} {}.log".format(cpu, ts)
        cpu_subdir = "{}/{}".format(args.sftp_path.rstrip("/"), cpu)
        run_n = ts
    else:
        today = datetime.datetime.now().strftime("%m-%d-%Y")
        prefix = "{} {} ".format(cpu, today)
        user = args.smb_user
        # Credential priority: SMB_PASSWORD env → OS keyring → prompt.
        pw_source = "none"
        if os.environ.get("SMB_PASSWORD"):
            password = os.environ["SMB_PASSWORD"]
            pw_source = "env"
        else:
            password = _keyring_get(user)
            if password is not None:
                print("[archive] SMB credentials loaded from system keyring", flush=True)
                pw_source = "keyring"
            elif sys.stdin.isatty():
                try:
                    password = getpass.getpass(
                        "SMB password for {}@{}: ".format(user, args.smb_share))
                    pw_source = "prompt"
                except Exception:
                    print("[archive] no password available; skipping upload", flush=True)
                    password = None
            else:
                print("[archive] no SMB password (non-interactive session); "
                      "set SMB_PASSWORD env var or seed the keyring interactively", flush=True)
                password = None
        cpu_subdir = "{}/{}".format(args.smb_subdir, cpu)
        run_n = 1
        if password is not None:
            existing = smb_list_all(args.smb_share, user, password, cpu_subdir)
            matching = [f for f in existing if f.startswith(prefix)]
            if existing:
                print("[archive] CPU folder exists on NAS: {} ({} files inside)".format(
                    cpu_subdir, len(existing)), flush=True)
            else:
                print("[archive] CPU folder missing or empty: {} (will create on upload)".format(
                    cpu_subdir), flush=True)
            run_n = next_run_number(matching, prefix)
            print("[archive] {} existing run(s) for today -> this run is #{}".format(
                len(matching), run_n), flush=True)
            smb_mkdir(args.smb_share, user, password, cpu_subdir)
        tag = getattr(args, "run_tag", "") or ""
        tag_safe = re.sub(r'[/\\:*?"<>|]', "_", tag).strip()[:40]
        if tag_safe:
            log_filename = "{}{} [{}].log".format(prefix, run_n, tag_safe)
        else:
            log_filename = "{}{}.log".format(prefix, run_n)

    raw_path = os.path.join(tempfile.gettempdir(), "_turbostat_raw_{}.tmp".format(os.getpid()))
    print("[archive] log filename: {}".format(log_filename), flush=True)

    # Step 5: start the platform-appropriate sensor source.
    proc = None
    lhm_sampler = None
    fans = []
    if sysname == "Linux":
        proc = start_turbostat(raw_path)
        fans = discover_fans()
        if fans:
            names = ", ".join(f["label"] for f in fans)
            print("[archive] fans detected: {}".format(names), flush=True)
        else:
            print("[archive] no fan sensors detected", flush=True)
    else:
        # Windows: LHM bootstrap + LHMSampler poll loop
        print("[archive] ensuring LibreHardwareMonitor is running...", flush=True)
        if not lhm_ensure_running():
            print("[archive] LHM bootstrap failed; archive cannot continue", flush=True)
            return state
        lhm_sampler = LHMSampler(interval=1.0)
        lhm_sampler.start()
        print("[archive] LHM sampler started (1Hz)", flush=True)
        # On Windows we read fan info out of the LHM samples themselves at
        # finalize time, so no separate fan discovery is needed here.

    state.update({
        "enabled": True,
        "proc": proc,                    # turbostat Popen on Linux, None on Windows
        "raw_path": raw_path,            # turbostat output path, set on both (unused on Windows)
        "lhm_sampler": lhm_sampler,      # LHMSampler on Windows, None on Linux
        "log_filename": log_filename,
        "cpu_name": cpu,
        "cpu_subdir": cpu_subdir,
        "run_n": run_n,
        "creds": (user, password),
        "pw_source": pw_source,
        "fans": fans,
        "fan_samples": [],
    })
    return state


def format_cooldown_section(cooldown_stats, ambient_c=None):
    """Format cool-down summary for inclusion in the text report."""
    if not cooldown_stats or not cooldown_stats.get("duration_s"):
        return None
    cd = cooldown_stats
    lines = [
        "Cool-down duration:   {:.0f}s  ({:.1f}°C → {:.1f}°C)".format(
            cd["duration_s"], cd["start_tmp_c"], cd["end_tmp_c"]),
        "Total temp drop:      {:.1f}°C".format(cd["drop_c"]),
        "Avg cooling rate:     {:.1f} °C/min  (higher = more effective cooler)".format(
            cd["rate_c_per_min"]),
    ]
    if ambient_c is not None:
        lines.append("Room temperature:     {:.0f}°C  (user-entered)".format(ambient_c))
    return "\n".join(lines)


def build_combined_report(cpu_name, run_n, args, bench_output, turbo_summary_text,
                          cooling_text=None, fan_text=None, sensor_source="turbostat",
                          cooldown_stats=None, ambient_c=None, run_tag=None):
    sep = "=" * 64
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    info = system_info()
    parts = [
        sep,
        " Pi Compute Benchmark - Run Report",
        sep,
        "Date:           {}".format(now),
        "CPU:            {}".format(cpu_name),
        "Run #:          {}".format(run_n),
    ]
    if run_tag:
        parts.append("Tag:            {}".format(run_tag))
    parts += [
        "Platform:       {}".format(info["platform"]),
        "Logical CPUs:   {}".format(info["logical_cpus"]),
        "Python:         {}".format(info["python"]),
        "Args:           --digits {} --mode {} --workers {}".format(
            args.digits, args.mode, args.workers),
        "",
        sep,
        " Benchmark output",
        sep,
        bench_output.rstrip(),
        "",
        sep,
        " Thermal / Power summary (parsed from {})".format(sensor_source),
        sep,
        turbo_summary_text,
        "",
    ]
    if cooling_text is not None:
        parts.extend([
            sep,
            " Cooler / Thermal analysis",
            sep,
            cooling_text,
            "",
        ])
    if fan_text is not None:
        parts.extend([
            sep,
            " Fan / Active-cooling analysis",
            sep,
            fan_text,
            "",
        ])
    cd_text = format_cooldown_section(cooldown_stats, ambient_c)
    if cd_text is not None:
        parts.extend([
            sep,
            " Cool-down analysis",
            sep,
            cd_text,
            "",
        ])
    return "\n".join(parts)


def archive_finalize(args, state, bench_output):
    if not state.get("enabled"):
        return

    # Step 6 (benchmark just finished). Step 7: stop the sensor source and
    # parse the captured data. The shape of the analysis output is identical
    # between Linux (turbostat) and Windows (LHM) so the report renders the
    # same on both.
    summary_text = "(no sensor data captured)"
    cooling_text = None
    fan_data = None

    lhm_sampler = state.get("lhm_sampler")
    if lhm_sampler is not None:
        # ---- Windows: LHM sampler thread ----
        lhm_sampler.stop()
        lhm_samples = lhm_sampler.all_samples()
        print("[archive] LHM sampler stopped: {} samples ({} fetch failures)".format(
            len(lhm_samples), lhm_sampler.fetch_failure_count()), flush=True)
        if lhm_samples:
            summary = summarize_lhm_samples(lhm_samples)
            summary_text = format_turbostat_summary(summary)
            cooling = analyze_cooling_lhm(lhm_samples)
            cooling_text = format_cooling_analysis(cooling)
            fan_data = analyze_fans_lhm(lhm_samples)
    else:
        # ---- Linux: turbostat subprocess ----
        stop_turbostat(state.get("proc"))
        raw_path = state.get("raw_path")
        raw_text = ""
        if raw_path and os.path.exists(raw_path):
            try:
                with open(raw_path) as f:
                    raw_text = f.read()
            except Exception as e:
                print("[archive] could not read turbostat output: {}".format(e), flush=True)
        if raw_text:
            summary = parse_turbostat(raw_text)
            summary_text = format_turbostat_summary(summary)
            cooling = analyze_cooling(raw_text)
            cooling_text = format_cooling_analysis(cooling)
        fan_data = analyze_fans(state.get("fan_samples", []), state.get("fans", []))

    fan_text = format_fan_analysis(fan_data) if fan_data else None
    sensor_source = "LibreHardwareMonitor" if lhm_sampler is not None else "turbostat"

    # Step 8: build the combined report (system specs + bench + sensor summary + cooler + fans)
    report = build_combined_report(state["cpu_name"], state["run_n"], args,
                                   bench_output, summary_text, cooling_text, fan_text,
                                   sensor_source=sensor_source)

    log_filename = state["log_filename"]
    final_path = os.path.join(tempfile.gettempdir(), log_filename)
    try:
        with open(final_path, "w") as f:
            f.write(report)
    except Exception as e:
        print("[archive] failed to write report: {}".format(e), flush=True)
        return

    user, password = state["creds"]
    cpu_subdir = state["cpu_subdir"]

    if password is None:
        print("[archive] saved locally only: {}".format(final_path), flush=True)
        return

    # Step 9: upload to the CPU-specific subfolder
    if platform.system() == "Windows":
        sftp_host = _sftp_host_from_share(args.smb_share)
        print("[archive] uploading {} via SFTP -> {}:{}/...".format(
            log_filename, sftp_host, cpu_subdir), flush=True)
        upload_ok, upload_err = _sftp_put_windows(sftp_host, user, password, cpu_subdir, final_path)
    else:
        print("[archive] uploading {} -> {}/{}/...".format(
            log_filename, args.smb_share, cpu_subdir), flush=True)
        result = smb_put(args.smb_share, user, password, cpu_subdir, final_path)
        upload_ok = result.returncode == 0
        upload_err = result.stderr.strip() if not upload_ok else ""

    if upload_ok:
        print("[archive] upload OK", flush=True)
        # Save credentials to the OS keyring on first manual entry so the user
        # won't be prompted again.  Credentials are encrypted at rest (DPAPI on
        # Windows, Secret Service on Linux).  We only save when the password was
        # typed interactively — CLI / env-var sources are intentionally ephemeral.
        if state.get("pw_source") == "prompt":
            if _keyring_set(user, password):
                print("[archive] password saved to system keyring "
                      "(won't prompt again on this machine)", flush=True)
            else:
                print("[archive] note: install the 'keyring' package to avoid "
                      "typing your password each run", flush=True)
        for p in (final_path, state.get("raw_path")):
            try:
                if p and os.path.exists(p):
                    os.unlink(p)
            except Exception:
                pass
    else:
        print("[archive] upload FAILED", flush=True)
        if upload_err:
            print("[archive] error: {}".format(upload_err), flush=True)
        print("[archive] report kept locally: {}".format(final_path), flush=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(
        description="Pi-crunching CPU benchmark (Chudnovsky + binary splitting).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("--digits", type=int, default=100_000)
    p.add_argument("--mode", choices=["single", "multi", "both"], default="both")
    p.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    p.add_argument("--json", action="store_true")
    p.add_argument("--archive", action="store_true",
                   help="Linux only: capture turbostat + parse summary + upload combined report to NAS")
    p.add_argument("--smb-share", default=DEFAULT_SMB_SHARE)
    p.add_argument("--smb-user", default=DEFAULT_SMB_USER)
    p.add_argument("--smb-subdir", default=DEFAULT_SMB_SUBDIR)
    p.add_argument("--sftp-user", default=DEFAULT_SFTP_USER,
                   help="SFTP username for Windows archive upload")
    p.add_argument("--sftp-path", default=DEFAULT_SFTP_PATH,
                   help="SFTP base path on NAS for Windows archive upload")
    p.add_argument("--sftp-password", default=None,
                   help="SFTP password (Windows); overrides SFTP_PASSWORD env var. "
                        "Avoid on shared machines — visible in the process list. "
                        "Prefer seeding the OS keyring interactively instead.")
    args = p.parse_args()

    sys.setrecursionlimit(100_000)
    _raise_int_str_limit(args.digits)

    info = system_info()
    quiet = args.json

    archive_state = {"enabled": False}
    if args.archive:
        archive_state = archive_setup(args)

    # Tee stdout so the archive log gets the same text the user sees.
    captured = io.StringIO()
    real_stdout = sys.stdout
    if args.archive and not quiet:
        sys.stdout = _Tee(real_stdout, captured)

    try:
        if not quiet:
            print("=" * 64)
            print(" Pi compute benchmark - Chudnovsky + binary splitting")
            print("=" * 64)
            print(" platform:     {}".format(info["platform"]))
            print(" processor:    {}".format(info["processor"] or info["machine"]))
            print(" python:       {}".format(info["python"]))
            print(" logical CPUs: {}".format(info["logical_cpus"]))

        results = {"system": info, "config": vars(args), "runs": []}

        raw_turbo_path = archive_state.get("raw_path") if archive_state.get("enabled") else None
        fans = archive_state.get("fans") if archive_state.get("enabled") else None
        fan_samples = archive_state.get("fan_samples") if archive_state.get("enabled") else None
        lhm_sampler = archive_state.get("lhm_sampler") if archive_state.get("enabled") else None
        if args.mode in ("single", "both"):
            results["runs"].append(run_single(args.digits, quiet=quiet,
                                              raw_turbo_path=raw_turbo_path,
                                              fans=fans, fan_samples=fan_samples,
                                              lhm_sampler=lhm_sampler,
                                              progress_callback=None))
        if args.mode in ("multi", "both"):
            results["runs"].append(run_multi(args.digits, args.workers, quiet=quiet,
                                             raw_turbo_path=raw_turbo_path,
                                             fans=fans, fan_samples=fan_samples,
                                             lhm_sampler=lhm_sampler,
                                             progress_callback=None))

        if args.mode == "both":
            single = results["runs"][0]
            multi = results["runs"][1]
            ideal = single["throughput_digits_per_sec"] * multi["workers"]
            eff = (multi["aggregate_throughput_digits_per_sec"] / ideal) if ideal > 0 else 0.0
            results["parallel_efficiency"] = eff
            if not quiet:
                print("\n[ scaling ] parallel efficiency vs single-thread x {}: {:.1f}%".format(
                    multi["workers"], eff * 100))
                if eff < 0.5:
                    print("           (low efficiency = thermal throttling, memory bandwidth, or SMT contention)")

        if quiet:
            print(json.dumps(results, indent=2, default=str))
    finally:
        if args.archive and not quiet:
            sys.stdout = real_stdout
            archive_finalize(args, archive_state, captured.getvalue())


if __name__ == "__main__":
    mp.freeze_support()
    main()
