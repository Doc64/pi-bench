# Changelog

All notable changes to Pi Bench are documented here.

---

## [1.0.1] — 2026-05-14

### Added
- **Frutiger Aero theme** — a second GUI launcher (`Pi Bench Aero`) with a
  Windows Vista-inspired visual style: sky-blue gradients, frosted-glass
  panels with bright white specular highlights, chrome gel buttons, and
  translucent sidebar/tab backgrounds.
- Both themes are installed side-by-side. Users can choose from the Start
  Menu: **Pi Bench** (classic dark) or **Pi Bench Aero**.

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
