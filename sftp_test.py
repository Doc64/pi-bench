"""
Incremental SFTP connectivity test against TrueNAS.
Stops at the first failure. Only writes inside a temp subfolder
and deletes everything it creates.

What this touches on the NAS:
  - Creates: /mnt/Family-Nas/Common-Room/Scripts/Benchmarks/sftp_test_tmp/
  - Creates: /mnt/Family-Nas/Common-Room/Scripts/Benchmarks/sftp_test_tmp/sftp_test.txt
  - Reads back that file
  - Deletes the file
  - Removes the directory
  - Nothing else is touched
"""
import paramiko, sys

HOST     = '192.168.200.36'
USER     = 'pi_bench'
PASSWORD = '040102'
BASE     = '/mnt/Family-Nas/Common-Room/Scripts/Benchmarks'
TEST_DIR = BASE + '/sftp_test_tmp'
TEST_FILE = TEST_DIR + '/sftp_test.txt'

print(f'=== Step 1: connect to {HOST} as {USER} ===')
transport = paramiko.Transport((HOST, 22))
try:
    transport.connect(username=USER, password=PASSWORD)
    print('  connected OK')
except Exception as e:
    print(f'  FAIL: {e}')
    sys.exit(1)

sftp = paramiko.SFTPClient.from_transport(transport)

print(f'\n=== Step 2: list base directory {BASE} ===')
try:
    entries = sftp.listdir(BASE)
    print(f'  OK — {len(entries)} entries: {entries[:5]}{"..." if len(entries)>5 else ""}')
except Exception as e:
    print(f'  FAIL: {e}')
    sftp.close(); transport.close(); sys.exit(1)

print(f'\n=== Step 3: create test directory {TEST_DIR} ===')
try:
    sftp.mkdir(TEST_DIR)
    print(f'  mkdir OK')
except IOError as e:
    if 'exists' in str(e).lower() or e.errno == 17:
        print(f'  already exists (OK)')
    else:
        print(f'  FAIL: {e}')
        sftp.close(); transport.close(); sys.exit(1)

print(f'\n=== Step 4: write test file ===')
try:
    with sftp.open(TEST_FILE, 'w') as f:
        f.write('sftp_test\n')
    print(f'  write OK')
except Exception as e:
    print(f'  FAIL: {e}')
    sftp.close(); transport.close(); sys.exit(1)

print(f'\n=== Step 5: read back and verify ===')
try:
    with sftp.open(TEST_FILE, 'r') as f:
        content = f.read().decode().strip()
    assert content == 'sftp_test', f'unexpected content: {content!r}'
    print(f'  read OK: {content!r}')
except Exception as e:
    print(f'  FAIL: {e}')
    sftp.close(); transport.close(); sys.exit(1)

print(f'\n=== Step 6: cleanup (delete file + directory) ===')
try:
    sftp.remove(TEST_FILE)
    print(f'  removed file OK')
    sftp.rmdir(TEST_DIR)
    print(f'  removed directory OK')
except Exception as e:
    print(f'  FAIL during cleanup: {e}')
    sftp.close(); transport.close(); sys.exit(1)

sftp.close()
transport.close()
print(f'\nPASS — SFTP to TrueNAS is fully working')
