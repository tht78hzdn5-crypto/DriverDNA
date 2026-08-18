# DriverDNA — Deploy Runbook (Oracle VM + SQLite)

The step-by-step for the deployment of record adopted in **SPEC.md A40**:
SQLite on an Oracle Cloud Always Free VM, published over a Cloudflare Tunnel +
Access, replacing the retired Cloud Run + Supabase setup. It exists so the box
is **rebuildable, not a pet** (DEPLOY-SPEC H3).

Design context: `docs/DEPLOY-SPEC.md` (H1 auth, H2 network, H3 ops) and
`docs/SPEC.md` A23 (the backend abstraction) and A40 (this migration).

## What you need before starting

- An Oracle Cloud account (Always Free tier).
- A domain on a Cloudflare account (for Access; ~$10/yr — the one non-free
  piece). Skip this and use Tailscale instead if you don't want a public URL.
- **The Supabase connection URL, still readable.** The whole clean migration is
  one `store-copy` off it. Confirm you can still connect before you tear
  anything down.
- **Your source lap CSVs**, to restore historical raw traces (`backfill-blobs`).
- The current secrets: `DRIVERDNA_SESSION_SECRET`, `GOOGLE_CLIENT_ID`,
  `GOOGLE_CLIENT_SECRET`, `GEMINI_API_KEY`, `GARAGE61_TOKEN`.

Commands below run **on the VM over SSH (bash)** unless marked otherwise. Where
a step runs on your own Windows machine, PowerShell syntax is given.

---

## Part B — Provision the VM

1. Create an **Always Free A1 (ARM64/aarch64)** compute instance (Ampere) with
   a block volume. Regional A1 capacity is the usual reason a free instance
   won't launch — retry or change availability domain if creation fails.
2. Base OS packages and a service user:
   ```bash
   sudo apt-get update && sudo apt-get install -y python3.12 python3.12-venv git sqlite3
   sudo useradd --system --home /var/lib/driverdna --create-home driverdna
   ```
   (On Oracle Linux, use `dnf install python3.12 git sqlite` and the same
   `useradd`.) Any Python **3.11 or 3.12** is fine.
3. Install the app into a dedicated venv:
   ```bash
   sudo git clone https://github.com/tht78hzdn5-crypto/driverdna /opt/driverdna/DriverDNA
   sudo python3.12 -m venv /opt/driverdna/venv
   sudo /opt/driverdna/venv/bin/pip install -e "/opt/driverdna/DriverDNA[ui,ai-gemini]"
   ```
   The built SPA ships in the package (`src/driverdna/ui/static/`), so **no
   Node build is needed**. No `pg` extra — this is a SQLite deployment.
