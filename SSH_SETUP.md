# SSH Setup for Next Session

Goal: switch from "Cowork inside a sandbox" → "Claude Code with local shell access" so Claude can ssh directly into your machines instead of you copy-pasting files through file explorer.

## Why this matters
Claude Code runs in your normal terminal with the same shell + ssh + network access you already have. From Claude Code, this just works:
```
ssh tom@macmini "uptime && systemctl is-active mbpfan"
scp pi_bench.py tom@macmini:~/
ssh tom@workbench "python C:\\Users\\tom\\Desktop\\pi_bench.py --digits 1000"
```
No file explorer, no NAS round-trip, no "drag from outputs to share to desktop" dance.

## Step 1 — Install Claude Code
If you don't already have it:
- Download from anthropic.com / install via npm
- Authenticate with your Anthropic account
- Open a terminal in the same folder where Cowork has been writing files (the outputs path), or any folder you want to work in

Then `claude` or `claude code` from that folder gives you Claude in shell mode.

## Step 2 — Set up SSH config
Add this to `~/.ssh/config` on your workstation (the laptop where you'll run Claude Code). Replace the IPs with the actual ones for your LAN.

```
# Linux benchmark targets
Host macmini
    HostName 192.168.200.??     # fill in: ip a | grep inet on the macmini
    User tom
    IdentityFile ~/.ssh/id_ed25519

Host testbench
    HostName 192.168.200.??     # fill in once recovered from the wedge
    User tom
    IdentityFile ~/.ssh/id_ed25519

# Windows benchmark targets (need OpenSSH server enabled, see Step 3)
Host workbench
    HostName 192.168.200.??     # fill in
    User tom
    IdentityFile ~/.ssh/id_ed25519

Host gaming
    HostName 192.168.200.??     # fill in
    User tom
    IdentityFile ~/.ssh/id_ed25519

Host worklaptop
    HostName ??.??.??.??        # fill in (DHCP or static)
    User tom
    IdentityFile ~/.ssh/id_ed25519

# NAS (already SMB; SSH is optional, only if your NAS supports it)
# Most consumer NAS boxes don't have SSH by default
```

If you don't have a key pair yet:
```
ssh-keygen -t ed25519 -C "tom@workstation"   # accept defaults
```
Then push your public key to each machine.

## Step 3 — Enable OpenSSH server on Windows machines

Windows 10/11 ships with OpenSSH server but it's not enabled by default. On each Windows benchmark target (workbench, gaming PC, work laptop):

```powershell
# Run PowerShell as Administrator on the target machine

# Install OpenSSH Server (one-time, may already be installed)
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0

# Start the service and set to auto-start on boot
Start-Service sshd
Set-Service -Name sshd -StartupType Automatic

# Open the firewall (rule usually exists but disabled)
if (!(Get-NetFirewallRule -Name "OpenSSH-Server-In-TCP" -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -DisplayName 'OpenSSH Server (sshd)' -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22
}
```

Then push your workstation's public key to the Windows target:
```powershell
# On the workstation, send your pub key to the target
type ~/.ssh/id_ed25519.pub | ssh tom@workbench "powershell -Command \"Add-Content -Path C:\\Users\\tom\\.ssh\\authorized_keys -Value $_\""
```

Or just copy `id_ed25519.pub` over and append it manually to `C:\Users\tom\.ssh\authorized_keys` on the target.

Verify:
```
ssh workbench "echo hello"      # should print hello with no password prompt
```

## Step 4 — Push your public key to Linux targets
```
ssh-copy-id tom@macmini
ssh-copy-id tom@testbench    # once it's back online
```

Verify:
```
ssh macmini "uname -a"          # should not prompt for password
```

## Step 5 — IPs on your LAN
Run on each machine to get its IP:

**Linux (Mac mini, testbench):**
```
ip a | grep "inet " | grep -v 127.0.0.1
```

**Windows (workbench, gaming PC, work laptop):**
```
ipconfig | findstr IPv4
```

Fill those into `~/.ssh/config` from Step 2.

## Step 6 — Quick reference for next session

When next session starts in Claude Code, the first thing to do is verify connectivity:

```bash
for h in macmini testbench workbench gaming worklaptop; do
    echo -n "$h: "
    ssh -o ConnectTimeout=3 -o BatchMode=yes "$h" "echo OK" 2>&1 | head -1
done
```

If they all say `OK`, Claude can drive everything from one terminal — edit pi_bench.py locally, scp it to each target, run, collect results, all in one flow.

## What pi_bench needs from each machine

| Machine | OS | Required |
|---|---|---|
| Mac mini | Ubuntu | `turbostat`, `sudo` (passwordless for turbostat), `mbpfan` running, `smbclient` |
| Testbench | Ubuntu | same as above |
| Workbench | Win10 | Python 3.10+, LHM available (script auto-installs to `%LOCALAPPDATA%\pi_bench\LibreHardwareMonitor` if missing) |
| Gaming PC | Win11 | same as Workbench |
| Work laptop | Windows | same as Workbench (this one is the fresh-machine validation target) |

## When you start next session

Open Claude Code in the folder containing `pi_bench_dev.py` and say something like:

> "Resuming pi_bench work. Read SESSION_HANDOFF.md and SSH_SETUP.md, then run a connectivity check across all my SSH hosts."

Claude will read both docs, ssh to each host, and you'll be set up to continue from where we left off (the workbench end-to-end test).
