# Pi Bench

A CPU compute benchmark that measures single-thread and multi-thread performance by computing Pi to a configurable number of digits, while simultaneously capturing live sensor data via LibreHardwareMonitor on Windows and turbostat on Linux.

Designed for three use cases:
- **CPU performance comparison** — compare throughput across different machines or configurations
- **CPU health validation** — verify computation correctness with SHA-256 cross-checks and detect thermal/power throttling
- **Cooler efficiency comparison** — thermal resistance (°C/W), cool-down rate, and throttle detection give an objective picture of how well a cooler handles sustained load

---

## Features

### Benchmark Engine
- Pi computed via the Chudnovsky algorithm (arbitrary precision, `mpmath`)
- Single-thread and multi-thread modes (configurable worker count)
- SHA-256 hash of output for correctness verification
- Cross-worker consistency check in multi mode

### Live Sensor Data (Windows via LibreHardwareMonitor, Linux via turbostat)
- Per-core clock speeds and temperatures charted in real time
- Package power and CPU load
- Fan RPM for all detected fans
- Supports Intel and AMD CPUs (Ryzen, including 3D V-Cache variants)

### Live Charts
- **Single Thread** and **Multi Thread** tabs — separate charts per phase so they don't overwrite each other
- **Cool-down** tab — automatically starts after the benchmark ends, plots temp/power/clock decay back to idle
- Per-core colour-coded lines using a golden-ratio hue sequence (scales cleanly from 1 to 128+ cores)
- Shared legend strip showing LHM sensor names for each core

### Analysis
- Thermal resistance (°C/W) — both CPU-baseline-referenced and ambient-referenced
- Clock consistency (coefficient of variation) — low CV = held boost steadily, high CV = throttle cycling
- Cool-down rate (°C/min) — direct cooler efficiency metric
- F-state and T-state throttle detection
- Throttle headroom below TjMax
- Fan analysis (min/avg/peak RPM for every detected fan)
- Automated recommendations (throttling, thermal resistance, temp headroom)

### AI Analysis Tab
- On-device LLM analysis using Phi-3.5 Mini Instruct (Q4_K_M, ~2.2 GB) via gpt4all
- Evaluates all metrics: performance, clock behaviour, power, thermals, cool-down
- Runs 100% locally — no data sent to any server
- Model downloads automatically on first launch of the AI tab

### History & Comparison
- Every run saved as JSON in `pi_bench_runs/`
- **History tab** — sortable table of all past runs (date, CPU, throughput, peak temp, Rth, clock CV, cool-down)
- **Compare tab** — side-by-side metric diff between any two saved runs with delta colouring
- **Reports tab** — full text report for any saved run
- Results archived to NAS via SFTP after each run (optional, configurable)

---

## Installation (End Users)

