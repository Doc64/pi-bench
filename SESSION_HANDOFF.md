# pi_bench Session Handoff
_Last updated: 2026-05-08, end of session_

## Current state of `pi_bench_dev.py`
- 89,375 bytes
- Parses cleanly (verified with `ast.parse`)
- All Linux-side functionality preserved (regression-tested on Mac mini today; matches baseline within 0.7%)
- Windows side: code complete but **end-to-end test on workbench still pending**
- Last 4 bug fixes (from end of today's session, all sandbox-verified, NOT yet workbench-tested):
  1. `run_single` and `run_multi` now accept and pass `lhm_sampler`
  2. `main()` pulls `lhm_sampler` from `archive_state` and threads it through
  3. `archive_finalize` cleanup uses `state.get("raw_path")` (no UnboundLocalError on Windows)
  4. `_smb_to_unc` docstring switched to raw string (no SyntaxWarnings)

## Architecture summary

### Linux pipeline (verified working)
- `archive_setup` starts `turbostat` subprocess + `discover_fans()`
- `HeartbeatReporter` shows live readout from turbostat tail + fan RPM from sysfs
- `archive_finalize` reads turbostat output, parses, runs `analyze_cooling()` and `analyze_fans()`
- Uploads via `smbclient` subprocess

### Windows pipeline (sandbox-verified, needs live test)
- `archive_setup` calls `lhm_ensure_running()` (auto-installs LHM if missing) + starts `LHMSampler` thread
- `HeartbeatReporter` shows live readout via `_format_lhm_live(sampler)`
- `archive_finalize` calls `summarize_lhm_samples()` / `analyze_cooling_lhm()` / `analyze_fans_lhm()` — same output dict shape as the Linux analyzers, so `format_*` formatters work unchanged
- Uploads via `net use` + `os.makedirs` + `shutil.copyfile` over UNC paths

### Cosmetic touches
- Report header: "Thermal / Power summary (parsed from LibreHardwareMonitor)" on Windows, "(parsed from turbostat)" on Linux
- `detect_cpu_name()` uses Windows registry `ProcessorNameString` for friendly name on Win

## Pending work (in suggested order)

### 1. Full Windows workbench end-to-end test
Drop the current `pi_bench_dev.py` on the workbench (Intel Core i5-4590S, Win10), run:
```
cd /d %USERPROFILE%\Desktop
set SMB_PASSWORD=040102
python pi_bench_dev.py --digits 5000000 --mode multi --workers 4 --archive
```
Pass criteria:
- No SyntaxWarnings
- Heartbeat shows `XX% busy @ XXXX MHz, XXC, XX.XXW` (the LHM live readout)
- Reference + cross-worker checks OK
- archive_finalize logs "LHM sampler stopped: NN samples"
- Upload OK (no traceback)
- Report on NAS at `\\192.168.200.36\Common-Room\Scripts\Benchmarks\Intel Core i5-4590S CPU @ 3.00GHz\<filename>.log`
- All 3 report sections present (Thermal/Power, Cooler analysis, Fan analysis)

### 2. CLI simplification
Goal: `python pi_bench.py` with NO args should "just run the real benchmark and upload it." Required changes:
- Default `--digits` to `5_000_000` (currently `100_000`)
- Default `--mode` to `multi` (currently `both`)
- Default `--archive` to `True`; add `--no-archive` flag (use `BooleanOptionalAction` or pair `--archive` / `--no-archive`)
- Update the `--archive` help text to remove "Linux only" (it works on both now)
- For SMB password: cache it in `~/.pi_bench_smb_pw` (chmod 600 on Linux, restricted ACL on Windows) on first prompt, read it back on subsequent runs. Env var `SMB_PASSWORD` still wins if set.

### 3. Promote `pi_bench_dev.py` → `pi_bench.py`
Once #1 passes:
- `cp pi_bench_dev.py pi_bench.py` in outputs
- Push to NAS at `//192.168.200.36/Common-Room/Scripts/pi_bench.py` (overwriting gold)
- Optionally archive the old gold first

### 4. Fresh-machine validation on work laptop
The work laptop has never been touched. Drop the new gold there, run with no setup, verify the full "drop, run, done" experience including:
- LHM auto-install (LHM not present yet on this machine)
- PawnIO driver prompt (one-time UAC click)
- LHM web server starts
- Sample collection works
- Upload to NAS works
- Report generated with correct CPU subfolder

## Machine inventory

| Machine | OS | Role | Network | SSH server | Notes |
|---|---|---|---|---|---|
| Workstation (this laptop) | Win10/11 | Where Cowork/Claude Code runs | LAN + VPN | n/a (host) | Has the workspace folder |
| Mac mini | Ubuntu 24.04 | Linux benchmark target #1 | 192.168.200.x | OpenSSH ✓ | mbpfan running, hostname `tom-Macmini6-2` |
| Testbench | Ubuntu | Linux benchmark target #2 | 192.168.200.x | OpenSSH ✓ | **Currently wedged** from nct6775 experiment — needs physical reboot |
| Workbench | Win10 | Windows benchmark target #1 | 192.168.200.x | TBD — see SSH setup | Has LHM installed from prior testing, hostname appears as `tom-PC` or similar |
| Gaming PC | Win11 | Windows benchmark target #2 | 192.168.200.x | TBD | Untouched by testing |
| Work laptop | Windows | Fresh-machine validation target | varies | TBD | Untouched by testing |
| NAS | varies | File storage / log archive | 192.168.200.36 | n/a | SMB only |

Tom's home LAN is 192.168.200.x. There's also a 10.8.0.x VPN (WireGuard or similar), where the workstation appears as 10.8.0.2 from the Mac mini's perspective.

## What was painful this session

1. **File transfer was manual** — Tom had to drag pi_bench_dev.py through two file explorer windows for every change. Slow round-trip. SSH would let next session edit + scp + run in one shot.
2. **Sandbox isolation** — Cowork's bash sandbox can't reach Tom's LAN, so we couldn't directly test net use / UNC uploads. Claude Code with local shell could.
3. **Edit tool truncating files** — multiple times Edit silently corrupted the tail of `pi_bench_dev.py`. Workaround was bash + python heredoc. For next session, keep `pi_bench.py.bak` (gold) handy in case the dev file gets clobbered again. **Always run `python -c "import ast; ast.parse(open('pi_bench_dev.py').read())"` after every edit.**

## Backup files in outputs (safe to delete after promotion)
- `pi_bench_dev.py.bak.truncated` — corrupted state from first Edit truncation
- `pi_bench_dev.py.bak.pre8e` — pre-LHM-analyzers
- `pi_bench_dev.py.bak.pre_finalize` — pre-archive_finalize-branching
- `pi_bench_dev.py.bak.pre_smbwin` — pre-Windows-SMB-helpers
- `pi_bench_dev.py.bak.fix1` — pre-final-bugfixes
