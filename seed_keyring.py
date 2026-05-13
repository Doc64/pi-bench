"""
Run this on the workbench ONCE to store the pi_bench SFTP credential in
Windows Credential Locker (DPAPI-encrypted).  After this, pi_bench.py
--archive will find the credential automatically -- no --sftp-password
flag or env var needed.

Usage:
    python seed_keyring.py
"""
import keyring, getpass, sys

SERVICE  = "pi_bench"
USERNAME = "pi_bench"

existing = keyring.get_password(SERVICE, USERNAME)
if existing:
    print(f"Credential already stored for {USERNAME!r} in service {SERVICE!r}.")
    ans = input("Overwrite? [y/N] ").strip().lower()
    if ans != "y":
        print("Aborted.")
        sys.exit(0)

pw = getpass.getpass(f"Enter SFTP password for {USERNAME}@NAS: ")
keyring.set_password(SERVICE, USERNAME, pw)
print("Saved to Windows Credential Locker (DPAPI-encrypted).")
print("pi_bench.py --archive will now load it silently.")
