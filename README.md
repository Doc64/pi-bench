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

Download `PiBenchSetup.exe` from the [latest pipeline artifacts](../../-/pipelines) and run it.

The installer:
1. Downloads Python 3.12.8 embeddable runtime (~26 MB)
2. Installs PyQt6, gpt4all, and dependencies (~200 MB)
3. Creates Start Menu and optional Desktop shortcuts
4. Installs to `%LOCALAPPDATA%\Programs\Pi Bench\` — no admin required

The LLM model (~2.2 GB) downloads automatically the first time the AI Analysis tab is opened.

**Requirements:** Windows 10/11 x64. LibreHardwareMonitor must be running with its web server enabled (the app will prompt you on first launch if it isn't).

---

## Building the Installer

The GitLab CI/CD pipeline builds `PiBenchSetup.exe` automatically on every push to `main`.

To build manually on the workbench:

```
build_installer.bat
```

Or with Inno Setup directly:

```
"C:\Users\tom\AppData\Local\Programs\Inno Setup 7\ISCC.exe" pi_bench_setup.iss
```

Output: `dist\PiBenchSetup.exe`

**Build requirements:** [Inno Setup 7](https://jrsoftware.org/isdl.php) installed on the build machine.

---

## Running from Source

```bash
# Install dependencies
pip install PyQt6 pyqtgraph mpmath gpt4all

# Dev build (no LLM)
python pi_bench_gui_dev.py

# Dev build + AI analysis
python pi_bench_gui_dev_llm.py

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
pi_bench.py              Core benchmark engine, LHM integration, analysis functions
pi_bench_gui_dev.py      GUI — dev build (no LLM)
pi_bench_gui_dev_llm.py  GUI — dev build + AI analysis tab
pi_bench_gui.py          GUI — production build (stable)
pi_bench_setup.iss       Inno Setup 7 installer script
_setup_python.bat        Bootstrap: downloads Python runtime during install
install.py               Post-install: pip installs packages, sets up VC++ runtime
uninstall.py             Removes runtime artifacts on uninstall
.gitlab-ci.yml           CI/CD pipeline — builds installer on push to main
pi_bench_runs/           Saved run JSON files (created at runtime)
pi_bench_models/         LLM model storage (created at runtime)
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

## Notes

- The 5800X3D and other 3D V-Cache CPUs hard-limit to 90°C to protect the cache stack — sustained 90°C under full load is normal behaviour, not a cooling failure
- Thermal resistance is most accurate when the CPU starts from a true idle state before the benchmark
- The cool-down phase runs automatically after the benchmark and stops when the CPU returns within 5°C of the pre-run idle temperature (max 90 seconds)
- Clock CV < 5% = boost held steadily; 5–15% = moderate variation; > 15% = significant throttle cycling