Download `PiBenchSetup-<version>.exe` from the
[**GitHub Releases page**](https://github.com/Doc64/pi-bench/releases/latest) and run it.

The installer:
1. Downloads Python 3.12.8 embeddable runtime (~26 MB)
2. Installs PyQt6, gpt4all, and dependencies (~200 MB)
3. Creates a single **Pi Bench** Start Menu shortcut and optional Desktop shortcut
4. Installs to `%LOCALAPPDATA%\Programs\Pi Bench\` — no admin required

The LLM model (~2.2 GB) downloads automatically on first launch (shown in the startup splash).

**Requirements:** Windows 10/11 x64. LibreHardwareMonitor must be running with its web server enabled
(the app will prompt you on first launch if it isn't).

### Automatic Updates

Pi Bench checks GitHub Releases 4 seconds after launch. If a newer version is available a banner
appears at the top of the window — click **Download & Install** and the new installer downloads,
runs silently, and relaunches the app automatically.

> **Note:** Automatic updates require v2.0.0 or later. If you have an older version installed,
> download v2.0.0 manually from the releases page once — all future updates will be automatic.

---

## Themes

Both visual styles are included in every install. Switch between them inside the app:
**Settings tab → Theme → select style → Apply & Restart**.

| Theme | Style |
|---|---|
| **Classic (dark)** | Deep navy/midnight blue with high-contrast Catppuccin-style accents |
| **Frutiger Aero** | Sky-blue gradient, frosted-glass panels, chrome gel buttons — Vista / mid-2000s aesthetic |

The selected theme relaunches the app with the matching script. Both themes have identical features
including AI analysis.

---

## Building the Installer

### Automated (recommended)

Push a version tag — GitHub Actions builds the installer and publishes a GitHub Release automatically:

```
# 1. Bump APP_VERSION in pi_bench.py
# 2. Add an entry to CHANGELOG.md
git add pi_bench.py CHANGELOG.md
git commit -m "bump version to x.y.z"
git tag vx.y.z
git push origin HEAD:main
git push github master:main
git push origin vx.y.z
git push github vx.y.z
```

The release body is populated automatically from the matching `## [x.y.z]` section in `CHANGELOG.md`.

### Manual (local)

Requires [Inno Setup 7](https://jrsoftware.org/isdl.php) installed.

```
build_installer.bat
```

Output: `dist\PiBenchSetup-<version>.exe`

---

## Running from Source

```bash
# Install dependencies
pip install PyQt6 pyqtgraph mpmath gpt4all

# Classic dark theme (includes AI analysis + theme switcher)
python pi_bench_gui_dev.py

# Frutiger Aero theme (includes AI analysis + theme switcher)
python pi_bench_gui_aero.py

# Command line only
python pi_bench.py --digits 5 --mode both --workers 16
```

### Command Line Options

| Flag | Default | Description |
|------|---------|-------------|
| `--digits N` | 5 | Digits of Pi to compute, in millions |
| `--mode` | both | `single`, `multi`, or `both` |
| `--workers N` | logical CPU count | Worker processes for multi-thread run |
| `--archive` | off | Upload report to NAS after run |
| `--json` | off | Print JSON summary to stdout |

---

## File Structure

```
pi_bench.py                   Core benchmark engine, sensor integration, analysis, update checker
pi_bench_gui_dev.py           GUI — Classic dark theme (AI analysis + theme switcher)
pi_bench_gui_aero.py          GUI — Frutiger Aero theme (AI analysis + theme switcher)
pi_bench_gui.py               GUI — minimal production build (stable, no extra tabs)
pi_bench_setup.iss            Inno Setup 7 installer script
build_installer.bat           Local build helper (wraps ISCC with version injection)
_setup_python.bat             Bootstrap: downloads Python runtime during install
install.py                    Post-install: pip installs packages, sets up VC++ runtime
uninstall.py                  Removes runtime artifacts on uninstall
CHANGELOG.md                  Version history
.github/workflows/release.yml GitHub Actions — builds + publishes release on vX.Y.Z tag
.gitlab-ci.yml                GitLab CI — builds installer on push to main, release on tag
pi_bench_runs/                Saved run JSON files (created at runtime)
pi_bench_models/              LLM model storage (created at runtime)
```

---

## Sensor Support

| Sensor | Intel | AMD |
|--------|-------|-----|
| Package power | `CPU Package` | `Package` |
| Package temp | `CPU Package` | `Core (Tctl/Tdie)` |
| Per-core clocks | `CPU Core #N` | `Core #N` |
| Per-core temps | `CPU Core #N` | CCD temps (fallback) |
| CPU load | `CPU Total` | `CPU Total` |
| Fan speeds | all detected fans | all detected fans |

---

## Privacy & Network Activity

Pi Bench makes **no background connections** and has **no telemetry or analytics** of any kind.

Network activity only happens in these specific, user-visible moments:

| When | What | Where |
|------|------|--------|
| Every launch (v2.0.0+) | Checks for newer release tag; no data sent, read-only | `api.github.com/repos/Doc64/pi-bench` |
| First run (Windows, archive mode) | Downloads LibreHardwareMonitor portable zip | `github.com/LibreHardwareMonitor` |
| During install | Downloads Python 3.12.8 embeddable runtime | `python.org` |
| During install | Installs Python packages via pip | `pypi.org` |
| During install (if needed) | Downloads VC++ 2022 runtime | `aka.ms` (Microsoft) |
| First launch | Downloads Phi-3.5 Mini model (~2.2 GB); SHA-256 verified before use | `huggingface.co/bartowski` |
| "Download & Install" clicked | Downloads the new installer `.exe` | `github.com/Doc64/pi-bench` (release asset) |
| Archive mode (optional, off by default) | Uploads benchmark report to your NAS | Your NAS (user-configured) |

**Sensor data stays on your machine.** LibreHardwareMonitor's JSON endpoint is bound to `localhost` only — not reachable from other machines on your network.

**Credentials are stored in the OS keyring** (Windows Credential Locker on Windows, Secret Service on Linux — both DPAPI-encrypted at rest). The app explicitly rejects plain-text fallback keyring backends. Credentials are removed from the keyring when you uninstall.

**The AI analysis runs 100% locally.** The LLM model is loaded directly from disk; no data is sent to any server. The model cannot make network calls (`allow_download=False`).

**NAS uploads use SSH/SFTP** with Trust-On-First-Use host key verification. The first upload to a NAS saves its SSH host key to `~/.ssh/known_hosts`; subsequent uploads verify against that key. A changed key (possible network tampering) aborts the upload with a clear error message.

**Uninstalling removes everything the app created:** the embedded Python runtime, installed packages, downloaded LLM model, benchmark run history, managed LibreHardwareMonitor copy, and the keyring entry. Nothing is left behind.

---

## Notes

- The 5800X3D and other 3D V-Cache CPUs hard-limit to 90°C to protect the cache stack — sustained 90°C under full load is normal behaviour, not a cooling failure
- Thermal resistance is most accurate when the CPU starts from a true idle state before the benchmark
- The cool-down phase runs automatically after the benchmark and stops when the CPU returns within 5°C of the pre-run idle temperature (max 90 seconds)
- Clock CV < 5% = boost held steadily; 5–15% = moderate variation; > 15% = significant throttle cycling
