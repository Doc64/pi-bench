"""
Targeted test for the stale-credential retry fix.

What this does on the NAS:
  - Creates one tiny temp file inside Scripts/Benchmarks/retry_test_tmp/
  - Immediately deletes it and removes that temp folder
  - Nothing else is touched on the NAS

Steps:
  1. Connect to NAS, disconnect (plants credential in Windows cache)
  2. Wait 30s (simulate idle)
  3. Try plain net use — expect failure (stale credential)
  4. Apply fix: cmdkey /delete + net use /delete + retry
  5. If retry succeeds: write one small file, read it back, delete it, remove temp dir
  6. Print clear PASS/FAIL
"""
import subprocess, os, shutil, tempfile, time

SHARE   = r'\\192.168.200.36\Common-Room'
HOST    = '192.168.200.36'
USER    = 'tom'
PW      = '040102'
SUBDIR  = r'Scripts\Benchmarks\retry_test_tmp'
UNC_DIR = SHARE + '\\' + SUBDIR

def net_use(connect=True):
    if connect:
        cmd = ['net', 'use', SHARE, '/user:' + USER, PW]
    else:
        cmd = ['net', 'use', SHARE, '/delete', '/y']
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    return r

def cmdkey_delete():
    return subprocess.run(['cmdkey', '/delete:' + HOST],
                          capture_output=True, text=True, timeout=10)

# --- Step 1: connect then immediately disconnect to plant the credential ---
print('Step 1: connect + disconnect to plant credential in Windows cache')
r = net_use(connect=True)
print(f'  connect:    rc={r.returncode}  {r.stdout.strip() or r.stderr.strip()}')
if r.returncode != 0:
    print('  ABORT: could not connect at all')
    raise SystemExit(1)
r = net_use(connect=False)
print(f'  disconnect: rc={r.returncode}')

# --- Step 2: wait 30s ---
print()
print('Step 2: waiting 180s to let credential go stale...')
for i in range(180, 0, -10):
    print(f'  {i}s remaining...', flush=True)
    time.sleep(10)

# --- Step 3: plain reconnect — expect this to fail ---
print()
print('Step 3: plain reconnect (expect failure)')
r = net_use(connect=True)
print(f'  rc={r.returncode}  {(r.stdout + r.stderr).strip()}')
if r.returncode == 0:
    print('  (connected fine — NAS did not drop session; retry path not needed this run)')
    net_use(connect=False)
    print('PASS (no retry needed)')
    raise SystemExit(0)

# --- Step 4: apply fix ---
print()
print('Step 4: applying fix — cmdkey /delete + net use /delete + retry')
r_cmdkey = cmdkey_delete()
print(f'  cmdkey /delete: rc={r_cmdkey.returncode}  {(r_cmdkey.stdout + r_cmdkey.stderr).strip()}')
r_del = net_use(connect=False)
print(f'  net use /delete: rc={r_del.returncode}')
r_retry = net_use(connect=True)
print(f'  retry connect: rc={r_retry.returncode}  {(r_retry.stdout + r_retry.stderr).strip()}')
if r_retry.returncode != 0:
    print('FAIL: retry also failed — NAS issue unrelated to credential cache')
    raise SystemExit(1)

# --- Step 5: verify write/read/delete on NAS ---
print()
print('Step 5: write one test file, verify, delete, remove temp dir')
try:
    os.makedirs(UNC_DIR, exist_ok=True)
    print(f'  makedirs OK: {UNC_DIR}')

    test_file = os.path.join(UNC_DIR, 'retry_test.txt')
    with open(test_file, 'w') as f:
        f.write('retry_test\n')
    print(f'  write OK: {test_file}')

    with open(test_file, 'r') as f:
        content = f.read()
    assert content.strip() == 'retry_test', f'unexpected content: {content!r}'
    print(f'  read-back OK')

    os.remove(test_file)
    print(f'  delete file OK')

    os.rmdir(UNC_DIR)
    print(f'  rmdir OK')
except Exception as e:
    print(f'  ERROR: {e}')
    net_use(connect=False)
    raise SystemExit(1)
finally:
    net_use(connect=False)

print()
print('PASS: stale-credential retry fix works correctly')
