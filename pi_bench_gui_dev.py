"""
pi_bench_gui_dev.py — Dev build of Pi Bench (no LLM).

Features vs production:
  • Splash / startup dependency checker with auto-install
  • Persistent run history saved as JSON next to the script
  • Results tab  — always accessible after a run (Summary + Full Report)
  • Reports tab  — browse + view any saved run
  • Compare tab  — side-by-side diff of two historical runs

Three-copy strategy:
  pi_bench_gui.py          production  (stable)
  pi_bench_gui_dev.py      this file   (dev, no LLM)
  pi_bench_gui_dev_llm.py  dev + LLM
"""

import argparse, atexit, datetime, importlib, io, json
import multiprocessing as mp, os, platform, signal, subprocess, sys, tempfile

from PyQt6.QtCore  import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui   import QColor, QFont, QPalette
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFrame, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QProgressBar, QPushButton, QScrollArea, QSpinBox,
    QSplitter, QStackedWidget, QTabWidget, QTableWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)
import pyqtgraph as pg

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pi_bench as pb

# ── Frutiger Aero palette ───────────────────────────────────────────────────
# Sky-blue backgrounds, white frosted-glass panels, bright aqua accents,
# chrome gloss buttons.  Think Windows Vista Aero / Zune / mid-2000s
# "clean tech + nature" aesthetic.
DARK_BG   = "#0B2850"   # rich midnight-sky blue — main window bg
PANEL_BG  = "#071A34"   # deeper navy — chart / log areas
ACCENT    = "#00DDFF"   # vivid sky-aqua
TEXT      = "#FFFFFF"   # pure white (on dark) / deep navy on glass
SUBTLE    = "#5A90CC"   # cornflower blue — secondary text
COL_TEMP  = "#FF7040"   # warm orange — temperature
COL_POWER = "#C060FF"   # violet — power
COL_FREQ  = "#00FFEE"   # bright teal-cyan — frequency
COL_BUSY  = "#60FF90"   # lime green — CPU load
COL_GOOD  = "#40EE80"   # green confirmation
COL_WARN  = "#FFDD44"   # amber warning
COL_CRIT  = "#FF4455"   # soft red critical

# Glass helpers — WHITE-tinted borders/fills are what make it feel like
# actual frosted glass rather than just another dark theme.
# _GLASS_HI must be high-alpha white for the classic Frutiger Aero "ice cap"
# specular — the top quarter of every panel should look like frosted glass
# catching direct light.
_GLASS_BORDER = "rgba(255,255,255,140)"  # bright white glass border
_GLASS_FILL   = "rgba(255,255,255,10)"   # nearly transparent — sky shows through
_GLASS_HI     = "rgba(255,255,255,215)"  # very bright white top gloss (was 60)

RUNS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pi_bench_runs")


# ═══════════════════════════════════════════════════════════════════════════
#  PROCESS CLEANUP — runs on exit, crash, or close
# ═══════════════════════════════════════════════════════════════════════════

def _kill_workers() -> None:
    """Kill every multiprocessing worker spawned by ProcessPoolExecutor.

    ProcessPoolExecutor creates workers via multiprocessing.Process, so
    they register in mp.active_children().  Calling p.kill() sends
    SIGKILL (Unix) / TerminateProcess (Windows) — no dangling CPU usage.
    """
    for p in mp.active_children():
        try:
            p.kill()
        except Exception:
            pass


def _signal_handler(signum, frame):
    _kill_workers()
    sys.exit(0)


# Register cleanup for normal exit, SIGTERM, and SIGINT (Ctrl-C)
atexit.register(_kill_workers)
for _sig in (signal.SIGTERM, signal.SIGINT):
    try:
        signal.signal(_sig, _signal_handler)
    except (OSError, ValueError):
        pass   # not all signals are available on every platform


def _apply_dark_palette(app: QApplication):
    """Apply the Frutiger Aero palette + comprehensive global stylesheet."""
    app.setStyle("Fusion")
    pal = QPalette()
    for role, hex_col in [
        (QPalette.ColorRole.Window,          DARK_BG),
        (QPalette.ColorRole.WindowText,      TEXT),
        (QPalette.ColorRole.Base,            PANEL_BG),
        (QPalette.ColorRole.AlternateBase,   DARK_BG),
        (QPalette.ColorRole.ToolTipBase,     PANEL_BG),
        (QPalette.ColorRole.ToolTipText,     TEXT),
        (QPalette.ColorRole.Text,            TEXT),
        (QPalette.ColorRole.Button,          PANEL_BG),
        (QPalette.ColorRole.ButtonText,      TEXT),
        (QPalette.ColorRole.BrightText,      "#ffffff"),
        (QPalette.ColorRole.Highlight,       ACCENT),
        (QPalette.ColorRole.HighlightedText, "#001428"),
    ]:
        pal.setColor(role, QColor(hex_col))
    app.setPalette(pal)

    # ── Global Frutiger Aero stylesheet ──────────────────────────────────────
    # Key principles:
    #  • WHITE glass borders (not blue) — makes panels look like frosted glass
    #  • Prominent white top-half on buttons (chrome gloss)
    #  • Sky-blue gradients, not flat dark fills
    #  • Pure white text for maximum contrast on the deep-blue bg
    app.setStyleSheet(f"""

/* ── Base ── */
QWidget {{
    font-family: "Segoe UI", "Trebuchet MS", Arial, sans-serif;
    font-size: 9pt;
    color: {TEXT};
}}

/* ── Main window background: sky-blue gradient top→bottom ── */
QMainWindow, QDialog {{
    background: qlineargradient(x1:0,y1:0,x2:0.2,y2:1,
        stop:0 #2060A8, stop:0.35 #0E3870, stop:0.7 {DARK_BG}, stop:1 #061020);
}}

/* ── Frosted glass group boxes ── */
QGroupBox {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0    {_GLASS_HI},
        stop:0.18 rgba(255,255,255,80),
        stop:0.35 {_GLASS_FILL},
        stop:1    rgba(10,50,130,25));
    border: 1px solid {_GLASS_BORDER};
    border-radius: 10px;
    margin-top: 12px;
    padding-top: 10px;
    font-weight: bold;
    font-size: 8pt;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 5px;
    color: {ACCENT};
    font-size: 8pt;
}}

/* ── Input fields — inset glass ── */
QLineEdit, QSpinBox, QComboBox {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 rgba(0,10,30,180), stop:1 rgba(0,20,60,160));
    border: 1px solid {_GLASS_BORDER};
    border-radius: 6px;
    padding: 3px 8px;
    color: {TEXT};
    selection-background-color: {ACCENT};
    selection-color: #001030;
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border: 1px solid {ACCENT};
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 rgba(0,20,60,200), stop:1 rgba(0,40,100,200));
}}
QTextEdit {{
    background: rgba(4,12,28,210);
    border: 1px solid {_GLASS_BORDER};
    border-radius: 8px;
    padding: 4px;
    color: {TEXT};
    selection-background-color: {ACCENT};
    selection-color: #001030;
}}
QSpinBox::up-button, QSpinBox::down-button {{
    background: rgba(255,255,255,30);
    border: 1px solid {_GLASS_BORDER};
    border-radius: 3px;
    width: 16px;
}}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
    background: rgba(0,200,255,80);
}}
QComboBox::drop-down {{
    border: none;
    width: 20px;
}}
QComboBox QAbstractItemView {{
    background: #0B2850;
    border: 1px solid {_GLASS_BORDER};
    selection-background-color: rgba(0,220,255,60);
    color: {TEXT};
    outline: none;
}}

/* ── Generic buttons: chrome gloss (white top half, blue bottom) ── */
QPushButton {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0   rgba(255,255,255,80),
        stop:0.45 rgba(255,255,255,30),
        stop:0.5  rgba(0,100,200,60),
        stop:1    rgba(0,60,140,100));
    border: 1px solid {_GLASS_BORDER};
    border-radius: 7px;
    padding: 4px 14px;
    color: {TEXT};
    font-weight: 500;
}}
QPushButton:hover {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0   rgba(255,255,255,120),
        stop:0.45 rgba(255,255,255,60),
        stop:0.5  rgba(0,180,255,80),
        stop:1    rgba(0,100,200,120));
    border: 1px solid rgba(255,255,255,180);
    color: #ffffff;
}}
QPushButton:pressed {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 rgba(0,100,200,120), stop:1 rgba(0,50,120,180));
    border: 1px solid {ACCENT};
}}
QPushButton:disabled {{
    background: rgba(20,50,90,0.5);
    color: {SUBTLE};
    border-color: rgba(255,255,255,30);
}}

/* ── Checkboxes ── */
QCheckBox {{
    color: {TEXT};
    spacing: 7px;
}}
QCheckBox::indicator {{
    width: 14px; height: 14px;
    border: 1px solid {_GLASS_BORDER};
    border-radius: 4px;
    background: rgba(0,10,40,0.8);
}}
QCheckBox::indicator:checked {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 rgba(100,240,255,240), stop:1 rgba(0,160,220,240));
    border-color: {ACCENT};
}}

/* ── Scrollbars — slim glass ── */
QScrollBar:vertical {{
    background: rgba(255,255,255,12);
    width: 7px; border-radius: 3px; margin: 0;
    border: 1px solid rgba(255,255,255,20);
}}
QScrollBar::handle:vertical {{
    background: rgba(255,255,255,70);
    border-radius: 3px; min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: {ACCENT};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: rgba(255,255,255,12);
    height: 7px; border-radius: 3px; margin: 0;
    border: 1px solid rgba(255,255,255,20);
}}
QScrollBar::handle:horizontal {{
    background: rgba(255,255,255,70);
    border-radius: 3px; min-width: 24px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {ACCENT};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

/* ── Glass transparency for labels/checkboxes inside panels ── */
/* Without this every QLabel inside a GroupBox paints an opaque slab   */
/* that covers the sky-gradient showing through the glass fill.        */
QGroupBox QLabel, QGroupBox QCheckBox, QGroupBox QFrame {{
    background: transparent;
}}

/* ── Tab widget ── */
QTabWidget::pane {{
    border: 1px solid {_GLASS_BORDER};
    border-radius: 0 8px 8px 8px;
    background: rgba(8,25,72,160);
}}
QTabBar::tab {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 rgba(255,255,255,50),
        stop:0.5 rgba(255,255,255,18),
        stop:1 rgba(0,40,100,60));
    color: rgba(255,255,255,140);
    padding: 7px 20px;
    border: 1px solid {_GLASS_BORDER};
    border-bottom: none;
    border-radius: 8px 8px 0 0;
    margin-right: 2px;
    font-size: 9pt;
}}
QTabBar::tab:selected {{
    color: {TEXT};
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 rgba(255,255,255,90),
        stop:0.5 rgba(255,255,255,35),
        stop:1 rgba(0,100,200,80));
    border-bottom: 2px solid {ACCENT};
}}
QTabBar::tab:hover:!selected {{
    color: {ACCENT};
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 rgba(255,255,255,70),
        stop:0.5 rgba(255,255,255,30),
        stop:1 rgba(0,80,180,70));
}}

/* ── Tables ── */
QTableWidget {{
    background: rgba(4,12,28,210);
    border: 1px solid {_GLASS_BORDER};
    border-radius: 8px;
    gridline-color: rgba(255,255,255,18);
    color: {TEXT};
    outline: none;
}}
QTableWidget::item:selected {{
    background: rgba(0,220,255,55);
    color: #ffffff;
}}
QHeaderView::section {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 rgba(255,255,255,55), stop:1 rgba(0,80,180,80));
    border: 1px solid {_GLASS_BORDER};
    padding: 5px 8px;
    color: {ACCENT};
    font-weight: bold;
    font-size: 8pt;
}}

/* ── Lists ── */
QListWidget {{
    background: rgba(4,12,28,210);
    border: 1px solid {_GLASS_BORDER};
    border-radius: 8px;
    color: {TEXT};
    outline: none;
}}
QListWidget::item:selected {{
    background: rgba(0,220,255,55);
    color: #ffffff;
}}
QListWidget::item:hover {{
    background: rgba(255,255,255,18);
}}

/* ── Splitter ── */
QSplitter::handle {{
    background: rgba(255,255,255,30);
}}

/* ── Separators ── */
QFrame[frameShape="4"], QFrame[frameShape="5"] {{
    color: rgba(255,255,255,50);
}}
""")


