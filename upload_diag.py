"""
Diagnostics: run on workbench to test subprocess net use vs shell net use.
Run via: python upload_diag.py
"""
import subprocess, os, platform, sys

SHARE = r'\\192.168.200.36\Common-Room'
USER = 'tom'
PW = '040102'

print(f"Platform: {platform.platform()}")
print(f"Running as: {os.environ.get('USERNAME', 'unknown')}")
print()

# Disconnect any stale session first
print("=== 0. Disconnect stale session (best-effort) ===")
r = subprocess.run(['net', 'use', SHARE, '/delete', '/y'],
                   capture_output=True, text=True, timeout=10)
print(f"rc={r.returncode} stdout={r.stdout.strip()} stderr={r.stderr.strip()}")
print()

# Test 1: subprocess list form
print("=== 1. subprocess list form ===")
cmd_list = ['net', 'use', SHARE, '/user:' + USER, PW]
print(f"cmd: {cmd_list}")
r = subprocess.run(cmd_list, capture_output=True, text=True, timeout=20)
print(f"rc={r.returncode}")
print(f"stdout: {r.stdout.strip()}")
print(f"stderr: {r.stderr.strip()}")
# Disconnect
subprocess.run(['net', 'use', SHARE, '/delete', '/y'], capture_output=True, timeout=10)
print()

# Test 2: subprocess string form via shell=True
print("=== 2. subprocess shell=True string form ===")
cmd_str = f'net use {SHARE} /user:{USER} {PW}'
print(f"cmd: {cmd_str}")
r = subprocess.run(cmd_str, capture_output=True, text=True, timeout=20, shell=True)
print(f"rc={r.returncode}")
print(f"stdout: {r.stdout.strip()}")
print(f"stderr: {r.stderr.strip()}")
subprocess.run(['net', 'use', SHARE, '/delete', '/y'], capture_output=True, timeout=10)
print()

# Test 3: no password, try anonymous
print("=== 3. no credentials (anonymous/guest) ===")
r = subprocess.run(['net', 'use', SHARE], capture_output=True, text=True, timeout=20)
print(f"rc={r.returncode}")
print(f"stdout: {r.stdout.strip()}")
print(f"stderr: {r.stderr.strip()}")
subprocess.run(['net', 'use', SHARE, '/delete', '/y'], capture_output=True, timeout=10)
print()

# Test 4: try with guest user
print("=== 4. guest user with password ===")
r = subprocess.run(['net', 'use', SHARE, '/user:guest', PW], capture_output=True, text=True, timeout=20)
print(f"rc={r.returncode}")
print(f"stdout: {r.stdout.strip()}")
print(f"stderr: {r.stderr.strip()}")
subprocess.run(['net', 'use', SHARE, '/delete', '/y'], capture_output=True, timeout=10)
print()

# Test 5: try with empty password
print("=== 5. guest user, empty password ===")
r = subprocess.run(['net', 'use', SHARE, '/user:guest', ''], capture_output=True, text=True, timeout=20)
print(f"rc={r.returncode}")
print(f"stdout: {r.stdout.strip()}")
print(f"stderr: {r.stderr.strip()}")
subprocess.run(['net', 'use', SHARE, '/delete', '/y'], capture_output=True, timeout=10)
