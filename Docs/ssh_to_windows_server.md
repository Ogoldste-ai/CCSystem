# SSH to a Windows server (instead of Remote Desktop)

Use this guide to log in to a Windows server (for example `nuvo-win2`) with `ssh` instead of Remote Desktop.
Once it's set up, you log in with an SSH key and no password.

Placeholders used below:

| Placeholder | Meaning | Example |
|---|---|---|
| `<machine>` | Server name (the "Computer" field in Remote Desktop) | `nuvo-win2` |
| `<user>` | Your account name, without the `machine\` prefix | `ogoldste` |
| `<key>` | Your private key file in `~\.ssh` | `id_ed25519_nuvoton` |
| `<alias>` | Short name you'll type after `ssh` | `nuvo-win2` |

There are two roles. **Part A** is done once by an administrator on the server, using Remote Desktop.
**Part B** is done by Copilot on your laptop (ask Copilot: *"connect to machine `<machine>` over ssh"*).

---

## Part A — Administrator, on the Windows server

Open **PowerShell as Administrator** on `<machine>`.

### A1. Turn on the SSH server (once per server)

```powershell
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
Start-Service sshd
Set-Service sshd -StartupType Automatic
New-NetFirewallRule -Name sshd -DisplayName 'OpenSSH Server' -Protocol TCP -LocalPort 22 -Action Allow -Direction Inbound
```

The last command fails harmlessly if a firewall rule for port 22 already exists.

### A2. Add the user's public key (once per user)

Copilot gives you the public key line in step B4. It's one line that starts with `ssh-ed25519` or `ssh-rsa`.
First check whether the user is a local Administrator:

```powershell
net localgroup Administrators
```

**If the user is an Administrator**, add the key here. For Administrator accounts, Windows ignores the
user's own `authorized_keys` file:

```powershell
$f = 'C:\ProgramData\ssh\administrators_authorized_keys'
Add-Content $f '<public key line>'
icacls $f /inheritance:r /grant 'Administrators:F' /grant 'SYSTEM:F'
```

The `icacls` line is required. If anyone other than Administrators and SYSTEM can access the file, Windows ignores it.

**If the user is not an Administrator:**

```powershell
$d = 'C:\Users\<user>\.ssh'
New-Item -ItemType Directory -Force $d | Out-Null
Add-Content "$d\authorized_keys" '<public key line>'
```

---

## Part B — Copilot, on the user's laptop

| Step | What Copilot does | Command |
|---|---|---|
| B1 | Ask for `<machine>` and `<user>`. Remote Desktop's `nuvo-win2\ogoldste` becomes SSH user `ogoldste`. | — |
| B2 | List your keys and let you choose `<key>`. If you have none, create one first. | `Get-ChildItem ~\.ssh\*.pub \| % { ssh-keygen -lf $_ }` |
| B3 | Check that the SSH server is reachable. If this returns `False`, ask the admin to do **A1**, then wait. | `Test-NetConnection <machine> -Port 22` |
| B4 | Show the public key line and ask the admin to do **A2**, then wait. | `Get-Content ~\.ssh\<key>.pub` |
| B5 | Test the key in a mode that never asks for a password. If it's denied, check A2: wrong file for an admin, or the `icacls` line was skipped. | `ssh -o IdentitiesOnly=yes -o BatchMode=yes -i ~\.ssh\<key> <user>@<machine> whoami` |
| B6 | Ask for `<alias>`. If it isn't already in `~\.ssh\config`, add the entry below and check that it's read correctly. | `ssh -G <alias>` |
| B7 | Final check. It should print `<machine>\<user>` with no password prompt. | `ssh -o BatchMode=yes <alias> whoami` |

Config entry added in B6:

```
Host <alias>
    HostName <machine>
    User <user>
    IdentityFile C:\Users\<you>\.ssh\<key>
    IdentitiesOnly yes
```

After this, connect with:

```powershell
ssh <alias>
scp file.txt <alias>:C:/Users/<user>/
```

---

## Pitfalls we hit

- **`ssh-copy-id` doesn't exist on Windows.** The key has to be added on the server by hand (A2).
- **For Administrator accounts, `C:\Users\<user>\.ssh\authorized_keys` is ignored.** Only
  `C:\ProgramData\ssh\administrators_authorized_keys` is used, and only with the restricted permissions from `icacls`.
  The sign of this problem is that you still get a password prompt even though the key is in your own `authorized_keys`.
- **Plain `ssh user@machine` only tries keys with default names** (`id_ed25519`, `id_rsa`). A key with any other
  name, such as `id_ed25519_nuvoton`, needs the `~\.ssh\config` entry from B6.
- **Copilot never handles your Windows password.** The admin step replaces the usual password-based key copy.

## Troubleshooting

- Still asked for a password: run `ssh -v <alias>` on the laptop and check the logs in `C:\ProgramData\ssh\logs` on the server.
- Connection refused or times out: A1 isn't done, the `sshd` service is stopped, or the firewall rule is missing.