# ═══════════════════════════════════════════════════════════════════════════
#  STARTUP CHECKER + SPLASH
# ═══════════════════════════════════════════════════════════════════════════

class StartupChecker(QThread):
    check_update = pyqtSignal(str, str, str)   # name, status, detail
    all_done     = pyqtSignal(bool)

    _CHECKS = [("pyqtgraph", True), ("keyring", False),
               ("paramiko", False), ("LHM", False)]

    def run(self):
        failed = False
        for name, critical in self._CHECKS:
            if name == "LHM":
                self._check_lhm()
            else:
                ok = self._check_pkg(name, critical)
                if not ok and critical:
                    failed = True
        self.all_done.emit(not failed)

    def _check_pkg(self, pkg, critical):
        """Verify the package is importable.  No auto-install — setup.bat/sh handles that.
        If missing, directs the user to re-run setup.bat or setup.sh."""
        self.check_update.emit(pkg, "checking", "")
        mod_name = pkg.replace("-", "_").split("[")[0]
        try:
            mod = importlib.import_module(mod_name)
            self.check_update.emit(pkg, "ok", f"v{getattr(mod,'__version__','?')}")
            return True
        except Exception:
            hint = ("run setup.bat to reinstall"
                    if platform.system() == "Windows" else "run setup.sh to reinstall")
            self.check_update.emit(pkg, "error" if critical else "warn", hint)
            return False

    def _check_lhm(self):
        if platform.system() != "Windows":
            self.check_update.emit("LHM", "ok", "N/A (Linux)")
            return
        self.check_update.emit("LHM", "checking", "pinging localhost:8085…")
        try:
            if pb.lhm_check_reachable():
                self.check_update.emit("LHM", "ok", "already running")
                return
            self.check_update.emit("LHM", "installing", "launching…")
            self.check_update.emit("LHM", "ok" if pb.lhm_ensure_running() else "warn",
                "started" if pb.lhm_check_reachable() else
                "could not start — install LHM + enable web server")
        except Exception as exc:
            self.check_update.emit("LHM", "warn", str(exc)[:80])


class _CheckRow(QWidget):
    _ICONS  = {"checking":"⋯","ok":"✓","warn":"⚠","installing":"↓","error":"✗"}
    _COLORS = {"checking":SUBTLE,"ok":COL_GOOD,"warn":COL_WARN,
               "installing":COL_FREQ,"error":COL_CRIT}

    def __init__(self, name):
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 1, 0, 1)
        self._icon   = QLabel("⋯"); self._icon.setFixedWidth(18)
        self._icon.setFont(QFont("Consolas", 11))
        self._name   = QLabel(name); self._name.setFixedWidth(90)
        self._name.setStyleSheet(f"color:{TEXT};font-size:10pt;")
        self._detail = QLabel(""); self._detail.setStyleSheet(
            f"color:{SUBTLE};font-size:9pt;")
        for w in (self._icon, self._name, self._detail):
            row.addWidget(w)
        row.addStretch()
        self.update_status("checking", "")

    def update_status(self, status, detail):
        c = self._COLORS.get(status, TEXT)
        self._icon.setText(self._ICONS.get(status, "?"))
        self._icon.setStyleSheet(
            f"color:{c};font-size:11pt;font-weight:bold;")
        self._detail.setText(detail)


