"""
Deploy pi_bench_dev.py, seed Windows Credential Locker with the SFTP password,
then run the full benchmark with NO --sftp-password flag to verify the keyring
path works end-to-end.
"""
import paramiko, sys, time, threading

OUTPUTS = (
    r'C:\Users\Tom\AppData\Local\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude'
    r'\local-agent-mode-sessions\7088940b-f196-432b-ba56-14c899170f28'
    r'\613d1dd2-576a-4108-a620-fc11774e11ac\local_e01eb427-0087-4549-aaae-2780dcf21c0e'
    r'\outputs'
)

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('192.168.200.163', username='tom', password='040102', timeout=10)

sftp = c.open_sftp()
sftp.put(OUTPUTS + r'\pi_bench_dev.py', r'C:/Users/tom/Desktop/pi_bench_dev.py')
stat = sftp.stat(r'C:/Users/tom/Desktop/pi_bench_dev.py')
print(f'Uploaded pi_bench_dev.py: {stat.st_size} bytes', flush=True)
sftp.close()

# Step 1: seed the keyring non-interactively
seed_cmd = (
    r'python -c "'
    r'import keyring; '
    r'keyring.set_password(\"pi_bench\", \"pi_bench\", \"040102\"); '
    r'print(\"keyring seeded OK\")'
    r'"'
)
_, stdout, stderr = c.exec_command(seed_cmd)
print(stdout.read().decode(errors='replace').strip())
err = stderr.read().decode(errors='replace').strip()
if err:
    print('SEED ERR:', err)

# Step 2: run benchmark with NO password argument -- must load from keyring
print('\n=== Running benchmark (keyring path -- no --sftp-password) ===\n', flush=True)
cmd = (
    r'cd /d C:\Users\tom\Desktop'
    r' && python pi_bench_dev.py --digits 5000000 --mode multi --workers 4 --archive'
)

transport = c.get_transport()
chan = transport.open_session()
chan.set_combine_stderr(False)
chan.exec_command(cmd)

def read_stderr():
    while True:
        data = chan.recv_stderr(4096)
        if not data:
            break
        sys.stderr.write(data.decode(errors='replace'))
        sys.stderr.flush()

t = threading.Thread(target=read_stderr, daemon=True)
t.start()

while True:
    if chan.recv_ready():
        sys.stdout.write(chan.recv(4096).decode(errors='replace'))
        sys.stdout.flush()
    elif chan.exit_status_ready():
        while chan.recv_ready():
            sys.stdout.write(chan.recv(4096).decode(errors='replace'))
        break
    else:
        time.sleep(0.5)

rc = chan.recv_exit_status()
print(f'\n--- exit code: {rc} ---')
c.close()
