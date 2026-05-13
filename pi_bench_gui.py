"""
pi_bench_gui.py — Native desktop frontend for pi_bench.

Requires:
    pip install PyQt6 pyqtgraph

Workers run as OS processes (ProcessPoolExecutor inside pi_bench.run_multi /
run_single) — the GUI thread never touches the GIL during computation.
Progress data flows: HeartbeatReporter callback → BenchmarkThread signal →
Qt main thread → live chart update.
"""

import argparse
import io
import multiprocessing as mp
import os
import platform
import sys

# ── PyQt6 ──────────────────────────────────────────────────────────────────
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QPalette
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QPushButton, QSpinBox, QSplitter, QTextEdit,
    QVBoxLayout, QWidget, QFrame,
)

# ── pyqtgraph ──────────────────────────────────────────────────────────────
import pyqtgraph as pg

# ── benchmark core ─────────────────────────────────────────────────────────
# pi_bench.py must live in the same directory as this file.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pi_bench as pb


# ---------------------------------------------------------------------------
# Dark palette (applied to the whole app)
# ---------------------------------------------------------------------------
DARK_BG      = "#1e1e2e"
PANEL_BG     = "#2a2a3e"
ACCENT       = "#cba6f7"   # lavender
TEXT         = "#cdd6f4"
SUBTLE       = "#6c7086"
COL_TEMP     = "#f38ba8"   # red-ish
COL_POWER    = "#fab387"   # peach
COL_FREQ     = "#89dceb"   # sky blue
COL_BUSY     = "#a6e3a1"   # green


def _apply_dark_palette(app: QApplication):
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window,          QColor(DARK_BG))
    pal.setColor(QPalette.ColorRole.WindowText,      QColor(TEXT))
    pal.setColor(QPalette.ColorRole.Base,            QColor(PANEL_BG))
    pal.setColor(QPalette.ColorRole.AlternateBase,   QColor(DARK_BG))
    pal.setColor(QPalette.ColorRole.ToolTipBase,     QColor(PANEL_BG))
    pal.setColor(QPalette.ColorRole.ToolTipText,     QColor(TEXT))
    pal.setColor(QPalette.ColorRole.Text,            QColor(TEXT))
    pal.setColor(QPalette.ColorRole.Button,          QColor(PANEL_BG))
    pal.setColor(QPalette.ColorRole.ButtonText,      QColor(TEXT))
    pal.setColor(QPalette.ColorRole.BrightText,      QColor("#ffffff"))
    pal.setColor(QPalette.ColorRole.Highlight,       QColor(ACCENT))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#000000"))
    app.setPalette(pal)