class SplashScreen(QWidget):
    launch_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Pi Bench")
        self.setFixedSize(460, 380)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setStyleSheet(f"background:{DARK_BG};border:1px solid {SUBTLE};")
        self._rows: dict[str, _CheckRow] = {}
        self._done = 0
        self._build_ui()
        checker = StartupChecker(self)
        checker.check_update.connect(self._on_update)
        checker.all_done.connect(self._on_done)
        checker.start()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 24)
        root.setSpacing(12)

        t = QLabel("Pi Bench")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t.setStyleSheet(f"color:{ACCENT};font-size:28pt;font-weight:bold;")
        root.addWidget(t)
        sub = QLabel("CPU Stress Benchmark  •  dev build")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet(f"color:{SUBTLE};font-size:9pt;")
        root.addWidget(sub)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color:{SUBTLE};"); root.addWidget(sep)

        cw = QWidget(); cl = QVBoxLayout(cw)
        cl.setContentsMargins(4,4,4,4); cl.setSpacing(2)
        for name, _ in StartupChecker._CHECKS:
            row = _CheckRow(name)
            self._rows[name] = row
            cl.addWidget(row)
        root.addWidget(cw)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color:{SUBTLE};"); root.addWidget(sep2)

        self._bar = QProgressBar()
        self._bar.setRange(0, len(StartupChecker._CHECKS))
        self._bar.setValue(0); self._bar.setTextVisible(False)
        self._bar.setFixedHeight(6)
        self._bar.setStyleSheet(
            f"QProgressBar{{background:{PANEL_BG};border-radius:3px;}}"
            f"QProgressBar::chunk{{background:{ACCENT};border-radius:3px;}}")
        root.addWidget(self._bar)

        self._status = QLabel("Initialising…")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setStyleSheet(f"color:{SUBTLE};font-size:8pt;")
        root.addWidget(self._status)
        root.addStretch()

        self._btn = QPushButton("Open App")
        self._btn.setMinimumHeight(40); self._btn.setEnabled(False)
        self._btn.setStyleSheet(
            f"QPushButton{{background:{ACCENT};color:#000;font-weight:bold;"
            f"border-radius:6px;font-size:12pt;}}"
            f"QPushButton:hover{{background:#40DFFF;}}"
            f"QPushButton:disabled{{background:{SUBTLE};color:#555;}}")
        self._btn.clicked.connect(self.launch_requested)
        root.addWidget(self._btn)

    def _on_update(self, name, status, detail):
        if name in self._rows:
            self._rows[name].update_status(status, detail)
        self._status.setText(f"{name}: {detail}" if detail else f"Checking {name}…")
        if status in ("ok", "warn", "error"):
            self._done += 1
            self._bar.setValue(self._done)

    def _on_done(self, ok):
        if ok:
            self._status.setText("All checks passed — ready")
            self._status.setStyleSheet(f"color:{COL_GOOD};font-size:8pt;")
            self._btn.setEnabled(True)
            QTimer.singleShot(1500, self.launch_requested)
        else:
            self._status.setText("Some critical checks failed")
            self._status.setStyleSheet(f"color:{COL_CRIT};font-size:8pt;")

    def showEvent(self, ev):
        super().showEvent(ev)
        sg = QApplication.primaryScreen().geometry()
        self.move((sg.width()-self.width())//2, (sg.height()-self.height())//2)


# ═══════════════════════════════════════════════════════════════════════════
#  RUN HISTORY
# ═══════════════════════════════════════════════════════════════════════════

class RunHistory:
    def __init__(self, runs_dir=RUNS_DIR):
        self.runs_dir = runs_dir
        os.makedirs(runs_dir, exist_ok=True)

    def save(self, report: dict) -> str:
        ts   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = (report.get("cpu") or "unknown")[:30].replace(" ", "_")
        slug = "".join(c for c in slug if c.isalnum() or c in "_-")
        run_id = f"{slug}_{ts}"
        data = {
            "run_id":         run_id,
            "timestamp":      datetime.datetime.now().isoformat(),
            "cpu":            report.get("cpu", ""),
            "run_tag":        report.get("run_tag", ""),
            "results":        report.get("results", {}),
            "summary":        report.get("summary"),
            "summary_text":   report.get("summary_text", ""),
            "cooling":        report.get("cooling"),
            "cooling_text":   report.get("cooling_text"),
            "fan_text":       report.get("fan_text"),
            "full_report":    report.get("full_report", ""),
            "cooldown_stats": report.get("cooldown_stats") or {},
            "ambient_c":      report.get("ambient_c", 22),
        }
        path = os.path.join(self.runs_dir, f"{run_id}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        return run_id

    def load_all(self) -> list:
        runs = []
        for fn in os.listdir(self.runs_dir):
            if not fn.endswith(".json"):
                continue
            try:
                with open(os.path.join(self.runs_dir, fn), encoding="utf-8") as f:
                    runs.append(json.load(f))
            except Exception:
                pass
        runs.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
        return runs


# ═══════════════════════════════════════════════════════════════════════════
#  ANALYSIS HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _generate_recommendations(report: dict) -> list:
    recos = []
    results = report.get("results", {}) or {}
    cooling = report.get("cooling") or {}
    f_thr   = cooling.get("throttled_sample_count", 0) or 0
    t_thr   = cooling.get("tstate_throttled_sample_count", 0) or 0
    load_n  = max(cooling.get("load_sample_count", 1) or 1, 1)

    if f_thr > 0:
        recos.append(("crit",
            f"F-state throttling on {100*f_thr/load_n:.0f}% of load samples — clock "
            f"dropped to stay within TDP. A better cooler or fresh thermal paste "
            f"would directly improve benchmark scores."))
    if t_thr > 0:
        recos.append(("crit",
            f"T-state (PROCHOT) throttling on {100*t_thr/load_n:.0f}% of load — CPU "
            f"inserting idle cycles while holding boost clock. Hidden performance hit; "
            f"improve cooling immediately."))

    rth = cooling.get("thermal_resistance_c_per_w")
    if rth and cooling.get("thermal_resistance_reliable"):
        if   rth > 0.60: recos.append(("crit",
            f"Thermal resistance {rth:.3f} °C/W — very high (stock or degraded TIM). "
            f"Re-seat cooler with fresh paste. Good tower: <0.30; AIO: <0.15."))
        elif rth > 0.30: recos.append(("warn",
            f"Thermal resistance {rth:.3f} °C/W — stock-class. Aftermarket tower "
            f"cooler would lower sustained temperatures."))
        else:            recos.append(("good",
            f"Thermal resistance {rth:.3f} °C/W — good cooler."))

    if f_thr == 0 and t_thr == 0:
        peak = cooling.get("peak_tmp", 0) or 0
        hdroom = cooling.get("throttle_headroom_c", 100) or 100
        if   peak >= 95: recos.append(("warn",
            f"Peak {peak:.0f}°C — near TjMax. No throttling this run, but longer "
            f"workloads or warmer ambient may push it over."))
        elif peak >= 85: recos.append(("warn",
            f"Peak {peak:.0f}°C — warm with ~{hdroom:.0f}°C margin. Watch on hot days."))
        elif peak <  70: recos.append(("good",
            f"Peak {peak:.0f}°C — excellent cooling, massive thermal headroom."))
        else:            recos.append(("good",
            f"Peak {peak:.0f}°C — comfortable margin to throttle threshold."))

    ramp = cooling.get("ramp_rate_c_per_s")
    if ramp and ramp > 3.0:
        recos.append(("warn",
            f"Temperature ramps at {ramp:.1f}°C/s in first 10s — fast. Check fan "
            f"curve responds quickly to load; consider repasting older coolers."))

    single = results.get("single") or {}
    multi  = results.get("multi") or {}
    if single and multi:
        ideal = (single.get("throughput_digits_per_sec") or 0) * (multi.get("workers") or 1)
        m_tput = multi.get("aggregate_throughput_digits_per_sec") or 0
        eff = m_tput / ideal if ideal > 0 else 0
        if   eff < 0.55: recos.append(("crit",
            f"Parallel efficiency only {eff*100:.1f}% — likely thermal throttling, "
            f"memory bandwidth saturation, or SMT contention."))
        elif eff < 0.80: recos.append(("warn",
            f"Parallel efficiency {eff*100:.1f}% — some scaling loss, possibly mild "
            f"throttling or memory bandwidth limits."))
        elif eff >= 0.90: recos.append(("good",
            f"Parallel efficiency {eff*100:.1f}% — near-ideal scaling, CPU not bottlenecked."))

    return recos or [("good", "No issues detected.")]


def _build_summary_text(report: dict) -> str:
    """Plain-text summary matching the .log style — shown in the Summary tab."""
    SEP  = "═" * 60
    lines = []
    results = report.get("results", {}) or {}
    single  = results.get("single") or {}
    multi   = results.get("multi")  or {}

    lines += [SEP, " PERFORMANCE", SEP]
    if single:
        ref = "✓" if single.get("verified_reference") else "✗"
        lines.append(f"  [single]      {single.get('wall_s',0):.1f}s  —  "
                     f"{single.get('throughput_digits_per_sec',0):,.0f} digits/s   (ref {ref})")
    if multi:
        ref = "✓" if multi.get("verified_reference") else "✗"
        xc  = "✓" if multi.get("cross_worker_consistent") else "✗"
        lines.append(f"  [multi ×{multi.get('workers',0)}]   {multi.get('wall_s',0):.1f}s  —  "
                     f"{multi.get('aggregate_throughput_digits_per_sec',0):,.0f} digits/s"
                     f"   (ref {ref}, cross {xc})")
        if single:
            ideal = (single.get("throughput_digits_per_sec",0) or 0) * (multi.get("workers",1) or 1)
            eff   = (multi.get("aggregate_throughput_digits_per_sec",0) or 0) / ideal if ideal else 0
            lines.append(f"  Parallel efficiency: {eff*100:.1f}%  across {multi.get('workers',0)} workers")

    lines += ["", SEP, " THERMAL / POWER SUMMARY", SEP]
    lines.append(report.get("summary_text") or "(no sensor data captured)")

    ct = report.get("cooling_text")
    if ct:
        lines += ["", SEP, " COOLER / THERMAL ANALYSIS", SEP, ct]

    ft = report.get("fan_text")
    if ft:
        lines += ["", SEP, " FAN ANALYSIS", SEP, ft]

    recos = _generate_recommendations(report)
    lines += ["", SEP, " RECOMMENDATIONS", SEP]
    icons = {"good": "✓", "warn": "⚠", "crit": "✗"}
    for sev, text in recos:
        lines.append(f"  {icons.get(sev,'•')} {text}")

    return "\n".join(lines)


def _extract_metrics(run_data: dict) -> dict:
    """Return {label: (value, unit, higher_is_better)} for comparison table."""
    results = run_data.get("results") or {}
    cooling = run_data.get("cooling") or {}
    summary = run_data.get("summary") or {}
    agg     = summary.get("aggregate") or {}
    single  = results.get("single") or {}
    multi   = results.get("multi")  or {}
    cd      = run_data.get("cooldown_stats") or {}
    amb     = run_data.get("ambient_c")

    s_tput  = single.get("throughput_digits_per_sec", 0) or 0
    m_tput  = multi.get("aggregate_throughput_digits_per_sec", 0) or 0
    workers = multi.get("workers", 1) or 1
    ideal   = s_tput * workers
    eff     = (m_tput / ideal * 100) if ideal > 0 else None

    # Ambient-referenced thermal resistance: (steady_tmp - ambient) / steady_watt
    # Complements the existing baseline-referenced Rth with an absolute metric.
    rth_ambient = None
    if (amb is not None and cooling.get("steady_tmp") and
            cooling.get("steady_watt") and cooling["steady_watt"] > 5.0):
        rth_ambient = (cooling["steady_tmp"] - amb) / cooling["steady_watt"]

    return {
        "Single throughput":        (s_tput,                                        "d/s",    True),
        "Multi throughput":         (m_tput,                                        "d/s",    True),
        "Parallel efficiency":      (eff,                                            "%",      True),
        "Avg CPU busy":             (agg.get("avg_busy_pct"),                        "%",      True),
        "Avg clock":                (agg.get("avg_clock_mhz"),                       "MHz",    True),
        "Peak clock":               (agg.get("peak_clock_mhz"),                      "MHz",    True),
        "Clock consistency (CV)":   (agg.get("clock_cv_pct"),                        "%CV",    False),
        "Steady temp":              (cooling.get("steady_tmp"),                      "°C",     False),
        "Peak temp":                (cooling.get("peak_tmp"),                        "°C",     False),
        "Steady power":             (cooling.get("steady_watt"),                     "W",      False),
        "Peak power":               (agg.get("peak_pkg_watt"),                       "W",      False),
        "Thermal resistance":       (cooling.get("thermal_resistance_c_per_w"),      "°C/W",   False),
        "Rth vs ambient":           (rth_ambient,                                    "°C/W",   False),
        "Throttle headroom":        (cooling.get("throttle_headroom_c"),             "°C",     True),
        "F-state throttle":         (cooling.get("throttled_sample_count", 0),       "samples",False),
        "T-state throttle":         (cooling.get("tstate_throttled_sample_count",0), "samples",False),
        "Cool-down duration":       (cd.get("duration_s"),                           "s",      False),
        "Cool-down rate":           (cd.get("rate_c_per_min"),                       "°C/min", True),
        "Cool-down drop":           (cd.get("drop_c"),                               "°C",     True),
    }


# ═══════════════════════════════════════════════════════════════════════════
#  BENCHMARK THREAD
# ═══════════════════════════════════════════════════════════════════════════

class BenchmarkThread(QThread):
    progress       = pyqtSignal(float, int, int, float, float, float, float, object, object)
    phase_changed  = pyqtSignal(str)            # "single" | "multi"
    core_labels    = pyqtSignal(object, object) # (clock_names, temp_names) — emitted once
    log_line       = pyqtSignal(str)
    run_finished   = pyqtSignal(dict)
    run_report     = pyqtSignal(dict)
    archive_status = pyqtSignal(str)

    def __init__(self, config: dict):
        super().__init__()
        self.config = config

    def cancel(self) -> None:
        """Stop the benchmark immediately — kills all worker processes."""
        _kill_workers()          # SIGKILL every ProcessPoolExecutor worker
        self.terminate()         # stop the QThread itself
        self.wait(2000)          # give it up to 2 s to exit cleanly

    def run(self):
        cfg  = self.config
        args = argparse.Namespace(
            digits=cfg["digits"], mode=cfg["mode"], workers=cfg["workers"],
            json=False, archive=cfg.get("archive", False),
            smb_share=cfg.get("smb_share", pb.DEFAULT_SMB_SHARE),
            smb_user=pb.DEFAULT_SMB_USER, smb_subdir=pb.DEFAULT_SMB_SUBDIR,
            sftp_user=cfg.get("sftp_user", pb.DEFAULT_SFTP_USER),
            sftp_path=pb.DEFAULT_SFTP_PATH,
            sftp_password=cfg.get("sftp_password"),
            run_tag=cfg.get("run_tag", ""),
        )
        pb.sys.setrecursionlimit(100_000)
        pb._raise_int_str_limit(args.digits)

        class _NoTTY:
            def isatty(self): return False
            def read(self, *_): return ""
            def readline(self, *_): return ""

        old_stdin = pb.sys.stdin
        pb.sys.stdin = _NoTTY()

        archive_state = {"enabled": False}
        if args.archive:
            self.archive_status.emit("[archive] setting up…")
            archive_state = pb.archive_setup(args)
            pb.sys.stdin = old_stdin

        own_lhm = None
        if platform.system() == "Windows":
            lhm_sampler = archive_state.get("lhm_sampler")
            if lhm_sampler is None:
                try:
                    if pb.lhm_ensure_running():
                        own_lhm = pb.LHMSampler(interval=1.0)
                        own_lhm.start()
                        lhm_sampler = own_lhm
                except Exception as exc:
                    self.log_line.emit(f"[lhm] error: {exc}")
        else:
            lhm_sampler = archive_state.get("lhm_sampler")

        raw_turbo   = archive_state.get("raw_path")
        fans        = archive_state.get("fans")
        fan_samples = archive_state.get("fan_samples")

        _labels_sent = [False]

        def on_progress(elapsed, done, total, busy, mhz, temp, power,
                        core_clocks=None, core_temps=None,
                        core_clock_names=None, core_temp_names=None):
            if not _labels_sent[0] and (core_clock_names or core_temp_names):
                self.core_labels.emit(core_clock_names or [], core_temp_names or [])
                _labels_sent[0] = True
            self.progress.emit(elapsed, done, total, busy, mhz, temp, power,
                               core_clocks or [], core_temps or [])

        captured = io.StringIO()
        log_sig  = self.log_line

        class _Tee:
            def write(self, t):
                captured.write(t)
                if t.strip(): log_sig.emit(t.rstrip())
            def flush(self): pass
            def isatty(self): return False

        old_stdout = pb.sys.stdout
        pb.sys.stdout = _Tee()
        results = {}
        cooldown_samples       = []
        _bench_end_sample_count = 0   # samples collected before cool-down starts

        try:
            if args.mode in ("single", "both"):
                self.phase_changed.emit("single")
                results["single"] = pb.run_single(
                    args.digits, quiet=False,
                    raw_turbo_path=raw_turbo, fans=fans, fan_samples=fan_samples,
                    lhm_sampler=lhm_sampler, progress_callback=on_progress)
            if args.mode in ("multi", "both"):
                self.phase_changed.emit("multi")
                results["multi"] = pb.run_multi(
                    args.digits, args.workers, quiet=False,
                    raw_turbo_path=raw_turbo, fans=fans, fan_samples=fan_samples,
                    lhm_sampler=lhm_sampler, progress_callback=on_progress)

            # ── Cool-down phase ──────────────────────────────────────────
            # Measure how fast the CPU returns to idle temps — a direct
            # indicator of cooler effectiveness.  Runs only when the
            # benchmark completed without error and LHM is active.
            _active_sampler = archive_state.get("lhm_sampler") or own_lhm
            if _active_sampler is not None:
                _bench_end_sample_count = len(_active_sampler.all_samples())
                _pre = pb.analyze_cooling_lhm(_active_sampler.all_samples())
                _idle_tmp = (_pre.get("baseline_tmp") if _pre else None) or 35.0
                self.phase_changed.emit("cooldown")
                self.log_line.emit("[cooldown] measuring cool-down (up to 90 s)…")
                cooldown_samples = pb.measure_cooldown(
                    _active_sampler, _idle_tmp, on_progress, max_duration=90)
                self.log_line.emit(
                    f"[cooldown] done — {len(cooldown_samples)} samples, "
                    f"dropped {pb.summarize_cooldown(cooldown_samples).get('drop_c', 0):.1f} °C")

        finally:
            pb.sys.stdout = old_stdout
            pb.sys.stdin  = old_stdin

            bench_text = captured.getvalue()
            report = {
                "results":          results,
                "bench_output":     bench_text,
                "lhm_samples":      [],
                "summary":          None,
                "summary_text":     "(no sensor data)",
                "cooling":          None,
                "cooling_text":     None,
                "fan_text":         None,
                "full_report":      None,
                "cpu":              pb.detect_cpu_name(),
                "run_tag":          cfg.get("run_tag", ""),
                "cooldown_samples": cooldown_samples,
                "cooldown_stats":   pb.summarize_cooldown(cooldown_samples),
                "ambient_c":        cfg.get("ambient_c", 22),
            }

            active = archive_state.get("lhm_sampler") or own_lhm
            if active is not None:
                all_samps = active.all_samples()
                # Use only pre-cooldown samples for thermal analysis so the
                # cooldown's low-load readings don't distort baseline temps.
                bench_samps = (all_samps[:_bench_end_sample_count]
                               if _bench_end_sample_count > 0 else all_samps)
                report["lhm_samples"] = bench_samps
                if bench_samps:
                    summary = pb.summarize_lhm_samples(bench_samps)
                    report["summary"]      = summary
                    report["summary_text"] = pb.format_turbostat_summary(summary)
                    cooling = pb.analyze_cooling_lhm(bench_samps)
                    report["cooling"]      = cooling
                    report["cooling_text"] = pb.format_cooling_analysis(cooling)
                    fd = pb.analyze_fans_lhm(bench_samps)
                    report["fan_text"]     = pb.format_fan_analysis(fd) if fd else None

            try:
                run_n = datetime.datetime.now().strftime("%m-%d-%Y %H-%M-%S")
                report["full_report"] = pb.build_combined_report(
                    report["cpu"], run_n, args, bench_text,
                    report["summary_text"],
                    cooling_text=report["cooling_text"],
                    fan_text=report["fan_text"],
                    sensor_source="LibreHardwareMonitor" if active else "none",
                    cooldown_stats=report.get("cooldown_stats"),
                    ambient_c=report.get("ambient_c"),
                    run_tag=report.get("run_tag") or None)
            except Exception:
                pass

            if own_lhm is not None:
                own_lhm.stop()

            self.run_report.emit(report)

            if args.archive:
                self.archive_status.emit("[archive] finalising…")
                pb.archive_finalize(args, archive_state, bench_text)
                self.archive_status.emit("[archive] done")

        self.run_finished.emit(results)


# ═══════════════════════════════════════════════════════════════════════════
#  LIVE VIEW WIDGETS
# ═══════════════════════════════════════════════════════════════════════════

def _core_color(idx: int) -> str:
    """Return a visually distinct colour for core *idx*.
    Uses the golden-ratio hue sequence so successive indices are maximally
    separated in hue for any core count — works cleanly from 1 to 128+ cores.
    Saturation/value alternate slightly to add extra separation when hues start
    converging on large counts."""
    import colorsys
    hue = (0.12 + idx * 0.618033988749895) % 1.0   # golden ratio conjugate
    sat = 0.80 if idx % 2 == 0 else 0.60
    val = 0.95 if idx % 3 != 2  else 0.78
    r, g, b = colorsys.hsv_to_rgb(hue, sat, val)
    return "#{:02x}{:02x}{:02x}".format(int(r*255), int(g*255), int(b*255))


class LiveChart(pg.GraphicsLayoutWidget):
    """Live telemetry chart with one line per physical core for freq and temp,
    plus a single package-power panel.  No in-plot legend — the parent
    DualLiveChart owns a shared legend strip below the tabs."""

    def __init__(self):
        super().__init__()
        self.setBackground(DARK_BG)
        ls = {"color": TEXT, "font-size": "10pt"}

        self._t:  list[float] = []
        self._pw: list[float] = []

        self.p_power = self.addPlot(row=0, col=0)
        self.p_power.setLabel("left", "Power (W)", **ls)
        self.p_power.showGrid(x=True, y=True, alpha=0.15)
        self.p_power.getAxis("bottom").setStyle(showValues=False)
        self.c_power = self.p_power.plot(pen=pg.mkPen(COL_POWER, width=2))

        self.p_temp = self.addPlot(row=1, col=0)
        self.p_temp.setLabel("left", "Temp (°C)", **ls)
        self.p_temp.showGrid(x=True, y=True, alpha=0.15)
        self.p_temp.getAxis("bottom").setStyle(showValues=False)
        self._temp_series: list[tuple] = []   # (PlotDataItem, list[float])

        self.p_freq = self.addPlot(row=2, col=0)
        self.p_freq.setLabel("left", "Freq (MHz)", **ls)
        self.p_freq.setLabel("bottom", "Elapsed (s)", **ls)
        self.p_freq.showGrid(x=True, y=True, alpha=0.15)
        self._freq_series: list[tuple] = []   # (PlotDataItem, list[float])

        self.p_temp.setXLink(self.p_power)
        self.p_freq.setXLink(self.p_power)
        for i in range(3):
            self.ci.layout.setRowStretchFactor(i, 1)

    def _ensure_core_series(self, n_cores: int) -> None:
        while len(self._temp_series) < n_cores:
            idx = len(self._temp_series)
            pen = pg.mkPen(_core_color(idx), width=1)
            self._temp_series.append((self.p_temp.plot(pen=pen), []))
            self._freq_series.append((self.p_freq.plot(pen=pen), []))

    def add_point(self, elapsed: float, temp: float, power: float, mhz: float,
                  core_clocks: list, core_temps: list) -> None:
        self._t.append(elapsed)
        self._pw.append(power)
        self.c_power.setData(self._t, self._pw)

        if not core_clocks and not core_temps:
            # No per-core LHM data — show package values as a single line
            self._ensure_core_series(1)
            c_t, t_data = self._temp_series[0]
            c_f, f_data = self._freq_series[0]
            t_data.append(temp); f_data.append(mhz)
            c_t.setData(self._t, t_data); c_f.setData(self._t, f_data)
        else:
            n_cores = max(len(core_clocks), len(core_temps))
            self._ensure_core_series(n_cores)
            for idx in range(n_cores):
                c_t, t_data = self._temp_series[idx]
                c_f, f_data = self._freq_series[idx]
                t_data.append(core_temps[idx]  if idx < len(core_temps)  else 0.0)
                f_data.append(core_clocks[idx] if idx < len(core_clocks) else 0.0)
                c_t.setData(self._t, t_data); c_f.setData(self._t, f_data)

    def reset(self) -> None:
        self._t.clear(); self._pw.clear()
        self.c_power.setData([], [])
        for curve, _ in self._temp_series:
            self.p_temp.removeItem(curve)
        for curve, _ in self._freq_series:
            self.p_freq.removeItem(curve)
        self._temp_series.clear()
        self._freq_series.clear()


class DualLiveChart(QWidget):
    """Two LiveChart panels — one for the single-thread phase, one for multi.
    A shared legend strip below the tabs shows all core colours and names.
    The legend is built from LHM names the first time they arrive and shared
    across both chart tabs (same hardware either way)."""

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(
            "QTabBar::tab{"
            "background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            f"stop:0 rgba(255,255,255,50),stop:1 rgba(0,40,100,60));"
            f"color:rgba(255,255,255,140);padding:4px 14px;font-size:9pt;"
            f"border:1px solid rgba(255,255,255,80);border-bottom:none;"
            f"border-radius:6px 6px 0 0;margin-right:2px;}}"
            f"QTabBar::tab:selected{{color:{TEXT};border-bottom:2px solid {ACCENT};"
            "background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "stop:0 rgba(255,255,255,90),stop:1 rgba(0,100,200,70));}"
            f"QTabWidget::pane{{background:transparent;border:none;}}")
        lay.addWidget(self._tabs, 1)

        self._charts: dict[str, LiveChart] = {}
        for phase, label in (("single", "Single Thread"),
                              ("multi",   "Multi Thread"),
                              ("cooldown","Cool-down")):
            c = LiveChart()
            self._charts[phase] = c
            self._tabs.addTab(c, label)

        # ── Shared core legend strip ───────────────────────────────────────
        # One coloured swatch + name per physical core.  Lives outside the
        # plot panels so it doesn't eat chart space regardless of core count.
        self._legend_lbl = QLabel()
        self._legend_lbl.setWordWrap(True)
        self._legend_lbl.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._legend_lbl.setStyleSheet(
            f"background:{PANEL_BG}; color:{SUBTLE}; "
            f"padding:5px 10px; font-size:9pt;")
        self._legend_lbl.setMinimumHeight(28)
        lay.addWidget(self._legend_lbl)

        self._active_phase = "single"

    # ── helpers ───────────────────────────────────────────────────────────

    def _build_legend_html(self, clock_names: list, temp_names: list) -> str:
        """Build an HTML swatch strip from whichever name list is non-empty."""
        names = clock_names or temp_names
        if not names:
            return ""
        parts = []
        for idx, name in enumerate(names):
            col = _core_color(idx)
            parts.append(f'<span style="color:{col}; font-size:13pt;">&#9632;</span>'
                         f'<span style="color:{TEXT};">&nbsp;{name}</span>')
        return "&nbsp;&nbsp;&nbsp;".join(parts)

    # ── public API ────────────────────────────────────────────────────────

    def set_active(self, phase: str) -> None:
        self._active_phase = phase
        idx = {"single": 0, "multi": 1, "cooldown": 2}.get(phase, 0)
        self._tabs.setCurrentIndex(idx)
        self._charts[phase].reset()

    def set_core_labels(self, clock_names: list, temp_names: list) -> None:
        """Render the legend strip. Both chart tabs share the same hardware."""
        self._legend_lbl.setText(self._build_legend_html(clock_names, temp_names))

    def add_point(self, elapsed, temp, power, mhz, core_clocks, core_temps) -> None:
        self._charts[self._active_phase].add_point(
            elapsed, temp, power, mhz, core_clocks, core_temps)

    def reset(self) -> None:
        self._active_phase = "single"
        self._tabs.setCurrentIndex(0)
        self._legend_lbl.clear()
        for c in self._charts.values():
            c.reset()


