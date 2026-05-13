"""Probe which paths pi_bench can see — read only, touches nothing."""
import paramiko, stat

transport = paramiko.Transport(('192.168.200.36', 22))
transport.connect(username='pi_bench', password='040102')
sftp = paramiko.SFTPClient.from_transport(transport)

def try_list(path):
    try:
        entries = sftp.listdir(path)
        print(f'  OK  {path}  ({len(entries)} entries: {entries[:4]})')
    except Exception as e:
        print(f'  ERR {path}  -> {e}')

def try_stat(path):
    try:
        s = sftp.stat(path)
        mode = oct(stat.S_IMODE(s.st_mode))
        print(f'  STAT {path}  uid={s.st_uid} gid={s.st_gid} mode={mode}')
    except Exception as e:
        print(f'  STAT {path}  -> {e}')

print('=== getcwd ===')
try:
    print(f'  {sftp.getcwd()!r}')
except Exception as e:
    print(f'  {e}')

print('\n=== listdir probes ===')
for p in [
    '.',
    '/mnt',
    '/mnt/Family-Nas',
    '/mnt/Family-Nas/Common-Room',
    '/mnt/Family-Nas/Common-Room/Scripts',
    '/mnt/Family-Nas/Common-Room/Scripts/Benchmarks',
]:
    try_list(p)

print('\n=== stat probes ===')
for p in [
    '/mnt/Family-Nas/Common-Room',
    '/mnt/Family-Nas/Common-Room/Scripts',
    '/mnt/Family-Nas/Common-Room/Scripts/Benchmarks',
]:
    try_stat(p)

sftp.close()
transport.close()
