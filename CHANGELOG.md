# Changelog

All notable changes to Pi Bench are documented here.

Versioning:
- `X.0.0` — new feature
- `1.x.0` — bug fix
- `1.0.x` — cosmetic / theme change

---

## [2.2.1] — 2026-05-14

### Fixed
- **GNOME keyring unlock dialog on RDP/headless Linux** — on RDP sessions
  the GNOME login keyring is not auto-unlocked.  Any query to the keyring
  daemon — even checking whether a key exists — causes the daemon to show an
  "Authentication required" dialog independently of the app.  The Settings
  panel was querying the keyring on startup and before every run to check for
  stored NAS credentials.  Both GUI files now skip all keyring access on Linux;
  NAS credentials are picked up in `archive_setup` only when an upload is
  actually attempted (and the user has set a password in the Settings field).
  `archive_setup` was also fixed to skip its own keyring lookup when
  `args.archive` is False.

---

## [2.2.0] — 2026-05-14

### Added
- **Linux auto-update via setup.sh** — the update checker now returns the
  `setup.sh` release asset on Linux instead of the Windows `.exe`.  Clicking
  "Download & Install" downloads `setup.sh`, marks it executable, and runs it
  detached so it updates `~/.local/share/pi-bench/` in the background while
  Pi Bench closes.  The next launch uses the new version automatically.

### Fixed
- **"Permission denied" crash on Linux update** — the previous flow
  downloaded `PiBenchSetup-X.Y.Z.exe` and tried to execute it directly on
  Linux, which the kernel rejects with `[Errno 13] Permission denied`.

---

## [2.1.0] — 2026-05-14

### Added
- **sudo prompt for sensor capture (Linux)** — when the `sudo` credential
  cache is empty, Pi Bench now shows a dialog explaining that `turbostat`
  requires a one-time `sudo` authorisation to read CPU temperatures, clocks,
  and power.  The dialog makes clear that the password is passed directly to
  `sudo` and never stored or logged by Pi Bench, and that the `sudo` cache
  expires automatically (5–15 min via `/etc/sudoers`).  A **Skip** button
  lets users run the benchmark without sensor capture.  If the cache is already
  warm the dialog never appears.

### Fixed
- **Benchmark skipped when NAS archive is off (Linux)** — `turbostat` was
  only started when the "Archive to NAS" checkbox was enabled.  With no NAS
  password the checkbox silently resolved to off, leaving the live chart
  empty and no report saved.  Sensor capture and local report saving now run
  on Linux regardless of the NAS archive setting; NAS upload remains optional.

---

## [2.0.1] — 2026-05-14

### Fixed
- **Update checker never triggered** — `_UPDATE_GITHUB_REPO` was blank `""`;
  set to `"Doc64/pi-bench"` so the GitHub Releases API is polled correctly.
- **Keyring D-Bus hang** — `_keyring_get` / `_keyring_set` now run in a
  daemon thread with a 3-second timeout, preventing indefinite blocks when
  Secret Service / D-Bus is unavailable in headless SSH sessions on Linux.
- **setup.sh stale file references** — launcher and desktop entries pointed
  to removed filenames (`pi_bench_gui_dev_llm.py`, `pi_bench_gui.py`);
  corrected to `pi_bench_gui_dev.py` and `pi_bench_gui_aero.py`.
- **install.py launcher names** — `run_llm.bat` / `run_llm.sh` renamed to
  `run.bat` / `run_aero.bat` and `run.sh` / `run_aero.sh` to match actual
  output filenames.
- **setup.sh self-bootstrapping** — running `setup.sh` standalone (without
  cloning the repo) now downloads all required source files from the GitHub
  Release assets automatically.
- **README `--digits` documentation** — clarified that `--digits` is a
  literal digit count, not a count in millions.

### Changed
- `release.yml` now injects the real version string into `setup.sh` at
  build time and uploads Linux source assets (`setup.sh`, `pi_bench.py`,
  both GUI files, `install.py`, `uninstall.py`) alongside the Windows
  installer.

---

## [2.0.0] — 2026-05-14

### Added
- **On-device AI analysis** — a new "AI Analysis" tab in the Results view
  streams a real-time diagnostic report from **Phi-3.5 Mini Instruct Q4_K_M**
  (~2.2 GB, runs 100 % locally, CPU-only via gpt4all).  The model is
  downloaded automatically on first launch and verified with SHA-256.
  It analyses every captured metric — throughput, parallel efficiency, clock
  boost sustainability, thermal resistance, throttle events, cool-down rate —
  and returns five paragraphs of actionable feedback.
- **In-app theme switcher** — Settings → Theme → "Classic (dark)" or
  "Frutiger Aero" → **Apply & Restart**.  Both themes now carry identical
  feature sets (LLM included).  The separate "Pi Bench Aero" Start Menu
  shortcut is removed; theme choice lives inside the app.

### Changed
- Single "Pi Bench" Start Menu / desktop shortcut.  Users switch themes from
  within the app; no re-install required.
- Startup splash lists two additional checks: `gpt4all` and `LLM model`.
  On first launch the model auto-downloads (~2.2 GB) in the background.

---

## [1.0.1] — 2026-05-14

### Added
- **Frutiger Aero theme** — a second GUI launcher (`Pi Bench Aero`) with a
  Windows Vista-inspired visual style: sky-blue gradients, frosted-glass
  panels with bright white specular highlights, chrome gel buttons, and
  translucent sidebar/tab backgrounds.
- Both themes are installed side-by-side. Users can choose from the Start
  Menu: **Pi Bench** (classic dark) or **Pi Bench Aero**.

### Fixed
- **Update system deadlock** — clicking "Download & Install" froze the app
  and the new version never launched. Two root causes:
  1. `/CLOSEAPPLICATIONS` flag told Inno Setup to kill the running app, but
     the app was blocked waiting for the installer — mutual deadlock.
  2. `QApplication.quit()` was called from a background thread, which is not
     thread-safe in Qt and was silently ignored.
  Fixed by removing `/CLOSEAPPLICATIONS` (the app now closes itself) and
  scheduling the quit via `QTimer.singleShot(0, QApplication.quit)` so it
  runs safely on the main thread.

---

## [1.0.0] — 2026-05-12

### Added
- **Settings tab** — benchmark settings moved from the left sidebar into a
  dedicated scrollable Settings tab. Sidebar is now slim (system info +
  config summary + run button).
- **In-app update notifications** — Pi Bench checks GitHub Releases on
  launch and shows a download-and-install banner when a newer version is
  available. Updates install silently and restart the app automatically.
- **Versioned installer** — `APP_VERSION` in `pi_bench.py` is the single
  source of truth. `build_installer.bat` injects it into Inno Setup at
  build time; the output is `PiBenchSetup-<version>.exe`.
- **GitHub Actions release workflow** — pushing a `vX.Y.Z` tag
  automatically builds the installer on a `windows-latest` runner and
  publishes it as a GitHub Release with the `.exe` attached.
- **GitLab CI pipeline** — smoke-build on every push to `main`; full
  build + GitLab Release on every `vX.Y.Z` tag.
- Live benchmark charts (single-thread, multi-thread, cool-down phases).
- Persistent run history saved as JSON; Results, Reports, Compare, and
  History tabs.
- Startup dependency checker with auto-install splash screen.