class StatBar(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet("background:transparent;")
        row = QHBoxLayout(self)
        row.setContentsMargins(6,4,6,4); row.setSpacing(24)

        def _s(label, color):
            col = QVBoxLayout()
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color:{SUBTLE};font-size:9pt;")
            val = QLabel("—")
            val.setStyleSheet(f"color:{color};font-size:15pt;font-weight:bold;")
            col.addWidget(lbl); col.addWidget(val)
            row.addLayout(col)
            return val

        self.v_temp  = _s("TEMP",    COL_TEMP)
        self.v_power = _s("PACKAGE", COL_POWER)
        self.v_freq  = _s("FREQ",    COL_FREQ)
        self.v_busy  = _s("BUSY",    COL_BUSY)
        self.v_prog  = _s("WORKERS", TEXT)
        self.v_time  = _s("ELAPSED", TEXT)
        row.addStretch()

    def update_stats(self, elapsed, done, total, busy, mhz, temp, power):
        self.v_temp.setText(f"{temp:.0f} °C")
        self.v_power.setText(f"{power:.1f} W")
        self.v_freq.setText(f"{mhz:.0f} MHz")
        self.v_busy.setText(f"{busy:.0f} %")
        self.v_prog.setText(f"{done} / {total}")
        self.v_time.setText(f"{elapsed:.0f} s")

    def clear(self):
        for v in (self.v_temp,self.v_power,self.v_freq,self.v_busy,self.v_prog,self.v_time):
            v.setText("—")


# ═══════════════════════════════════════════════════════════════════════════
#  RESULTS VIEW (reused in Results tab + Reports detail)
# ═══════════════════════════════════════════════════════════════════════════

class ResultsView(QWidget):
    """Two-tab widget: Summary (plain text) | Full Report (.log text).
    Fully self-contained — just call load_report(report_dict) to populate."""

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0,0,0,0)

        tabs = QTabWidget()
        tabs.setStyleSheet(
            f"QTabBar::tab{{background:{PANEL_BG};color:{SUBTLE};padding:5px 14px;}}"
            f"QTabBar::tab:selected{{color:{TEXT};border-bottom:2px solid {ACCENT};}}")
        lay.addWidget(tabs)

        mono = QFont("Consolas", 9)
        base_style = f"background:{PANEL_BG};color:{TEXT};border:none;"

        self._summary_te = QTextEdit()
        self._summary_te.setReadOnly(True)
        self._summary_te.setFont(mono)
        self._summary_te.setStyleSheet(base_style)
        tabs.addTab(self._summary_te, "Summary")

        self._report_te = QTextEdit()
        self._report_te.setReadOnly(True)
        self._report_te.setFont(mono)
        self._report_te.setStyleSheet(base_style)
        tabs.addTab(self._report_te, "Full Report (.log)")

    def load_report(self, report: dict):
        self._summary_te.setPlainText(_build_summary_text(report))
        self._summary_te.verticalScrollBar().setValue(0)
        self._report_te.setPlainText(report.get("full_report") or "(not available)")
        self._report_te.verticalScrollBar().setValue(0)

    def clear(self):
        self._summary_te.clear()
        self._report_te.clear()