# ---------------------------------------------------------------------------
# BenchmarkThread — wraps pi_bench functions; workers are OS processes
# ---------------------------------------------------------------------------
class BenchmarkThread(QThread):
    """
    Runs archive_setup → run_multi/run_single → archive_finalize in a
    background QThread.  The actual Chudnovsky workers are spawned as
    separate OS processes by ProcessPoolExecutor — no GIL, full CPU pressure.

    Signals (all safe to connect directly to Qt widgets):
        progress(elapsed_s, workers_done, workers_total,
                 busy_pct, mhz, temp_c, power_w)
        log_line(text)
        run_finished(result_dict)
        archive_status(text)
    """

    progress       = pyqtSignal(float, int, int, float, float, float, float)
    log_line       = pyqtSignal(str)
    run_finished   = pyqtSignal(dict)
    archive_status = pyqtSignal(str)

    def __init__(self, config: dict):
        super().__init__()
        self.config = config

    # ------------------------------------------------------------------
    def run(self):
        cfg = self.config

        # Build an argparse.Namespace so we can reuse archive_setup /
        # archive_finalize without duplicating their logic.
        args = argparse.Namespace(
            digits       = cfg["digits"],
            mode         = cfg["mode"],
            workers      = cfg["workers"],
            json         = False,
            archive      = cfg.get("archive", False),
            smb_share    = cfg.get("smb_share", pb.DEFAULT_SMB_SHARE),
            smb_user     = pb.DEFAULT_SMB_USER,
            smb_subdir   = pb.DEFAULT_SMB_SUBDIR,
            sftp_user    = cfg.get("sftp_user", pb.DEFAULT_SFTP_USER),
            sftp_path    = pb.DEFAULT_SFTP_PATH,
            sftp_password= cfg.get("sftp_password"),   # always explicit from GUI
        )

        pb.sys.setrecursionlimit(100_000)
        pb._raise_int_str_limit(args.digits)

        # Stub stdin so archive_setup never blocks on getpass — the GUI
        # always supplies the password explicitly via args.sftp_password.
        class _NoTTY:
            def isatty(self): return False
            def read(self, *_): return ""
            def readline(self, *_): return ""

        old_stdin = pb.sys.stdin
        pb.sys.stdin = _NoTTY()

        # ── Archive setup (Windows: SFTP creds + LHM; Linux: turbostat) ──
        archive_state = {"enabled": False}
        if args.archive:
            self.archive_status.emit("[archive] setting up…")
            archive_state = pb.archive_setup(args)
            pb.sys.stdin = old_stdin   # restore before benchmark runs

        # ── Always start LHM on Windows for live chart data ───────────────
        # archive_setup already started a sampler when archive is enabled.
        # When archive is off (or failed), start our own sampler here so the
        # charts still get data — LHM is always needed on Windows.
        own_lhm = None
        if platform.system() == "Windows":
            lhm_sampler = archive_state.get("lhm_sampler")
            if lhm_sampler is None:
                try:
                    self.log_line.emit("[lhm] ensuring LibreHardwareMonitor is running…")
                    if pb.lhm_ensure_running():
                        own_lhm = pb.LHMSampler(interval=1.0)
                        own_lhm.start()
                        self.log_line.emit("[lhm] sampler started (1 Hz)")
                        lhm_sampler = own_lhm
                    else:
                        self.log_line.emit("[lhm] could not start LHM — charts will be empty")
                except Exception as exc:
                    self.log_line.emit(f"[lhm] error starting sampler: {exc}")
        else:
            lhm_sampler = archive_state.get("lhm_sampler")

        raw_turbo    = archive_state.get("raw_path")
        fans         = archive_state.get("fans")
        fan_samples  = archive_state.get("fan_samples")

        # ── Progress callback: HeartbeatReporter → this thread → GUI ──
        def on_progress(elapsed, done, total, busy, mhz, temp, power):
            self.progress.emit(elapsed, done, total, busy, mhz, temp, power)

        # ── Redirect stdout so we can capture it AND send it to the log ──
        captured   = io.StringIO()
        log_signal = self.log_line

        class _Tee:
            def write(self, txt):
                captured.write(txt)
                if txt.strip():
                    log_signal.emit(txt.rstrip())
            def flush(self): pass
            def isatty(self): return False

        old_stdout = pb.sys.stdout
        pb.sys.stdout = _Tee()

        results = {}
        try:
            if args.mode in ("single", "both"):
                results["single"] = pb.run_single(
                    args.digits, quiet=False,
                    raw_turbo_path=raw_turbo,
                    fans=fans, fan_samples=fan_samples,
                    lhm_sampler=lhm_sampler,
                    progress_callback=on_progress,
                )
            if args.mode in ("multi", "both"):
                results["multi"] = pb.run_multi(
                    args.digits, args.workers, quiet=False,
                    raw_turbo_path=raw_turbo,
                    fans=fans, fan_samples=fan_samples,
                    lhm_sampler=lhm_sampler,
                    progress_callback=on_progress,
                )
        finally:
            pb.sys.stdout = old_stdout
            pb.sys.stdin  = old_stdin
            # Stop the sampler we own (archive_finalize stops its own sampler)
            if own_lhm is not None:
                own_lhm.stop()
                self.log_line.emit(
                    f"[lhm] sampler stopped: {own_lhm.sample_count()} samples")
            if args.archive:
                self.archive_status.emit("[archive] finalising…")
                pb.archive_finalize(args, archive_state, captured.getvalue())
                self.archive_status.emit("[archive] done")

        self.run_finished.emit(results)


