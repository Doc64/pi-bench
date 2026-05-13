import paramiko, sys, time, threading

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('192.168.200.163', username='tom', password='040102', timeout=10)

cmd = (
    r'cd /d C:\Users\tom\Desktop'
    r' && set SMB_PASSWORD=040102'
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