# ═══════════════════════════════════════════════════════════════════════════
#  REPORTS TAB
# ═══════════════════════════════════════════════════════════════════════════

class ReportsTab(QWidget):
    def __init__(self, history: RunHistory):
        super().__init__()
        self._history = history
        self._runs: list[dict] = []

        root = QHBoxLayout(self)
        root.setContentsMargins(0,0,0,0)
        root.setSpacing(0)

        # Left: run list
        left = QWidget()
        left.setFixedWidth(220)
        left.setStyleSheet(f"background:{PANEL_BG};")
        ll = QVBoxLayout(left)
        ll.setContentsMargins(8,8,8,8); ll.setSpacing(4)

        hdr = QLabel("Run History")
        hdr.setStyleSheet(f"color:{ACCENT};font-size:10pt;font-weight:bold;")
        ll.addWidget(hdr)

        self._list = QListWidget()
        self._list.setStyleSheet(
            f"QListWidget{{background:{PANEL_BG};border:none;color:{TEXT};}}"
            f"QListWidget::item{{padding:6px 4px;border-bottom:1px solid {DARK_BG};}}"
            f"QListWidget::item:selected{{background:{ACCENT};color:#000;}}")
        self._list.currentRowChanged.connect(self._on_select)
        ll.addWidget(self._list, 1)

        refresh_btn = QPushButton("↻ Refresh")
        refresh_btn.setStyleSheet(
            f"QPushButton{{background:{DARK_BG};color:{SUBTLE};border:none;"
            f"font-size:8pt;padding:4px;border-radius:3px;}}"
            f"QPushButton:hover{{color:{TEXT};}}")
        refresh_btn.clicked.connect(self.refresh)
        ll.addWidget(refresh_btn)

        root.addWidget(left)

        # Divider
        div = QFrame(); div.setFrameShape(QFrame.Shape.VLine)
        div.setStyleSheet(f"color:{SUBTLE};")
        root.addWidget(div)

        # Right: detail view
        self._detail = ResultsView()
        root.addWidget(self._detail, 1)

        self.refresh()

    def refresh(self):
        self._runs = self._history.load_all()
        self._list.clear()
        for r in self._runs:
            ts  = r.get("timestamp", "")[:16].replace("T", "  ")
            cpu = (r.get("cpu") or "")[:24]
            results = r.get("results") or {}
            multi   = results.get("multi") or {}
            single  = results.get("single") or {}
            score   = (multi.get("aggregate_throughput_digits_per_sec")
                       or single.get("throughput_digits_per_sec") or 0)
            text = f"{ts}\n{cpu}\n{score:,.0f} d/s" if score else f"{ts}\n{cpu}"
            item = QListWidgetItem(text)
            item.setFont(QFont("Consolas", 8))
            self._list.addItem(item)

        if self._runs:
            self._list.setCurrentRow(0)

    def show_run(self, report: dict):
        """Highlight the most recently added run (called after a new run is saved)."""
        self.refresh()
        if self._list.count() > 0:
            self._list.setCurrentRow(0)

    def _on_select(self, row: int):
        if 0 <= row < len(self._runs):
            self._detail.load_report(self._runs[row])


# ═══════════════════════════════════════════════════════════════════════════
#  COMPARE TAB
# ═══════════════════════════════════════════════════════════════════════════

class CompareTab(QWidget):
    def __init__(self, history: RunHistory):
        super().__init__()
        self._history = history

        root = QVBoxLayout(self)
        root.setContentsMargins(12,12,12,12); root.setSpacing(10)

        # Run selectors
        sel_row = QHBoxLayout()
        sel_row.setSpacing(16)

        for attr, label in (("_combo_a", "Run A"), ("_combo_b", "Run B")):
            col = QVBoxLayout()
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color:{ACCENT};font-weight:bold;font-size:10pt;")
            combo = QComboBox()
            combo.setStyleSheet(
                f"QComboBox{{background:{PANEL_BG};color:{TEXT};border:1px solid {SUBTLE};"
                f"padding:4px;border-radius:3px;}}"
                f"QComboBox QAbstractItemView{{background:{PANEL_BG};color:{TEXT};}}")
            setattr(self, attr, combo)
            col.addWidget(lbl); col.addWidget(combo)
            sel_row.addLayout(col, 1)

        compare_btn = QPushButton("Compare →")
        compare_btn.setFixedHeight(36)
        compare_btn.setStyleSheet(
            f"QPushButton{{background:{ACCENT};color:#000;font-weight:bold;"
            f"border-radius:4px;padding:0 16px;}}"
            f"QPushButton:hover{{background:#40DFFF;}}")
        compare_btn.clicked.connect(self._do_compare)
        sel_row.addWidget(compare_btn)
        root.addLayout(sel_row)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color:{SUBTLE};"); root.addWidget(sep)

        # Comparison table
        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["Metric", "Run A", "Run B", "Δ (B − A)"])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet(
            f"QTableWidget{{background:{PANEL_BG};color:{TEXT};gridline-color:{SUBTLE};"
            f"border:none;}}"
            f"QHeaderView::section{{background:{DARK_BG};color:{ACCENT};"
            f"padding:6px;border:none;}}"
            f"QTableWidget::item{{padding:4px;}}"
            f"QTableWidget::item:alternate{{background:{DARK_BG};}}")
        self._table.setColumnWidth(0, 200)
        self._table.setColumnWidth(1, 160)
        self._table.setColumnWidth(2, 160)
        root.addWidget(self._table, 1)

        self._runs: list[dict] = []
        self.refresh()

    def refresh(self):
        self._runs = self._history.load_all()
        for combo in (self._combo_a, self._combo_b):
            prev = combo.currentIndex()
            combo.clear()
            for r in self._runs:
                ts  = (r.get("timestamp", "")[:16]).replace("T", " ")
                cpu = (r.get("cpu") or "")[:22]
                tag = r.get("run_tag") or ""
                label = f"{ts}  {cpu}  [{tag}]" if tag else f"{ts}  {cpu}"
                combo.addItem(label)
            if prev >= 0 and prev < combo.count():
                combo.setCurrentIndex(prev)
            elif len(self._runs) >= 2:
                combo.setCurrentIndex(1 if combo is self._combo_b else 0)

    def _do_compare(self):
        if len(self._runs) < 2:
            return
        ia = self._combo_a.currentIndex()
        ib = self._combo_b.currentIndex()
        if ia < 0 or ib < 0 or ia >= len(self._runs) or ib >= len(self._runs):
            return
        ma = _extract_metrics(self._runs[ia])
        mb = _extract_metrics(self._runs[ib])
        self._render(ma, mb)

    def _render(self, ma: dict, mb: dict):
        self._table.setRowCount(0)
        for label in ma:
            row = self._table.rowCount()
            self._table.insertRow(row)

            va, unit, higher = ma[label]
            vb, _,    _      = mb.get(label, (None, unit, higher))

            def fmt(v): return f"{v:,.1f} {unit}" if v is not None else "—"

            item_label = QTableWidgetItem(label)
            item_a     = QTableWidgetItem(fmt(va))
            item_b     = QTableWidgetItem(fmt(vb))

            # Delta
            if va is not None and vb is not None and va != 0:
                delta     = vb - va
                delta_pct = delta / abs(va) * 100
                delta_str = f"{delta:+.1f} {unit}  ({delta_pct:+.1f}%)"
                better_b  = (delta > 0) == higher
                d_color   = COL_GOOD if better_b else (COL_CRIT if delta != 0 else TEXT)
                # Colour the winning column
                win_col   = COL_GOOD if better_b else COL_CRIT
                (item_b if better_b else item_a).setForeground(QColor(win_col))
            else:
                delta_str = "—"
                d_color   = TEXT

            item_delta = QTableWidgetItem(delta_str)
            item_delta.setForeground(QColor(d_color))

            for col_idx, item in enumerate((item_label, item_a, item_b, item_delta)):
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignVCenter |
                    (Qt.AlignmentFlag.AlignLeft if col_idx == 0
                     else Qt.AlignmentFlag.AlignRight))
                self._table.setItem(row, col_idx, item)