# ---------------------------------------------------------------------------
# LiveChart — three stacked pyqtgraph plots, X-linked
# ---------------------------------------------------------------------------
class LiveChart(pg.GraphicsLayoutWidget):
    def __init__(self):
        super().__init__()
        self.setBackground(DARK_BG)

        self._t  = []
        self._tc = []   # temperature °C
        self._pw = []   # package power W
        self._mz = []   # max core MHz
        self._by = []   # busy %

        label_style = {"color": TEXT, "font-size": "10pt"}
        tick_style  = {"color": SUBTLE}

        # ── Temperature ──────────────────────────────────────────────────
        self.p_temp = self.addPlot(row=0, col=0)
        self.p_temp.setLabel("left", "Temp (°C)", **label_style)
        self.p_temp.showGrid(x=True, y=True, alpha=0.15)
        self.p_temp.getAxis("bottom").setStyle(showValues=False)
        self.c_temp = self.p_temp.plot(pen=pg.mkPen(COL_TEMP, width=2))

        # ── Power ────────────────────────────────────────────────────────
        self.p_power = self.addPlot(row=1, col=0)
        self.p_power.setLabel("left", "Power (W)", **label_style)
        self.p_power.showGrid(x=True, y=True, alpha=0.15)
        self.p_power.getAxis("bottom").setStyle(showValues=False)
        self.c_power = self.p_power.plot(pen=pg.mkPen(COL_POWER, width=2))

        # ── Frequency ────────────────────────────────────────────────────
        self.p_freq = self.addPlot(row=2, col=0)
        self.p_freq.setLabel("left", "Freq (MHz)", **label_style)
        self.p_freq.setLabel("bottom", "Elapsed (s)", **label_style)
        self.p_freq.showGrid(x=True, y=True, alpha=0.15)
        self.c_freq = self.p_freq.plot(pen=pg.mkPen(COL_FREQ, width=2))

        # Link X axes so panning/zooming stays in sync
        self.p_power.setXLink(self.p_temp)
        self.p_freq.setXLink(self.p_temp)

        # Equal height rows
        self.ci.layout.setRowStretchFactor(0, 1)
        self.ci.layout.setRowStretchFactor(1, 1)
        self.ci.layout.setRowStretchFactor(2, 1)

    def add_point(self, elapsed: float, temp: float, power: float, mhz: float):
        self._t.append(elapsed)
        self._tc.append(temp)
        self._pw.append(power)
        self._mz.append(mhz)
        self.c_temp.setData(self._t, self._tc)
        self.c_power.setData(self._t, self._pw)
        self.c_freq.setData(self._t, self._mz)

    def reset(self):
        self._t.clear(); self._tc.clear(); self._pw.clear(); self._mz.clear()
        self.c_temp.setData([], [])
        self.c_power.setData([], [])
        self.c_freq.setData([], [])


# ---------------------------------------------------------------------------
# StatBar — compact live stat display above the chart
# ---------------------------------------------------------------------------
class StatBar(QWidget):
    def __init__(self):
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 4, 6, 4)
        row.setSpacing(24)

        def _stat(label, color):
            col = QVBoxLayout()
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color: {SUBTLE}; font-size: 9pt;")
            val = QLabel("—")
            val.setStyleSheet(f"color: {color}; font-size: 15pt; font-weight: bold;")
            col.addWidget(lbl)
            col.addWidget(val)
            row.addLayout(col)
            return val

        self.v_temp  = _stat("TEMP",    COL_TEMP)
        self.v_power = _stat("PACKAGE", COL_POWER)
        self.v_freq  = _stat("FREQ",    COL_FREQ)
        self.v_busy  = _stat("BUSY",    COL_BUSY)
        self.v_prog  = _stat("WORKERS", TEXT)
        self.v_time  = _stat("ELAPSED", TEXT)
        row.addStretch()

    def update_stats(self, elapsed, done, total, busy, mhz, temp, power):
        self.v_temp.setText(f"{temp:.0f} °C")
        self.v_power.setText(f"{power:.1f} W")
        self.v_freq.setText(f"{mhz:.0f} MHz")
        self.v_busy.setText(f"{busy:.0f} %")
        self.v_prog.setText(f"{done} / {total}")
        self.v_time.setText(f"{elapsed:.0f} s")

    def clear(self):
        for v in (self.v_temp, self.v_power, self.v_freq,
                  self.v_busy, self.v_prog, self.v_time):
            v.setText("—")


