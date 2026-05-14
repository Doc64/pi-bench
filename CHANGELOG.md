# Changelog

All notable changes to Pi Bench are documented here.

Versioning:
- `X.0.0` — new feature
- `1.x.0` — bug fix
- `1.0.x` — cosmetic / theme change

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