# ═══════════════════════════════════════════════════════════════════════════
#  HISTORY TAB
# ═══════════════════════════════════════════════════════════════════════════

class _NumItem(QTableWidgetItem):
    """QTableWidgetItem that sorts numerically (not lexicographically)."""
    def __init__(self, display: str, sort_val):
        super().__init__(display)
        self._sv = sort_val if sort_val is not None else -1e18
        self.setTextAlignment(Qt.AlignmentFlag.AlignVCenter |
                              Qt.AlignmentFlag.AlignRight)
    def __lt__(self, other):
        try:    return self._sv < other._sv
        except: return super().__lt__(other)


class HistoryTab(QWidget):
    """Sortable table of every saved benchmark run.
    Double-click a row to load that run in the Reports tab."""

    run_selected = pyqtSignal(dict)

    _COLS = [
        ("Date",           120),
        ("CPU",            170),
        ("Tag",            130),
        ("Single (d/s)",   100),
        ("Multi (d/s)",    100),
        ("Peak °C",         70),
        ("Avg W",           60),
        ("Rth °C/W",        70),
        ("Clock CV %",      75),
        ("Cooldown (s)",    80),
    ]

    def __init__(self, history: RunHistory):
        super().__init__()
        self._history = history
        self._runs: list[dict] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        btn_row = QHBoxLayout()
        refresh_btn = QPushButton("↺  Refresh")
        refresh_btn.setFixedWidth(100)
        refresh_btn.setStyleSheet(
            f"QPushButton{{background:{PANEL_BG};color:{TEXT};"
            f"border:1px solid {SUBTLE};border-radius:3px;padding:4px 8px;}}"
            f"QPushButton:hover{{border-color:{ACCENT};}}")
        refresh_btn.clicked.connect(self.refresh)
        lbl = QLabel("Double-click a row to view that run's full report")
        lbl.setStyleSheet(f"color:{SUBTLE};font-size:8pt;")
        btn_row.addWidget(refresh_btn)
        btn_row.addWidget(lbl)
        btn_row.addStretch()
        root.addLayout(btn_row)

        self._table = QTableWidget()
        self._table.setColumnCount(len(self._COLS))
        self._table.setHorizontalHeaderLabels([c for c, _ in self._COLS])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.setSortingEnabled(True)
        self._table.setStyleSheet(
            f"QTableWidget{{background:{PANEL_BG};color:{TEXT};"
            f"gridline-color:{SUBTLE};border:none;}}"
            f"QHeaderView::section{{background:{DARK_BG};color:{ACCENT};"
            f"padding:6px;border:none;}}"
            f"QTableWidget::item{{padding:4px;}}"
            f"QTableWidget::item:alternate{{background:{DARK_BG};}}")
        for i, (_, w) in enumerate(self._COLS):
            self._table.setColumnWidth(i, w)
        self._table.doubleClicked.connect(self._on_double_click)
        root.addWidget(self._table, 1)
        self.refresh()

    # ------------------------------------------------------------------
    def refresh(self):
        self._runs = self._history.load_all()
        self._table.setSortingEnabled(False)
        self._table.setRowCount(0)

        for r in self._runs:
            results = r.get("results") or {}
            cooling = r.get("cooling") or {}
            summary = r.get("summary") or {}
            agg     = summary.get("aggregate") or {}
            single  = results.get("single") or {}
            multi   = results.get("multi")  or {}
            cd      = r.get("cooldown_stats") or {}

            ts   = (r.get("timestamp", "")[:16]).replace("T", " ")
            cpu  = r.get("cpu", "")
            s_t  = single.get("throughput_digits_per_sec")    or 0
            m_t  = multi.get("aggregate_throughput_digits_per_sec") or 0
            p_c  = cooling.get("peak_tmp")
            a_w  = agg.get("avg_pkg_watt")
            rth  = cooling.get("thermal_resistance_c_per_w")
            cv   = agg.get("clock_cv_pct")
            cds  = cd.get("duration_s")

            row = self._table.rowCount()
            self._table.insertRow(row)

            tag  = r.get("run_tag") or ""

            # Text columns: 0=date, 1=cpu, 2=tag
            ts_item = QTableWidgetItem(ts)
            ts_item.setData(Qt.ItemDataRole.UserRole + 1, r)   # stash run dict
            self._table.setItem(row, 0, ts_item)
            self._table.setItem(row, 1, QTableWidgetItem(cpu))
            tag_item = QTableWidgetItem(tag)
            tag_item.setForeground(QColor(ACCENT if tag else SUBTLE))
            self._table.setItem(row, 2, tag_item)

            # Numeric columns
            def _ni(v, fmt):
                s = fmt.format(v) if v is not None else "—"
                return _NumItem(s, float(v) if v is not None else None)

            self._table.setItem(row, 3, _ni(s_t,  "{:,.0f}"))
            self._table.setItem(row, 4, _ni(m_t,  "{:,.0f}"))
            self._table.setItem(row, 5, _ni(p_c,  "{:.1f}"))
            self._table.setItem(row, 6, _ni(a_w,  "{:.1f}"))
            self._table.setItem(row, 7, _ni(rth,  "{:.3f}"))
            self._table.setItem(row, 8, _ni(cv,   "{:.1f}"))
            self._table.setItem(row, 9, _ni(cds,  "{:.0f}"))

        self._table.setSortingEnabled(True)

    def _on_double_click(self, index):
        item = self._table.item(index.row(), 0)
        if item:
            r = item.data(Qt.ItemDataRole.UserRole + 1)
            if r:
                self.run_selected.emit(r)


# ═══════════════════════════════════════════════════════════════════════════
#  UPDATE BAR
# ═══════════════════════════════════════════════════════════════════════════

class UpdateBar(QWidget):
    """Full-width notification strip shown when a newer version is available."""
    update_clicked = pyqtSignal(str, str)   # version, download_url

    def __init__(self):
        super().__init__()
        self.hide()
        self.setFixedHeight(36)
        self.setStyleSheet(
            "background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            f"stop:0 rgba(0,80,160,120),stop:1 rgba(0,40,90,180));"
            f"border-bottom:2px solid {ACCENT};")
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 0, 8, 0); row.setSpacing(10)

        ico = QLabel("⬆")
        ico.setStyleSheet(f"color:{ACCENT};font-size:12pt;")
        row.addWidget(ico)

        self._lbl = QLabel()
        self._lbl.setStyleSheet(f"color:{TEXT};font-size:9pt;")
        row.addWidget(self._lbl, 1)

        self._dl_btn = QPushButton("Download & Install")
        self._dl_btn.setStyleSheet(
            "QPushButton{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "stop:0 #40E8FF,stop:0.48 #00AADD,stop:0.52 #0088BB,stop:1 #005577);"
            f"color:#001828;font-weight:bold;border-radius:5px;"
            f"padding:2px 12px;font-size:9pt;border:1px solid rgba(0,220,255,180);}}"
            "QPushButton:hover{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "stop:0 #70F0FF,stop:0.48 #20CCEE,stop:0.52 #00AACC,stop:1 #006688);}"
            f"QPushButton:disabled{{background:rgba(0,40,80,0.5);color:{SUBTLE};}}")
        self._dl_btn.clicked.connect(self._on_install)
        row.addWidget(self._dl_btn)

        dismiss = QPushButton("✕")
        dismiss.setFixedWidth(26)
        dismiss.setStyleSheet(
            f"color:{SUBTLE};background:transparent;border:none;font-size:10pt;")
        dismiss.clicked.connect(self.hide)
        row.addWidget(dismiss)

        self._version = ""
        self._url     = ""

    def notify(self, version: str, url: str):
        self._version = version
        self._url     = url
        self._lbl.setText(
            f"Pi Bench {version} is available  —  "
            f"current version: {pb.APP_VERSION}")
        self._dl_btn.setEnabled(True)
        self.show()

    def set_downloading(self):
        self._dl_btn.setEnabled(False)
        self._lbl.setText(f"Downloading Pi Bench {self._version}…")

    def _on_install(self):
        self.update_clicked.emit(self._version, self._url)


# ═══════════════════════════════════════════════════════════════════════════
#  SETTINGS PANEL
# ═══════════════════════════════════════════════════════════════════════════