# ---------------------------------------------------------------------------
# SettingsPanel — left sidebar
# ---------------------------------------------------------------------------
class SettingsPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedWidth(230)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        # ── Benchmark ────────────────────────────────────────────────────
        bench = QGroupBox("Benchmark")
        bl = QVBoxLayout(bench)

        bl.addWidget(QLabel("Digits (millions):"))
        self.digits = QSpinBox()
        self.digits.setRange(1, 500)
        self.digits.setValue(5)
        self.digits.setToolTip("Higher = longer, more thermal stress")
        bl.addWidget(self.digits)

        bl.addWidget(QLabel("Workers:"))
        self.workers = QSpinBox()
        self.workers.setRange(1, 256)
        self.workers.setValue(os.cpu_count() or 4)
        self.workers.setToolTip("Typically = logical CPU count for max stress")
        bl.addWidget(self.workers)

        bl.addWidget(QLabel("Mode:"))
        self.mode = QComboBox()
        self.mode.addItems(["both", "multi", "single"])
        bl.addWidget(self.mode)

        root.addWidget(bench)

        # ── Archive / NAS ─────────────────────────────────────────────
        nas = QGroupBox("Archive to NAS")
        nl = QVBoxLayout(nas)

        self.archive_chk = QCheckBox("Upload report after run")
        self.archive_chk.setChecked(True)
        nl.addWidget(self.archive_chk)

        nl.addWidget(QLabel("NAS IP:"))
        self.nas_ip = QLineEdit("192.168.200.36")
        nl.addWidget(self.nas_ip)

        nl.addWidget(QLabel("SFTP user:"))
        self.sftp_user = QLineEdit(pb.DEFAULT_SFTP_USER)
        nl.addWidget(self.sftp_user)

        nl.addWidget(QLabel("SFTP password:"))
        pw_row = QHBoxLayout()
        self._pw_field = QLineEdit()
        self._pw_field.setEchoMode(QLineEdit.EchoMode.Password)
        self._pw_field.setPlaceholderText("(loaded from keyring)")
        pw_row.addWidget(self._pw_field, 1)

        self._save_pw_btn = QPushButton("Save")
        self._save_pw_btn.setFixedWidth(48)
        self._save_pw_btn.setToolTip("Save password to OS keyring")
        self._save_pw_btn.clicked.connect(self._save_password)
        pw_row.addWidget(self._save_pw_btn)
        nl.addLayout(pw_row)

        self._keyring_status = QLabel()
        self._keyring_status.setStyleSheet(f"color: {SUBTLE}; font-size: 8pt;")
        nl.addWidget(self._keyring_status)

        # Try to load credential from keyring on startup
        self._try_load_keyring()

        root.addWidget(nas)
        root.addStretch()

    def _try_load_keyring(self):
        """Attempt to read the SFTP credential from the OS keyring.
        Called on startup and again on every Run click.
        The password is never shown in the field — field stays as placeholder.
        """
        user = self.sftp_user.text().strip() or pb.DEFAULT_SFTP_USER
        try:
            pw = pb._keyring_get(user)
        except Exception:
            pw = None
        if pw is not None:
            self._keyring_pw = pw
            self._keyring_status.setText("✓ password loaded from keyring")
            self._keyring_status.setStyleSheet("color: #a6e3a1; font-size: 8pt;")
        else:
            self._keyring_pw = None
            typed = self._pw_field.text().strip()
            if typed:
                self._keyring_status.setText("using password from field")
                self._keyring_status.setStyleSheet(f"color: {TEXT}; font-size: 8pt;")
            else:
                self._keyring_status.setText("⚠ no password — enter below or archive is off")
                self._keyring_status.setStyleSheet(f"color: {COL_POWER}; font-size: 8pt;")

    def _save_password(self):
        """Save the typed password to the OS keyring, then reload status."""
        pw = self._pw_field.text().strip()
        if not pw:
            self._keyring_status.setText("⚠ enter a password first")
            self._keyring_status.setStyleSheet(f"color: {COL_TEMP}; font-size: 8pt;")
            return
        user = self.sftp_user.text().strip() or pb.DEFAULT_SFTP_USER
        try:
            pb._keyring_set(user, pw)
            self._pw_field.clear()          # don't leave plaintext in the field
            self._try_load_keyring()        # re-read + update status label
        except Exception as exc:
            self._keyring_status.setText(f"✗ keyring error: {exc}")
            self._keyring_status.setStyleSheet(f"color: {COL_TEMP}; font-size: 8pt;")

    def reload_keyring(self):
        """Re-check keyring (called on every Run click)."""
        self._try_load_keyring()

    def get_config(self) -> dict:
        nas_ip = self.nas_ip.text().strip() or "192.168.200.36"
        smb_share = f"//{nas_ip}/Common-Room"
        user = self.sftp_user.text().strip() or pb.DEFAULT_SFTP_USER

        # Password priority: typed in field → keyring (loaded on startup) → None
        # We always pass it explicitly so archive_setup never falls through to getpass.
        pw = self._pw_field.text().strip() or getattr(self, "_keyring_pw", None)

        if self.archive_chk.isChecked() and pw is None:
            self._keyring_status.setText("⚠ no password — archive disabled for this run")
            self._keyring_status.setStyleSheet(f"color: {COL_TEMP}; font-size: 8pt;")

        return {
            "digits"        : self.digits.value() * 1_000_000,
            "workers"       : self.workers.value(),
            "mode"          : self.mode.currentText(),
            "archive"       : self.archive_chk.isChecked() and pw is not None,
            "sftp_password" : pw,
            "smb_share"     : smb_share,
            "sftp_user"     : user,
        }


