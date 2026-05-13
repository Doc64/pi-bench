"""
Simulate the archive connect/disconnect sequence on the workbench:
  1. net use (list_all)  → disconnect
  2. net use (mkdir)     → disconnect
  3. net use (put)       → copy → disconnect
Run via: python seq_test.py
"""
import subprocess, os, shutil, tempfile

SHARE = r'\\192.168.200.36\Common-Room'
USER = 'tom'
PW = '040102'
TEST_SUBDIR = r'Scripts\Benchmarks\seq_test_tmp'
UNC_SUBDIR = SHARE + '\\' + TEST_SUBDIR

def net_use_connect():
    cmd = ['net', 'use', SHARE, '/user:' + USER, PW]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    print(f"  net_use_connect: rc={r.returncode} out={r.stdout.strip()!r} err={r.stderr.strip()!r}")
    return r.returncode == 0

def net_use_disconnect():
    r = subprocess.run(['net', 'use', SHARE, '/delete', '/y'],
                       capture_output=True, text=True, timeout=10)
    print(f"  net_use_disconnect: rc={r.returncode}")

print("=== Step 1: smb_list_all simulation ===")
if net_use_connect():
    try:
        entries = os.listdir(UNC_SUBDIR)
        print(f"  listdir: {entries}")
    except FileNotFoundError:
        print(f"  listdir: FileNotFoundError (folder doesn't exist yet, expected)")
    except Exception as e:
        print(f"  listdir error: {e}")
    finally:
        net_use_disconnect()

print()
print("=== Step 2: smb_mkdir simulation ===")
if net_use_connect():
    try:
        os.makedirs(UNC_SUBDIR, exist_ok=True)
        print(f"  makedirs: OK - {UNC_SUBDIR}")
    except Exception as e:
        print(f"  makedirs error: {e}")
    finally:
        net_use_disconnect()

print()
print("=== Step 3: smb_put simulation (no delay, immediate) ===")
# Create a local test file
tmp = os.path.join(tempfile.gettempdir(), 'seq_test_file.txt')
with open(tmp, 'w') as f:
    f.write('seq_test\n')

if net_use_connect():
    try:
        dest = UNC_SUBDIR + '\\seq_test_file.txt'
        shutil.copyfile(tmp, dest)
        print(f"  copyfile: OK -> {dest}")
        # Cleanup
        try:
            os.remove(dest)
            shutil.rmtree(UNC_SUBDIR, ignore_errors=True)
            print("  cleanup: OK")
        except Exception as e:
            print(f"  cleanup error: {e}")
    except Exception as e:
        print(f"  copyfile error: {e}")
    finally:
        net_use_disconnect()

os.remove(tmp)
print()
print("DONE")