class SettingsPanel(QWidget):
    # Signal used to return the auto-detect result to the main thread.
    # QTimer.singleShot from a worker thread is unreliable (no event loop);
    # signals are the correct Qt mechanism for thread → main-thread callbacks.
    _autodetect_result = pyqtSignal(object)   # str | None
    # Emitted whenever any setting value changes so the sidebar summary can refresh.
    settings_changed   = pyqtSignal()

    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(12,12,12,12); root.setSpacing(12)

        bench = QGroupBox("Benchmark")
        bl    = QVBoxLayout(bench)
        bl.addWidget(QLabel("Digits (millions):"))
        self.digits = QSpinBox(); self.digits.setRange(1,500); self.digits.setValue(5)
        bl.addWidget(self.digits)
        bl.addWidget(QLabel("Workers:"))
        self.workers = QSpinBox(); self.workers.setRange(1,256)
        self.workers.setValue(os.cpu_count() or 4)
        bl.addWidget(self.workers)
        bl.addWidget(QLabel("Mode:"))
        self.mode = QComboBox(); self.mode.addItems(["both","multi","single"])
        bl.addWidget(self.mode)
        bl.addWidget(QLabel("Room temp (°C):"))
        self.ambient_c = QSpinBox()
        self.ambient_c.setRange(10, 45); self.ambient_c.setValue(22)
        self.ambient_c.setToolTip("Ambient room temperature — used for ambient-referenced\nthermal resistance and cool-down analysis")
        bl.addWidget(self.ambient_c)
        root.addWidget(bench)

        tag_grp = QGroupBox("Run Tag")
        tl = QVBoxLayout(tag_grp)
        tag_hint = QLabel(
            "Label this run for easy comparison\n"
            "(cooler swap, RAM OC, new paste, etc.)")
        tag_hint.setStyleSheet(f"color:{SUBTLE};font-size:8pt;")
        tl.addWidget(tag_hint)
        self.run_tag = QLineEdit()
        self.run_tag.setPlaceholderText("e.g. 32GB DDR5-6000, Noctua NH-D15…")
        self.run_tag.setMaxLength(60)
        tl.addWidget(self.run_tag)
        tag_btn_row = QHBoxLayout(); tag_btn_row.setSpacing(4)
        self._detect_btn = QPushButton("Auto-detect")
        self._detect_btn.setToolTip("Detect RAM spec from system")
        self._detect_btn.clicked.connect(self._run_autodetect)
        tag_btn_row.addWidget(self._detect_btn)
        clear_tag_btn = QPushButton("Clear")
        clear_tag_btn.clicked.connect(self.run_tag.clear)
        tag_btn_row.addWidget(clear_tag_btn)
        tl.addLayout(tag_btn_row)
        self._tag_status = QLabel("detecting…")
        self._tag_status.setStyleSheet(f"color:{SUBTLE};font-size:8pt;")
        tl.addWidget(self._tag_status)
        root.addWidget(tag_grp)

        # Wire signal → slot before triggering the worker
        self._autodetect_result.connect(self._on_autodetect)
        # Kick off auto-detect in background after the UI is shown
        QTimer.singleShot(200, self._run_autodetect)

        # Notify listeners (e.g. sidebar summary) when any setting changes
        self.digits.valueChanged.connect(self.settings_changed)
        self.workers.valueChanged.connect(self.settings_changed)
        self.mode.currentIndexChanged.connect(self.settings_changed)
        self.ambient_c.valueChanged.connect(self.settings_changed)
        self.run_tag.textChanged.connect(self.settings_changed)

        nas = QGroupBox("Archive to NAS")
        nl  = QVBoxLayout(nas)
        self.archive_chk = QCheckBox("Upload report after run")
        self.archive_chk.setChecked(True); nl.addWidget(self.archive_chk)
        self.archive_chk.stateChanged.connect(self.settings_changed)
        nl.addWidget(QLabel("NAS IP:"))
        self.nas_ip = QLineEdit("192.168.200.36"); nl.addWidget(self.nas_ip)
        nl.addWidget(QLabel("SFTP user:"))
        self.sftp_user = QLineEdit(pb.DEFAULT_SFTP_USER); nl.addWidget(self.sftp_user)
        nl.addWidget(QLabel("SFTP password:"))
        pw_row = QHBoxLayout()
        self._pw_field = QLineEdit()
        self._pw_field.setEchoMode(QLineEdit.EchoMode.Password)
        self._pw_field.setPlaceholderText("(loaded from keyring)")
        pw_row.addWidget(self._pw_field, 1)
        self._save_btn = QPushButton("Save"); self._save_btn.setFixedWidth(48)
        self._save_btn.setToolTip("Save to OS keyring")
        self._save_btn.clicked.connect(self._save_pw)
        pw_row.addWidget(self._save_btn)
        nl.addLayout(pw_row)
        self._kr_lbl = QLabel()
        self._kr_lbl.setStyleSheet(f"color:{SUBTLE};font-size:8pt;")
        nl.addWidget(self._kr_lbl)
        self._try_load_keyring()
        root.addWidget(nas)
        root.addStretch()

    def _run_autodetect(self):
        """Detect RAM spec in a background thread so the UI never blocks.

        The worker emits _autodetect_result (a pyqtSignal) rather than calling
        QTimer.singleShot — signals are the correct way to marshal a result from
        a plain Python thread back onto the Qt main thread.
        """
        import threading
        self._tag_status.setText("detecting…")
        self._tag_status.setStyleSheet(f"color:{SUBTLE};font-size:8pt;")
        self._detect_btn.setEnabled(False)

        def _worker():
            spec = pb.detect_ram_spec()
            self._autodetect_result.emit(spec)  # always safe to emit from any thread

        threading.Thread(target=_worker, daemon=True).start()

    def _on_autodetect(self, spec):
        self._detect_btn.setEnabled(True)
        if spec:
            if not self.run_tag.text().strip():
                self.run_tag.setText(spec)
            self._tag_status.setText(f"detected: {spec}")
            self._tag_status.setStyleSheet(f"color:{COL_GOOD};font-size:8pt;")
        else:
            self._tag_status.setText("auto-detect unavailable — enter manually")
            self._tag_status.setStyleSheet(f"color:{SUBTLE};font-size:8pt;")

    def _try_load_keyring(self):
        user = self.sftp_user.text().strip() or pb.DEFAULT_SFTP_USER
        try:   pw = pb._keyring_get(user)
        except: pw = None
        if pw is not None:
            self._keyring_pw = pw
            self._kr_lbl.setText("✓ password loaded from keyring")
            self._kr_lbl.setStyleSheet(f"color:{COL_GOOD};font-size:8pt;")
        else:
            self._keyring_pw = None
            if self._pw_field.text().strip():
                self._kr_lbl.setText("using password from field")
                self._kr_lbl.setStyleSheet(f"color:{TEXT};font-size:8pt;")
            else:
                self._kr_lbl.setText("⚠ no password — enter below or archive is off")
                self._kr_lbl.setStyleSheet(f"color:{COL_POWER};font-size:8pt;")

    def _save_pw(self):
        pw = self._pw_field.text().strip()
        if not pw:
            self._kr_lbl.setText("⚠ enter a password first")
            self._kr_lbl.setStyleSheet(f"color:{COL_TEMP};font-size:8pt;"); return
        user = self.sftp_user.text().strip() or pb.DEFAULT_SFTP_USER
        try:
            pb._keyring_set(user, pw)
            self._pw_field.clear()
            self._try_load_keyring()
        except Exception as exc:
            self._kr_lbl.setText(f"✗ {exc}")
            self._kr_lbl.setStyleSheet(f"color:{COL_TEMP};font-size:8pt;")

    def reload_keyring(self): self._try_load_keyring()

    def get_config(self) -> dict:
        nas = self.nas_ip.text().strip() or "192.168.200.36"
        user = self.sftp_user.text().strip() or pb.DEFAULT_SFTP_USER
        pw   = self._pw_field.text().strip() or getattr(self,"_keyring_pw",None)
        if self.archive_chk.isChecked() and pw is None:
            self._kr_lbl.setText("⚠ no password — archive disabled")
            self._kr_lbl.setStyleSheet(f"color:{COL_TEMP};font-size:8pt;")
        return {
            "digits":        self.digits.value() * 1_000_000,
            "workers":       self.workers.value(),
            "mode":          self.mode.currentText(),
            "archive":       self.archive_chk.isChecked() and pw is not None,
            "sftp_password": pw,
            "smb_share":     f"//{nas}/Common-Room",
            "sftp_user":     user,
            "ambient_c":     self.ambient_c.value(),
            "run_tag":       self.run_tag.text().strip(),
        }


# ═══════════════════════════════════════════════════════════════════════════
#  MAIN WINDOW
# ═══════════════════════════════════════════════════════════════════════════