4. **Verify the ARM wheels installed without a source build** (don't assume):
   ```bash
   /opt/driverdna/venv/bin/python -c "import numpy, scipy; print(numpy.__version__, scipy.__version__)"
   ```

---

## Part C — Migrate the data

This is the load-bearing step. Run it on the VM (which can reach Supabase).

1. Copy every compact row (PKs preserved, checksum-verified):
   ```bash
   sudo -u driverdna /opt/driverdna/venv/bin/driverdna store-copy \
     --from "postgresql://USER:PASSWORD@HOST:6543/postgres?sslmode=require" \
     --to /var/lib/driverdna/driverdna.db
   ```
   > On your Windows machine instead, keep the URL out of history:
   > ```powershell
   > $env:SRC = "postgresql://…"
   > driverdna store-copy --from $env:SRC --to driverdna.db
   > ```
2. **Gate on the last line.** Proceed only on
   `verified: all N tables checksum-identical`. If it prints
   `MISMATCH … the copy is NOT faithful — do not cut over`, stop and
   investigate — that check exists precisely to catch a bad copy at the row
   level rather than months later in a report.
3. Restore historical raw traces from your CSVs (optional but recommended — a
   plain re-import is a no-op, since the copied rows already dedup by content
   hash):
   ```bash
   sudo -u driverdna /opt/driverdna/venv/bin/driverdna backfill-blobs \
     --from /path/to/your/csvs --db /var/lib/driverdna/driverdna.db
   ```
   It matches each CSV to a lap by content fingerprint and writes only the
   missing `<lap_pk>.npz`, never touching a lap row. Laps it couldn't match and
   CSVs that matched nothing are itemized. Going forward, every lap you
   `import`/`sync` on the VM gets a durable blob automatically.

---

## Part D — Bring up the service

1. Generate a stable session secret (do this once and keep it — rotating it
   signs everyone out):
   ```bash
   openssl rand -hex 32
   ```
   Secrets file, `0600`, owned by the service user:
   ```bash
   sudo install -d -m 0700 -o driverdna -g driverdna /etc/driverdna
   sudo -u driverdna tee /etc/driverdna/driverdna.env >/dev/null <<'EOF'
   DRIVERDNA_SESSION_SECRET=...      # required — keep STABLE, rotating logs you out
   GEMINI_API_KEY=...                # required for AI coaching/chat
   GARAGE61_TOKEN=...                # required for driverdna sync
   GOOGLE_CLIENT_ID=...              # optional — enables Google OAuth login
   GOOGLE_CLIENT_SECRET=...          # optional — required only if GOOGLE_CLIENT_ID is set
   EOF
   sudo chmod 0600 /etc/driverdna/driverdna.env
   ```
   `DRIVERDNA_DATABASE_URL`/`DRIVERDNA_BLOB_ROOT` are already set by the unit,
   so they don't belong here.
2. Install the systemd units from `deploy/`:
   ```bash
   sudo cp /opt/driverdna/DriverDNA/deploy/driverdna.service /etc/systemd/system/
   sudo cp /opt/driverdna/DriverDNA/deploy/driverdna-backup.* /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now driverdna driverdna-backup.timer
   sudo systemctl status driverdna --no-pager
   sudo journalctl -u driverdna -n 20 --no-pager
   ```
   The service binds `127.0.0.1:8710` only; the tunnel publishes it. **Confirm
   the startup log line reads `auth=yes behind_proxy=yes`** — the unit already
   passes `--behind-proxy` (SPEC.md A41): without it, the auth interlock still
   protects you (a missing secret refuses to start either way), but per-client
   login throttling and rate limiting silently collapse to one shared bucket
   keyed on the tunnel's own loopback address instead of the real caller.
3. Cloudflare Tunnel + Access — follow `deploy/cloudflared/README.md`. In
   short: `cloudflared tunnel login && create`, copy
   `deploy/cloudflared/config.example.yml` → `/etc/cloudflared/config.yml`
   (fill UUID + hostname), `cloudflared tunnel route dns …`,
   `cloudflared service install`, then add a self-hosted **Access application**
   whose policy allowlists your single owner email.
4. **Update the Google OAuth redirect URI** in the Google Cloud console to the
   new Cloudflare hostname (e.g. `https://driverdna.example.com/api/auth/google/callback`).
   Miss this and sign-in breaks — the most common cutover mistake. Skip if you
   are not using Google OAuth.
5. **Create your account.** On a fresh deployment (or after a store-copy from
   Supabase), there is no usable login yet — the DB seed row at
   `owner@example.com` is a migration scaffold with no real password. Visit
   the app URL through the Cloudflare Access gate; the SPA shows a sign-in
   screen. Click **Register**, enter your email and a password (≥ 8
   characters), and submit. On success you're signed in and your account
   (`user_pk=2`) is the one all future Driver Model history accrues to. If you
   set up Google OAuth and prefer that path, click the Google button instead —
   it creates the account automatically on first sign-in.

---

## Part E — Verify (H done-criteria)

- **Faithful copy:** the `store-copy` checksum line was green (Part C.2).
- **Full suite on the VM against the real SQLite DB:**
  ```bash
  cd /opt/driverdna/DriverDNA && sudo /opt/driverdna/venv/bin/pip install -e ".[dev]"
  sudo /opt/driverdna/venv/bin/python -m pytest -rs
  ```
  Report the receipt: command, that the backend was SQLite, and that the only
  skips are Postgres-absent (a skip is not a pass).
- **Determinism on ARM:** import a cohort twice into throwaway DBs and confirm
  the generated reports are byte-identical — the existing mechanical check, now
  on aarch64.
- **Parity spot-check:** a report generated on the migrated SQLite matches one
  generated from Supabase pre-cutover (A23's byte-identical guarantee).
- **Auth / unreachability:** sign in through the Cloudflare URL; load Driver
  home, a cohort, and one chat turn; confirm a request from an
  un-allowlisted identity is blocked at Access, and that `/api/*` returns 401
  without a session.
- **Configuration is visible, not inferred:** `curl https://<vm-domain>/health`
  reports `{"status":"ok","store":"sqlite","auth":true}`. If `auth` ever reads
  `false` here after this setup, the session secret didn't load — stop and
  fix it before relying on the deployment; don't infer correctness from the
  site merely rendering (docs/VM-MIGRATION.md §1, on exactly this mistake).
- **A restart doesn't sign you out:** `sudo systemctl restart driverdna`, then
  reload the site without clearing cookies — you should still be signed in.
  (This is what the retired ephemeral-secret fallback used to break.)

---

## Part F — Decommission (only after the VM is verified stable for a few days)

1. Take a final safety copy: re-run `store-copy` to a dated SQLite file and
   keep it off the box.
2. Tear down the Cloud Run service (`driverdna`, `northamerica-northeast1`).
3. **Delete the Supabase project** — this is what actually ends the egress
   billing.
4. Remove/rotate the now-unused `DRIVERDNA_DATABASE_URL` (Supabase) GitHub
   Actions secret. The Cloud Run deploy workflow was already removed in the
   A40 change, so nothing will try to redeploy.

## Ongoing

- **Lap intake:** `driverdna sync` on a systemd timer pulls owned laps from
  Garage61 directly on the VM (idempotent by content-hash dedup); `#/upload`
  remains for manual/reference CSVs from the phone browser.
- **Backups:** `driverdna-backup.timer` snapshots the DB daily to
  `/var/lib/driverdna/backups/`. Pull one to your own machine occasionally —
  the dated Driver-Model history and chat/coach transcripts are the
  irreplaceable rows.

---

## Part G — Troubleshooting

BUG-018 was lost because journald defaulted to volatile storage — the service
crashed (or refused to start), and the evidence vanished on the next reboot.
The steps below make that impossible going forward.

### 1. Enable persistent journal storage

Without this, `journalctl -u driverdna` shows nothing after a reboot.

```bash
sudo mkdir -p /etc/systemd/journald.conf.d
sudo cp /opt/driverdna/DriverDNA/deploy/journald-driverdna.conf \
    /etc/systemd/journald.conf.d/
sudo systemctl restart systemd-journald
```

Verify: `journalctl --disk-usage` should report a non-zero archived size after
the next service restart.

### 2. Service won't start (Cloudflare 1033 / port unreachable)

```bash
# What the unit thinks happened:
sudo systemctl status driverdna --no-pager
sudo journalctl -u driverdna -n 100 --no-pager

# Health probe (if the port is up at all):
curl -s http://127.0.0.1:8710/health | python3 -m json.tool

# Common causes, most likely first:
# - auth=false in /health → DRIVERDNA_SESSION_SECRET missing or empty in
#   /etc/driverdna/driverdna.env. The interlock (A41) refuses a non-loopback
#   bind without one, and --behind-proxy makes every bind non-loopback.
# - "Address already in use" → another process on port 8710.
# - Import error after pip install → a dependency shifted. Check the traceback.
```

### 3. Garage61 sync fails with an auth error

A `Garage61AuthError` in the journal means the stored OAuth token expired.
The SPA shows "Garage61 sign-in expired — reconnect" with a link; the CLI
prints the same. Reconnect through the OAuth flow at `#/import` → "Connect
Garage61" (or set a fresh `GARAGE61_TOKEN` in the env file and restart).

### 4. Capturing a full diagnostic snapshot

If the service is misbehaving and you need to share the state:

```bash
sudo journalctl -u driverdna --since "1 hour ago" --no-pager > ~/driverdna-journal.txt
sudo systemctl status driverdna --no-pager >> ~/driverdna-journal.txt
curl -s http://127.0.0.1:8710/health >> ~/driverdna-journal.txt 2>&1
```

This captures the journal, the unit status, and the health probe in one file.
**Never include `/etc/driverdna/driverdna.env`** — it contains secrets.

---

## Part H — Operating the live VM (learned the hard way)

Facts established by running work on the deployed machine, recorded so the next
agent does not rediscover them by taking production down. Part B above is
*prescriptive* — what to provision. This part is *descriptive* — what the
machine actually is, and where the two disagree.

### The deployed VM does not match Part B

| | Part B prescribes | The VM actually is |
|---|---|---|
| Architecture | Ampere A1, ARM64/aarch64 | **x86_64** |
| Memory | (A1 shapes offer several GB) | **~960 MB, no swap** |
| Python | `python3.12` | **3.11.0rc1** (a release candidate) |

The architecture line was recorded as "Ampere A1 ARM64" on 2026-08-08 without
being checked, and a whole diagnostic track was built on it before anyone ran
`uname -m` (BUG-019). The exact instance shape is still unverified — ~1 GB on
x86 is consistent with `VM.Standard.E2.1.Micro`, but confirm it from the OCI
console or instance metadata rather than inferring it from RAM:

```bash
curl -sH "Authorization: Bearer Oracle" http://169.254.169.254/opc/v2/instance/ | grep -i shape
```

Provisioning a replacement per Part B would produce an **ARM64** host, which is
a different platform from the one running today. That is fine — but it makes
BUG-019's original float-divergence question a real question for the first
time, rather than the false premise it turned out to be here.

### Never run the full test suite on this machine

`python3 -m pytest` in one shot exhausts the ~960 MB and takes the whole VM
down — SSH and ping stop answering, and it needs a hard reboot from the OCI
console. The DriverDNA service goes down with it. This has happened twice
(BUG-032), and is the leading explanation for BUG-018's outage.

Batch it instead — roughly 10-13 test files at a time:

```bash
sudo -u driverdna /opt/driverdna/venv/bin/python -m pytest \
  tests/test_parser.py tests/test_schema_lock.py tests/test_segmenter.py \
  tests/test_metrics.py tests/test_scoring.py --tb=short
```

A full batched pass takes ~17 minutes across ~7 batches. Note that a batched
pass is **weaker** than a single run: it does not exercise cross-file
interference or ordering-dependence, so treat it as a smoke check of the
deployed environment, not as a substitute for CI.

### Give the machine swap, and cap the service

Two guards, both cheap, both worth doing before anything else (BUG-032). The
VM has ~960 MB and **no swap**, which is why memory pressure here is instantly
fatal rather than merely slow: the kernel has nowhere to spill, so the OOM
killer takes whatever it likes — including sshd.

**1. Add swap.** A 2 GB swapfile on the durable volume turns "the VM dies and
needs a console reboot" into "the VM gets slow for a minute":

```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -h        # confirm a Swap row with 2.0Gi
```

**2. Cap the service.** `deploy/driverdna.service` now sets `MemoryHigh=300M`
and `MemoryMax=450M`, so a runaway DriverDNA is killed and restarted by
`Restart=always` instead of taking the machine with it. These are ~2x and ~3x
the **measured** peak — every real path (import, `census`, `report`,
`rebuild-map`) sits flat at 116-135 MB, since the footprint is numpy/scipy/
FastAPI at import rather than telemetry. After copying the unit:

```bash
sudo systemctl daemon-reload && sudo systemctl restart driverdna
systemctl show driverdna -p MemoryMax -p MemoryHigh     # confirm applied
systemctl show driverdna -p MemoryCurrent               # watch actual usage
```

If `MemoryCurrent` ever approaches `MemoryHigh` in normal use, raise **both**
values together — never one alone, or the soft throttle stops preceding the
hard kill and you lose the graceful step.

**The service fits this machine comfortably.** With ~150-250 MB for the OS,
~30-50 MB for `cloudflared` and ~135-150 MB for DriverDNA, roughly 500 MB stays
free. What does not fit is the **test suite** — see the section above. Those are
different workloads and only one of them ever crashed this box.

### What is not installed on the VM

- **No Postgres** — the dual-backend tests skip (~16). Expected; this is a
  SQLite deployment.
- **No Chromium/Playwright** — every `-m browser` test skips (26). Also
  expected, but remember AGENTS.md's rule: a skip is not a pass. The browser
  tests are covered by CI, not by the VM.

### `pip install` on the live venv can half-succeed

`pip install -e ".[dev]"` can fail late — a distro-owned package it wants to
replace (e.g. Debian's `cryptography`, which has no `RECORD` file) aborts the
install **after** other packages are already staged, leaving some dependencies
missing while the command still looks like it finished. Always check the tail
of the output for `ERROR:`, and verify imports afterwards rather than trusting
the exit:

```bash
/opt/driverdna/venv/bin/python -c "import driverdna, fastapi, typer; print('ok')"
```

BUG-018's outage began immediately after a `pip install .[dev]` against the
live venv. That was never proven to be the cause, but a half-installed venv is
a plausible mechanism and costs nothing to rule out.

### Keeping the machine current

The VM pulls over SSH with a read-only deploy key (`/opt/driverdna/.ssh/`,
generated on the machine — the private half has never left it). If `git pull`
starts asking for credentials, the remote has reverted to HTTPS:

```bash
sudo -u driverdna git -C /opt/driverdna remote set-url origin git@github.com:tht78hzdn5-crypto/DriverDNA.git
```

The repo lives at `/opt/driverdna`, not `/opt/driverdna/DriverDNA`.

### Persistent journald

`deploy/journald-driverdna.conf` sets `Storage=persistent` so a crash survives
the reboot that follows it. Verify it is actually applied — BUG-018 could not
be diagnosed at all because journald was still on its volatile default and
every log from the outage was lost:

```bash
journalctl --disk-usage          # a persistent journal reports real on-disk bytes
grep -r Storage /etc/systemd/journald.conf.d/ 2>/dev/null
```