# ---------------------------------------------------------------------------
# MainWindow
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Pi Bench")
        self.setMinimumSize(1150, 740)
        self._thread: BenchmarkThread | None = None
        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        # ── Left: settings + run button ──────────────────────────────────
        left = QVBoxLayout()
        self.settings = SettingsPanel()
        left.addWidget(self.settings)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {SUBTLE};")
        left.addWidget(sep)

        # ── System info ──────────────────────────────────────────────────
        info_box = QGroupBox("System")
        info_layout = QVBoxLayout(info_box)
        info_layout.setSpacing(2)
        sysinfo = pb.system_info()
        cpu_name = pb.detect_cpu_name()
        for label, value in [
            ("CPU",     cpu_name),
            ("Cores",   str(sysinfo["logical_cpus"])),
            ("Python",  sysinfo["python"]),
        ]:
            row = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color: {SUBTLE}; font-size: 8pt;")
            lbl.setFixedWidth(46)
            val = QLabel(value)
            val.setStyleSheet(f"color: {TEXT}; font-size: 8pt;")
            val.setWordWrap(True)
            row.addWidget(lbl)
            row.addWidget(val, 1)
            info_layout.addLayout(row)
        left.addWidget(info_box)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {SUBTLE};")
        left.addWidget(sep2)

        self.run_btn = QPushButton("▶  Run Benchmark")
        self.run_btn.setMinimumHeight(46)
        self.run_btn.setStyleSheet(
            f"QPushButton {{ background: {ACCENT}; color: #000; font-weight: bold;"
            f"  border-radius: 6px; font-size: 12pt; }}"
            f"QPushButton:hover {{ background: #b4befe; }}"
            f"QPushButton:disabled {{ background: {SUBTLE}; color: #888; }}"
        )
        self.run_btn.clicked.connect(self._start)
        left.addWidget(self.run_btn)

        self.status_lbl = QLabel("Ready")
        self.status_lbl.setWordWrap(True)
        self.status_lbl.setStyleSheet(f"color: {SUBTLE}; font-size: 9pt;")
        left.addWidget(self.status_lbl)

        left_widget = QWidget()
        left_widget.setLayout(left)

        # ── Right: stat bar + chart + log ────────────────────────────────
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        self.stat_bar = StatBar()
        right_layout.addWidget(self.stat_bar)

        splitter = QSplitter(Qt.Orientation.Vertical)

        self.chart = LiveChart()
        splitter.addWidget(self.chart)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont("Consolas", 9))
        self.log.setStyleSheet(f"background: {PANEL_BG}; color: {TEXT};")
        splitter.addWidget(self.log)
        splitter.setSizes([520, 200])

        right_layout.addWidget(splitter, 1)

        root.addWidget(left_widget)
        root.addWidget(right, 1)

    # ------------------------------------------------------------------
    def closeEvent(self, event):
        """Stop any running benchmark thread before closing."""
        if self._thread and self._thread.isRunning():
            self._thread.requestInterruption()
            self._thread.quit()
            self._thread.wait(3000)
        event.accept()

    # ------------------------------------------------------------------
    def _start(self):
        if self._thread and self._thread.isRunning():
            return

        self.chart.reset()
        self.stat_bar.clear()
        self.log.clear()
        self.run_btn.setEnabled(False)
        self.status_lbl.setText("Running…")

        # Re-check keyring on every run (in case it was populated since the GUI opened)
        self.settings.reload_keyring()
        config = self.settings.get_config()

        # Patch the NAS share into the pb defaults so archive_setup picks it up
        pb.DEFAULT_SMB_SHARE = config["smb_share"]
        pb.DEFAULT_SFTP_USER = config["sftp_user"]

        self._thread = BenchmarkThread(config)
        self._thread.progress.connect(self._on_progress)
        self._thread.log_line.connect(self._on_log)
        self._thread.run_finished.connect(self._on_finished)
        self._thread.archive_status.connect(self._on_log)
        self._thread.start()

    # ------------------------------------------------------------------
    def _on_progress(self, elapsed, done, total, busy, mhz, temp, power):
        self.chart.add_point(elapsed, temp, power, mhz)
        self.stat_bar.update_stats(elapsed, done, total, busy, mhz, temp, power)

    def _on_log(self, line: str):
        self.log.append(line)
        sb = self.log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_finished(self, results: dict):
        self.run_btn.setEnabled(True)
        self.status_lbl.setText("Done")

        lines = ["\n══ Results ══"]
        for mode_key in ("single", "multi"):
            r = results.get(mode_key)
            if r is None:
                continue
            lines.append(f"\n[{mode_key}]")
            lines.append(f"  Wall time  : {r['wall_s']:.3f} s")
            if mode_key == "multi":
                lines.append(f"  Workers    : {r['workers']}")
                lines.append(f"  Throughput : {r['aggregate_throughput_digits_per_sec']:,.0f} digits/s")
            else:
                lines.append(f"  Throughput : {r.get('throughput_digits_per_sec', 0):,.0f} digits/s")
            ref = "✓ OK" if r.get("verified_reference") else "✗ FAIL"
            lines.append(f"  Reference  : {ref}")
            if mode_key == "multi":
                cw  = "✓ OK" if r.get("cross_worker_consistent") else "✗ FAIL"
                lines.append(f"  Cross-check: {cw}")

        for ln in lines:
            self._on_log(ln)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    mp.freeze_support()          # needed if ever compiled to .exe
    pg.setConfigOptions(antialias=True, background=DARK_BG, foreground=TEXT)

    app = QApplication(sys.argv)
    _apply_dark_palette(app)

    win = MainWindow()
    win.show()
    sys.exit(app.exec())