class MainWindow(QMainWindow):
    # Thread → main-thread signals for the update checker
    _update_available = pyqtSignal(str, str)   # version, download_url
    _update_failed    = pyqtSignal(str)         # error message

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Pi Bench  [dev]  v{pb.APP_VERSION}")
        self.setMinimumSize(1200, 760)
        self._thread: BenchmarkThread | None = None
        self._history = RunHistory()
        self._build_ui()

        # Wire update signals (bar is created inside _build_ui)
        self._update_available.connect(self._update_bar.notify)
        self._update_failed.connect(
            lambda msg: self.status_lbl.setText(f"Update check failed: {msg}"))

        # Check for updates 4 seconds after launch (non-blocking background thread)
        QTimer.singleShot(4000, self._check_for_update)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        # Sky-blue gradient painted directly on the central widget so it
        # shows through the transparent glass panels above it.
        central.setObjectName("_central")
        central.setStyleSheet(
            "QWidget#_central{"
            "background:qlineargradient(x1:0.3,y1:0,x2:0.7,y2:1,"
            "stop:0 #6EC8F8,"       # bright sky-blue top
            "stop:0.12 #3A9AE8,"   # mid sky
            "stop:0.35 #1A5CC0,"   # deeper blue
            "stop:0.65 #0B2850,"   # midnight blue
            "stop:1    #04091A);}" # near-black base
        )

        # Outer vertical layout: update bar (hidden by default) + main content
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)
        self._update_bar = UpdateBar()
        self._update_bar.update_clicked.connect(self._do_update)
        outer.addWidget(self._update_bar)

        inner = QWidget()
        inner.setStyleSheet("background:transparent;")   # let sky gradient show through
        outer.addWidget(inner, 1)
        root = QHBoxLayout(inner)
        root.setContentsMargins(10,10,10,10); root.setSpacing(10)

        # ── Left sidebar (slim: system info + config summary + run button) ──
        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0); left.setSpacing(8)

        # System info group
        info = QGroupBox("System")
        il   = QVBoxLayout(info); il.setSpacing(2)
        si   = pb.system_info(); cpu = pb.detect_cpu_name()
        for lbl, val in [("CPU", cpu), ("Cores", str(si["logical_cpus"])),
                          ("Python", si["python"])]:
            row = QHBoxLayout()
            lb = QLabel(lbl); lb.setStyleSheet(f"color:{SUBTLE};font-size:8pt;"); lb.setFixedWidth(46)
            vl = QLabel(val); vl.setStyleSheet(f"color:{TEXT};font-size:8pt;"); vl.setWordWrap(True)
            row.addWidget(lb); row.addWidget(vl, 1)
            il.addLayout(row)
        left.addWidget(info)

        # Compact run-config summary — auto-updates when settings change
        cfg_grp = QGroupBox("Run Config")
        cl = QVBoxLayout(cfg_grp); cl.setContentsMargins(6, 4, 6, 6)
        self._cfg_summary = QLabel("—")
        self._cfg_summary.setStyleSheet(f"color:{TEXT};font-size:8pt;")
        self._cfg_summary.setWordWrap(True)
        open_btn = QPushButton("Edit settings…")
        open_btn.setStyleSheet(f"font-size:8pt; padding:2px 6px;")
        open_btn.clicked.connect(lambda: self._tabs.setCurrentIndex(
            next(i for i in range(self._tabs.count())
                 if "Settings" in self._tabs.tabText(i))))
        cl.addWidget(self._cfg_summary)
        cl.addWidget(open_btn)
        left.addWidget(cfg_grp)

        left.addStretch()

        self.run_btn = QPushButton("▶  Run Benchmark")
        self.run_btn.setMinimumHeight(46)
        self.run_btn.setStyleSheet(
            # Chrome-gloss aqua pill — classic Frutiger Aero "gel" button:
            # bright white upper half, deep aqua lower half, white border glow
            "QPushButton{"
            "background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "stop:0 rgba(255,255,255,230),"   # bright white top gloss
            "stop:0.46 rgba(0,220,255,200),"  # aqua mid-top
            "stop:0.5  rgba(0,160,220,230),"  # seam
            "stop:1    rgba(0,80,160,255));"  # deep blue bottom
            "color:#001830;font-weight:bold;border-radius:12px;font-size:12pt;"
            "border:1px solid rgba(255,255,255,200);"
            "}"
            "QPushButton:hover{"
            "background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "stop:0 rgba(255,255,255,255),"
            "stop:0.46 rgba(80,240,255,220),"
            "stop:0.5  rgba(0,200,240,240),"
            "stop:1    rgba(0,120,200,255));"
            "border:1px solid rgba(255,255,255,255);}"
            "QPushButton:pressed{"
            "background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "stop:0 rgba(0,120,200,255),stop:1 rgba(0,60,140,255));}"
            f"QPushButton:disabled{{background:rgba(20,50,90,0.6);"
            f"color:{SUBTLE};border-color:rgba(255,255,255,40);}}")
        self.run_btn.clicked.connect(self._start)
        left.addWidget(self.run_btn)
        self.status_lbl = QLabel("Ready")
        self.status_lbl.setWordWrap(True)
        self.status_lbl.setStyleSheet(f"color:{SUBTLE};font-size:9pt;")
        left.addWidget(self.status_lbl)
        left_w = QWidget(); left_w.setLayout(left)
        left_w.setFixedWidth(180)
        left_w.setStyleSheet("background:transparent;")  # let sky show through sidebar

        # ── Right: tab widget ────────────────────────────────────────────
        self._tabs = QTabWidget()
        # Global QSS handles tab styling; no inline override needed.

        # Tab 0 — Live
        live_w = QWidget()
        live_w.setStyleSheet("background:transparent;")
        ll     = QVBoxLayout(live_w); ll.setContentsMargins(0,0,0,0); ll.setSpacing(6)
        self.stat_bar = StatBar(); ll.addWidget(self.stat_bar)
        spl   = QSplitter(Qt.Orientation.Vertical)
        self.chart = DualLiveChart(); spl.addWidget(self.chart)
        self.log   = QTextEdit(); self.log.setReadOnly(True)
        self.log.setFont(QFont("Consolas",9))
        self.log.setStyleSheet(f"background:{PANEL_BG};color:{TEXT};")
        spl.addWidget(self.log); spl.setSizes([520,200]); ll.addWidget(spl,1)
        self._tabs.addTab(live_w, "Live")

        # Tab 1 — Results (persists across runs until a new run finishes)
        self._results_view = ResultsView()
        self._tabs.addTab(self._results_view, "Results")

        # Tab 2 — Reports
        self._reports_tab = ReportsTab(self._history)
        self._tabs.addTab(self._reports_tab, "Reports")

        # Tab 3 — Compare
        self._compare_tab = CompareTab(self._history)
        self._tabs.addTab(self._compare_tab, "Compare")

        # Tab 4 — History
        self._history_tab = HistoryTab(self._history)
        self._history_tab.run_selected.connect(self._on_history_run_selected)
        self._tabs.addTab(self._history_tab, "History")

        # Tab 5 — Settings (SettingsPanel in a scroll area)
        self.settings = SettingsPanel()
        self.settings.settings_changed.connect(self._refresh_config_summary)
        # Populate summary once autodetect fires (give the worker time to finish)
        QTimer.singleShot(600, self._refresh_config_summary)
        _settings_scroll = QScrollArea()
        _settings_scroll.setWidgetResizable(True)
        _settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        _settings_scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}"
                                        "QScrollArea>QWidget>QWidget{background:transparent;}")
        _settings_scroll.setWidget(self.settings)
        self._tabs.addTab(_settings_scroll, "⚙  Settings")

        root.addWidget(left_w)
        root.addWidget(self._tabs, 1)

    # ------------------------------------------------------------------
    def _refresh_config_summary(self):
        """Update the compact run-config summary label on the left sidebar."""
        s = self.settings
        digits_m = s.digits.value()
        mode     = s.mode.currentText()
        workers  = s.workers.value()
        ambient  = s.ambient_c.value()
        tag      = s.run_tag.text().strip()
        archive  = s.archive_chk.isChecked()
        lines = [
            f"{digits_m}M digits · {mode}",
            f"{workers} workers · {ambient}°C",
        ]
        if tag:
            lines.append(f"Tag: {tag}")
        lines.append(f"Archive: {'on' if archive else 'off'}")
        self._cfg_summary.setText("\n".join(lines))

    # ------------------------------------------------------------------
    def _check_for_update(self):
        """Spawn a background thread to query GitHub for a newer release."""
        import threading
        def _worker():
            try:
                version, url = pb.check_for_update()
                if version:
                    self._update_available.emit(version, url)
            except Exception as exc:
                self._update_failed.emit(str(exc))
        threading.Thread(target=_worker, daemon=True).start()

    def _do_update(self, version: str, url: str):
        """Download the installer and run it silently, then quit."""
        import threading, urllib.request
        self._update_bar.set_downloading()
        self.run_btn.setEnabled(False)
        self.status_lbl.setText(f"Downloading Pi Bench {version}…")

        def _worker():
            try:
                tmp_dir = tempfile.mkdtemp(prefix="pibench_update_")
                installer = os.path.join(tmp_dir, f"PiBenchSetup_{version}.exe")
                urllib.request.urlretrieve(url, installer)

                # Launch the installer as a fully detached process so it
                # survives after this process exits.
                # /SILENT    — progress window, no wizard pages
                # /NORESTART — never auto-reboot
                # Do NOT pass /CLOSEAPPLICATIONS — that tells Inno Setup to
                # kill running instances itself, which deadlocks because this
                # process is still alive waiting for the Popen to return.
                # We close ourselves immediately below instead.
                flags = 0
                if hasattr(subprocess, "DETACHED_PROCESS"):
                    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                subprocess.Popen([installer, "/SILENT", "/NORESTART"], creationflags=flags)

                # Quit must be scheduled on the main thread — calling
                # QApplication.quit() directly from a worker thread is not
                # thread-safe and will be silently ignored by Qt.
                QTimer.singleShot(0, QApplication.quit)
            except Exception as exc:
                self._update_failed.emit(str(exc))
                self.run_btn.setEnabled(True)

        threading.Thread(target=_worker, daemon=True).start()

    # ------------------------------------------------------------------
    def closeEvent(self, event):
        """On window close: cancel any live benchmark before exiting."""
        if self._thread and self._thread.isRunning():
            self.status_lbl.setText("Stopping workers…")
            self._thread.cancel()   # kills OS processes + terminates QThread
        _kill_workers()             # belt-and-suspenders: catch anything missed
        event.accept()

    # ------------------------------------------------------------------
    def _start(self):
        if self._thread and self._thread.isRunning():
            return
        self.chart.reset(); self.stat_bar.clear(); self.log.clear()
        self._tabs.setCurrentIndex(0)
        self.run_btn.setEnabled(False)
        self.status_lbl.setText("Running…")
        self.settings.reload_keyring()
        cfg = self.settings.get_config()
        pb.DEFAULT_SMB_SHARE = cfg["smb_share"]
        pb.DEFAULT_SFTP_USER = cfg["sftp_user"]

        self._thread = BenchmarkThread(cfg)
        self._thread.progress.connect(self._on_progress)
        self._thread.phase_changed.connect(self.chart.set_active)
        self._thread.core_labels.connect(self.chart.set_core_labels)
        self._thread.log_line.connect(self._on_log)
        self._thread.run_finished.connect(self._on_finished)
        self._thread.run_report.connect(self._on_report)
        self._thread.archive_status.connect(self._on_log)
        self._thread.start()

    def _on_progress(self, elapsed, done, total, busy, mhz, temp, power,
                     core_clocks, core_temps):
        self.chart.add_point(elapsed, temp, power, mhz, core_clocks, core_temps)
        self.stat_bar.update_stats(elapsed, done, total, busy, mhz, temp, power)

    def _on_log(self, line):
        self.log.append(line)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def _on_report(self, report: dict):
        # Save to disk
        try:
            self._history.save(report)
        except Exception as exc:
            self._on_log(f"[history] save failed: {exc}")

        # Populate Results tab
        self._results_view.load_report(report)

        # Refresh history tabs
        self._reports_tab.show_run(report)
        self._compare_tab.refresh()
        self._history_tab.refresh()

        # Switch to Results tab after a beat
        QTimer.singleShot(400, lambda: self._tabs.setCurrentIndex(1))

    def _on_history_run_selected(self, run_data: dict):
        """Load a historical run into the Reports tab and switch to it."""
        self._reports_tab.show_run(run_data)
        # Find and switch to Reports tab (index 2)
        for i in range(self._tabs.count()):
            if self._tabs.tabText(i) == "Reports":
                self._tabs.setCurrentIndex(i)
                break

    def _on_finished(self, results: dict):
        self.run_btn.setEnabled(True)
        self.status_lbl.setText("Done")


# ═══════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════

def main():
    mp.freeze_support()
    pg.setConfigOptions(antialias=True, background=PANEL_BG, foreground=SUBTLE)
    app = QApplication(sys.argv)
    _apply_dark_palette(app)

    splash = SplashScreen()
    _win   = []

    def _launch():
        splash.close()
        w = MainWindow()
        _win.append(w)
        w.show()

    splash.launch_requested.connect(_launch)
    splash.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
