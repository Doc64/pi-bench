import paramiko

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('192.168.200.163', username='tom', password='040102', timeout=10)

test_cmd = (
    r'net use \\192.168.200.36\Common-Room /user:tom 040102'
    r' && echo testcontent > %TEMP%\upload_test.txt'
    r' && copy %TEMP%\upload_test.txt \\192.168.200.36\Common-Room\Scripts\Benchmarks\upload_test.txt'
    r' && del \\192.168.200.36\Common-Room\Scripts\Benchmarks\upload_test.txt'
    r' && net use \\192.168.200.36\Common-Room /delete /y'
    r' && echo UPLOAD_OK'
)

stdin, stdout, stderr = c.exec_command(test_cmd)
out = stdout.read().decode()
err = stderr.read().decode()
print(out)
if err.strip():
    print("STDERR:", err)
c.close()
