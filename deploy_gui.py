"""Deploy pi_bench_dev.py + pi_bench_gui.py to workbench, run import smoke test."""
import paramiko, sys, time, threading

OUTPUTS = (
    r'C:\Users\Tom\AppData\Local\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude'
    r'\local-agent-mode-sessions\7088940b-f196-432b-ba56-14c899170f28'
    r'\613d1dd2-576a-4108-a620-fc11774e11ac\local_e01eb427-0087-4549-aaae-2780dcf21c0e'
    r'\outputs'
)
DEST = r'C:/Users/tom/Desktop'

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('192.168.200.163', username='tom', password='040102', timeout=10)

sftp = c.open_sftp()
files_to_upload = [
    'pi_bench_dev.py',
    'pi_bench_gui.py',           # production
    'pi_bench_gui_dev.py',       # dev build (splash + results + reports + compare)
    'pi_bench_gui_dev_llm.py',   # dev + on-device LLM
    'pi_bench.py',               # gold copy (imported by all GUIs)
    'install.py',                # package installer (called by setup scripts)
    'uninstall.py',              # complete uninstaller
    'setup.bat',                 # Windows zero-prereq bootstrap
    'setup.sh',                  # Linux/macOS zero-prereq bootstrap
]
for fname in files_to_upload:
    local  = OUTPUTS + '\\' + fname
    remote = DEST + '/' + fname
    sftp.put(local, remote)
    stat = sftp.stat(remote)
    print(f'Uploaded {fname}: {stat.st_size} bytes')
sftp.close()

# Smoke test: import all three GUI modules without showing a window
smoke = r'python -c "import sys; sys.argv=[\"\"]; import os; os.environ[\"QT_QPA_PLATFORM\"]=\"offscreen\"; sys.path.insert(0,r\"C:\Users\tom\Desktop\"); import pi_bench; import pyqtgraph; from PyQt6.QtWidgets import QApplication; app=QApplication([]); import pi_bench_gui; w=pi_bench_gui.MainWindow(); import pi_bench_gui_dev; import pi_bench_gui_dev_llm; print(\"SMOKE OK\")"'
_, out, err = c.exec_command(f'cd /d C:\\Users\\tom\\Desktop && {smoke}')
stdout_txt = out.read().decode(errors='replace')
stderr_txt = err.read().decode(errors='replace')
print('\n--- smoke test ---')
print(stdout_txt)
if stderr_txt.strip():
    print('STDERR:', stderr_txt[:2000])
print('exit:', out.channel.recv_exit_status())
c.close()
