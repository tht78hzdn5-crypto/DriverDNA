# Oracle VM Access

The production Oracle VM can be accessed via SSH using a local private key.
If you need to CLI into the VM or run remote commands, use the following details:

- **Host**: 147.5.99.21
- **User**: ubuntu
- **Private Key**: `E:\benja\Documents\VIBE CODING\ssh-key-new.key`

**SSH Command:**
```bash
ssh -i "E:\benja\Documents\VIBE CODING\ssh-key-new.key" -o StrictHostKeyChecking=no ubuntu@147.5.99.21
```

**Run Remote Command Example:**
```bash
ssh -i "E:\benja\Documents\VIBE CODING\ssh-key-new.key" -o StrictHostKeyChecking=no ubuntu@147.5.99.21 "sudo systemctl status driverdna"
```

## Operational Notes

- **RAM**: ~960 MB total, **no swap**. Running the full pytest suite in one
  shot will OOM and crash the VM (requires a hard reboot from Oracle Cloud
  console). Always run tests in batches of 10–13 files.
- **Architecture**: x86_64 (not ARM64/Ampere A1).
- **Python venv**: `/opt/driverdna/venv/bin/python` (Python 3.11.0rc1).
- **Repo location**: `/opt/driverdna` (not `/opt/driverdna/DriverDNA`).
- **Git remote**: HTTPS with no credential configured — `git pull` fails.
  To update the VM, either configure a PAT or switch to an SSH deploy key.
- **No Postgres** on the VM — ~16 tests skip (expected).
- **No Playwright/Chromium** — ~24 browser tests skip (expected).
- **ServerAliveInterval**: Use `-o ServerAliveInterval=30` on long SSH
  commands to prevent the connection from dropping.
- **tee permissions**: The `driverdna` user cannot write to `/var/lib/driverdna/`
  for tee output — use `/tmp/` instead or fix permissions first.
