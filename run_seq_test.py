import paramiko

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('192.168.200.163', username='tom', password='040102', timeout=10)

sftp = c.open_sftp()
sftp.put(
    r'C:\Users\Tom\AppData\Local\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\local-agent-mode-sessions\7088940b-f196-432b-ba56-14c899170f28\613d1dd2-576a-4108-a620-fc11774e11ac\local_e01eb427-0087-4549-aaae-2780dcf21c0e\outputs\seq_test.py',
    r'C:/Users/tom/Desktop/seq_test.py'
)
sftp.close()

stdin, stdout, stderr = c.exec_command(r'python C:\Users\tom\Desktop\seq_test.py')
print(stdout.read().decode())
err = stderr.read().decode()
if err.strip():
    print("STDERR:", err)
c.close()
