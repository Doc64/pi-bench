#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  Pi Bench — Linux / macOS installer
#
#  Usage:
#    bash setup.sh            Install Pi Bench
#    bash setup.sh --uninstall  Remove Pi Bench
#
#  Install location:  ~/.local/share/pi-bench/
#  Launcher command:  pi-bench  (added to ~/.local/bin/)
#  Desktop entry:     ~/.local/share/applications/pi-bench.desktop
#  Uninstall:         pi-bench --uninstall
#                 OR  bash ~/.local/share/pi-bench/setup.sh --uninstall
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$HOME/.local/share/pi-bench"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"
LAUNCHER="$BIN_DIR/pi-bench"
DESKTOP_FILE="$DESKTOP_DIR/pi-bench.desktop"

# ── Uninstall ─────────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--uninstall" ]]; then
    echo ""
    echo "============================================================"
    echo "  Pi Bench Uninstaller"
    echo "============================================================"
    echo ""

    # Run uninstall.py to clean up keyring, LHM, models, run history
    if [ -f "$INSTALL_DIR/venv/bin/python" ] && [ -f "$INSTALL_DIR/uninstall.py" ]; then
        echo "  Cleaning up app data (keyring, LHM download, run history)..."
        "$INSTALL_DIR/venv/bin/python" "$INSTALL_DIR/uninstall.py" --yes || true
    fi

    echo "  Removing install directory..."
    rm -rf "$INSTALL_DIR"

    echo "  Removing launcher command..."
    rm -f "$LAUNCHER"

    echo "  Removing desktop entry..."
    rm -f "$DESKTOP_FILE"

    # Update desktop database if available
    command -v update-desktop-database &>/dev/null && \
        update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true

    echo ""
    echo "  Pi Bench has been removed."
    echo ""
    exit 0
fi

# ── Install ───────────────────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo "  Pi Bench Setup"
echo "============================================================"
echo "  Install location : $INSTALL_DIR"
echo "  Launcher         : $LAUNCHER  (pi-bench)"
echo "  Desktop entry    : $DESKTOP_FILE"
echo ""

# ── [1/5] Find Python 3.10+ ──────────────────────────────────────────────────
echo "[1/5] Checking for Python 3.10+ ..."
PYEXE=""
for cmd in python3.12 python3.11 python3.10 python3 python; do
    if command -v "$cmd" &>/dev/null; then
        if "$cmd" -c "import sys; assert sys.version_info >= (3,10)" 2>/dev/null; then
            PYEXE=$(command -v "$cmd")
            break
        fi
    fi
done

if [ -z "$PYEXE" ]; then
    echo "      Python 3.10+ not found — attempting auto-install ..."
    if command -v apt-get &>/dev/null; then
        sudo apt-get update -qq
        sudo apt-get install -y python3 python3-venv python3-pip
        PYEXE=$(command -v python3)
    elif command -v dnf &>/dev/null; then
        sudo dnf install -y python3 python3-pip
        PYEXE=$(command -v python3)
    elif command -v pacman &>/dev/null; then
        sudo pacman -Sy --noconfirm python
        PYEXE=$(command -v python3)
    elif command -v brew &>/dev/null; then
        brew install python@3.12
        PYEXE=$(command -v python3.12)
    else
        echo "ERROR: Cannot find or install Python 3.10+."
        echo "       Install Python 3.12 from https://python.org then re-run."
        exit 1
    fi
fi
echo "      Python: $PYEXE  ($("$PYEXE" --version))"

# ── [2/5] Copy app files to install directory ────────────────────────────────
echo ""
echo "[2/5] Installing app files to $INSTALL_DIR ..."
mkdir -p "$INSTALL_DIR"

for f in pi_bench.py pi_bench_dev.py pi_bench_gui.py \
          pi_bench_gui_dev.py pi_bench_gui_dev_llm.py \
          install.py uninstall.py setup.sh setup.bat; do
    if [ -f "$SCRIPT_DIR/$f" ]; then
        cp "$SCRIPT_DIR/$f" "$INSTALL_DIR/$f"
    fi
done
# Copy setup.sh as the installed uninstaller too
cp "${BASH_SOURCE[0]}" "$INSTALL_DIR/setup.sh"
chmod +x "$INSTALL_DIR/setup.sh"
echo "      Done."

# ── [3/5] Create / update virtual environment ────────────────────────────────
echo ""
echo "[3/5] Setting up Python virtual environment ..."
"$PYEXE" "$INSTALL_DIR/install.py" "$@"

# ── [4/5] Create launcher command ────────────────────────────────────────────
echo ""
echo "[4/5] Creating launcher command ..."
mkdir -p "$BIN_DIR"
cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
# Pi Bench launcher
if [[ "\${1:-}" == "--uninstall" ]]; then
    bash "$INSTALL_DIR/setup.sh" --uninstall
    exit 0
fi
exec "$INSTALL_DIR/venv/bin/python" "$INSTALL_DIR/pi_bench_gui.py" "\$@"
EOF
chmod +x "$LAUNCHER"
echo "      Created: $LAUNCHER"

# ── [5/5] Create desktop entry ───────────────────────────────────────────────
echo ""
echo "[5/5] Creating desktop entry ..."
mkdir -p "$DESKTOP_DIR"
cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Pi Bench
GenericName=CPU Benchmark
Comment=Pi Bench CPU performance and thermal benchmark
Exec=$INSTALL_DIR/venv/bin/python $INSTALL_DIR/pi_bench_gui.py
Terminal=false
Categories=Utility;System;
Keywords=benchmark;cpu;performance;thermal;
EOF
chmod +x "$DESKTOP_FILE"

# Update desktop database if available
command -v update-desktop-database &>/dev/null && \
    update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
echo "      Created: $DESKTOP_FILE"

# ── Ensure ~/.local/bin is on PATH ────────────────────────────────────────────
PATH_HINT=""
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    PATH_HINT="
  NOTE: Add ~/.local/bin to your PATH to use the 'pi-bench' command:
        echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc
        source ~/.bashrc
"
fi

echo ""
echo "============================================================"
echo "  Setup complete!"
echo ""
echo "  Start from app menu : Pi Bench"
echo "  Start from terminal : pi-bench"
echo "  Uninstall           : pi-bench --uninstall"
echo "$PATH_HINT"
echo "============================================================"
echo ""
