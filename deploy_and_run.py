import paramiko, sys, time, threading

LOCAL = (
    r'C:\Users\Tom\AppData\Local\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude'
    r'\local-agent-mode-sessions\7088940b-f196-432b-ba56-14c899170f28'
    r'\613d1dd2-576a-4108-a620-fc11774e11ac\local_e01eb427-0087-4549-aaae-2780dcf21c0e'
    r'\outputs\pi_bench_dev.py'
)
REMOTE = r'C:/Users/tom/Desktop/pi_bench_dev.py'

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('192.168.200.163', username='tom', password='040102', timeout=10)

sftp = c.open_sftp()
sftp.put(LOCAL, REMOTE)
stat = sftp.stat(REMOTE)
print(f'Uploaded: {stat.st_size} bytes', flush=True)
sftp.close()

cmd = (
    r'cd /d C:\Users\tom\Desktop'
    r' && python pi_bench_dev.py --digits 5000000 --mode multi --workers 4 --archive'
    r' --sftp-password 040102'
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
        chunk = chan.recv(4096).decode(errors='replace')
        sys.stdout.write(chunk)
        sys.stdout.flush()
    elif chan.exit_status_ready():
        while chan.recv_ready():
            chunk = chan.recv(4096).decode(errors='replace')
            sys.stdout.write(chunk)
        break
    else:
        time.sleep(0.5)

exit_code = chan.recv_exit_status()
print(f'\n--- exit code: {exit_code} ---')
c.close()
