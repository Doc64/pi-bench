import paramiko, sys

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('192.168.200.163', username='tom', password='040102', timeout=10)

sftp = c.open_sftp()
sftp.put(
    r'C:\Users\Tom\AppData\Local\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude'
    r'\local-agent-mode-sessions\7088940b-f196-432b-ba56-14c899170f28'
    r'\613d1dd2-576a-4108-a620-fc11774e11ac\local_e01eb427-0087-4549-aaae-2780dcf21c0e'
    r'\outputs\retry_test.py',
    r'C:/Users/tom/Desktop/retry_test.py'
)
sftp.close()
print('Uploaded retry_test.py — starting test...', flush=True)

stdin, stdout, stderr = c.exec_command(r'python C:\Users\tom\Desktop\retry_test.py')

# Stream output live
import threading, time

def drain(stream, label):
    while True:
        data = stream.read(4096)
        if not data:
            break
        sys.stdout.write(data.decode('cp1252', errors='replace'))
        sys.stdout.flush()

t_out = threading.Thread(target=drain, args=(stdout, 'OUT'), daemon=True)
t_err = threading.Thread(target=drain, args=(stderr, 'ERR'), daemon=True)
t_out.start()
t_err.start()
t_out.join()
t_err.join()

rc = stdout.channel.recv_exit_status()
print(f'\n--- exit code: {rc} ---')
c.close()
