import paramiko, sys
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect('192.168.200.163', username='tom', password='040102', timeout=10)
stdin, stdout, stderr = c.exec_command('pip install paramiko')
print(stdout.read().decode(errors='replace'))
print(stderr.read().decode(errors='replace'))
print('exit:', stdout.channel.recv_exit_status())
c.close()
